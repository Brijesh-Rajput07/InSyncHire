# LOCATION: services/agent_service/agent_service/tools/sandbox_execution_tool.py

"""
`sandbox_execution_tool` (Section: GRAPH 1 -- `code_analysis_node` --
"sandbox_execution_tool(code, language, test_cases) → runs in Piston/
Judge0, returns {stdout, stderr, passed_tests, failed_tests,
execution_time_ms, memory_used_mb}").

*** INTERIM / MOCKED -- DO NOT WIRE UP REAL CODE EXECUTION HERE WITHOUT
EXPLICIT CONFIRMATION ***

Section 10a is unambiguous: "NEVER exec/eval/subprocess candidate code
on app server. Always through sandbox service." This module does NOT
call a real Piston/Judge0 sandbox, does NOT shell out, and does NOT
`exec`/`eval` anything -- it returns a deterministic, clearly-labeled
mock result (`SandboxExecutionResult.mocked=True`) computed from static
properties of the submitted `test_cases` list only (never running the
candidate's `code` string in any interpreter).

This keeps `code_analysis_node`'s guardrail wiring (Rule 2.2's semantic
consistency check needs a real `sandbox_passed_tests` value to compare
against the LLM's claimed `correctness_pct`) structurally complete and
testable NOW, without taking on the very real security/infra decision
of standing up an actual sandboxed execution environment (network
isolation, CPU/mem/time limits, disposable filesystem) as a side effect
of an unrelated milestone. Swapping in a real Piston/Judge0 HTTP client
behind this exact function signature is a follow-up task that should be
explicitly requested and reviewed on its own, precisely because Section
10a calls out this specific operation as needing extra care.
"""

from __future__ import annotations

from ..schemas.interview_io_schemas import SandboxExecutionResult


def run_in_sandbox(
    *,
    code: str,
    language: str,
    test_cases: list[dict] | None = None,
) -> SandboxExecutionResult:
    """Returns a MOCKED result. `code` is never executed, interpreted,
    or passed to `exec`/`eval`/`subprocess` -- Section 10a. The mock
    result is deterministic given `test_cases` alone, so the same
    submission always produces the same mocked pass/fail counts (useful
    for exercising Rule 2.2's sandbox-vs-LLM consistency check in
    tests) without ever touching `code`'s actual content.
    """
    total_cases = len(test_cases) if test_cases else 0
    # Deterministic mock: every declared test case "passes" in the mock
    # world. This is intentionally naive -- a real sandbox is the only
    # thing that could tell us otherwise, and pretending otherwise here
    # would be worse than an honest, clearly-labeled no-op.
    return SandboxExecutionResult(
        stdout="",
        stderr="",
        passed_tests=total_cases,
        failed_tests=0,
        execution_time_ms=0,
        memory_used_mb=0.0,
        mocked=True,
    )