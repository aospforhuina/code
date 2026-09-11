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

# --- 경로 ---
WORKSPACE_DIR = BASE_DIR / "workspace"
PROMPTS_DIR = BASE_DIR / "prompts"

WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
