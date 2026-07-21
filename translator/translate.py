"""번역 모듈.

기본은 구글 번역(무료, API 키 불필요).
--engine deepl 로 DeepL을 쓰면 일→한 번역이 훨씬 자연스럽다
(무료 API 키 필요, 월 50만 자 무료 — README 참고).
DeepL이 실패하면 자동으로 구글 번역으로 넘어간다.
"""

import time


class Translator:
    """일본어 → 한국어 번역기. 실패하면 잠깐 기다렸다가 다시 시도한다."""

    def __init__(self, source="ja", target="ko", engine="google", deepl_key=None):
        from deep_translator import GoogleTranslator

        self._google = GoogleTranslator(source=source, target=target)
        self._primary = self._google
        self.engine = "google"

        if engine == "deepl":
            if not deepl_key:
                raise SystemExit(
                    "DeepL 엔진을 쓰려면 API 키가 필요합니다: --deepl-key 발급받은키\n"
                    "무료 키 발급 방법은 README의 '번역 품질 높이기'를 참고하세요."
                )
            from deep_translator import DeeplTranslator
            self._primary = DeeplTranslator(api_key=deepl_key, source=source,
                                            target=target, use_free_api=True)
            self.engine = "deepl"

    def _try(self, translator, text, retries):
        for attempt in range(retries):
            try:
                result = translator.translate(text)
                if result:
                    return result.strip()
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        return None

    def translate(self, text, retries=2):
        """번역된 문자열을 반환한다. 계속 실패하면 None."""
        result = self._try(self._primary, text, retries)
        if result is None and self._primary is not self._google:
            # DeepL 실패(키 오류/무료 한도 초과 등) → 구글 번역으로 대체
            result = self._try(self._google, text, retries)
        return result
