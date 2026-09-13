"""workspace 파일 읽기/쓰기, 셸 테스트 실행 도구."""
import os
import re
import subprocess
from pathlib import Path

import config

# 읽기에서 제외할 디렉터리/파일
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git", ".env", ".pytest_cache"}

# DevA/DevB/DevC/Fixer 가 출력하는 파일 블록 형식
FILE_RE = re.compile(r"=== FILE: (.+?) ===\r?\n(.*?)\r?\n=== END FILE ===", re.DOTALL)


def read_workspace_files():
    """workspace 내 모든 텍스트 파일을 {상대경로: 내용} 으로 반환."""
    files = {}
    for root, dirs, names in os.walk(config.WORKSPACE_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name in SKIP_DIRS:
                continue
            p = Path(root) / name
            try:
                rel = str(p.relative_to(config.WORKSPACE_DIR))
                files[rel] = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
    return files


def _resolve(rel_path: str) -> Path:
    """workspace 내부로 경로를 제한(디렉터리 트래버설 방지)."""
    base = config.WORKSPACE_DIR.resolve()
    target = (base / rel_path).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"경로가 workspace 밖입니다: {rel_path}")
    return target


def write_file(rel_path: str, content: str) -> str:
    """파일 생성 또는 전체 덮어쓰기."""
    target = _resolve(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return rel_path


def parse_file_blocks(text: str):
    """'=== FILE: path === ... === END FILE ===' 블록을 파싱해 [(경로, 내용)] 반환."""
    return [(m.group(1).strip(), m.group(2)) for m in FILE_RE.finditer(text)]


def run_command(command: str, cwd=None, timeout: int = 300) -> dict:
    """셸 명령 실행. stdout/stderr/exit_code 수집."""
    cwd = cwd or config.WORKSPACE_DIR
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
        return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired as e:
        return {
            "exit_code": -1,
            "stdout": e.stdout or "",
            "stderr": (e.stderr or "") + "\n[TIMEOUT]",
        }
    except Exception as e:  # noqa: BLE001
        return {"exit_code": -2, "stdout": "", "stderr": str(e)}
