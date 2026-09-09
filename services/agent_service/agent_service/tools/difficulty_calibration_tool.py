# LOCATION: services/agent_service/agent_service/tools/difficulty_calibration_tool.py

"""
`difficulty_calibration_tool` (Section: GRAPH 1 -- `question_strategist_node`
-- "difficulty_calibration_tool(code_analysis_results, question_history)
→ determines appropriate next difficulty level based on performance").

Rule-based on the running average of `correctness_pct` across the
session's `code_analysis_results` so far -- never an LLM call, so
nothing about which difficulty gets picked next can be influenced by
prompt injection in the candidate's code (the same "keep scoring
decisions outside the LLM" precedent `profile_scorer_tool` established
for Graph 2's ranking score).
"""

from __future__ import annotations

from ..schemas.interview_io_schemas import DifficultyCalibrationResult

DIFFICULTY_LADDER = ["easy", "medium", "hard"]


def calibrate_difficulty(
    *,
    correctness_percentages: list[float],
    current_difficulty: str | None = None,
) -> DifficultyCalibrationResult:
    """`correctness_percentages` is every `CodeAnalysisResult.correctness_pct`
    recorded so far this session (state.code_analysis_results), oldest
    first. An empty list means no signal yet -- starts at 'medium'."""
    if not correctness_percentages:
        return DifficultyCalibrationResult(
            recommended_difficulty="medium",
            rationale="No prior performance data this session -- starting at medium difficulty.",
            average_correctness_pct=None,
        )

    average = sum(correctness_percentages) / len(correctness_percentages)
    current_index = DIFFICULTY_LADDER.index(current_difficulty) if current_difficulty in DIFFICULTY_LADDER else 1

    if average >= 85.0:
        target_index = min(current_index + 1, len(DIFFICULTY_LADDER) - 1)
        rationale = f"Average correctness {average:.1f}% is strong -- stepping up difficulty."
    elif average <= 40.0:
        target_index = max(current_index - 1, 0)
        rationale = f"Average correctness {average:.1f}% is low -- stepping down difficulty."
    else:
        target_index = current_index
        rationale = f"Average correctness {average:.1f}% is moderate -- holding difficulty steady."

    return DifficultyCalibrationResult(
        recommended_difficulty=DIFFICULTY_LADDER[target_index],
        rationale=rationale,
        average_correctness_pct=round(average, 1),
    )