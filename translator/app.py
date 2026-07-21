"""전체 파이프라인 조립: 오디오 캡처 → 음성 인식 → 번역 → 자막 표시.

실시간성을 위해 "부분(partial) 자막"을 지원한다:
- 말하는 도중에도 1초마다 지금까지의 내용을 인식·번역해 자막을 갱신
- 문장이 끝나면 확정(final) 자막으로 교체
- 처리가 밀리면 오래된 partial은 건너뛰고 항상 최신 것만 처리 (지연 누적 방지)
"""

import datetime
import queue
import threading

from .audio import AudioCapture, find_device
from .asr import SpeechRecognizer
from .translate import Translator


def _drain_latest(q, first_item):
    """큐에 쌓인 항목을 모두 꺼내서, final은 순서대로 전부 유지하고
    partial은 가장 최신 것 하나만 남긴다. (밀림 방지의 핵심)

    항목 형식: (kind, seq, payload)
    """
    items = [first_item]
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            break
    finals = [it for it in items if it[0] == "final"]
    partials = [it for it in items if it[0] == "partial"]
    keep = list(finals)
    if partials:
        latest = partials[-1]
        final_seqs = {seq for _, seq, _ in finals}
        # 이미 확정된 문장의 partial은 버린다 (확정본이 곧 표시되므로)
        if latest[1] not in final_seqs:
            keep.append(latest)
    return keep


def run(args):
    print("=" * 60)
    print("  일본어 라이브 방송 실시간 번역기")
    print("=" * 60)

    stop_event = threading.Event()
    segment_q = queue.Queue(maxsize=8)   # (kind, seq, 오디오) — 인식 대기
    text_q = queue.Queue()               # (kind, seq, 일본어) — 번역 대기
    ui_q = queue.Queue()                 # (일본어, 한국어, partial여부) → 자막창

    # 1) Whisper 모델 로드 (처음 실행하면 모델을 자동으로 내려받음)
    print(f"[1/3] 음성 인식 모델({args.model}) 불러오는 중... "
          "(처음이면 다운로드에 몇 분 걸릴 수 있어요)")
    recognizer = SpeechRecognizer(model_size=args.model,
                                  device=args.asr_device,
                                  source_lang=args.source)
    print(f"      완료! (실행 장치: {recognizer.device.upper()})")

    # 2) 번역기 준비
    translator = Translator(source=args.source, target=args.target,
                            engine=args.engine, deepl_key=args.deepl_key)
    print(f"[2/3] 번역기 준비 완료 ({args.source} → {args.target}, "
          f"엔진: {translator.engine})")

    # 3) 오디오 장치
    device = find_device(args.device, use_mic=args.mic)
    print(f"[3/3] 소리 캡처 장치: {device.name}")
    print("-" * 60)
    print("방송 소리가 들리면 자동으로 자막이 나옵니다. 종료: ESC 또는 Ctrl+C")
    print("-" * 60)

    log_file = open(args.log, "a", encoding="utf-8") if args.log else None

    # 자막창이 없으면 partial 자막은 보여줄 곳이 없으므로 끈다
    partial_interval = 0 if args.no_overlay else args.partial_interval

    capture = AudioCapture(device, segment_q, stop_event,
                           vad_threshold=args.vad_threshold,
                           partial_interval=partial_interval)

    def asr_loop():
        last = {}  # kind -> 마지막으로 보낸 텍스트 (중복 전송 방지)
        while not stop_event.is_set():
            try:
                first = segment_q.get(timeout=0.2)
            except queue.Empty:
                continue
            for kind, seq, audio in _drain_latest(segment_q, first):
                if stop_event.is_set():
                    break
                try:
                    # 확정(final) 자막은 정밀 모드로 한 번 더 정확하게 인식한다
                    text = recognizer.transcribe(audio, accurate=(kind == "final"))
                except Exception as e:
                    print(f"(음성 인식 오류: {e})")
                    continue
                if text and text != last.get(kind):
                    last[kind] = text
                    text_q.put((kind, seq, text))

    def translate_loop():
        disp_seq = -1      # 지금 화면에 떠 있는 자막의 문장 번호
        disp_final = False  # 그 자막이 확정본인지
        while not stop_event.is_set():
            try:
                first = text_q.get(timeout=0.2)
            except queue.Empty:
                continue
            for kind, seq, ja in _drain_latest(text_q, first):
                if stop_event.is_set():
                    break
                is_final = kind == "final"
                # 더 오래된 문장이거나, 이미 확정된 문장의 partial이면 건너뛴다
                if seq < disp_seq or (seq == disp_seq and disp_final and not is_final):
                    continue
                ko = translator.translate(ja)
                if ko is None:
                    ko = "(번역 실패 — 인터넷 연결을 확인하세요)"
                disp_seq, disp_final = seq, is_final
                if is_final:
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts}] {ja}")
                    print(f"         → {ko}")
                    if log_file:
                        try:
                            log_file.write(f"[{ts}] {ja}\n[{ts}] → {ko}\n")
                            log_file.flush()
                        except ValueError:  # 종료 직후 파일이 먼저 닫힌 경우
                            pass
                if not args.no_overlay:
                    ui_q.put((ja, ko, not is_final))

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
