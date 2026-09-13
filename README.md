# AI Coding Pipeline Runner — 엔터프라이즈 AI 개발 팀 (Textual TUI)

OpenRouter(OpenAI 호환 API) 기반으로 **가상의 엔터프라이즈 AI 개발 팀**이
파이프라인을 순서대로 수행하고, 진행 상황을 TUI(터미널 UI)로 실시간 보여주는
작은 도구입니다.

- GUI / 웹 서버 / 데이터베이스 / LangChain 등 복잡한 프레임워크 없음
- 프로젝트 루트에서 `bash agent.sh` 한 번으로 준비부터 실행까지 자동화

## 파이프라인

```
CEO(사용자 = 당신)
→ PO/PM          : CEO와 진득한 질의응답(최소 5회~최대 20회) → 니즈 도출 → 명세서(PRD)
→ Architect       : 시스템 구조 / 클린 아키텍처 / 폴더 구조 / 기술 스택 설계
→ DevA/DevB/DevC  : 백엔드 개발자 3명 분업 구현 (도메인 · API·인프라 · 테스트·예외)
→ QA              : 품질 검수 + 테스트 실행 + 예외/에지케이스 검증
→ (실패 시 Fixer → QA 재실행, 최대 5회)
→ Finalizer       : CEO 최종 보고
```

## 실행

```bash
cd code
bash agent.sh
```

`agent.sh` 가 자동으로 수행합니다:
1. `libs/.venv` 가상환경 생성 (없으면)
2. `pip install -r requirements.txt` (필수 패키지 누락 시에만)
3. `.env` 자동 생성 (없으면 `libs/.env.example` 에서 복사)
4. `OPENROUTER_API_KEY` 부재 시 대화형 입력 (터미널에서만, 60초 대기)
5. TUI 실행

준비만 필요할 때는 `bash agent.sh --prepare`

## 사용법 — 작업별 채팅방

실행하면 **채팅방(작업) 목록**이 나옵니다. Cline 처럼 작업마다 방이 분리되어
있어, 같은 작업은 방을 다시 열면 **대화 내역과 작업 결과물이 그대로 유지**되고,
`Ctrl+R` 로 다른 작업(방)으로 쉽게 전환할 수 있습니다.

| 키 | 동작 |
|---|---|
| `Enter` | 목록에서 채팅방 열기 (기존 대화 이어가기) |
| `n` | 새 채팅방(새 작업) 만들기 |
| `Ctrl+E` | 채팅방 이름 수정 (방 화면에서만) |
| `Ctrl+Backspace` | 채팅방 삭제 (방 화면에서만, 확인 다이얼로그) |
| `Ctrl+R` | 채팅방 목록으로 전환 |
| `Ctrl+N` | 다른 방을 새로 열기 |
| `Ctrl+Q` / `q` | 종료 |

### CEO로 지시하기

방 안에 **CEO처럼 지시** 를 입력하면 파이프라인이 시작됩니다.

- 먼저 **PO가 질문을 하나씩** 던지고 입력창이 활성화됩니다. 답변을 입력하고
  Enter 를 누르면 다음 질문으로 이어집니다. **최소 5회, 최대 20회** 질문 후
  명세서가 작성됩니다.
- 이후 설계 → 개발자 3명 구현 → QA 검수 → 최종 보고가 말풍선과 단계 상태로
  표시됩니다.
- 작업 공간에는 문서 산출물이 남습니다:
  `docs/PRD.md`(명세서), `docs/ARCHITECTURE.md`(설계), `docs/QA_REPORT.md`(검수 보고)

## 설정 (libs/.env)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `OPENROUTER_API_KEY` | (없음) | OpenRouter 키. `sk-or-…` |
| `MODEL` | `openai/gpt-4o-mini` | 사용할 모델 (예: `anthropic/claude-3.5-sonnet`) |
| `PO_MIN_QUESTIONS` | `5` | PO가 CEO에게 묻는 **최소** 질문 수 |
| `PO_MAX_QUESTIONS` | `20` | PO가 CEO에게 묻는 **최대** 질문 수 |
| `MAX_FIX_ATTEMPTS` | `5` | QA 실패 시 Fixer 최대 반복 횟수 |
| `TEST_TIMEOUT` | `300` | 테스트 명령 타임아웃(초) |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | API 엔드포인트 |

## 프로젝트 구조

```
code/
├── agent.sh       실행 스크립트 (준비 + TUI 실행)
├── workspace/     작업 결과물 — 채팅방별 폴더(/채팅방ID)로 저장, git 제외
├── .gitignore     개인정보(.env, chats/, workspace/) 커밋 방지
└── libs/
    ├── main.py        Textual TUI (방 목록 / 채팅 화면, 작업 전환)
    ├── pipeline.py    고정 파이프라인 오케스트레이션 + 인터랙티브 Q&A(ask/respond)
    ├── agents.py      작업 AI 8종 (PO, Architect, DevA/B/C, QA, Fixer, Finalizer)
    ├── chats.py       채팅방 저장소 (info.json + messages.jsonl)
    ├── tools.py       workspace 파일 읽기/쓰기, 셸 테스트 실행, 파일 블록 파싱
    ├── config.py      .env 로드, 모델/경로/횟수 설정
    ├── prompt/        작업 AI별 프롬프트 — <작업AI이름>.txt
    ├── chats/         작업별 대화 기록 (git 제외)
    ├── requirements.txt
    └── .env / .env.example
```

## 프롬프트 수정 (작업 AI 조정)

각 작업 AI 의 프롬프트는 `libs/prompt/<작업AI이름>.txt` 에 분리되어 있습니다.
파일을 수정하면 **다음 실행부터 즉시 반영**됩니다 (재시작 불필요).

| 파일 | 작업 AI |
|---|---|
| `PO.txt` | CEO 질의응답 → 명세서(PRD) |
| `Architect.txt` | 구조/클린 아키텍처/폴더/기술스택 설계 |
| `DevA.txt` | 백엔드 DevA — 도메인 계층 |
| `DevB.txt` | 백엔드 DevB — API·인프라 계층 |
| `DevC.txt` | 백엔드 DevC — 테스트·설정·예외처리 |
| `QA.txt` | QA 검수 (VERDICT 규칙 포함) |
| `Fixer.txt` | 문제 수정 |
| `Finalizer.txt` | CEO 최종 보고 |

## 동작 방식

- PO 는 `Pipeline.ask()` 로 질문을 채팅에 내보내고 CEO(사용자)의 답변
  (`Pipeline.respond()`) 을 기다렸다가, 최소 질문 횟수를 채운 뒤에만 PRD 를
  작성합니다.
- DevA/B/C 와 Fixer 는 `=== FILE: 경로 === ... === END FILE ===` 블록으로 전체
  파일 내용을 반환하면 tools 가 해당 파일을 **채팅방 전용 workspace**에
  생성/덮어씁니다. (방마다 폴더가 분리되어 **작업 간 파일이 섞이지 않음**)
- QA 는 LLM 으로 테스트 명령을 결정해 셸에서 실행하고 stdout/stderr/exit code 를
  수집하며, `VERDICT: FAIL` 또는 테스트 실패 시 Fixer 가 수정하고 QA 를 다시
  실행합니다 (최대 5회).
```