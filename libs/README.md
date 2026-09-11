# AI Coding Pipeline Runner (Textual TUI)

OpenRouter 기반의 고정 파이프라인을 순서대로 실행하고 상태를 TUI로 보여주는
작은 도구입니다. GUI/웹서버/DB/Agent Framework 는 사용하지 않습니다.

```
Analyzer → Planner → Coder → Tester → Reviewer → (Fixer → Tester 반복) → Finalizer
```

## 실행 (venv 수동 활성화 필요 없음)

프로젝트 루트(`code/`)에서:

```bash
bash agent.sh
```

`agent.sh` 가 다음을 **자동으로** 수행합니다:
1. `libs/.venv` 가상환경 생성 (없으면)
2. `pip install -r requirements.txt` (필수 패키지 누락 시에만)
3. `.env` 자동 생성 (없으면 `.env.example` 에서 복사)
4. `OPENROUTER_API_KEY` 부재 시 대화형 입력 (터미널에서만, 60초 대기)
5. TUI 실행 (`python main.py`)

준비만 원하면:

```bash
bash agent.sh --prepare
```

## 설정 (libs/.env)

- `OPENROUTER_API_KEY` — OpenRouter API 키
- `MODEL` — 모델 (예: `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`)
- `MAX_FIX_ATTEMPTS` — Fixer 최대 반복 횟수 (기본 5)
- `TEST_TIMEOUT` — 테스트 명령 타임아웃(초, 기본 300)

## 구조

```
code/
├── agent.sh    실행 스크립트 (준비 + TUI 실행)
└── libs/
    ├── main.py       Textual TUI (상태/로그 표시, 요청 입력)
    ├── pipeline.py   고정 파이프라인 오케스트레이션 (Fixer 반복 포함)
    ├── agents.py     단계별 Agent
    ├── tools.py      workspace 파일 읽기/쓰기, 셸 테스트 실행
    ├── config.py     .env 로드, 모델/경로/반복 설정
    ├── prompts/      각 Agent 의 시스템 프롬프트
    └── workspace/    에이전트가 생성/수정하는 파일
```

## 동작 방식

- Coder/Fixer 가 `=== FILE: 경로 === ... === END FILE ===` 블록으로 전체 파일
  내용을 반환하면 tools 가 해당 파일을 workspace 에 생성/덮어씁니다.
- Tester 는 LLM 으로 테스트 명령을 결정해 셸에서 실행하고 stdout/stderr/exit
  code 를 수집합니다.
- Reviewer 가 `VERDICT: FAIL` 을 주거나 테스트가 실패하면 Fixer 가 수정 후
  Tester 를 다시 실행합니다 (최대 5회).