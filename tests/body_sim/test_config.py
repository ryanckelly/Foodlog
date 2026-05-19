from body_sim import config


def test_default_profile_has_required_fields():
    profile = config.DEFAULT_PROFILE
    assert "age" in profile
    assert "sex" in profile
    assert "height_cm" in profile
    assert profile["sex"] in ("male", "female")


def test_default_parameters_are_population_means():
    params = config.DEFAULT_PARAMETERS
    assert params["intake_bias"] == 0.85
    assert params["RMR_scale"] == 1.0
    assert params["NEAT_response"] == 0.2
    assert params["protein_protection"] == 0.5
    assert params["activity_bias"] == 1.0
    assert params["water_noise_sd"] > 0


def test_tef_coefficients_match_spec():
    coeffs = config.TEF_COEFFICIENTS
    assert coeffs["protein"] == 0.25
    assert coeffs["carb"] == 0.08
    assert coeffs["fat"] == 0.03


def test_glycogen_water_ratio():
    assert config.GLYCOGEN_WATER_G_PER_G == 3.5
