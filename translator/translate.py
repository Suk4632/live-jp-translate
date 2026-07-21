"""구글 번역(무료, API 키 불필요)을 이용한 번역 모듈."""

import time


class Translator:
    """일본어 → 한국어 번역기. 실패하면 잠깐 기다렸다가 다시 시도한다."""

    def __init__(self, source="ja", target="ko"):
        from deep_translator import GoogleTranslator
        self._translator = GoogleTranslator(source=source, target=target)

    def translate(self, text, retries=3):
        """번역된 문자열을 반환한다. 계속 실패하면 None."""
        for attempt in range(retries):
            try:
                result = self._translator.translate(text)
                if result:
                    return result.strip()
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        return None
