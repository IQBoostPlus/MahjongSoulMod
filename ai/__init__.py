"""
AI 决策引擎
"""

from .shanten import ShantenCalculator, to_count_array, TILE_COUNT, MAX_PER_TILE
from .engine import (
    AIDecisionMaker,
    CandidateDiscard,
    StrategyParams,
    GameAction,
    ActionType,
    DoraCalculator,
    DefenseAnalysis,
    cached_shanten,
    clear_shanten_cache,
)

__all__ = [
    "ShantenCalculator",
    "AIDecisionMaker",
    "CandidateDiscard",
    "StrategyParams",
    "GameAction",
    "ActionType",
    "DoraCalculator",
    "DefenseAnalysis",
    "to_count_array",
    "TILE_COUNT",
    "MAX_PER_TILE",
    "cached_shanten",
    "clear_shanten_cache",
]
