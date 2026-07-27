"""Domain exceptions — raised inside the agent, caught at API/UI boundaries."""


class CommuteAgentError(Exception):
    """Base for all commute-agent errors."""


class RouteNotFoundError(CommuteAgentError):
    """No route matches the commuter's request."""


class DisruptionCheckError(CommuteAgentError):
    """Disruption feed could not be queried (network, parse, etc.)."""


class NLUParseError(CommuteAgentError):
    """LLM returned output that could not be parsed into a ParsedIntent."""


class EmbeddingError(CommuteAgentError):
    """Vector embedding call failed."""


class MaxReplanAttemptsExceeded(CommuteAgentError):
    """Graph hit the hard cap on replanning iterations."""


class OffTopicQueryError(CommuteAgentError):
    """Commuter's query is not transport-related."""
