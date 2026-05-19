import numpy as np
import pytest

from body_sim import adaptation


def test_no_adaptation_at_zero_balance():
    state = adaptation.AdaptiveThermogenesisState()
    # Maintenance: 7 days of zero ΔE
    for _ in range(7):
        state = adaptation.update(state, delta_e_kcal=0, rmr_kcal=1700)
    assert state.adapt == pytest.approx(0.0, abs=0.005)


def test_adapt_drops_during_deficit():
    state = adaptation.AdaptiveThermogenesisState()
    for _ in range(30):
        state = adaptation.update(state, delta_e_kcal=-500, rmr_kcal=1700)
    assert state.adapt < -0.01  # at least 1% drop


def test_adapt_rises_during_surplus():
    state = adaptation.AdaptiveThermogenesisState()
    for _ in range(30):
        state = adaptation.update(state, delta_e_kcal=500, rmr_kcal=1700)
    assert state.adapt > 0.01


def test_adapt_capped_at_bounds():
    state = adaptation.AdaptiveThermogenesisState()
    # Extreme prolonged deficit
    for _ in range(365):
        state = adaptation.update(state, delta_e_kcal=-1500, rmr_kcal=1700)
    assert state.adapt >= -adaptation.MAX_ADAPT


def test_kcal_term_scales_with_rmr():
    state = adaptation.AdaptiveThermogenesisState(adapt=-0.05)
    assert adaptation.kcal_term(state, rmr_kcal=2000) == pytest.approx(-100.0)
