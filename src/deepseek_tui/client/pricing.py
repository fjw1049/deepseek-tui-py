from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.protocol.responses import Usage


@dataclass(frozen=True, slots=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cache_write_per_million: float = 0.0
    cache_read_per_million: float = 0.0

    def estimate_cost(self, usage: Usage) -> float:
        return (
            usage.input_tokens / 1_000_000 * self.input_per_million
            + usage.output_tokens / 1_000_000 * self.output_per_million
            + usage.cache_creation_input_tokens / 1_000_000 * self.cache_write_per_million
            + usage.cache_read_input_tokens / 1_000_000 * self.cache_read_per_million
        )


class PricingTable:
    def __init__(self) -> None:
        self._pricing: dict[str, ModelPricing] = {
            "deepseek-chat": ModelPricing(input_per_million=0.27, output_per_million=1.10),
            "deepseek-reasoner": ModelPricing(input_per_million=0.55, output_per_million=2.19),
        }

    def get(self, model_name: str) -> ModelPricing | None:
        return self._pricing.get(model_name)
