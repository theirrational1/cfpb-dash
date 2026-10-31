"""USD per million tokens (input, output). Unknown models fail loudly; never assume free."""

from agent.adapters.base import Usage

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "fake": (0.0, 0.0),
    "qwen3.5:9b-q4_K_M": (0.0, 0.0),  # local
    "qwen3.6:27b-q4_K_M": (0.0, 0.0),  # local
}


class UnknownModelPrice(LookupError):
    pass


def cost_usd(model: str, usage: Usage) -> float:
    if model not in PRICES_PER_MTOK:
        raise UnknownModelPrice(
            f"no price for model {model!r}; add it to agent/adapters/pricing.py"
        )
    price_in, price_out = PRICES_PER_MTOK[model]
    return (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000
