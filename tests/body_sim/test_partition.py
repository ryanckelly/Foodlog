import pytest

from body_sim import partition


def test_forbes_p_higher_at_higher_fat():
    p_lean = partition.forbes_p(fat_mass_kg=10)
    p_fat = partition.forbes_p(fat_mass_kg=30)
    assert p_fat > p_lean


def test_forbes_p_in_unit_interval():
    for F in (5, 15, 25, 40):
        p = partition.forbes_p(fat_mass_kg=F)
        assert 0 < p < 1


def test_protein_protection_only_in_deficit():
    # Surplus: protein doesn't change p
    p_base = partition.forbes_p(fat_mass_kg=20)
    p_adj_surplus = partition.adjusted_p(
        fat_mass_kg=20, protein_g=120, weight_kg=80, delta_e_kcal=500
    )
    assert p_adj_surplus == pytest.approx(p_base)


def test_protein_protection_increases_p_in_deficit():
    # Deficit + adequate protein: p shifts toward fat-loss preservation of lean
    p_base = partition.forbes_p(fat_mass_kg=20)
    p_adj_deficit = partition.adjusted_p(
        fat_mass_kg=20, protein_g=150, weight_kg=80, delta_e_kcal=-500  # 1.875 g/kg
    )
    assert p_adj_deficit > p_base


def test_protein_protection_no_effect_below_threshold():
    # Deficit + low protein: no protection
    p_base = partition.forbes_p(fat_mass_kg=20)
    p_adj = partition.adjusted_p(
        fat_mass_kg=20, protein_g=60, weight_kg=80, delta_e_kcal=-500  # 0.75 g/kg
    )
    assert p_adj == pytest.approx(p_base)


def test_protein_protection_capped_at_one():
    # Even with massive protein, p doesn't exceed 1.0
    p_adj = partition.adjusted_p(
        fat_mass_kg=40, protein_g=300, weight_kg=80, delta_e_kcal=-1000
    )
    assert p_adj <= 1.0
