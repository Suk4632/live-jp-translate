"""일본어 라이브 방송 실시간 번역기 — 실행 파일.

사용법:
    python main.py                # 기본 실행 (스피커 소리 → 한국어 자막)
    python main.py --list-devices # 오디오 장치 목록 보기
    python main.py --model tiny   # 컴퓨터가 느리면 작은 모델 사용
"""

import argparse
import os
import sys

# 모델 다운로드 시 헷갈리는 경고문(심링크/미로그인 안내)이 안 나오게 한다
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")


def build_parser():
    p = argparse.ArgumentParser(
        prog="jp-live-translator",
        description="유튜브 라이브 등 컴퓨터에서 나는 일본어 소리를 "
                    "실시간으로 한국어 자막으로 보여줍니다.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--list-devices", action="store_true",
                   help="사용 가능한 오디오 장치 목록을 출력하고 종료")
    p.add_argument("--device", type=str, default=None,
                   help="사용할 오디오 장치 이름(일부만 적어도 됨)")
    p.add_argument("--mic", action="store_true",
                   help="스피커 소리 대신 마이크 소리를 번역")
    p.add_argument("--model", type=str, default="small",
                   choices=["tiny", "base", "small", "medium", "large-v3"],
                   help="Whisper 모델 크기 (클수록 정확하지만 느림)")
    p.add_argument("--asr-device", type=str, default="auto",
                   choices=["auto", "cpu", "cuda"],
                   help="음성 인식 실행 장치 (auto: 그래픽카드 있으면 자동 사용)")
    p.add_argument("--source", type=str, default="ja",
                   help="원본 언어 코드 (일본어: ja)")
    p.add_argument("--target", type=str, default="ko",
                   help="번역할 언어 코드 (한국어: ko)")
    p.add_argument("--no-overlay", action="store_true",
                   help="자막창 없이 콘솔(검은 창)에만 출력")
    p.add_argument("--no-japanese", action="store_true",
                   help="자막창에 일본어 원문을 표시하지 않음")
    p.add_argument("--font-scale", type=float, default=1.0,
                   help="자막 글자 크기 배율 (예: 1.5)")
    p.add_argument("--vad-threshold", type=float, default=0.01,
                   help="말소리 감지 민감도 (자막이 안 나오면 0.005로 낮춰보세요)")
    p.add_argument("--partial-interval", type=float, default=1.0,
                   help="말하는 도중 자막 갱신 주기(초). 0이면 문장이 끝난 뒤에만 표시")
    p.add_argument("--log", type=str, default=None,
                   help="자막을 저장할 파일 경로 (예: --log 방송기록.txt)")
    return p


def main():
    # 한국어 Windows 콘솔(cp949)에서 이모지 등으로 프로그램이 죽지 않게 보호
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
