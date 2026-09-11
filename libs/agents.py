"""파이프라인 단계별 Agent.

OpenRouter(OpenAI 호환 API)를 사용하며, workspace 파일 도구와 셸 테스트 도구를
호출한다. 모든 Agent는 emit(event_type, payload) 콜백으로 TUI에 로그를 전달한다.
"""
import re

from openai import OpenAI

import config
import tools


class Agent:
    """공통 베이스: OpenAI 호환 클라이언트 + 프롬프트 파일 로드 + emit."""

    name = "Agent"
    prompt_file = None  # Tester 는 프롬프트 파일이 없음

    def __init__(self, emit=None):
        self.emit = emit or (lambda *args: None)
        self._client = None

    @property
    def client(self):
        # API 키가 없어도 Agent 생성은 가능하도록 호출 시점에 지연 생성
        if self._client is None:
            self._client = OpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.BASE_URL)
        return self._client

    def log(self, msg):
        self.emit("log", f"[{self.name}] {msg}")

    def system_prompt(self) -> str:
        if self.prompt_file is None:
            return ""
        return (config.PROMPTS_DIR / self.prompt_file).read_text(encoding="utf-8")

    def chat(self, user_text: str, system: str | None = None) -> str:
        if system is None:
            system = self.system_prompt()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_text})
        resp = self.client.chat.completions.create(
            model=config.MODEL,
            messages=messages,
        )
        return resp.choices[0].message.content or ""


def _format_files(files: dict) -> str:
    if not files:
        return "(빈 workspace)"
    return "\n".join(f"--- {rel} ---\n{content}" for rel, content in files.items())


class Analyzer(Agent):
    name = "Analyzer"
    prompt_file = "analyzer.txt"

    def run(self, ctx: dict) -> dict:
        self.log("요청 분석 시작")
        out = self.chat(f"사용자 요청:\n{ctx['request']}")
        ctx["analysis"] = out
        self.log("분석 완료")
        return {"analysis": out}


class Planner(Agent):
    name = "Planner"
    prompt_file = "planner.txt"

    def run(self, ctx: dict) -> dict:
        self.log("구현 계획 수립 시작")
        user = f"사용자 요청:\n{ctx['request']}\n\n분석 결과:\n{ctx.get('analysis', '')}"
        out = self.chat(user)
        ctx["plan"] = out
        self.log("계획 수립 완료")
class Coder(Agent):
    name = "Coder"
    prompt_file = "coder.txt"

    def run(self, ctx: dict) -> dict:
        self.log("코드 작성 시작")
        files = tools.read_workspace_files()
        user = (
            f"사용자 요청:\n{ctx['request']}\n\n"
            f"분석:\n{ctx.get('analysis', '')}\n\n"
            f"계획:\n{ctx.get('plan', '')}\n\n"
            f"현재 workspace 파일:\n{_format_files(files)}"
        )
        out = self.chat(user)
        blocks = tools.parse_file_blocks(out)
        written = []
        for rel, content in blocks:
            tools.write_file(rel, content)
            written.append(rel)
            self.log(f"파일 작성: {rel}")
        if not written:
            self.log("⚠️ Coder가 파일 블록을 생성하지 못했습니다 (원본 응답 기록).")
            ctx["coder_raw"] = out
        ctx["written_files"] = written
        self.log(f"코드 작성 완료 ({len(written)}개 파일)")
        return {"written_files": written, "raw": out}


