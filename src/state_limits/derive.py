"""Derive per-block state gas targets and limits from growth profiles."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .profiles import StateGrowthProfile


@dataclass(frozen=True)
class StateLimitResult:
    profile_name: str
    annual_growth_gib: float
    cpsb: int
    blocks_per_year: int
    limit_target_ratio: int
    target_bytes_per_block: float
    state_gas_target: int
    state_gas_limit: int


def derive_state_limit(profile: StateGrowthProfile) -> StateLimitResult:
    annual_growth_gib = Fraction(str(profile.annual_growth_gib))
    target_bytes = annual_growth_gib * 2**30
    target_bytes_per_block = float(target_bytes / int(profile.blocks_per_year))
    state_gas_target = int(
        target_bytes * int(profile.cpsb) // int(profile.blocks_per_year)
    )
    state_gas_limit = state_gas_target * int(profile.limit_target_ratio)

    return StateLimitResult(
        profile_name=profile.name,
        annual_growth_gib=float(profile.annual_growth_gib),
        cpsb=int(profile.cpsb),
        blocks_per_year=int(profile.blocks_per_year),
        limit_target_ratio=int(profile.limit_target_ratio),
        target_bytes_per_block=target_bytes_per_block,
        state_gas_target=state_gas_target,
        state_gas_limit=state_gas_limit,
    )
