"""Payload propagation safety helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PropagationFit:
    name: str
    slope_ms_per_kb: float
    intercept_ms: float


EMPIRICAL_P90 = PropagationFit(
    name="empirical_p90",
    slope_ms_per_kb=0.443,
    intercept_ms=569,
)

CONSERVATIVE_P90 = PropagationFit(
    name="conservative_p90",
    slope_ms_per_kb=1.061,
    intercept_ms=355,
)


def propagation_time_ms(payload_bytes: int | float, fit: PropagationFit) -> float:
    return fit.intercept_ms + fit.slope_ms_per_kb * (float(payload_bytes) / 1024)


def safe_payload_bytes(
    window_ms: int | float,
    fit: PropagationFit,
    safety_factor: float = 0.75,
) -> int:
    usable_ms = float(window_ms) * float(safety_factor)
    remaining_ms = usable_ms - fit.intercept_ms
    if remaining_ms <= 0:
        return 0
    return int((remaining_ms / fit.slope_ms_per_kb) * 1024)
