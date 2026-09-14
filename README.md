# AI Coding Pipeline Runner — 엔터프라이즈 AI 개발 팀 (Textual TUI)

OpenRouter(OpenAI 호환 API) 기반으로 **가상의 엔터프라이즈 AI 개발 팀**이
파이프라인을 순서대로 수행하고, 진행 상황을 TUI(터미널 UI)로 실시간 보여주는
작은 도구입니다.

- GUI / 웹 서버 / 데이터베이스 / LangChain 등 복잡한 프레임워크 없음
- 프로젝트 루트에서 `bash agent.sh` 한 번으로 준비부터 실행까지 자동화

## 파이프라인

```
CEO(사용자 = 당신)
→ PO/PM          : CEO와 질의응답(꼭 필요할 때만, 충분하면 스스로 명세서) → PRD
→ Architect       : 시스템 구조 / 클린 아키텍처 / 폴더 구조 / 기술 스택 설계
→ Dev             : 백엔드 구현
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
| `Ctrl+T` | 사고 중인 내용(thinking)을 크게 팝업으로 보기 |
| `Ctrl+R` | 채팅방 목록으로 전환 |
| `Ctrl+N` | 다른 방을 새로 열기 |
| `Ctrl+Q` / `q` | 종료 |

### CEO로 지시하기

방 안에 **CEO처럼 지시** 를 입력하면 파이프라인이 시작됩니다.

- 먼저 **PO가 질문을 하나씩** 던지고 입력창이 활성화됩니다. 답변을 입력하고
  Enter 를 누르면 다음 질문으로 이어집니다. **꼭 필요할 때만** 물어보고,
포가 "충분하다"고 판단하면 스스로 그만두고 명세서를 작성합니다.
  명세서가 작성됩니다.
- 이후 설계 → 개발자(Dev) 구현 → QA 검수 → 최종 보고가 말풍선과 단계 상태로
  표시됩니다.
- 작업 중에는 화면 하단의 **막대바**가 움직이고, 응답은 **스트리밍**으로
  실시간 표시됩니다. 사고(reasoning) 모델을 쓰면 🧠 영역에서 생각하는 과정도
  보이며, 우상단에 **누적 토큰 사용량**(prompt → completion) 이 표시됩니다.
- 작업 공간에는 문서 산출물이 남습니다:
  `docs/PRD.md`(명세서), `docs/ARCHITECTURE.md`(설계), `docs/QA_REPORT.md`(검수 보고)

## 설정 (libs/.env)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `OPENROUTER_API_KEY` | (없음) | OpenRouter 키. `sk-or-…` |
| `MODEL` | `openai/gpt-4o-mini` | 사용할 모델 (예: `anthropic/claude-3.5-sonnet`, 사고 모델 `deepseek/deepseek-reasoner`) |
| `STREAMING` | `1` | 응답을 스트리밍으로 표시 (0 이면 일반 호출) |
| `SHOW_THINKING` | `1` | 사고 과정(thinking)을 화면에 표시·누적 (0 이면 화면만 숨김) |
| `PO_MAX_QUESTIONS` | `20` | PO 가 CEO에게 묻는 **상한** (충분하면 스스로 명세서 작성) |
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
    ├── agents.py      작업 AI 6종 (PO, Architect, Dev, QA, Fixer, Finalizer)
    ├── chats.py       채팅방 저장소 (info.json + messages.jsonl)
    ├── tools.py       workspace 파일 읽기/쓰기, 셸 테스트 실행, 파일 블록 파싱
    ├── config.py      .env 로드, 모델/경로/횟수 설정
    ├── prompt/        작업 AI별 프롬프트 — <작업AI이름>.txt (자연어)
    ├── chats/         작업별 대화 기록 (git 제외)
    ├── requirements.txt
    └── .env / .env.example
```

## 프롬프트 수정 (작업 AI 조정)

각 작업 AI 의 프롬프트는 `libs/prompt/<작업AI이름>.txt` 에 분리되어 있습니다.
**자연어 프롬프트 방식**이며, 파일 내용이 그대로 시스템 프롬프트로 사용됩니다.
응답은 정해진 마커 규약을 따릅니다:

| 작업 AI | 프롬프트 파일 | 응답 마커 |
|---|---|---|
| PO | `PO.txt` | 질문(한 줄) 또는 `=== PRD === ... === END PRD ===` |
| Architect | `Architect.txt` | `=== FILE: 경로 === ... === END FILE ===` (설계 파일·폴더 스켈레톤) |
| Dev | `Dev.txt` | `=== FILE: 경로 === ... === END FILE ===` |
| QA | `QA.txt` | `=== QA_REPORT === ... === END QA_REPORT ===` + `VERDICT: PASS/FAIL` |
| Fixer | `Fixer.txt` | `=== FILE: 경로 === ... === END FILE ===` |
| Finalizer | `Finalizer.txt` | 자연어 요약 |

파일을 수정하면 **다음 실행부터 즉시 반영**됩니다 (재시작 불필요).

## 동작 방식

- PO 는 `Pipeline.ask()` 로 질문을 채팅에 내보내고 CEO(사용자)의 답변
  (`Pipeline.respond()`) 을 기다립니다. 강제 횟수는 없으며, **충분하다고
  판단하면 스스로 PRD 를 작성**해 넘어갑니다 (상한은 PO_MAX_QUESTIONS).
- **스트리밍**: 모든 에이전트 응답은 `chat_stream()` 로 실시간 수신되며
  `stream`(작성 중인 글자) / `think`(사고 과정) / `work_start·work_end`(막대바)
  이벤트로 TUI 에 전달됩니다.
- Dev 와 Fixer 는 `=== FILE: 경로 === ... === END FILE ===` 블록으로 전체
  파일 내용을 반환하면 tools 가 해당 파일을 **채팅방 전용 workspace**에
  생성/덮어씁니다. (방마다 폴더가 분리되어 **작업 간 파일이 섞이지 않음**)
- QA 는 LLM 으로 테스트 명령을 결정해 셸에서 실행하고 stdout/stderr/exit code 를
  수집하며, `VERDICT: FAIL` 또는 테스트 실패 시 Fixer 가 수정하고 QA 를 다시
  실행합니다 (최대 5회).
```