class Tester(Agent):
    """LLM으로 테스트 명령을 결정한 뒤 셸에서 실행한다. (프롬프트 파일 없음)"""

    name = "Tester"

    def run(self, ctx: dict) -> dict:
        self.log("테스트 명령 결정 중")
        file_list = "\n".join(sorted(tools.read_workspace_files().keys())) or "(빈 workspace)"
        prompt = (
            "다음 프로젝트를 테스트하기 위한 단일 셸 명령어를 하나만 제시하라.\n"
            "JSON이나 마크다운 코드펜스 없이 명령어 한 줄만 출력하라.\n\n"
            f"계획:\n{ctx.get('plan', '')}\n\n프로젝트 파일:\n{file_list}"
        )
        try:
            cmd = self.chat(prompt).strip().splitlines()[0].strip()
        except Exception as e:  # noqa: BLE001 - 키 없음/네트워크 등 → 기본 명령
            self.log(f"테스트 명령 결정 실패, 기본 명령 사용: {e}")
            cmd = "python -m pytest"
        cmd = cmd.strip("`\"'").strip()
        self.log(f"테스트 명령: {cmd}")

        result = tools.run_command(cmd, timeout=config.TEST_TIMEOUT)
        ctx["test"] = result
        ctx["test_command"] = cmd
        self.log(f"테스트 완료 (exit={result['exit_code']})")
        if result["stdout"].strip():
            self.log(f"[stdout] {result['stdout'][-800:].strip()}")
        if result["stderr"].strip():
            self.log(f"[stderr] {result['stderr'][-800:].strip()}")
        return result


class Reviewer(Agent):
    name = "Reviewer"
    prompt_file = "reviewer.txt"

    def run(self, ctx: dict) -> dict:
        self.log("구현 결과 검토 시작")
        files = tools.read_workspace_files()
        test = ctx.get("test", {})
        user = (
            f"사용자 요청:\n{ctx['request']}\n\n"
            f"계획:\n{ctx.get('plan', '')}\n\n"
            f"테스트 결과 (exit={test.get('exit_code')}):\n"
            f"STDOUT:\n{test.get('stdout', '')[-2000:]}\n"
            f"STDERR:\n{test.get('stderr', '')[-2000:]}\n\n"
            f"구현 파일:\n{_format_files(files)}"
        )
        out = self.chat(user)
        verdict = "PASS" if re.search(r"VERDICT:\s*PASS", out, re.IGNORECASE) else "FAIL"
        ctx["review"] = out
        ctx["verdict"] = verdict
        self.log(f"검토 완료: VERDICT={verdict}")
        return {"verdict": verdict, "review": out}


class Fixer(Agent):
    name = "Fixer"
    prompt_file = "fixer.txt"

    def run(self, ctx: dict) -> dict:
        self.log("코드 수정 시작")
        files = tools.read_workspace_files()
        test = ctx.get("test", {})
        user = (
            f"사용자 요청:\n{ctx['request']}\n\n"
            f"계획:\n{ctx.get('plan', '')}\n\n"
            f"리뷰 의견:\n{ctx.get('review', '')}\n\n"
            f"실패한 테스트 (exit={test.get('exit_code')}):\n"
            f"STDOUT:\n{test.get('stdout', '')[-3000:]}\n"
            f"STDERR:\n{test.get('stderr', '')[-3000:]}\n\n"
            f"현재 파일:\n{_format_files(files)}"
        )
        out = self.chat(user)
        blocks = tools.parse_file_blocks(out)
        written = []
        for rel, content in blocks:
            tools.write_file(rel, content)
            written.append(rel)
            self.log(f"수정 파일: {rel}")
        ctx["fixed_files"] = written
        self.log(f"수정 완료 ({len(written)}개 파일)")
        return {"fixed_files": written}


class Finalizer(Agent):
    name = "Finalizer"
    prompt_file = "finalizer.txt"

    def run(self, ctx: dict) -> dict:
        self.log("최종 요약 시작")
        files = tools.read_workspace_files()
        test = ctx.get("test", {})
        user = (
            f"사용자 요청:\n{ctx['request']}\n\n"
            f"계획:\n{ctx.get('plan', '')}\n\n"
            f"최종 테스트 (exit={test.get('exit_code')}):\n"
            f"STDOUT:\n{test.get('stdout', '')[-2000:]}\n"
            f"STDERR:\n{test.get('stderr', '')[-2000:]}\n\n"
            f"최종 파일:\n{_format_files(files)}"
        )
        out = self.chat(user)
        ctx["summary"] = out
        self.log("최종 요약 완료")
        return {"summary": out}
        return {"plan": out}