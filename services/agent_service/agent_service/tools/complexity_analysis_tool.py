# LOCATION: services/agent_service/agent_service/tools/complexity_analysis_tool.py

"""
`complexity_analysis_tool` (Section: GRAPH 1 -- `code_analysis_node` --
"complexity_analysis_tool(code, language) → static analysis: time/space
complexity estimate, style issues").

Rule-based (regex/heuristic line scanning), never an LLM call -- same
"deterministic tool, not LLM" precedent `profile_scorer_tool` (M6)
established for ranking scores. `code` is analyzed as TEXT only (line
counts, loop-nesting heuristics, simple style checks) -- it is never
`exec`/`eval`'d (Section 10a), and per Layer 1 Rule 1.4 the caller
(`code_analysis_node`) still wraps `code` in `<candidate_data>` before
it reaches any LLM prompt elsewhere in the same node; this tool itself
never builds an LLM prompt at all.

This is a lightweight heuristic, not a real static analyzer (no AST
parsing per language) -- good enough to populate
`CodeAnalysisResult.complexity_estimate`/`style_issues` with something
real and auditable, flagged the same way M6's `rag_job_similarity_tool`
flagged its own Jaccard-similarity stand-in.
"""

from __future__ import annotations

import re

from ..schemas.interview_io_schemas import ComplexityAnalysisResult

_NESTED_LOOP_PATTERN = re.compile(r"^(\s*)(for|while)\b", re.MULTILINE)
_LONG_LINE_THRESHOLD = 120


def analyze_complexity(*, code: str, language: str) -> ComplexityAnalysisResult:
    lines = code.splitlines()
    line_count = len(lines)

    # Heuristic: count loop keywords and their indentation depth to
    # guess at nested-loop time complexity. Two or more distinct
    # indentation depths starting a loop keyword suggests nested loops.
    loop_indents = {len(m.group(1)) for m in _NESTED_LOOP_PATTERN.finditer(code)}
    loop_count = len(_NESTED_LOOP_PATTERN.findall(code))

    if loop_count == 0:
        time_estimate = "O(1)"
    elif len(loop_indents) >= 2:
        time_estimate = "O(n^2) or worse (nested loops detected)"
    else:
        time_estimate = "O(n)"

    style_issues: list[str] = []
    for i, line in enumerate(lines, start=1):
        if len(line) > _LONG_LINE_THRESHOLD:
            style_issues.append(f"line {i} exceeds {_LONG_LINE_THRESHOLD} characters")
        if line.rstrip() != line and line.strip():
            style_issues.append(f"line {i} has trailing whitespace")

    space_estimate = "O(n)" if "append" in code or "[]" in code or "{}" in code else "O(1)"

    return ComplexityAnalysisResult(
        time_complexity_estimate=time_estimate,
        space_complexity_estimate=space_estimate,
        style_issues=style_issues[:10],
        line_count=line_count,
    )