"""Deterministic strategy registry for research orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.strategy.engine import StrategyConfig, evaluate_signal


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    name: str
    description: str
    timeframe_role: str
    evaluator: Callable = evaluate_signal


STRATEGIES: dict[str, StrategyDefinition] = {
    "sma_rsi_momentum": StrategyDefinition(
        strategy_id="sma_rsi_momentum",
        name="SMA / RSI Momentum",
        description="Moving-average trend context with RSI momentum confirmation.",
        timeframe_role="research",
    ),
}


def list_strategies() -> list[dict[str, str]]:
    return [
        {
            "strategy_id": item.strategy_id,
            "name": item.name,
            "description": item.description,
            "timeframe_role": item.timeframe_role,
        }
        for item in STRATEGIES.values()
    ]


def evaluate_registered_strategy(
    strategy_id: str,
    candles: list[dict],
    config: StrategyConfig | None = None,
) -> dict:
    definition = STRATEGIES.get(strategy_id)
    if definition is None:
        raise ValueError(f"Unknown strategy_id: {strategy_id}")
    return definition.evaluator(candles, config or StrategyConfig())
