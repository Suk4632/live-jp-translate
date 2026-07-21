"""faster-whisper 기반 음성 인식."""

import os

import numpy as np

# 무음/음악 구간에서 Whisper가 자주 만들어내는 상투 문구 (끝 문장부호 제거 후 비교)
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
    def __init__(self, model_size="small", device="auto", source_lang="ja"):
        from faster_whisper import WhisperModel

        self.source_lang = source_lang
        self.device = None
        cpu_threads = min(8, os.cpu_count() or 4)

        if device in ("auto", "cuda"):
            try:
                model = WhisperModel(model_size, device="cuda",
                                     compute_type="float16")
                self._warmup(model)  # 로드는 되지만 실행이 안 되는 환경 걸러냄
                self.model = model
                self.device = "cuda"
            except Exception:
                if device == "cuda":
                    raise SystemExit(
                        "CUDA로 모델을 실행할 수 없습니다. "
                        "--asr-device cpu로 실행하세요.")
        if self.device is None:
            self.model = WhisperModel(model_size, device="cpu",
                                      compute_type="int8",
                                      cpu_threads=cpu_threads)
            self.device = "cpu"
            self._warmup(self.model)

    def _warmup(self, model):
        segments, _ = model.transcribe(
            np.zeros(8000, dtype=np.float32), language=self.source_lang,
            beam_size=1)
        for _ in segments:
            pass

    def transcribe(self, audio, accurate=False):
        """오디오(16kHz float32)를 텍스트로 변환. accurate=True면 beam 5."""
        audio = np.asarray(audio, dtype=np.float32)
        segments, _info = self.model.transcribe(
            audio,
            language=self.source_lang,
            beam_size=5 if accurate else 1,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
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
