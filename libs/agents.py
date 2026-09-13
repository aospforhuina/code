"""파이프라인 단계별 Agent (엔터프라이즈).

CEO(사용자) → PO/PM(니즈 도출·명세서) → Architect(기술설계)
→ Dev(백엔드 구현) → QA(검수·예외검증) → Fixer(보완) → Finalizer(보고)

- 프롬프트: libs/prompt/<작업AI>.txt (자연어). 파일 내용을 그대로 시스템 프롬프트로 사용.
- 응답 규약(마커):
  PO       → 질문(한 줄) 또는 "=== PRD === ... === END PRD ===" 블록
  Architect/Dev/Fixer → "=== FILE: 경로 === ... === END FILE ===" 블록
  QA       → "VERDICT: PASS/FAIL" + "=== QA_REPORT === ... === END QA_REPORT ==="
  Finalizer→ 자연어 요약
- 스트리밍: chat_stream() 로 실시간 수신(stream/think/work 이벤트), 실패 시 폴백.
- PO 는 CEO(사용자)와 인터랙티브 질의응답(emit "question" → Pipeline.respond()).
"""
import re

from openai import OpenAI

import config
import tools

PRD_RE = re.compile(r"=== PRD ===\s*\n(.*?)\n=== END PRD ===", re.DOTALL)
QA_REPO_RE = re.compile(r"=== QA_REPORT ===\s*\n(.*?)\n=== END QA_REPORT ===", re.DOTALL)
VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)", re.IGNORECASE)


class Agent:
    """공통 베이스: OpenAI 호환 클라이언트 + 자연어 프롬프트 로드 + emit."""

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

    def system_prompt(self) -> str:
        """libs/prompt/<작업AI>.txt 를 그대로 시스템 프롬프트로 사용."""
        if self.prompt_file is None:
            return ""
        try:
            return (config.PROMPTS_DIR / self.prompt_file).read_text(encoding="utf-8")
        except OSError:
            return ""

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

    def ask_llm(self, user_text: str, system: str | None = None) -> str:
        """스트리밍 설정에 따라 응답을 받아온다 (테스트에서 패치하기 쉬운 경로)."""
        return self.chat_stream(user_text, system=system) if config.STREAMING \
            else self.chat(user_text, system=system)


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


def _format_files(files: dict) -> str:
    if not files:
        return "(파일 없음)"
    return "\n".join(f"--- {rel} ---\n{content}" for rel, content in files.items())


def _write_blocks(out: str, ctx: dict, key: str) -> list[str]:
    """"=== FILE: 경로 === ... === END FILE ===" 블록을 파싱해 workspace 에 저장."""
    written = []
    for rel, content in tools.parse_file_blocks(out):
        tools.write_file(rel, content)
        written.append(rel)
    if not written:
        ctx[f"{key}_raw"] = out
    ctx[key] = written
    return written


class PO(Agent):
    """PO/PM: CEO(사용자)와 질의응답(충분하면 스스로 그만) → PRD 명세서."""

    name = "PO"
    prompt_file = "PO.txt"

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
            if PRD_RE.search(out):
                break  # PO 가 충분하다고 판단하면 스스로 그만
            question = out.splitlines()[0].strip() or "조금 더 구체적으로 알려주세요."
            answer = ask(question) if ask else "(없음)"
            history += f"Q. {question}\nA. {answer}\n"
            ctx.setdefault("answers", []).append((question, answer))
        else:
            # 상한 도달 시에만 강제로 PRD 작성
            self.chat_msg(f"질문 횟수 상한({max_q}회)에 도달했습니다. 명세서를 작성합니다.")
            forced = self.ask_llm(
                "질문을 멈추고 지금까지 정보로 아래 형식의 PRD 를 작성하라:\n"
                "=== PRD ===\n<명세서>\n=== END PRD ===\n\n지금까지 답변:\n" + history
            )
            out = forced

        m = PRD_RE.search(out)
        prd = m.group(1).strip() if m else out.strip()
        tools.write_file("docs/PRD.md", prd)
        ctx["prd"] = prd
        n_answers = len(ctx.get("answers", []))
        self.chat_msg(f"📋 명세서(PRD) 작성 완료 ({n_answers}회 질문)\n\n{prd[:800]}")
        return {"prd": prd, "answers": ctx.get("answers", [])}


class Architect(Agent):
    """테크 리드 겸 아키텍트: 시스템 구조/클린 아키텍처/폴더 구조/기술스택 설계."""

    name = "Architect"
    prompt_file = "Architect.txt"

    def run(self, ctx: dict) -> dict:
        self.log("기술 설계(아키텍처/폴더/기술스택) 시작")
        files = tools.read_workspace_files()
        user = (
            f"CEO 지시:\n{ctx['request']}\n\n"
            f"PRD(명세서):\n{ctx.get('prd', '')}\n\n"
            f"현재 파일:\n{_format_files(files)}"
        )
        out = self.ask_llm(user)
        written = _write_blocks(out, ctx, "arch_files")
        self.chat_msg(
            f"🏗 아키텍처 설계 완료 ({len(written)}개 파일)\n\n{out.strip()[:500]}"
        )
        return {"arch_files": written, "raw": out}


class Dev(Agent):
    """백엔드 개발자. PRD/아키텍처 문서에 따라 프로젝트 전체를 구현한다."""

    name = "Dev"
    prompt_file = "Dev.txt"

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
        written = _write_blocks(out, ctx, "dev_files")
        summary = "\n".join(f"- {rel}" for rel in written) or "- (없음)"
        self.chat_msg(f"✅ {self.name} 구현 완료 ({len(written)}개 파일)\n\n{summary}")
        return {"files": written, "raw": out}


class QA(Agent):
    """QA: 품질 검수 + 테스트 실행 + 예외/에지케이스 검증."""

    name = "QA"
    prompt_file = "QA.txt"

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

        # 2) 정적 검수 (요구사항/아키텍처/품질/예외상황)
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

        m_report = QA_REPO_RE.search(out)
        report = m_report.group(1).strip() if m_report else out.strip()
        m_verdict = VERDICT_RE.search(out)
        verdict = m_verdict.group(1).upper() if m_verdict else (
            "FAIL" if test.get("exit_code", 0) != 0 else "PASS"
        )

        qa_doc = (
            f"VERDICT: {verdict}\n\n테스트 명령: {cmd} (exit={test.get('exit_code')})\n\n{report}"
        )
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
    prompt_file = "Fixer.txt"

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
        written = _write_blocks(out, ctx, "fixed_files")
        summary = "\n".join(f"- {rel}" for rel in written) or "- (없음)"
        self.chat_msg(f"🔧 문제 수정 완료 ({len(written)}개 파일)\n\n{summary}")
        return {"fixed_files": written}


class Finalizer(Agent):
    """CEO(사용자)를 위한 최종 보고서 작성."""

    name = "Finalizer"
    prompt_file = "Finalizer.txt"

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
        summary = out.strip()
        ctx["summary"] = summary
        self.chat_msg(f"🏁 CEO 최종 보고\n\n{summary[:1500]}")
        return {"summary": summary}