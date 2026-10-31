"""Errors that mean "the model got it wrong", as opposed to infrastructure failures.

The eval runner scores AgentModelError subclasses as a case `error`; anything else (mf/DuckDB
failures, missing files, code bugs) propagates and stops the run.
"""


class AgentModelError(Exception):
    """Base for mistakes attributable to the model's output."""


class ToolArgumentError(AgentModelError, ValueError):
    """The model called a tool with arguments the governed layer refuses."""


class FinalAnswerError(AgentModelError, ValueError):
    """The final answer is not the required JSON shape."""


class NoGovernedNumbersError(AgentModelError):
    """The model produced a final answer without calling query_metric."""


class StepLimitError(AgentModelError):
    """The model kept calling tools without giving a final answer."""
