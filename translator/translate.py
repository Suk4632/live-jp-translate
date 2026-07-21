"""번역. 기본은 Google, --engine deepl 사용 시 실패하면 Google로 폴백."""

import time


class Translator:
    def __init__(self, source="ja", target="ko", engine="google", deepl_key=None):
        from deep_translator import GoogleTranslator

        self._google = GoogleTranslator(source=source, target=target)
        self._primary = self._google
        self.engine = "google"

        if engine == "deepl":
            if not deepl_key:
                raise SystemExit(
                    "DeepL 엔진에는 API 키가 필요합니다: --deepl-key KEY "
                    "(발급 방법은 README 참고)")
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
        """번역 결과 문자열, 실패 시 None."""
        result = self._try(self._primary, text, retries)
        if result is None and self._primary is not self._google:
            result = self._try(self._google, text, retries)
        return result
