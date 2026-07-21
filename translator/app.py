"""파이프라인 조립: 캡처 -> 인식 -> 번역 -> 자막.

발화 중에는 partial 자막을 계속 갱신하고 문장이 끝나면 final로 교체한다.
처리가 밀리면 오래된 partial은 버리고 최신 것만 처리해 지연이 쌓이지 않게 한다.
"""

import datetime
import queue
import threading

from .audio import AudioCapture, find_device
from .asr import SpeechRecognizer
from .translate import Translator


def _drain_latest(q, first_item):
    """큐를 비우면서 final은 순서대로 모두 유지, partial은 최신 하나만 남긴다."""
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
        if latest[1] not in final_seqs:
            keep.append(latest)
    return keep


def run(args):
    stop_event = threading.Event()
    segment_q = queue.Queue(maxsize=8)
    text_q = queue.Queue()
    ui_q = queue.Queue()

    print(f"음성 인식 모델({args.model}) 로드 중... 처음이면 다운로드에 몇 분 걸립니다.")
    recognizer = SpeechRecognizer(model_size=args.model,
                                  device=args.asr_device,
                                  source_lang=args.source)
    print(f"모델 준비 완료 (장치: {recognizer.device})")

    translator = Translator(source=args.source, target=args.target,
                            engine=args.engine, deepl_key=args.deepl_key)
    print(f"번역 엔진: {translator.engine} ({args.source} -> {args.target})")

    device = find_device(args.device, use_mic=args.mic)
    print(f"캡처 장치: {device.name}")
    print("방송 소리가 들리면 자막이 표시됩니다. 종료: ESC 또는 Ctrl+C")

    log_file = open(args.log, "a", encoding="utf-8") if args.log else None

    # 자막창이 없으면 partial을 보여줄 곳이 없다
    partial_interval = 0 if args.no_overlay else args.partial_interval

    capture = AudioCapture(device, segment_q, stop_event,
                           vad_threshold=args.vad_threshold,
                           partial_interval=partial_interval)

    def asr_loop():
        last = {}
        while not stop_event.is_set():
            try:
                first = segment_q.get(timeout=0.2)
            except queue.Empty:
                continue
            for kind, seq, audio in _drain_latest(segment_q, first):
                if stop_event.is_set():
                    break
                try:
                    text = recognizer.transcribe(audio,
                                                 accurate=(kind == "final"))
                except Exception as e:
                    print(f"음성 인식 오류: {e}")
                    continue
                if text and text != last.get(kind):
                    last[kind] = text
                    text_q.put((kind, seq, text))

    def translate_loop():
        disp_seq = -1
        disp_final = False
        while not stop_event.is_set():
            try:
                first = text_q.get(timeout=0.2)
            except queue.Empty:
                continue
            for kind, seq, ja in _drain_latest(text_q, first):
                if stop_event.is_set():
                    break
                is_final = kind == "final"
                # 이미 지나간 문장이거나 확정된 문장의 partial이면 무시
                if seq < disp_seq or (seq == disp_seq and disp_final
                                      and not is_final):
                    continue
                ko = translator.translate(ja)
                if ko is None:
                    ko = "(번역 실패 - 인터넷 연결 확인)"
                disp_seq, disp_final = seq, is_final
                if is_final:
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts}] {ja}")
                    print(f"         -> {ko}")
                    if log_file:
                        try:
                            log_file.write(f"[{ts}] {ja}\n[{ts}] -> {ko}\n")
                            log_file.flush()
                        except ValueError:
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
        asr_thread.join(timeout=2)
        translate_thread.join(timeout=2)
        if capture.error:
            print(f"오디오 캡처 오류: {capture.error}")
            print("--list-devices로 장치를 확인해 보세요.")
        if log_file:
            log_file.close()
        print("종료합니다.")
