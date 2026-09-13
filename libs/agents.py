"""파이프라인 단계별 Agent (엔터프라이즈, JSON 기반).

CEO(사용자) → PO/PM(니즈 도출·명세서) → Architect(기술설계)
→ Dev(백엔드 구현) → QA(검수·예외검증) → Fixer(보완) → Finalizer(보고)

- 프롬프트: libs/prompt/<작업AI>.json (role/mission/rules/output_schema). 
  시스템 프롬프트로 렌더링되어 모델 출력을 JSON 스키마로 강제한다.
- 응답: 각 에이전트는 output_schema 의 JSON을 반환하며, _parse_json_response() 로
  안정적으로 파싱한다 (파싱 실패 시 자연어 폴백으로 예외 없이 진행).
- PO 는 CEO(사용자)와 인터랙티브 질의응답을 하며, 질문은 emit("question", ...) 로
  보내고 Pipeline.respond() 로 답변을 받는다 (ctx["_ask"]).
"""
import ast
import json
import re

from openai import OpenAI

import config
import tools


class Agent:
    """공통 베이스: OpenAI 호환 클라이언트 + JSON 프롬프트 렌더링 + emit."""

    name = "Agent"
    prompt_file = None

    def __init__(self, emit=None):
        self.emit = emit or (lambda *args: None)
        self._client = None

    @property
    def client(self):
        if self._client is None:  # API 키가 없어도 생성은 되도록 지연 생성
            self._client = OpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.BASE_URL)
        return self._client

    def log(self, msg):
        self.emit("log", f"[{self.name}] {msg}")

    def chat_msg(self, content):
        self.emit("chat", self.name, content)

    def prompt_data(self) -> dict:
        """libs/prompt/<이름>.json 를 읽어 dict 로 반환."""
        if self.prompt_file is None:
            return {}
        try:
            return json.loads((config.PROMPTS_DIR / self.prompt_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def system_prompt(self) -> str:
        """JSON 프롬프트를 사람이 읽을 수 있는 시스템 프롬프트로 렌더링."""
        data = self.prompt_data()
        if not data:
            return ""
        lines = [f"역할: {data.get('role', self.name)}"]
        mission = data.get("mission")
        if mission:
            lines.append(f"임무: {mission}")
        rules = data.get("rules") or []
        if rules:
            lines.append("규칙:")
            lines += [f"- {rule}" for rule in rules]
        schema = data.get("output_schema")
        if schema:
            lines.append("출력 형식: 반드시 아래 스키마의 JSON 문서 하나만 출력하고, 그 외 텍스트·주석·마크다운은 붙이지 않는다.")
            lines.append(json.dumps(schema, ensure_ascii=False, indent=2))
        return "\n".join(lines)

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

    def chat_stream(self, user_text: str, system: str | None = None) -> str:
        """스트리밍 호출.

        토큰이 도착하면 emit("stream", 이름, 조각) 으로 실시간 출력되고,
        사고 모델의 reasoning 은 emit("think", 이름, 조각) 으로 전달된다.
        작업 시작/종료는 emit("work_start"/"work_end", 이름). 실패 시 비스트리밍 폴백.
        """
        if system is None:
            system = self.system_prompt()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_text})
        self.emit("work_start", self.name)
        try:
            stream = self.client.chat.completions.create(
                model=config.MODEL, messages=messages, stream=True,
            )
            parts = []
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                reason = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if reason:
                    self.emit("think", self.name, reason)
                content = getattr(delta, "content", None)
                if content:
                    parts.append(content)
                    self.emit("stream", self.name, content)
            return "".join(parts)
        except Exception as e:  # noqa: BLE001 - 스트리밍 미지원 등 → 일반 호출
            self.log(f"스트리밍 불가, 일반 호출로 폴백: {type(e).__name__}")
            return self.chat(user_text, system=system)
        finally:
            self.emit("work_end", self.name)

    def ask_llm(self, user_text: str, system: str | None = None) -> str:
        """스트리밍 설정에 따라 응답을 받아온다 (테스트에서 패치하기 쉬운 경로)."""
        return self.chat_stream(user_text, system=system) if config.STREAMING \
            else self.chat(user_text, system=system)


