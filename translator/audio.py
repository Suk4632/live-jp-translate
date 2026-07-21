"""스피커(루프백) 또는 마이크에서 소리를 캡처해 음성 구간 단위로 잘라내는 모듈.

유튜브 라이브 소리를 잡으려면 "스피커 루프백"을 사용한다.
(컴퓨터에서 재생되는 소리를 그대로 녹음하는 기능 — Windows는 기본 지원)

큐에 넣는 항목 형식: (kind, seq, 오디오배열)
  kind = "partial" : 아직 말하는 중 — 지금까지 모인 소리 (자막 즉시 갱신용)
  kind = "final"   : 문장이 끝남 — 확정된 구간
  seq  = 문장(세그먼트) 번호. 같은 문장의 partial과 final은 같은 번호.
"""

import threading
import queue
import warnings

import numpy as np
import soundcard as sc

# soundcard가 녹음 중 가끔 내는 경고(자막 품질에 영향 없음)를 숨긴다
warnings.filterwarnings("ignore", message="data discontinuity in recording")

CAPTURE_RATE = 48000   # 캡처 샘플레이트 (대부분의 장치가 지원)
TARGET_RATE = 16000    # Whisper 입력 샘플레이트
BLOCK_SECONDS = 0.1    # 한 번에 읽는 오디오 길이


def list_devices():
    """사용 가능한 오디오 장치를 출력한다."""
    print("=== 스피커 루프백 (방송 소리를 잡을 때 사용) ===")
    found_loopback = False
    for m in sc.all_microphones(include_loopback=True):
        if getattr(m, "isloopback", False) or "monitor" in m.name.lower():
            found_loopback = True
            print(f"  [루프백] {m.name}")
    if not found_loopback:
        print("  (루프백 장치가 없습니다 — README의 '소리가 안 잡혀요' 항목을 참고하세요)")

    print("=== 마이크 ===")
    for m in sc.all_microphones(include_loopback=False):
        print(f"  [마이크] {m.name}")

    try:
        print(f"=== 기본 스피커: {sc.default_speaker().name} ===")
    except Exception:
        pass


def find_device(name=None, use_mic=False):
    """녹음에 사용할 장치를 고른다.

    name  -- 장치 이름 일부(대소문자 무시). 없으면 기본 장치 사용.
    use_mic -- True면 스피커 루프백 대신 마이크를 사용.
    """
    if name:
        candidates = sc.all_microphones(include_loopback=True)
        for m in candidates:
            if name.lower() in m.name.lower():
                return m
        raise SystemExit(
            f"'{name}' 이름을 가진 장치를 찾지 못했습니다.\n"
            "python main.py --list-devices 로 장치 목록을 확인해 보세요."
        )

    if use_mic:
        return sc.default_microphone()

    # 기본 스피커의 루프백 (컴퓨터에서 나는 소리를 그대로 캡처)
    try:
        speaker = sc.default_speaker()
        return sc.get_microphone(id=str(speaker.name), include_loopback=True)
    except Exception:
        pass

    # 루프백을 못 찾으면 이름에 monitor가 들어간 장치(리눅스)라도 찾아본다
    for m in sc.all_microphones(include_loopback=True):
        if getattr(m, "isloopback", False) or "monitor" in m.name.lower():
            return m

    raise SystemExit(
        "스피커 루프백 장치를 찾지 못했습니다.\n"
        "python main.py --list-devices 로 장치를 확인하고 --device 옵션으로 지정하거나,\n"
        "마이크로 잡으려면 --mic 옵션을 사용하세요. (자세한 내용은 README 참고)"
    )


def _resample(block, src_rate=CAPTURE_RATE, dst_rate=TARGET_RATE):
    """선형 보간으로 샘플레이트를 변환한다 (음성 인식 용도로 충분한 품질)."""
    if src_rate == dst_rate:
        return block.astype(np.float32)
    n_out = int(len(block) * dst_rate / src_rate)
    x_old = np.arange(len(block), dtype=np.float64)
    x_new = np.linspace(0.0, len(block), n_out, endpoint=False)
    return np.interp(x_new, x_old, block).astype(np.float32)


