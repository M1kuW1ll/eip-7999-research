"""Named state-growth profiles for state limit derivation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateGrowthProfile:
    name: str
    annual_growth_gib: float
    cpsb: int
    blocks_per_year: int = 2_628_000
    limit_target_ratio: int = 2

    def __post_init__(self) -> None:
        if self.annual_growth_gib < 0:
            raise ValueError("annual_growth_gib must be non-negative")
        if self.cpsb <= 0:
            raise ValueError("cpsb must be positive")
        if self.blocks_per_year <= 0:
            raise ValueError("blocks_per_year must be positive")
        if self.limit_target_ratio <= 0:
            raise ValueError("limit_target_ratio must be positive")


BRIEF_100GIB_CPSB1174 = StateGrowthProfile(
    name="brief_100gib_cpsb1174",
    annual_growth_gib=100,
    cpsb=1174,
    limit_target_ratio=2,
)


CURRENT_EIP8037_120GIB_CPSB1530 = StateGrowthProfile(
    name="current_eip8037_120gib_cpsb1530",
    annual_growth_gib=120,
    cpsb=1530,
    limit_target_ratio=2,
)
