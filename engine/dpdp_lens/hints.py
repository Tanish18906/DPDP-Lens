"""Hook for the ML laptop (docs/15 D8). No model code lives here.
A detection that comes from a hint must set Evidence.detector="model" and never rate above medium."""


def semantic_hints(identifiers: list[str]) -> dict:
    """Map identifier names the rules did not classify to a personal data type. Empty until a model is wired in."""
    return {}
