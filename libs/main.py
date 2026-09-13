"""Textual TUI — 작업별 채팅방 인터페이스.

- 시작: 채팅방(작업) 목록 화면. Enter 로 열어 대화를 이어서 진행
- 방마다 전용 workspace/대화 내역이 있어 다른 작업과 섞이지 않는다
- 키: Ctrl+R 방 목록(전환) / Ctrl+N 새 방 / Ctrl+Q 종료

실행: python main.py  (또는 code/ 루트에서 bash agent.sh)
"""
import threading
from queue import Empty, Queue

import chats
import config
from pipeline import Pipeline, STEPS
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, ProgressBar, Static

# 파이프라인 단계 표시 상태
PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"

MARKS = {
    PENDING: ("[ ]", "dim"),
    RUNNING: ("[▶]", "bold yellow"),
    DONE: ("[✓]", "bold green"),
    FAILED: ("[✗]", "bold red"),
}

ROOM_HINT = "Ctrl+R 방 목록  •  Ctrl+N 새 방  •  Ctrl+Q 종료"


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


class RenameDialog(ModalScreen[str]):
    """채팅방 이름 수정 다이얼로그 (Enter: 저장, Esc: 취소)."""

    BINDINGS = [("escape", "cancel", "취소")]

    def __init__(self, current_title: str):
        super().__init__()
        self.current_title = current_title

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("채팅방 이름 수정", id="rename-title"),
            Input(value=self.current_title, placeholder="이름을 입력하세요...", id="rename-input"),
            Static("Enter: 저장    Esc: 취소", id="rename-hint"),
            id="rename-dialog",
        )

    def on_mount(self):
        self.query_one("#rename-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted):
        name = event.value.strip()
        self.dismiss(name or None)

    def action_cancel(self):
        self.dismiss(None)


class ConfirmDialog(ModalScreen[bool]):
    """예/아니오 확인 다이얼로그 (Y=예, N/Esc=아니오)."""

    BINDINGS = [
        ("y", "yes", "예"),
        ("n", "no", "아니오"),
        ("escape", "no", "아니오"),
    ]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.message, id="confirm-message"),
            Static("Y: 예    N/Esc: 아니오", id="confirm-hint"),
            id="confirm-dialog",
        )

    def action_yes(self):
        self.dismiss(True)

    def action_no(self):
        self.dismiss(False)


