"""설정: .env 로드, OpenRouter/모델, 경로 정의."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- OpenRouter (OpenAI 호환) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# 모델은 여기서(또는 .env의 MODEL) 쉽게 변경
MODEL = os.getenv("MODEL", "openai/gpt-4o-mini")

# --- 파이프라인 동작 ---
MAX_FIX_ATTEMPTS = int(os.getenv("MAX_FIX_ATTEMPTS", "5"))
TEST_TIMEOUT = int(os.getenv("TEST_TIMEOUT", "300"))
# PO가 CEO와 주고받는 질문 최대 횟수
PO_MAX_QUESTIONS = int(os.getenv("PO_MAX_QUESTIONS", "3"))

# --- 경로 ---
# 프로젝트 루트 = agent.sh 가 있는 디렉터리 (libs 의 상위)
ROOT_DIR = BASE_DIR.parent

# 작업 결과물: 루트 workspace/ 아래에 채팅방별로 저장 (workspace/<방ID>/)
WORKSPACE_DIR = ROOT_DIR / "workspace"
# 작업 AI별 프롬프트: prompt/<작업AI이름>.txt (PO.txt, DevA.txt, QA.txt, ...)
PROMPTS_DIR = BASE_DIR / "prompt"

WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
