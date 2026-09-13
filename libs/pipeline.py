"""고정 파이프라인 오케스트레이션 (엔터프라이즈).

CEO(사용자)
→ PO      : 인터랙티브 질의응답(상한 PO_MAX_QUESTIONS, 되면 알아서 멈춤) → PRD 명세서
→ Architect : 시스템 구조/클린 아키텍처/폴더 구조/기술스택 설계
→ Dev     : 백엔드 구현
→ QA      : 품질 검수 + 테스트 실행 + 예외상황 검증
→ (실패 시 Fixer → QA 반복, 최대 MAX_FIX_ATTEMPTS)
→ Finalizer : CEO 최종 보고

채팅방(chat_id)이 주어지면 사용자 요청과 에이전트 메시지를 해당 방에 기록하고,
방 전용 workspace 로 전환해 다른 작업과 파일이 섞이지 않게 한다.
"""
import threading
import traceback

import agents
import chats
import config

# TUI 에 표시할 고정 단계 순서
STEPS = [
    "PO", "Architect", "Dev",
    "QA", "Fixer", "Finalizer",
]


class Pipeline:
    def __init__(self, request: str, chat_id: str | None = None,
                 chat_history: str = "", emit=None):
        self.request = request
        self.chat_id = chat_id
        self._emit_cb = emit or (lambda *args: None)
        self.context = {"request": request}
        if chat_history.strip():
            self.context["chat_history"] = chat_history.strip()
        # 인터랙티브 Q&A 상태
        self._answer_event = threading.Event()
        self._answer: str | None = None
        self._waiting = False

    # --- emit: 채팅 메시지는 저장소에도 기록 후 전달 ---
    def emit(self, *args):
        if self.chat_id and args and args[0] == "chat":
            try:
                chats.append_message(self.chat_id, args[1], args[2])
            except OSError:
                pass
        self._emit_cb(*args)

    # --- 인터랙티브: PO 가 CEO(사용자)에게 질문 ---
    def ask(self, question: str) -> str:
        """질문을 채팅+UI 으로 내보내고 사용자 답변을 기다린다."""
        self.emit("chat", "PO", f"❓ {question}")
        self._waiting = True
        self._answer_event.clear()
        self.emit("question", question)
        self._answer_event.wait()
        self._waiting = False
        return self._answer or ""

    def respond(self, answer: str):
        """TUI 에서 사용자가 답변을 입력했을 때 호출."""
        if self._waiting:
            self._answer = answer
            self.emit("chat", "나", answer)
            self._answer_event.set()

    @property
    def waiting_for_answer(self) -> bool:
        return self._waiting

    def run(self):
        """스레드에서 호출. 예외는 잡아서 emit 으로 보고하고 done 을 보낸다."""
        try:
            self._prepare_room()
            self._run()
        except Exception as e:  # noqa: BLE001
            self.emit("error", f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        finally:
            self._waiting = False
            self._emit_cb("done", self.context.get("summary", "파이프라인 완료"))

    def _prepare_room(self):
        """채팅방 제목/전용 workspace 설정 + 사용자 지시 메시지 기록."""
        if not self.chat_id:
            return
        if chats.get_title(self.chat_id) == chats.DEFAULT_TITLE:
            chats.set_title(self.chat_id, self.request.strip()[:24] or chats.DEFAULT_TITLE)
        ws = chats.workspace_dir(self.chat_id)
        ws.mkdir(parents=True, exist_ok=True)
        config.WORKSPACE_DIR = ws
        self.emit("chat", "나", self.request)

    def _step(self, name: str, fn):
        self.emit("step_start", name)
        try:
            result = fn()
        except Exception:
            self.emit("step_fail", name, traceback.format_exc())
            raise
        self.emit("step_done", name)
        return result

    def _run(self):
        po = agents.PO(self.emit)
        architect = agents.Architect(self.emit)
        dev = agents.Dev(self.emit)
        qa = agents.QA(self.emit)
        fixer = agents.Fixer(self.emit)
        finalizer = agents.Finalizer(self.emit)
        self.context["_ask"] = self.ask  # PO 가 인터랙티브 질문에 사용

        self.emit("activity", "PO가 CEO 니즈를 파악하기 위해 질문합니다...")
        self._step("PO", lambda: po.run(self.context))

        self.emit("activity", "아키텍트가 시스템 설계 중...")
        self._step("Architect", lambda: architect.run(self.context))

        self.emit("activity", "백엔드 개발자가 코드 작성 중...")
        self._step("Dev", lambda: dev.run(self.context))

        # QA → (실패 시 Fixer) 반복
        fix_count = 0
        while True:
            self.emit("activity", "QA가 품질 검수를 진행 중...")
            result = self._step("QA", lambda: qa.run(self.context))

            if result.get("verdict") == "PASS":
                self.emit("chat", "System", "✅ QA 검수 통과.")
                break

            if fix_count >= config.MAX_FIX_ATTEMPTS:
                self.emit("chat", "System",
                          f"⚠️ 최대 수정 횟수({config.MAX_FIX_ATTEMPTS}회) 도달. 종료합니다.")
                break

            fix_count += 1
            self.emit("activity", f"QA 지적사항 수정 중... ({fix_count}/{config.MAX_FIX_ATTEMPTS})")
            self._step("Fixer", lambda: fixer.run(self.context))

        self.emit("activity", "최종 CEO 보고서 작성 중...")
        self._step("Finalizer", lambda: finalizer.run(self.context))