import pytest

from body_sim import tef


def test_tef_zero_intake():
    assert tef.tef_kcal(protein_g=0, carb_g=0, fat_g=0) == 0.0


def test_tef_protein_only():
    # 100g protein = 400 kcal, TEF = 0.25*400 = 100
    assert tef.tef_kcal(protein_g=100, carb_g=0, fat_g=0) == pytest.approx(100.0)


def test_tef_mixed_meal():
    # 150g protein (600 kcal), 200g carb (800 kcal), 60g fat (540 kcal)
    # TEF = 0.25*600 + 0.08*800 + 0.03*540 = 150 + 64 + 16.2 = 230.2
    assert tef.tef_kcal(protein_g=150, carb_g=200, fat_g=60) == pytest.approx(230.2, abs=0.1)


def test_tef_high_carb_vs_high_protein_same_kcal():
    # Same kcal, different macros → different TEF (high-protein burns more)
    hi_protein = tef.tef_kcal(protein_g=150, carb_g=200, fat_g=60)  # ~2000 kcal
    hi_carb = tef.tef_kcal(protein_g=80, carb_g=250, fat_g=80)  # ~2040 kcal, similar
    assert hi_protein > hi_carb
