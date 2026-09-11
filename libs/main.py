"""Textual TUI + 파이프라인 실행 진입점.

실행: python main.py
사용자에게 "무엇을 만들까요?"를 물어보고 Enter 를 누르면
Pipeline 을 백그라운드 스레드로 실행하며 상태/로그를 실시간 표시한다.
"""
import threading
from queue import Empty, Queue

import config
from pipeline import Pipeline, STEPS
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

# 파이프라인 단계 표시 상태
PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"

MARKS = {
    PENDING: ("[ ]", "dim"),
    RUNNING: ("[▶]", "bold yellow"),
    DONE: ("[✓]", "bold green"),
    FAILED: ("[✗]", "bold red"),
}


class StepsView(Static):
    """고정 파이프라인 단계 목록 상태 표시."""

    def __init__(self, steps: list[str], **kwargs):
        super().__init__("", **kwargs)
        self._steps = steps
        self._states = {s: PENDING for s in steps}
        self.update(self.render_text())

    def set_state(self, name: str, state: str):
        if name in self._states:
            self._states[name] = state
            self.update(self.render_text())

    def render_text(self) -> Text:
        text = Text()
        text.append("Pipeline 단계\n", style="bold cyan")
        for step in self._steps:
            mark, style = MARKS[self._states[step]]
            text.append(f"{mark} {step}\n", style=style)
        return text


class PipelineApp(App):
    TITLE = "AI Coding Pipeline (OpenRouter)"
    CSS = """
    #body { padding: 0 1; }
    #steps { height: 9; }
    #activity {
        height: 3;
        border: round $primary;
        content-align: left middle;
        padding: 0 1;
    }
    #log {
        height: 1fr;
        border: round $secondary;
        padding: 0 1;
    }
    #prompt { height: 3; }
    """

    def __init__(self):
        super().__init__()
        self.queue: Queue = Queue()
        self.pipeline: Pipeline | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        self.steps_view = StepsView(STEPS, id="steps")
        self.activity = Static("요청을 입력하고 Enter 를 누르세요.", id="activity")
        self.log_view = RichLog(wrap=True, highlight=False, id="log")
        self.prompt = Input(placeholder="무엇을 만들까요? (예: FastAPI로 간단한 Todo API를 만들어줘)", id="prompt")
        yield Vertical(
            self.steps_view,
            self.activity,
            self.log_view,
            self.prompt,
            id="body",
        )
        yield Footer()

    def on_mount(self):
        self.prompt.focus()
        self.set_interval(0.1, self._poll_queue)
        if not config.OPENROUTER_API_KEY:
            self._log("⚠️ .env에 OPENROUTER_API_KEY가 없습니다. 파이프라인이 고급 단계에서 실패할 수 있습니다.", "bold red")

    # --- 입력 → 파이프라인 시작 ---
    def on_input_submitted(self, event: Input.Submitted):
        request = event.value.strip()
        if not request or self.pipeline is not None:
            return
        self.prompt.disabled = True
        self._log(f"📝 요청: {request}", "bold cyan")
        self.pipeline = Pipeline(request, emit=lambda *args: self.queue.put(args))
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    # --- 큐 폴링 → UI 갱신 ---
    def _poll_queue(self):
        try:
            while True:
                event = self.queue.get_nowait()
                self._handle(event)
        except Empty:
            pass

    def _handle(self, event: tuple):
        kind = event[0]
        if kind == "step_start":
            self.steps_view.set_state(event[1], RUNNING)
            self._log(f"[{event[1]}] 시작", "yellow")
        elif kind == "step_done":
            self.steps_view.set_state(event[1], DONE)
            self._log(f"[{event[1]}] 완료 ✓", "green")
        elif kind == "step_fail":
            self.steps_view.set_state(event[1], FAILED)
            self._log(f"[{event[1]}] 실패 ✗\n{event[2]}", "red")
        elif kind == "activity":
            self.activity.update(event[1])
        elif kind == "log":
            self._log(event[1], None)
        elif kind == "summary_set":
            self.activity.update(event[1])
        elif kind == "error":
            self._log(f"🚨 오류\n{event[1]}", "red")
        elif kind == "done":
            self._log("🏁 파이프라인 종료 (Ctrl+C 로 닫기)", "bold green")

    def _log(self, message: str, style: str | None):
        # Rich 마크업 오류 방지를 위해 Text 로 기록
        self.log_view.write(Text(message, style=style))


if __name__ == "__main__":
    PipelineApp().run()