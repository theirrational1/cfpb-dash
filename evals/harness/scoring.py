"""Deterministic scoring. Do not edit to make a result pass (AGENTS.md)."""


def score(value: int | float | None, expected: int | float) -> str:
    """E1 numeric answers: exact match against the SQL ground truth."""
    if value is None:
        return "fail"
    return "pass" if float(value) == float(expected) else "fail"
