"""오디오 캡처와 발화 구간 분리.

segment_queue에 (kind, seq, audio) 형태로 넣는다.
kind는 "partial"(발화 진행 중) 또는 "final"(문장 종료), seq는 세그먼트 번호.
"""

import queue
import threading
import warnings

import numpy as np
import soundcard as sc

warnings.filterwarnings("ignore", message="data discontinuity in recording")

CAPTURE_RATE = 48000
TARGET_RATE = 16000
BLOCK_SECONDS = 0.1


def list_devices():
    print("루프백 (시스템 사운드 캡처용):")
    found = False
    for m in sc.all_microphones(include_loopback=True):
        if getattr(m, "isloopback", False) or "monitor" in m.name.lower():
            found = True
            print(f"  {m.name}")
    if not found:
        print("  (없음)")

    print("마이크:")
    for m in sc.all_microphones(include_loopback=False):
        print(f"  {m.name}")

    try:
        print(f"기본 스피커: {sc.default_speaker().name}")
    except Exception:
        pass


def find_device(name=None, use_mic=False):
    if name:
        for m in sc.all_microphones(include_loopback=True):
            if name.lower() in m.name.lower():
                return m
        raise SystemExit(
            f"'{name}' 장치를 찾을 수 없습니다. --list-devices로 확인하세요.")

    if use_mic:
        return sc.default_microphone()

    try:
        speaker = sc.default_speaker()
        return sc.get_microphone(id=str(speaker.name), include_loopback=True)
    except Exception:
        pass

    for m in sc.all_microphones(include_loopback=True):
        if getattr(m, "isloopback", False) or "monitor" in m.name.lower():
            return m

    raise SystemExit(
        "루프백 장치를 찾을 수 없습니다. --list-devices로 확인 후 --device로 "
        "지정하거나, --mic 옵션을 사용하세요.")


def _resample(block, src_rate=CAPTURE_RATE, dst_rate=TARGET_RATE):
    if src_rate == dst_rate:
        return block.astype(np.float32)
    n_out = int(len(block) * dst_rate / src_rate)
    x_old = np.arange(len(block), dtype=np.float64)
    x_new = np.linspace(0.0, len(block), n_out, endpoint=False)
    return np.interp(x_new, x_old, block).astype(np.float32)


class AudioCapture(threading.Thread):
    def __init__(self, device, segment_queue, stop_event,
                 vad_threshold=0.01, silence_sec=0.45, min_speech_sec=0.3,
                 max_segment_sec=8.0, pre_roll_sec=0.3, partial_interval=1.0):
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
        self._noise_floor = 0.005

    def _effective_threshold(self):
        return max(self.vad_threshold, self._noise_floor * 3.0)

    def _put_final(self, blocks, seq):
        segment = np.concatenate(blocks)
        try:
            self.segment_queue.put_nowait(("final", seq, segment))
        except queue.Full:
            # 처리가 밀리면 오래된 것을 버리고 실시간을 유지
            try:
                self.segment_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.segment_queue.put_nowait(("final", seq, segment))
            except queue.Full:
                pass

    def _put_partial(self, blocks, seq):
        try:
            self.segment_queue.put_nowait(("partial", seq, np.concatenate(blocks)))
        except queue.Full:
            pass

    def run(self):
        numframes = int(CAPTURE_RATE * BLOCK_SECONDS)
        pre_roll = []
        seg_blocks = []
        speech_count = 0
        silence_count = 0
        since_partial = 0
        in_speech = False
        seq = 0

        try:
            # channels=1로 열면 WASAPI 루프백에서 깨진 소리가 들어오는
            # soundcard 알려진 버그가 있어 장치 기본 채널로 받아서 다운믹스한다
            with self.device.recorder(samplerate=CAPTURE_RATE) as rec:
                while not self.stop_event.is_set():
                    data = rec.record(numframes=numframes)
                    mono = data.mean(axis=1) if data.ndim > 1 else data
                    block = _resample(mono)
                    rms = float(np.sqrt(np.mean(block ** 2)))
                    is_speech = rms >= self._effective_threshold()

                    if not is_speech:
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

                    seg_blocks.append(block)
                    since_partial += 1
                    if is_speech:
                        speech_count += 1
                        silence_count = 0
                    else:
                        silence_count += 1

                    if silence_count >= self.silence_blocks:
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
                        self._put_final(seg_blocks, seq)
                        seq += 1
                        seg_blocks = seg_blocks[-2:]
                        speech_count = 0
                        silence_count = 0
                        since_partial = 0
                    elif (self.partial_blocks
                          and since_partial >= self.partial_blocks
                          and speech_count >= self.min_speech_blocks):
                        self._put_partial(seg_blocks, seq)
                        since_partial = 0
        except Exception as e:
            self.error = e
            self.stop_event.set()
