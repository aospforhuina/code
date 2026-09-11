"""고정 파이프라인 오케스트레이션.

Analyzer → Planner → Coder → (Tester → Reviewer → Fixer 반복) → Finalizer
Fixer 는 문제가 없거나 최대 MAX_FIX_ATTEMPTS 회에 도달할 때까지 반복한다.
"""
import traceback

import agents
import config

# TUI 에 표시할 고정 단계 순서
STEPS = [
    "Analyzer", "Planner", "Coder",
    "Tester", "Reviewer", "Fixer", "Finalizer",
]


class Pipeline:
    def __init__(self, request: str, emit=None):
        self.request = request
        # emit(event_type, payload) — 기본은 무시
        self.emit = emit or (lambda *args: None)
        self.context = {"request": request}

    def run(self):
        """스레드에서 호출. 예외는 잡아서 emit 으로 보고하고 done 을 보낸다."""
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self.emit("error", f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        finally:
            self.emit("done", self.context.get("summary", "파이프라인 완료"))

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
                self.emit("log", "✅ 검토 통과 및 테스트 성공.")
                break

            if fix_count >= config.MAX_FIX_ATTEMPTS:
                self.emit("log", f"⚠️ 최대 수정 횟수({config.MAX_FIX_ATTEMPTS}회) 도달. 종료합니다.")
                break

            fix_count += 1
            self.emit("activity", f"문제 발견. 코드 수정 중... ({fix_count}/{config.MAX_FIX_ATTEMPTS})")
            self._step("Fixer", lambda: fixer.run(self.context))

        self.emit("activity", "최종 결과를 요약하는 중...")
        self._step("Finalizer", lambda: finalizer.run(self.context))