def _format_files(files: dict) -> str:
    if not files:
        return "(파일 없음)"
    return "\n".join(f"--- {rel} ---\n{content}" for rel, content in files.items())


def _parse_json_response(text: str) -> dict:
    """LLM 응답에서 JSON 을 최대한 추출 (실패 시 빈 dict → 자연어 폴백).

    1) 그대로 파싱 → 2) 코드펜스 제거 후 파싱 → 3) 첫 {...} 블록 추출 → 4) 파이썬 리터럴.
    """
    text = (text or "").strip()
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else {}
    except (json.JSONDecodeError, TypeError):
        pass
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    if cleaned and cleaned != text:
        try:
            val = json.loads(cleaned)
            return val if isinstance(val, dict) else {}
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            val = json.loads(m.group(0))
            return val if isinstance(val, dict) else {}
        except json.JSONDecodeError:
            pass
    try:
        val = ast.literal_eval(text)
        return val if isinstance(val, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _files_from(data: dict) -> list[tuple[str, str]]:
    """JSON 의 files 배열 → [(path, content)] 리스트."""
    out = []
    for f in data.get("files") or []:
        if isinstance(f, dict) and f.get("path"):
            out.append((str(f["path"]), str(f.get("content", ""))))
    return out


def _write_blocks(blocks: list[tuple[str, str]], ctx: dict, key: str) -> list[str]:
    """(경로, 내용) 목록을 workspace 에 저장."""
    written = []
    for rel, content in blocks:
        tools.write_file(rel, content)
        written.append(rel)
    ctx[key] = written
    return written


class PO(Agent):
    """PO/PM: CEO(사용자)와 진득한 질의응답(min~max) → 니즈 도출 → PRD 명세서."""

    name = "PO"
    prompt_file = "PO.json"

    def run(self, ctx: dict) -> dict:
        self.log("CEO 니즈 파악을 위한 질의응답 시작")
        ask = ctx.get("_ask")
        max_q = config.PO_MAX_QUESTIONS
        history = ""
        out = ""
        for i in range(1, max_q + 1):
            user = (
                f"CEO 지시:\n{ctx['request']}\n\n"
                f"최근 대화:\n{ctx.get('chat_history', '')}\n\n"
                f"지금까지 질문 수: {len(ctx.get('answers', []))}\n"
                f"지금까지의 질문/답변:\n{history or '(없음)'}"
            )
            out = self.ask_llm(user).strip()
            data = _parse_json_response(out)
            if data.get("action") == "prd":
                break  # PO 가 충분하다고 판단하면 스스로 그만
            question = str(data.get("question") or "").strip() or "조금 더 구체적으로 알려주세요."
            answer = ask(question) if ask else "(없음)"
            history += f"Q. {question}\nA. {answer}\n"
            ctx.setdefault("answers", []).append((question, answer))
        else:
            # 상한 도달 시에만 강제로 PRD 작성
            self.chat_msg(f"질문 횟수 상한({max_q}회)에 도달했습니다. 명세서를 작성합니다.")
            forced = self.ask_llm(
                "질문을 멈추고 지금까지의 정보로 PRD 를 작성하라.\n"
                f"output_schema 의 JSON 으로 action=prd 를 출력하라.\n\n지금까지 답변:\n{history}"
            )
            out = forced

        data = _parse_json_response(out)
        prd = data.get("prd")
        if not isinstance(prd, str):
            prd = json.dumps(data or out, ensure_ascii=False, indent=2)
        prd = prd.strip()
        tools.write_file("docs/PRD.md", prd)
        ctx["prd"] = prd
        n_answers = len(ctx.get("answers", []))
        self.chat_msg(f"📋 명세서(PRD) 작성 완료 ({n_answers}회 질문)\n\n{prd[:800]}")
        return {"prd": prd, "answers": ctx.get("answers", [])}


class Architect(Agent):
    """테크 리드 겸 아키텍트: 시스템 구조/클린 아키텍처/폴더 구조/기술스택 설계."""

    name = "Architect"
    prompt_file = "Architect.json"

    def run(self, ctx: dict) -> dict:
        self.log("기술 설계(아키텍처/폴더/기술스택) 시작")
        files = tools.read_workspace_files()
        user = (
            f"CEO 지시:\n{ctx['request']}\n\n"
            f"PRD(명세서):\n{ctx.get('prd', '')}\n\n"
            f"현재 파일:\n{_format_files(files)}"
        )
        out = self.ask_llm(user)
        blocks = _files_from(_parse_json_response(out))
        written = _write_blocks(blocks, ctx, "arch_files")
        self.chat_msg(
            f"🏗 아키텍처 설계 완료 ({len(written)}개 파일)\n\n{out.strip()[:500]}"
        )
        return {"arch_files": written, "raw": out}


class Dev(Agent):
    """백엔드 개발자. PRD/아키텍처 문서에 따라 프로젝트 전체를 구현한다."""

    name = "Dev"
    prompt_file = "Dev.json"

    def run(self, ctx: dict) -> dict:
        self.log(f"{self.name} 코드 작성 시작")
        files = tools.read_workspace_files()
        arch = files.get("docs/ARCHITECTURE.md", ctx.get("architecture", ""))
        user = (
            f"CEO 지시:\n{ctx['request']}\n\n"
            f"PRD(명세서):\n{ctx.get('prd', '')}\n\n"
            f"아키텍처 문서:\n{arch}\n\n"
            f"현재 파일:\n{_format_files(files)}"
        )
        out = self.ask_llm(user)
        blocks = _files_from(_parse_json_response(out))
        written = _write_blocks(blocks, ctx, "dev_files")
        summary = "\n".join(f"- {rel}" for rel in written) or "- (없음)"
        self.chat_msg(f"✅ {self.name} 구현 완료 ({len(written)}개 파일)\n\n{summary}")
        return {"files": written, "raw": out}


class QA(Agent):
    """QA: 품질 검수 + 테스트 실행 + 예외/에지케이스 검증."""

    name = "QA"
    prompt_file = "QA.json"

    def _pick_test_command(self, ctx: dict) -> str:
        file_list = "\n".join(sorted(tools.read_workspace_files().keys())) or "(없음)"
        instruction = (
            "다음 프로젝트를 테스트하기 위한 단일 셸 명령어를 하나만 제시하라.\n"
            "JSON이나 마크다운 코드펜스 없이 명령어 한 줄만 출력하라."
        )
        try:
            cmd = self.chat(
                f"{instruction}\n\n아키텍처:\n{ctx.get('prd', '')[:400]}\n\n프로젝트 파일:\n{file_list}",
                system="",  # 테스트 명령 결정에는 시스템 프롬프트를 붙이지 않는다
            ).strip().splitlines()[0].strip()
        except Exception as e:  # noqa: BLE001 - 키 없음/네트워크 등 → 기본 명령
            self.log(f"테스트 명령 결정 실패, 기본 명령 사용: {e}")
            cmd = "python -m pytest"
        return cmd.strip("`\"'").strip() or "python -m pytest"

    def run(self, ctx: dict) -> dict:
        self.log("QA 검수 시작")
        # 1) 테스트 실행
        cmd = self._pick_test_command(ctx)
        self.log(f"테스트 명령: {cmd}")
        test = tools.run_command(cmd, timeout=config.TEST_TIMEOUT)
        ctx["test"] = test
        ctx["test_command"] = cmd
        self.log(f"테스트 완료 (exit={test['exit_code']})")

        # 2) 정적 검수 (요구사항/아키텍처/품질/예외상황) → JSON 판정
        files = tools.read_workspace_files()
        user = (
            f"CEO 지시:\n{ctx['request']}\n\n"
            f"PRD(명세서):\n{ctx.get('prd', '')}\n\n"
            f"테스트 결과 (exit={test.get('exit_code')}):\n"
            f"STDOUT:\n{test.get('stdout', '')[-2000:]}\n"
            f"STDERR:\n{test.get('stderr', '')[-2000:]}\n\n"
            f"구현 파일:\n{_format_files(files)}"
        )
        out = self.ask_llm(user, system=self.system_prompt())
        data = _parse_json_response(out)

        raw_verdict = str(data.get("verdict") or "").upper()
        verdict = raw_verdict if raw_verdict in ("PASS", "FAIL") else (
            "FAIL" if test.get("exit_code", 0) != 0 else "PASS"
        )
        report = str(data.get("report") or "").strip() or json.dumps(data, ensure_ascii=False)
        issues = data.get("issues") or []
        if isinstance(issues, str):
            issues = [issues]

        qa_doc = (
            f"VERDICT: {verdict}\n\n테스트 명령: {cmd} (exit={test.get('exit_code')})\n\n{report}"
        )
        if issues:
            qa_doc += "\n\n이슈:\n" + "\n".join(f"- {i}" for i in issues)
        qa_doc += f"\n\n-- 테스트 출력 --\n{test.get('stdout','')[-1000:]}"
        tools.write_file("docs/QA_REPORT.md", qa_doc)
        ctx["qa_report"] = report
        ctx["verdict"] = verdict
        tail = (test.get("stdout") or test.get("stderr"))[-300:].strip() or ""
        self.chat_msg(
            f"🧪 QA 검수 완료 — {verdict}\n명령: {cmd} (exit={test.get('exit_code')})\n\n"
            f"{report.strip()[:600]}\n{tail}"
        )
        return {"verdict": verdict, "report": report, "test": test}


class Fixer(Agent):
    """QA가 발견한 이슈를 수정한다 (수정 후 QA 재실행, 최대 MAX_FIX_ATTEMPTS)."""

    name = "Fixer"
    prompt_file = "Fixer.json"

    def run(self, ctx: dict) -> dict:
        self.log("코드 수정 시작")
        files = tools.read_workspace_files()
        test = ctx.get("test", {})
        user = (
            f"CEO 지시:\n{ctx['request']}\n\n"
            f"PRD(명세서):\n{ctx.get('prd', '')}\n\n"
            f"QA 검수 보고:\n{ctx.get('qa_report', '')}\n\n"
            f"실패한 테스트 (exit={test.get('exit_code')}):\n"
            f"STDOUT:\n{test.get('stdout', '')[-3000:]}\n"
            f"STDERR:\n{test.get('stderr', '')[-3000:]}\n\n"
            f"현재 파일:\n{_format_files(files)}"
        )
        out = self.ask_llm(user)
        blocks = _files_from(_parse_json_response(out))
        written = _write_blocks(blocks, ctx, "fixed_files")
        summary = "\n".join(f"- {rel}" for rel in written) or "- (없음)"
        self.chat_msg(f"🔧 문제 수정 완료 ({len(written)}개 파일)\n\n{summary}")
        return {"fixed_files": written}


class Finalizer(Agent):
    """CEO(사용자)를 위한 최종 보고서 작성."""

    name = "Finalizer"
    prompt_file = "Finalizer.json"

    def run(self, ctx: dict) -> dict:
        self.log("최종 보고서 작성 시작")
        files = tools.read_workspace_files()
        test = ctx.get("test", {})
        user = (
            f"CEO 지시:\n{ctx['request']}\n\n"
            f"PRD(명세서):\n{ctx.get('prd', '')}\n\n"
            f"QA 검수 결과: {ctx.get('verdict', '-')}\n"
            f"QA 보고:\n{ctx.get('qa_report', '')}\n\n"
            f"최종 테스트 (exit={test.get('exit_code')}):\n"
            f"STDOUT:\n{test.get('stdout', '')[-1500:]}\n"
            f"STDERR:\n{test.get('stderr', '')[-1500:]}\n\n"
            f"최종 파일:\n{_format_files(files)}"
        )
        out = self.ask_llm(user)
        data = _parse_json_response(out)
        summary = str(data.get("summary") or "").strip() or out.strip()
        ctx["summary"] = summary
        self.chat_msg(f"🏁 CEO 최종 보고\n\n{summary.strip()}")
        return {"summary": summary}