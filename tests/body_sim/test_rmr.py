import pytest

from body_sim import rmr


def test_rmr_male_known_value():
    # 80kg, 180cm, 40yr, male
    # = 10*80 + 6.25*180 - 5*40 + 5 = 800 + 1125 - 200 + 5 = 1730
    assert rmr.mifflin_st_jeor(weight_kg=80, height_cm=180, age=40, sex="male") == pytest.approx(1730)


def test_rmr_female_known_value():
    # 70kg, 165cm, 40yr, female
    # = 10*70 + 6.25*165 - 5*40 - 161 = 700 + 1031.25 - 200 - 161 = 1370.25
    assert rmr.mifflin_st_jeor(weight_kg=70, height_cm=165, age=40, sex="female") == pytest.approx(1370.25)


def test_rmr_scales_with_weight():
    a = rmr.mifflin_st_jeor(weight_kg=70, height_cm=180, age=40, sex="male")
    b = rmr.mifflin_st_jeor(weight_kg=80, height_cm=180, age=40, sex="male")
    assert b - a == pytest.approx(100.0)


def test_rmr_rejects_invalid_sex():
    with pytest.raises(ValueError):
        rmr.mifflin_st_jeor(weight_kg=80, height_cm=180, age=40, sex="other")