class ChatListView(Screen):
    """채팅방(작업) 목록 + 새 채팅 생성."""

    BINDINGS = [("n", "new_chat", "새 채팅"), ("q", "quit", "종료")]

    def __init__(self, app: "PipelineApp"):
        super().__init__()
        self._app = app
        self._ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        self.list_view = ListView(id="chat-list")
        yield Vertical(
            self.list_view,
            Static("n: 새 채팅  Enter: 열기  q: 종료", id="hint"),
            id="body",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._app.title = "AI Coding Pipeline (Chat)"
        self._app.sub_title = "작업별 채팅방"
        self._ids = []
        for c in chats.list_chats():
            self._ids.append(c["id"])
            updated = c.get("updated", "")[5:16]
            self.list_view.append(ListItem(Label(f"🗂 {updated}  {c['title']}")))
        self.list_view.focus()

    def _open_chat(self, chat_id: str):
        self._app.active_chat = chat_id
        self._app.switch_screen(ChatRoomView(self._app, chat_id))

    def action_new_chat(self) -> None:
        self._open_chat(chats.create_chat())

    def action_quit(self) -> None:
        self._app.exit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = self.list_view.index
        if index is not None and 0 <= index < len(self._ids):
            self._open_chat(self._ids[index])
class ChatRoomView(Screen):
    """개별 채팅방: 단계 상태 + 활동 + 채팅 말풍선 + 입력."""

    BINDINGS = [
        ("ctrl+r", "rooms", "방 목록"),
        ("ctrl+n", "new_chat", "새 방"),
        ("ctrl+e", "rename", "이름 수정"),
        ("ctrl+backspace", "delete_chat", "방 삭제"),
        ("q", "quit", "종료"),
    ]

    def __init__(self, app: "PipelineApp", chat_id: str):
        super().__init__()
        self._app = app
        self.chat_id = chat_id
        self._busy = 0  # 진행 중 에이전트 수

    def compose(self) -> ComposeResult:
        yield Header()
        self.steps_view = StepsView(STEPS, id="steps")
        self.activity = Static(ROOM_HINT, id="activity")
        self.live = Static("", id="live")
        self.busy = ProgressBar(total=None, show_percentage=False, id="busy")
        self.chat_box = VerticalScroll(id="chat")
        self.prompt = Input(placeholder="메시지를 입력하세요 (Enter 로 실행)...", id="prompt")
        yield Vertical(
            self.steps_view,
            self.activity,
            self.live,
            self.busy,
            self.chat_box,
            self.prompt,
            id="body",
        )
        yield Footer()

    def on_mount(self) -> None:
        info = chats.get_info(self.chat_id)
        self._app.title = info.get("title") or chats.DEFAULT_TITLE
        self._app.sub_title = f"room {self.chat_id}"
        for m in chats.load_messages(self.chat_id):
            self._add_bubble(m["author"], m["content"])
        self.chat_box.scroll_end(animate=False)
        if not config.OPENROUTER_API_KEY:
            self._add_bubble("System", "⚠️ .env에 OPENROUTER_API_KEY가 없어 API 호출이 실패할 수 있습니다.")
        self.prompt.focus()

    # --- 파이프라인 요청 / PO 질문 답변 ---
    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text:
            return
        p = self._app.pipeline
        # PO(또는 어느 에이전트)의 질문에 답변
        if p is not None and p.waiting_for_answer and p.chat_id == self.chat_id:
            p.respond(text)
            event.input.value = ""
            self.prompt.disabled = True
            return
        if p is not None:
            return  # 실행 중(질문 대기 아님)이면 무시
        self._start_pipeline(text)

    def _start_pipeline(self, text: str):
        self.prompt.value = ""
        self.prompt.disabled = True
        # 이전 대화를 짧게 요약해 다음 작업의 맥락으로 넘긴다
        msgs = chats.load_messages(self.chat_id)
        history = "\n".join(f"[{m['author']}] {m['content'][:200]}" for m in msgs[-6:])
        self._app.pipeline_chat_id = self.chat_id
        self._app.pipeline = Pipeline(
            text,
            chat_id=self.chat_id,
            chat_history=history,
            emit=lambda *args: self._app.queue.put(args),
        )
        threading.Thread(target=self._app.pipeline.run, daemon=True).start()

    # --- 파이프라인 이벤트 렌더링 ---
    def show_chat(self, author: str, content: str):
        self._add_bubble(author, content)
        self.chat_box.scroll_end(animate=False)

    def _add_bubble(self, author: str, content: str):
        if author == "나":
            text = Text(f"👤 {content}\n", style="bold cyan")
        elif author == "System":
            text = Text(f"⚙️ {content}\n", style="dim")
        else:
            text = Text(f"🤖 [{author}]\n{content}\n", style="bright_green")
        self.chat_box.mount(Static(text, classes="bubble"))

    def show_activity(self, msg: str):
        self.activity.update(msg)

    # --- 스트리밍 / 작업 진행 표시 ---
    def show_work_start(self, name: str):
        self._busy += 1
        self.busy.update(total=None)  # 불확정(인디터미닛) 막대바
        self.live.update(f"⏳ [{name}] 작업 중...")

    def show_work_end(self, name: str):
        self._busy = max(0, self._busy - 1)
        if self._busy == 0:
            self.busy.update(total=1, progress=0)  # 대기 표시
            self.live.update(ROOM_HINT)

    def show_think(self, name: str, chunk: str):
        self.live.update(f"🧠 [{name}] thinking... {chunk[-160:]}")
        self.busy.update(total=None)

    def show_stream(self, name: str, chunk: str):
        self.live.update(f"✍️ [{name}] {chunk[-160:]}")
        self.busy.update(total=None)

    def show_question(self):
        """PO(또는 에이전트)의 질문이 왔을 때 입력을 활성화."""
        self.prompt.disabled = False
        self.prompt.placeholder = "🤔 PO 질문에 답변하세요 (Enter)..."
        self.prompt.focus()

    def show_steps(self, name: str, state: str):
        self.steps_view.set_state(name, state)

    def show_done(self):
        self._app.pipeline = None
        self._app.pipeline_chat_id = None
        info = chats.get_info(self.chat_id)
        self._app.title = info.get("title") or chats.DEFAULT_TITLE
        self.prompt.disabled = False
        self.prompt.placeholder = "메시지를 입력하세요 (Enter 로 실행)..."
        self.prompt.focus()

    # --- 방 전환 / 이름 수정 ---
    def action_rooms(self):
        self._app.active_chat = None
        self._app.switch_screen(ChatListView(self._app))

    def action_rename(self):
        self.app.push_screen(
            RenameDialog(chats.get_title(self.chat_id)),
            self._rename_done,
        )

    def _rename_done(self, result):
        if not result:
            return
        chats.set_title(self.chat_id, result)
        self._app.title = result
        self._app.sub_title = f"room {self.chat_id}"
        self.activity.update(f"✏️ 이름을 '{result}'(으)로 변경했습니다.  {ROOM_HINT}")

    def action_delete_chat(self):
        if self._app.pipeline is not None:
            self.activity.update(f"⛔ 파이프라인이 실행 중입니다. 종료 후 삭제하세요.  {ROOM_HINT}")
            return
        title = chats.get_title(self.chat_id)
        self.app.push_screen(
            ConfirmDialog(
                f"채팅방 '{title}'\n대화와 작업 결과물을 영구 삭제합니다.\n계속할까요?"
            ),
            self._delete_done,
        )

    def _delete_done(self, result):
        if not result:
            return
        chats.delete_room(self.chat_id)
        self._app.active_chat = None
        # 모달 dismiss가 끝난 뒤 방 목록으로 전환 (타이머로 예약)
        self.app.set_timer(0.05, self._go_to_rooms)

    def _go_to_rooms(self):
        self._app.switch_screen(ChatListView(self._app))

    def action_new_chat(self):
        chat_id = chats.create_chat()
        self._app.active_chat = chat_id
        self._app.switch_screen(ChatRoomView(self._app, chat_id))

    def action_quit(self):
        self._app.exit()
class PipelineApp(App):
    TITLE = "AI Coding Pipeline (Chat)"
    CSS = """
    #body { padding: 0 1; }
    #steps { height: 9; }
    #activity {
        height: 3;
        border: round $primary;
        content-align: left middle;
        padding: 0 1;
    }
    #live {
        height: 3;
        border: round $accent;
        content-align: left middle;
        padding: 0 1;
    }
    #busy { height: 1; }
    #chat {
        height: 1fr;
        border: round $secondary;
        padding: 0 1;
    }
    #prompt { height: 3; }
    #chat-list { height: 1fr; border: round $primary; padding: 0 1; }
    #hint { height: 1; color: $text-muted; }
    .bubble { margin: 0 0 1 0; }
    RenameDialog, ConfirmDialog {
        align: center middle;
    }
    #rename-dialog {
        width: 60;
        height: 7;
        border: round $primary;
        padding: 0 1;
    }
    #rename-title { text-style: bold; text-align: center; }
    #rename-hint { color: $text-muted; text-align: center; }
    #confirm-dialog {
        width: 60;
        height: 7;
        border: round $error;
        padding: 0 1;
    }
    #confirm-message { text-style: bold; }
    #confirm-hint { color: $text-muted; text-align: center; }
    """

    BINDINGS = [("ctrl+q", "quit", "종료")]

    def __init__(self):
        super().__init__()
        self.queue: Queue = Queue()
        self.pipeline = None
        self.pipeline_chat_id: str | None = None
        self.active_chat: str | None = None

    def on_mount(self):
        self.set_interval(0.1, self._poll_queue)
        self.push_screen(ChatListView(self))

    def action_quit(self):
        self.exit()

    # --- 파이프라인 이벤트 큐 → 현재 화면 ---
    def _poll_queue(self):
        try:
            while True:
                event = self.queue.get_nowait()
                self._handle_event(event)
        except Empty:
            pass

    def _handle_event(self, ev: tuple):
        room = self.screen if isinstance(self.screen, ChatRoomView) else None
        if room is None:
            return  # 목록 화면에서는 건너뜀 (기록은 먼저 저장되어 있음)
        kind = ev[0]
        if kind == "chat":
            room.show_chat(ev[1], ev[2])
        elif kind == "activity":
            room.show_activity(ev[1])
        elif kind == "step_start":
            room.show_steps(ev[1], RUNNING)
        elif kind == "step_done":
            room.show_steps(ev[1], DONE)
        elif kind == "step_fail":
            room.show_steps(ev[1], FAILED)
        elif kind == "work_start":
            room.show_work_start(ev[1])
        elif kind == "work_end":
            room.show_work_end(ev[1])
        elif kind == "think":
            room.show_think(ev[1], ev[2])
        elif kind == "stream":
            room.show_stream(ev[1], ev[2])
        elif kind == "question":
            room.show_question()
        elif kind == "error":
            room.show_chat("System", f"🚨 오류\n{ev[1]}")
        elif kind == "done":
            room.show_done()


if __name__ == "__main__":
    PipelineApp().run()