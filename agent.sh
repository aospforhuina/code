#!/usr/bin/env bash
#
# agent.sh — AI Coding Pipeline 자동 준비 + 실행
#
# code/ 루트에서 다음처럼 실행하면 libs/ 안에서 필요한 작업을 자동 수행하고
# TUI 를 띄운다:
#
#   bash agent.sh        # 준비 후 TUI 실행
#   bash agent.sh --prepare   # 준비만 하고 실행하지 않음
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBS_DIR="$REPO_DIR/libs"
RUN_TUI=1
if [ "${1:-}" = "--prepare" ]; then
    RUN_TUI=0
fi

cd "$LIBS_DIR"
echo "[agent.sh] 작업 디렉터리: $LIBS_DIR"

# 1) Python 가상환경 생성 (없으면)
if [ ! -d ".venv" ]; then
    echo "[agent.sh] 가상환경 생성 중..."
    python3 -m venv .venv
fi
# activate 스크립트는 set -u 에 안전하지 않을 수 있어 잠시 해제
set +u
# shellcheck disable=SC1091
source .venv/bin/activate
set -u
python --version

# 2) 필요 패키지 설치 (누락 시에만)
if python -c "import textual, dotenv, openai" >/dev/null 2>&1; then
    echo "[agent.sh] 의존성 확인 완료."
else
    echo "[agent.sh] 의존성 설치 중 (pip install -r requirements.txt)..."
    pip install -q -r requirements.txt
    echo "[agent.sh] 의존성 설치 완료."
fi

# 3) .env 준비 (없으면 .env.example 에서 복사)
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "[agent.sh] .env 를 새로 만들었습니다."
fi

# 4) OpenRouter API 키 확인 (없으면 대화형 입력 — 터미널일 때만)
if ! grep -Eq '^OPENROUTER_API_KEY=.+' .env; then
    echo "[agent.sh] .env 에 OPENROUTER_API_KEY 가 없습니다."
    if [ -t 0 ]; then
        # 60초간 기다렸다가 입력이 없으면 빈 값으로 진행
        read -r -t 60 -p "[agent.sh] OpenRouter API 키를 입력하세요 (60초 대기, 건너뛰려면 Enter): " api_key </dev/tty || api_key=""
    else
        api_key=""
        echo "[agent.sh] 비대화형 실행 감지 - 키 입력을 건너뜁니다."
    fi
    if [ -n "${api_key:-}" ]; then
        if grep -q '^OPENROUTER_API_KEY=' .env; then
            sed -i "s|^OPENROUTER_API_KEY=.*|OPENROUTER_API_KEY=${api_key}|" .env
        else
            echo "OPENROUTER_API_KEY=${api_key}" >> .env
        fi
        echo "[agent.sh] API 키 저장 완료."
    else
        echo "[agent.sh] 경고: 키 없이 실행합니다 (API 호출 단계에서 실패할 수 있습니다)."
    fi
fi

echo "[agent.sh] 준비 완료."

# 5) 실행
if [ "$RUN_TUI" -eq 1 ]; then
    exec python main.py
fi