"""faster-whisper를 이용한 일본어 음성 인식 모듈."""

import os

import numpy as np

# Whisper가 무음/음악 구간에서 자주 지어내는(환각) 문장들 — 자막에서 걸러낸다
# (뒤쪽 문장부호를 뗀 형태로 비교한다)
_HALLUCINATIONS = {
    "ご視聴ありがとうございました",
    "ご視聴ありがとうございます",
    "ご覧いただきありがとうございます",
    "チャンネル登録お願いします",
    "チャンネル登録よろしくお願いします",
    "おやすみなさい",
    "字幕視聴ありがとうございました",
    "本日はご視聴いただきありがとうございます",
}

_JUNK_CHARS = set("♪♫♬・.。、,!?!?~〜ー- 　")


def _is_hallucination(text):
    return text.rstrip("。.!!??  　") in _HALLUCINATIONS


class SpeechRecognizer:
    """Whisper 모델을 불러와 오디오 세그먼트를 일본어 텍스트로 바꾼다."""

    def __init__(self, model_size="small", device="auto", source_lang="ja"):
        from faster_whisper import WhisperModel

        self.source_lang = source_lang
        self.device = None

        cpu_threads = min(8, os.cpu_count() or 4)

        if device in ("auto", "cuda"):
            # 그래픽카드(CUDA)가 있으면 훨씬 빠르다 — 안 되면 CPU로 자동 전환
            try:
                model = WhisperModel(model_size, device="cuda",
                                     compute_type="float16")
                self._warmup(model)  # 로드는 됐지만 실행이 안 되는 경우까지 확인
                self.model = model
                self.device = "cuda"
            except Exception:
                if device == "cuda":
                    raise SystemExit(
                        "CUDA(그래픽카드)로 모델을 실행하지 못했습니다. "
                        "--asr-device cpu 로 실행해 보세요."
                    )
        if self.device is None:
            self.model = WhisperModel(model_size, device="cpu",
                                      compute_type="int8",
                                      cpu_threads=cpu_threads)
            self.device = "cpu"
            self._warmup(self.model)  # 첫 자막이 빨리 나오도록 미리 예열

    def _warmup(self, model):
        segments, _ = model.transcribe(
            np.zeros(8000, dtype=np.float32), language=self.source_lang,
            beam_size=1)
        for _ in segments:
            pass

    def transcribe(self, audio, accurate=False):
        """16kHz float32 오디오를 텍스트로 변환한다. 인식 실패 시 빈 문자열.

        accurate=True면 정밀 모드(beam 5) — 확정 자막용으로 더 정확하게 인식.
        False면 빠른 모드(beam 1) — 말하는 중 부분 자막용.
        """
        audio = np.asarray(audio, dtype=np.float32)
        segments, _info = self.model.transcribe(
            audio,
            language=self.source_lang,
            beam_size=5 if accurate else 1,
            vad_filter=True,                  # 무음 구간 자동 제거
            condition_on_previous_text=False, # 환각(반복) 방지
            without_timestamps=True,          # 타임스탬프 생략 → 더 빠름
        )

        texts = []
        for seg in segments:
            if seg.no_speech_prob > 0.8:
                continue
            t = seg.text.strip()
            if t and not _is_hallucination(t):
                texts.append(t)

        text = "".join(texts).strip()
        if not text or _is_hallucination(text):
            return ""
        if all(ch in _JUNK_CHARS for ch in text):
            return ""
        return text
