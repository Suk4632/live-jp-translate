@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   일본어 실시간 번역기 - 설치
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)

%PY% --version >nul 2>nul
if errorlevel 1 (
    echo [오류] 파이썬이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 파이썬을 먼저 설치하세요.
    echo 설치할 때 "Add Python to PATH" 체크박스를 꼭 켜야 합니다!
    pause
    exit /b 1
)

echo 필요한 라이브러리를 설치합니다. 몇 분 걸릴 수 있어요...
echo.
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [오류] 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 실행해 보세요.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   설치 완료!
echo   이제 "실행.bat" 을 더블클릭하면 번역기가 시작됩니다.
echo ============================================
pause