class AudioCapture(threading.Thread):
    """오디오를 계속 녹음하면서 말소리 구간을 segment_queue로 보낸다.

    - 말하는 도중에도 partial_interval초마다 지금까지의 소리를 "partial"로 보내
      자막이 실시간으로 갱신되게 한다.
    - 무음이 이어지면 문장이 끝난 것으로 보고 "final"을 보낸다.
    - 말이 너무 길면 max_segment_sec에서 강제로 잘라 "final"을 보낸다.
    """

    def __init__(self, device, segment_queue, stop_event,
                 vad_threshold=0.01, silence_sec=0.45, min_speech_sec=0.3,
                 max_segment_sec=6.0, pre_roll_sec=0.3, partial_interval=1.0):
        super().__init__(daemon=True, name="audio-capture")
        self.device = device
        self.segment_queue = segment_queue
        self.stop_event = stop_event
        self.vad_threshold = vad_threshold
        self.silence_blocks = max(1, int(silence_sec / BLOCK_SECONDS))
        self.min_speech_blocks = max(1, int(min_speech_sec / BLOCK_SECONDS))
        self.max_segment_blocks = max(2, int(max_segment_sec / BLOCK_SECONDS))
        self.pre_roll_blocks = max(1, int(pre_roll_sec / BLOCK_SECONDS))
        self.partial_blocks = (max(1, int(partial_interval / BLOCK_SECONDS))
                               if partial_interval > 0 else 0)
        self.error = None
        self._noise_floor = 0.005  # 배경 소음 크기 추정치 (계속 갱신됨)

    def _effective_threshold(self):
        return max(self.vad_threshold, self._noise_floor * 3.0)

    def _put_final(self, blocks, seq):
        segment = np.concatenate(blocks)
        try:
            self.segment_queue.put_nowait(("final", seq, segment))
        except queue.Full:
            # 인식이 밀리면 가장 오래된 항목을 버리고 실시간을 유지한다
            try:
                self.segment_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.segment_queue.put_nowait(("final", seq, segment))
            except queue.Full:
                pass

    def _put_partial(self, blocks, seq):
        # partial은 어차피 곧 다음 것이 오므로, 큐가 차 있으면 그냥 버린다
        try:
            self.segment_queue.put_nowait(("partial", seq, np.concatenate(blocks)))
        except queue.Full:
            pass

    def run(self):
        numframes = int(CAPTURE_RATE * BLOCK_SECONDS)
        pre_roll = []       # 말 시작 직전의 소리 (첫 음절이 잘리지 않도록)
        seg_blocks = []     # 현재 세그먼트에 모인 블록들
        speech_count = 0    # 세그먼트 안에서 실제 말소리였던 블록 수
        silence_count = 0   # 연속 무음 블록 수
        since_partial = 0   # 마지막 partial 전송 후 지난 블록 수
        in_speech = False
        seq = 0             # 문장(세그먼트) 번호

        try:
            with self.device.recorder(samplerate=CAPTURE_RATE, channels=1) as rec:
                while not self.stop_event.is_set():
                    data = rec.record(numframes=numframes)
                    mono = data.mean(axis=1) if data.ndim > 1 else data
                    block = _resample(mono)
                    rms = float(np.sqrt(np.mean(block ** 2)))
                    threshold = self._effective_threshold()
                    is_speech = rms >= threshold

                    if not is_speech:
                        # 무음 블록으로 배경 소음 크기를 천천히 갱신
                        self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms

                    if not in_speech:
                        if is_speech:
                            in_speech = True
                            seg_blocks = list(pre_roll) + [block]
                            speech_count = 1
                            silence_count = 0
                            since_partial = 0
                        else:
                            pre_roll.append(block)
                            if len(pre_roll) > self.pre_roll_blocks:
                                pre_roll.pop(0)
                        continue

                    # 말하는 중
                    seg_blocks.append(block)
                    since_partial += 1
                    if is_speech:
                        speech_count += 1
                        silence_count = 0
                    else:
                        silence_count += 1

                    if silence_count >= self.silence_blocks:
                        # 문장이 끝났다 → 확정(final) 전송
                        if speech_count >= self.min_speech_blocks:
                            self._put_final(seg_blocks, seq)
                            seq += 1
                        pre_roll = seg_blocks[-self.pre_roll_blocks:]
                        seg_blocks = []
                        speech_count = 0
                        silence_count = 0
                        since_partial = 0
                        in_speech = False
                    elif len(seg_blocks) >= self.max_segment_blocks:
                        # 말이 너무 길다 → 일단 확정하고 이어서 계속 녹음
                        self._put_final(seg_blocks, seq)
                        seq += 1
                        seg_blocks = seg_blocks[-2:]  # 약간 겹치게 남겨 단어 잘림을 줄인다
                        speech_count = 0
                        silence_count = 0
                        since_partial = 0
                    elif (self.partial_blocks
                          and since_partial >= self.partial_blocks
                          and speech_count >= self.min_speech_blocks):
                        # 아직 말하는 중 → 지금까지 내용을 부분(partial) 자막으로 전송
                        self._put_partial(seg_blocks, seq)
                        since_partial = 0
        except Exception as e:  # 장치 뽑힘 등
            self.error = e
            self.stop_event.set()
