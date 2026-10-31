"""Deterministic scoring. Do not edit to make a result pass (AGENTS.md)."""


def score(value: int | float | None, expected: int | float) -> str:
    """E1 numeric answers: exact match against the SQL ground truth."""
    if value is None:
        return "fail"
    return "pass" if float(value) == float(expected) else "fail"


def score_case(
    value: int | float | None,
    expected: int | float,
    value_traced: bool,
    untraced_numbers: list[float],
) -> tuple[str, str | None]:
    """E1 case status and reason. Every number spoken must be traceable (PRD §1): an untraced
    number in the answer text fails the case even when `value` is right."""
    if score(value, expected) == "fail":
        return "fail", "wrong_value"
    if not value_traced:
        return "fail", "value_not_traced"
    if untraced_numbers:
        return "fail", "untraced_numbers"
    return "pass", None
