# live-jp-translate

컴퓨터에서 재생 중인 일본어 음성(유튜브 라이브 등)을 실시간으로 인식해서
한국어 자막으로 보여주는 프로그램.

```
시스템 사운드 캡처 -> Whisper 음성 인식 -> 번역(Google/DeepL) -> 화면 오버레이 자막
```

- 발화 중에도 약 1초 간격으로 자막이 갱신되고, 문장이 끝나면 확정 자막으로 교체됨
- 자막창은 항상 위에 떠 있고 드래그로 위치 이동 가능
- 기본 설정은 API 키 없이 동작 (번역 요청에만 인터넷 사용)

## 설치 (Windows)

1. https://www.python.org/downloads/ 에서 파이썬 설치
   - 설치 첫 화면의 "Add Python to PATH" 체크 필수
2. `설치.bat` 실행

## 사용

1. 유튜브 라이브를 켠다 (소리가 재생되고 있어야 함)
2. `실행.bat` 실행. 최초 실행 시 모델 다운로드로 몇 분 걸림 (약 500MB, 한 번만)
3. 자막창이 뜨고, 음성이 들리면 자막이 표시됨

- 발화 중 자막은 흐린 색 + `...`, 확정 자막은 흰색
- 종료: ESC 또는 자막창 우상단 x
- 이어폰을 써도 됨 (시스템 내부에서 소리를 캡처하므로)

## 옵션

```
python main.py --model tiny              # 컴퓨터가 느릴 때 (속도 우선)
python main.py --model medium            # GPU 있을 때 (정확도 우선)
python main.py --font-scale 1.5          # 자막 크게
python main.py --no-japanese             # 한국어만 표시
python main.py --no-overlay              # 자막창 없이 콘솔만
python main.py --log 기록.txt            # 자막 파일 저장
python main.py --partial-interval 0      # 발화 중 자막 갱신 끄기
python main.py --list-devices            # 오디오 장치 목록
python main.py --device "이름"           # 캡처 장치 지정
```

`python`이 안 되면 `py`로 실행.

모델 크기별 특성:

| 모델 | 속도 | 정확도 | 용도 |
|---|---|---|---|
| tiny | 매우 빠름 | 낮음 | 저사양 |
| base | 빠름 | 보통 | 저사양 |
| small | 보통 | 좋음 | 기본값 |
| medium | 느림 | 매우 좋음 | GPU 권장 |
| large-v3 | 매우 느림 | 최고 | GPU 필수 |

NVIDIA GPU가 있으면 자동으로 사용한다.

## 번역 품질 높이기

번역 품질은 인식 정확도와 번역 엔진 품질에서 결정된다.

**모델 키우기** — 효과가 가장 크다. 잘못 알아들으면 번역도 무너진다.
GPU가 있으면 `--model medium` 이상을 권장.

**DeepL 사용** — 구어체 일한 번역이 Google보다 자연스럽다.

1. https://www.deepl.com/pro-api 에서 DeepL API Free 가입 (월 50만 자 무료)
2. 계정 페이지에서 API 키 복사
3. `python main.py --engine deepl --deepl-key 발급받은키`

DeepL 요청이 실패하면 자동으로 Google로 폴백된다.

한계: 게임 용어, 방송 특유의 별명/유행어는 어떤 번역기도 잘 처리하지 못한다.
발화 중 자막(`...`)은 문장이 완성되기 전 결과이므로 확정 자막 기준으로 볼 것.

## 문제 해결

**자막이 안 나옴**
- 방송 소리가 실제로 재생 중인지 확인 (음소거/볼륨)
- `--list-devices`로 장치 확인, 기본 스피커가 아니면 `--device "이름"` 지정
- 소리가 작으면 `--vad-threshold 0.005`

**자막이 늦거나 갱신이 뜸함**
- 인식 속도가 부족한 것. `--model base` 또는 `tiny`로 실행

**"번역 실패" 표시**
- 번역은 인터넷을 사용한다. 연결 상태 확인

**macOS**
- 시스템 사운드 캡처에 가상 오디오 장치(BlackHole 등)가 필요.
  설치 후 `--device "BlackHole"` 지정

**Linux**
- PulseAudio/PipeWire의 monitor 장치를 자동 탐색. 안 되면 `--device "monitor"`

**이상한 상투 문구가 가끔 나옴**
- 무음/음악 구간에서 모델이 만들어내는 문장(환각). 흔한 것은 걸러내지만
  완벽하지 않으며, 노래 구간에서 특히 자주 발생

## 구조

```
main.py             진입점, 옵션 처리
translator/
  audio.py          시스템 사운드 캡처, 발화 구간 분리
  asr.py            Whisper 음성 인식
  translate.py      번역 (Google / DeepL)
  overlay.py        자막 오버레이 창
  app.py            파이프라인 조립
설치.bat            의존성 설치 (Windows)
실행.bat            실행 (Windows)
```
