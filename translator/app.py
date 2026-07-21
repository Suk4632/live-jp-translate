"""전체 파이프라인 조립: 오디오 캡처 → 음성 인식 → 번역 → 자막 표시."""

import datetime
import queue
import threading

from .audio import AudioCapture, find_device
from .asr import SpeechRecognizer
from .translate import Translator


def run(args):
    print("=" * 60)
    print("  일본어 라이브 방송 실시간 번역기")
    print("=" * 60)

    stop_event = threading.Event()
    segment_q = queue.Queue(maxsize=8)   # 오디오 세그먼트 (인식 대기)
    text_q = queue.Queue()               # 인식된 일본어 (번역 대기)
    ui_q = queue.Queue()                 # (일본어, 한국어) → 자막창

    # 1) Whisper 모델 로드 (처음 실행하면 모델을 자동으로 내려받음)
    print(f"[1/3] 음성 인식 모델({args.model}) 불러오는 중... "
          "(처음이면 다운로드에 몇 분 걸릴 수 있어요)")
    recognizer = SpeechRecognizer(model_size=args.model,
                                  device=args.asr_device,
                                  source_lang=args.source)
    print(f"      완료! (실행 장치: {recognizer.device.upper()})")

    # 2) 번역기 준비
    print(f"[2/3] 번역기 준비 중... ({args.source} → {args.target})")
    translator = Translator(source=args.source, target=args.target)

    # 3) 오디오 장치
    device = find_device(args.device, use_mic=args.mic)
    print(f"[3/3] 소리 캡처 장치: {device.name}")
    print("-" * 60)
    print("방송 소리가 들리면 자동으로 자막이 나옵니다. 종료: ESC 또는 Ctrl+C")
    print("-" * 60)

    log_file = open(args.log, "a", encoding="utf-8") if args.log else None

    capture = AudioCapture(device, segment_q, stop_event,
                           vad_threshold=args.vad_threshold)

    def asr_loop():
        last_text = ""
        while not stop_event.is_set():
            try:
                audio = segment_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                text = recognizer.transcribe(audio)
            except Exception as e:
                print(f"(음성 인식 오류: {e})")
                continue
            if text and text != last_text:
                last_text = text
                text_q.put(text)

    def translate_loop():
        while not stop_event.is_set():
            try:
                ja = text_q.get(timeout=0.2)
            except queue.Empty:
                continue
            ko = translator.translate(ja)
            if ko is None:
                ko = "(번역 실패 — 인터넷 연결을 확인하세요)"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {ja}")
            print(f"         → {ko}")
            if log_file:
                log_file.write(f"[{ts}] {ja}\n[{ts}] → {ko}\n")
                log_file.flush()
            ui_q.put((ja, ko))

    asr_thread = threading.Thread(target=asr_loop, daemon=True, name="asr")
    translate_thread = threading.Thread(target=translate_loop, daemon=True,
                                        name="translate")
    capture.start()
    asr_thread.start()
    translate_thread.start()

    try:
        if args.no_overlay:
            # 자막창 없이 콘솔에만 출력
            while not stop_event.is_set():
                stop_event.wait(timeout=0.5)
        else:
            from .overlay import SubtitleOverlay
            overlay = SubtitleOverlay(ui_q, stop_event,
                                      font_scale=args.font_scale,
                                      show_japanese=not args.no_japanese)
            overlay.run()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        # 작업 스레드가 하던 일을 마칠 때까지 잠깐 기다린다 (로그 파일 충돌 방지)
        asr_thread.join(timeout=2)
        translate_thread.join(timeout=2)
        if capture.error:
            print(f"\n오디오 캡처 중 오류가 발생했습니다: {capture.error}")
            print("python main.py --list-devices 로 장치를 확인해 보세요.")
        if log_file:
            log_file.close()
        print("\n번역기를 종료합니다. 또 만나요! 👋")
