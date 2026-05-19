"""Adaptive thermogenesis as a slow-moving multiplicative scalar.

Model: a state variable `adapt` (dimensionless) moves toward the recent
trailing energy balance fraction (ΔE/RMR), and the kcal contribution to
expenditure is `adapt * RMR`. Deficit → adapt < 0 → expenditure drops below
what mass alone predicts.

The adaptation timescale is set by TAU; the cap by MAX_ADAPT.
"""

from dataclasses import dataclass


TAU = 0.02            # per-day responsiveness; half-life ~35 days
MAX_ADAPT = 0.20      # ±20% bound


@dataclass
class AdaptiveThermogenesisState:
    adapt: float = 0.0


def update(
    state: AdaptiveThermogenesisState, delta_e_kcal: float, rmr_kcal: float
) -> AdaptiveThermogenesisState:
    """One-day update of the adaptation state.

    Args:
        state: previous-day state
        delta_e_kcal: today's energy imbalance
        rmr_kcal: today's RMR (so we can normalize ΔE)

    Returns:
        New state with `adapt` updated.
    """
    target = delta_e_kcal / rmr_kcal if rmr_kcal > 0 else 0.0
    new_adapt = state.adapt + TAU * (target - state.adapt)
    new_adapt = max(-MAX_ADAPT, min(MAX_ADAPT, new_adapt))
    return AdaptiveThermogenesisState(adapt=new_adapt)


def kcal_term(state: AdaptiveThermogenesisState, rmr_kcal: float) -> float:
    """The kcal contribution to today's expenditure from adaptation."""
    return state.adapt * rmr_kcal
