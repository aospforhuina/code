"""고정 파이프라인 오케스트레이션.

Analyzer → Planner → Coder → (Tester → Reviewer → Fixer 반복) → Finalizer
Fixer 는 문제가 없거나 최대 MAX_FIX_ATTEMPTS 회에 도달할 때까지 반복한다.

채팅방(chat_id)이 주어지면:
- 사용자 요청과 에이전트 메시지를 해당 방의 messages.jsonl 에 기록
- 그 방 전용 workspace 로 전환해 다른 작업과 파일이 섞이지 않게 한다
"""
import traceback

import agents
import chats
import config

# TUI 에 표시할 고정 단계 순서
STEPS = [
    "Analyzer", "Planner", "Coder",
    "Tester", "Reviewer", "Fixer", "Finalizer",
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

    # --- emit: 채팅 메시지는 저장소에도 기록 후 전달 ---
    def emit(self, *args):
        if self.chat_id and args and args[0] == "chat":
            try:
                chats.append_message(self.chat_id, args[1], args[2])
            except OSError:
                pass
        self._emit_cb(*args)

    def run(self):
        """스레드에서 호출. 예외는 잡아서 emit 으로 보고하고 done 을 보낸다."""
        try:
            self._prepare_room()
            self._run()
        except Exception as e:  # noqa: BLE001
            self.emit("error", f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        finally:
            self._emit_cb("done", self.context.get("summary", "파이프라인 완료"))

    def _prepare_room(self):
        """채팅방 제목/전용 workspace 설정 + 사용자 메시지 기록."""
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
        analyzer = agents.Analyzer(self.emit)
        planner = agents.Planner(self.emit)
        coder = agents.Coder(self.emit)
        tester = agents.Tester(self.emit)
        reviewer = agents.Reviewer(self.emit)
        fixer = agents.Fixer(self.emit)
        finalizer = agents.Finalizer(self.emit)

        self.emit("activity", "사용자 요청을 분석하는 중...")
        self._step("Analyzer", lambda: analyzer.run(self.context))

        self.emit("activity", "구현 계획을 수립하는 중...")
        self._step("Planner", lambda: planner.run(self.context))

        self.emit("activity", "코드를 작성하는 중...")
        self._step("Coder", lambda: coder.run(self.context))

        # Fixer → Tester 반복 (최대 MAX_FIX_ATTEMPTS 회)
        fix_count = 0
        while True:
            self.emit("activity", "테스트를 실행하는 중...")
            test = self._step("Tester", lambda: tester.run(self.context))

            self.emit("activity", "구현 결과를 검토하는 중...")
            review = self._step("Reviewer", lambda: reviewer.run(self.context))

            if review.get("verdict") == "PASS" and test.get("exit_code") == 0:
                self.emit("chat", "System", "✅ 검토 통과 및 테스트 성공.")
                break

            if fix_count >= config.MAX_FIX_ATTEMPTS:
                self.emit("chat", "System",
                          f"⚠️ 최대 수정 횟수({config.MAX_FIX_ATTEMPTS}회) 도달. 종료합니다.")
                break

            fix_count += 1
            self.emit("activity", f"문제 발견. 코드 수정 중... ({fix_count}/{config.MAX_FIX_ATTEMPTS})")
            self._step("Fixer", lambda: fixer.run(self.context))

        self.emit("activity", "최종 결과를 요약하는 중...")
        self._step("Finalizer", lambda: finalizer.run(self.context))