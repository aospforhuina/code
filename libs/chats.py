"""채팅방(작업 세션) 저장소.

각 작업은 하나의 "채팅방"으로 관리되며:
  libs/chats/<id>/info.json     - 방 정보(제목, 생성/수정 시각)
  libs/chats/<id>/messages.jsonl - 대화 내역(작성자, 내용, 시각)
  workspace/<id>/               - 작업 결과물 (루트 workspace 아래 채팅방별 저장)

데이터베이스 없이 파일로만 저장한다.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

import config

CHATS_DIR = config.BASE_DIR / "chats"
DEFAULT_TITLE = "새 대화"

# 루트 workspace 의 고정 기준.
# (config.WORKSPACE_DIR 은 실행 중 채팅방별로 바뀌므로, 방 경로 계산에는 이 상수를 쓴다)
WORKSPACE_ROOT = config.WORKSPACE_DIR


def _chat_dir(chat_id: str) -> Path:
    return CHATS_DIR / chat_id


def _info_path(chat_id: str) -> Path:
    return _chat_dir(chat_id) / "info.json"


def _msgs_path(chat_id: str) -> Path:
    return _chat_dir(chat_id) / "messages.jsonl"


def create_chat(title: str = DEFAULT_TITLE) -> str:
    """새 채팅방 생성 후 chat_id 반환."""
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    chat_id, n = base, 2
    while _chat_dir(chat_id).exists():
        chat_id = f"{base}-{n}"
        n += 1
    _chat_dir(chat_id).mkdir(parents=True, exist_ok=True)
    workspace_dir(chat_id).mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    _write_info(chat_id, {"id": chat_id, "title": title, "created": now, "updated": now})
    return chat_id


def get_info(chat_id: str) -> dict:
    try:
        return json.loads(_info_path(chat_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get_title(chat_id: str) -> str:
    return get_info(chat_id).get("title", DEFAULT_TITLE)


def _write_info(chat_id: str, info: dict):
    _info_path(chat_id).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def set_title(chat_id: str, title: str):
    info = get_info(chat_id)
    info["title"] = title.strip() or DEFAULT_TITLE
    _write_info(chat_id, info)


def _touch(chat_id: str):
    info = get_info(chat_id)
    info["updated"] = datetime.now().isoformat(timespec="seconds")
    _write_info(chat_id, info)


def list_chats() -> list[dict]:
    """채팅방 목록 (최근 수정순)."""
    out = []
    if not CHATS_DIR.exists():
        return out
    for d in CHATS_DIR.iterdir():
        if d.is_dir() and _info_path(d.name).exists():
            info = get_info(d.name)
            if info:
                out.append(info)
    out.sort(key=lambda i: i.get("updated", ""), reverse=True)
    return out


def append_message(chat_id: str, author: str, content: str):
    """대화 메시지 추가."""
    msg = {
        "author": author,
        "content": content,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    with open(_msgs_path(chat_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    _touch(chat_id)


def load_messages(chat_id: str) -> list[dict]:
    """저장된 대화 내역을 순서대로 반환."""
    try:
        lines = _msgs_path(chat_id).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def workspace_dir(chat_id: str) -> Path:
    """채팅방 전용 작업 결과물 경로 (루트 workspace/<채팅방>/)."""
    return WORKSPACE_ROOT / chat_id


def delete_room(chat_id: str):
    """채팅방 삭제: 대화 기록(libs/chats/<id>) + 작업 결과물(workspace/<id>) 제거."""
    shutil.rmtree(_chat_dir(chat_id), ignore_errors=True)
    shutil.rmtree(workspace_dir(chat_id), ignore_errors=True)