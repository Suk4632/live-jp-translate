"""faster-whisper를 이용한 일본어 음성 인식 모듈."""

import numpy as np

# Whisper가 무음/음악 구간에서 자주 지어내는(환각) 문장들 — 자막에서 걸러낸다
_HALLUCINATIONS = {
    "ご視聴ありがとうございました",
    "ご視聴ありがとうございました。",
    "ご視聴ありがとうございます",
    "ご視聴ありがとうございます。",
    "チャンネル登録お願いします",
    "チャンネル登録お願いします。",
    "おやすみなさい",
    "字幕視聴ありがとうございました",
    "本日はご視聴いただきありがとうございます",
}

_JUNK_CHARS = set("♪♫♬・.。、,!?!?~〜ー- 　")


class SpeechRecognizer:
    """Whisper 모델을 불러와 오디오 세그먼트를 일본어 텍스트로 바꾼다."""

    def __init__(self, model_size="small", device="auto", source_lang="ja"):
        from faster_whisper import WhisperModel

        self.source_lang = source_lang
        self.device = None

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
                                      compute_type="int8")
            self.device = "cpu"
            self._warmup(self.model)  # 첫 자막이 빨리 나오도록 미리 예열

    def _warmup(self, model):
        segments, _ = model.transcribe(
            np.zeros(8000, dtype=np.float32), language=self.source_lang,
            beam_size=1)
        for _ in segments:
            pass

    def transcribe(self, audio):
        """16kHz float32 오디오를 텍스트로 변환한다. 인식 실패 시 빈 문자열."""
        audio = np.asarray(audio, dtype=np.float32)
        segments, _info = self.model.transcribe(
            audio,
            language=self.source_lang,
            beam_size=1,                      # 속도 우선 (실시간용)
            vad_filter=True,                  # 무음 구간 자동 제거
            condition_on_previous_text=False, # 환각(반복) 방지
        )

        texts = []
        for seg in segments:
            if seg.no_speech_prob > 0.8:
                continue
            t = seg.text.strip()
            if t:
                texts.append(t)

        text = "".join(texts).strip()
        if not text or text in _HALLUCINATIONS:
            return ""
        if all(ch in _JUNK_CHARS for ch in text):
            return ""
        return text
