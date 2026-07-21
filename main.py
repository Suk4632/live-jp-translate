"""일본어 라이브 방송 실시간 번역기 진입점."""

import argparse
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")


def build_parser():
    p = argparse.ArgumentParser(
        prog="jp-live-translator",
        description="시스템 사운드의 일본어 음성을 실시간 한국어 자막으로 표시",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--list-devices", action="store_true",
                   help="오디오 장치 목록 출력 후 종료")
    p.add_argument("--device", default=None,
                   help="사용할 오디오 장치 이름 (부분 일치)")
    p.add_argument("--mic", action="store_true",
                   help="스피커 루프백 대신 마이크 입력 사용")
    p.add_argument("--model", default="small",
                   choices=["tiny", "base", "small", "medium", "large-v3"],
                   help="Whisper 모델 크기")
    p.add_argument("--asr-device", default="auto",
                   choices=["auto", "cpu", "cuda"],
                   help="음성 인식 실행 장치")
    p.add_argument("--source", default="ja", help="원본 언어 코드")
    p.add_argument("--target", default="ko", help="번역 대상 언어 코드")
    p.add_argument("--engine", default="google", choices=["google", "deepl"],
                   help="번역 엔진 (deepl은 --deepl-key 필요)")
    p.add_argument("--deepl-key", default=None, help="DeepL API 키")
    p.add_argument("--no-overlay", action="store_true",
                   help="자막창 없이 콘솔 출력만 사용")
    p.add_argument("--no-japanese", action="store_true",
                   help="자막창에 일본어 원문 숨김")
    p.add_argument("--font-scale", type=float, default=1.0,
                   help="자막 글자 크기 배율")
    p.add_argument("--vad-threshold", type=float, default=0.01,
                   help="음성 감지 임계값 (자막이 안 나오면 낮춰볼 것)")
    p.add_argument("--partial-interval", type=float, default=1.0,
                   help="발화 중 자막 갱신 주기(초), 0이면 비활성화")
    p.add_argument("--log", default=None, help="자막 로그 파일 경로")
    return p


def main():
    # cp949 콘솔에서 출력 문자로 죽지 않도록
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args()

    if args.list_devices:
        from translator.audio import list_devices
        list_devices()
        return 0

    from translator.app import run
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
