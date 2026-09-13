# AI Coding Pipeline Runner (Textual TUI)

OpenRouter 기반의 **엔터프라이즈 AI 개발 팀** 파이프라인을 순서대로 실행하고
상태를 TUI로 보여주는 작은 도구입니다. GUI/웹서버/DB/Agent Framework 는
사용하지 않습니다.

```
CEO(사용자)
→ PO/PM  : CEO와 진득한 질의응답 → 니즈 도출 → 명세서(PRD)
→ Architect : 시스템 구조/클린 아키텍처/폴더 구조/기술스택 설계
→ DevA / DevB / DevC : 백엔드 개발자 3명 분업 구현
→ QA     : 품질 검수 + 테스트 실행 + 예외상황 검증
→ (실패 시 Fixer → QA 반복, 최대 5회)
→ Finalizer : CEO 최종 보고
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

## 사용법 — 작업별 채팅방

실행하면 먼저 **채팅방(작업) 목록**이 나옵니다. Cline 처럼 작업마다 방이
분리되어 있어, 같은 작업은 방을 다시 열면 **대화 내역과 해당 작업의 파일이
그대로 유지**되어 이어서 진행할 수 있고, **다른 작업으로 쉽게 전환**할 수
있습니다.

| 키 | 동작 |
|---|---|
| `Enter` | 목록에서 채팅방 열기 (기존 대화 이어가기) |
| `n` | 새 채팅방(새 작업) 만들기 |
| `Ctrl+E` | 채팅방 이름 수정 (방 화면에서만, 다이얼로그 입력) |
| `Ctrl+Backspace` | 채팅방 삭제 (방 화면에서만 — 대화·작업 결과물 영구 삭제, 확인 다이얼로그) |
| `Ctrl+R` | 채팅방 목록으로 전환 |
| `Ctrl+N` | 다른 방을 새로 열기 |
| `Ctrl+Q` / `q` | 종료 |

방 안에서 **CEO 처럼 지시**를 입력하면 파이프라인이 실행됩니다. 먼저 **PO 가
질문을 하고** 입력창이 활성화되므로 답변하며 (최대 3회), 니즈가 정리되면 명세서가
작성되고 이후 아키텍처 설계 → 개발자 3명(DevA/B/C) 분업 구현 → QA 검수 순서로
진행됩니다. 각 에이전트의 결과는 **말풍선 형태로** 대화 목록에 추가되고,
`docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md` 도 작업 공간에
남습니다. 다음 메시지부터는 이전 대화 내역이 맥락으로 전달되어 이어집니다.

## 프롬프트 수정

각 작업 AI 의 프롬프트는 `libs/prompt/<작업AI이름>.txt` 에 분리되어 있습니다.
파일을 수정하면 **다음 실행부터 즉시 반영**됩니다 (재시작 불필요).

| 파일 | 작업 AI |
|---|---|
| `libs/prompt/PO.txt` | CEO와 질의응답 → 명세서(PRD) |
| `libs/prompt/Architect.txt` | 시스템 구조/클린 아키텍처/폴더/기술스택 설계 |
| `libs/prompt/DevA.txt` | 백엔드 DevA (도메인 계층) |
| `libs/prompt/DevB.txt` | 백엔드 DevB (API·인프라 계층) |
| `libs/prompt/DevC.txt` | 백엔드 DevC (테스트·설정·예외처리) |
| `libs/prompt/QA.txt` | QA 검수 (VERDICT 규칙 포함) |
| `libs/prompt/Fixer.txt` | 문제 수정 (파일 블록 형식 규칙 포함) |
| `libs/prompt/Finalizer.txt` | CEO 최종 보고 |

## 설정 (libs/.env)

- `OPENROUTER_API_KEY` — OpenRouter API 키
- `MODEL` — 모델 (예: `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`)
- `MAX_FIX_ATTEMPTS` — Fixer 최대 반복 횟수 (기본 5)
- `TEST_TIMEOUT` — 테스트 명령 타임아웃(초, 기본 300)
- `PO_MAX_QUESTIONS` — PO가 CEO에게 묻는 최대 질문 수 (기본 3)

## 구조

```
code/
├── agent.sh     실행 스크립트 (준비 + TUI 실행)
├── workspace/   작업 결과물 — 채팅방별 폴더로 저장, git 제외
└── libs/
    ├── main.py       Textual TUI (채팅방 목록/채팅 화면)
    ├── chats.py      채팅방 저장소 (info.json + messages.jsonl)
    ├── pipeline.py   고정 파이프라인 오케스트레이션 (Fixer 반복 포함)
    ├── agents.py     단계별 Agent
    ├── tools.py      workspace 파일 읽기/쓰기, 셸 테스트 실행
    ├── config.py     .env 로드, 모델/경로/반복 설정
    ├── prompt/       작업 AI별 프롬프트 — <작업AI이름>.txt (PO.txt, DevA.txt, QA.txt 등)
    └── chats/        작업별 대화 기록 (git 제외)
```

## 동작 방식

- **질의응답**: PO가 `Pipeline.ask()` 로 질문을 채팅에 내보내고 CEO(사용자)의
  답변(`Pipeline.respond()`)을 기다렸다가 명세서(docs/PRD.md)를 만든다.
- **문서 산출물**: PO→`docs/PRD.md`, Architect→`docs/ARCHITECTURE.md`(+, 폴더
  스켈레톤 `.gitkeep`), QA→`docs/QA_REPORT.md` 가 채팅방 workspace 에 남는다.
- DevA/B/C 와 Fixer 는 `=== FILE: 경로 === ... === END FILE ===` 블록으로 전체
  파일 내용을 반환하면 tools 가 해당 파일을 workspace 에 생성/덮어씁니다.
- QA 는 LLM 으로 테스트 명령을 결정해 셸에서 실행하고 stdout/stderr/exit code 를
  수집하며, `VERDICT: FAIL` 이거나 테스트가 실패하면 Fixer 가 수정 후 QA 를
  다시 실행합니다 (최대 5회).