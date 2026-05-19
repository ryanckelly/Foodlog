"""One-day state update for the extended Hall energy-balance model.

Composes Keytel HR-to-kcal, Mifflin RMR, TEF, Forbes partition, glycogen-water,
sodium-water, and adaptive thermogenesis into a single per-day step function.

This is the kernel of the simulator. Both forward simulation and validation
call `step()` repeatedly with daily inputs.
"""

import math
from dataclasses import dataclass, field

from body_sim import adaptation, glycogen, partition, rmr, sodium, tef
from body_sim.config import (
    DEFAULT_PARAMETERS,
    KCAL_PER_KG_FAT,
    KCAL_PER_KG_LEAN,
    UserProfile,
)

HR_COVERAGE_THRESHOLD_PCT = 50.0
KCAL_PER_STEP = 0.04  # rough fallback when HR data is unavailable


@dataclass
class BodyState:
    fat_mass_kg: float
    lean_mass_kg: float
    glycogen_g: float = glycogen.INITIAL_GLYCOGEN_G
    adapt: adaptation.AdaptiveThermogenesisState = field(
        default_factory=adaptation.AdaptiveThermogenesisState
    )

    @property
    def total_mass_kg(self) -> float:
        return self.fat_mass_kg + self.lean_mass_kg

    def predicted_weight_kg(self, sodium_mg: float) -> float:
        """Predicted scale reading: total mass + glycogen water + sodium water."""
        return (
            self.fat_mass_kg
            + self.lean_mass_kg
            + glycogen.water_kg_from_glycogen(self.glycogen_g)
            + sodium.water_kg(sodium_mg)
        )

    @property
    def body_fat_pct(self) -> float:
        return 100.0 * self.fat_mass_kg / max(0.001, self.total_mass_kg)


# Note: `vigorous_min` is part of the input schema but not consumed at Phase 1.
# Reserved for future MET-based intensity weighting (Phase 3+).
def _activity_kcal(inputs: dict, parameters: dict) -> tuple[float, str]:
    """Pick HR-Keytel when coverage is high; fall back to workout + steps."""
    hr_coverage = inputs.get("hr_coverage_pct", 0.0)
    if hr_coverage >= HR_COVERAGE_THRESHOLD_PCT:
        kcal = inputs["ee_hr_keytel_kcal"] * parameters["activity_bias"]
        return kcal, "keytel"
    workout = inputs.get("workout_kcal", 0.0)
    steps = inputs.get("steps", 0) or 0
    kcal = (workout + steps * KCAL_PER_STEP) * parameters["activity_bias"]
    return kcal, "fallback"


def step(
    state: BodyState,
    inputs: dict,
    profile: UserProfile,
    parameters: dict | None = None,
) -> tuple[BodyState, dict]:
    """Advance the body state by one day.

    Args:
        state: previous-day state
        inputs: daily input dict (see module docstring for keys)
        profile: user profile (age, sex, height)
        parameters: model parameters; defaults to population values

    Returns:
        (new state, diagnostics dict with derived intermediates)
    """
    if parameters is None:
        parameters = DEFAULT_PARAMETERS

    # Skip-and-return-unchanged for missing-intake days. The daily-rollup
    # pipeline produces NaN intake when meal coverage is insufficient; that
    # day's state should not be advanced. Validation harness handles missing
    # observation days separately.
    intake_kcal = inputs.get("intake_kcal")
    if intake_kcal is None or not math.isfinite(intake_kcal):
        return state, {"skipped": True, "reason": "non-finite intake_kcal"}

    if parameters["intake_bias"] <= 0:
        raise ValueError(
            f"intake_bias must be positive, got {parameters['intake_bias']}"
        )

    # --- Effective intake: correct for systematic under-reporting ---
    effective_intake = intake_kcal / parameters["intake_bias"]

    # --- Expenditure components ---
    rmr_kcal = rmr.mifflin_st_jeor(
        weight_kg=state.total_mass_kg,
        height_cm=profile["height_cm"],
        age=profile["age"],
        sex=profile["sex"],
    ) * parameters["RMR_scale"]

    activity_kcal, activity_source = _activity_kcal(inputs, parameters)

    tef_kcal = tef.tef_kcal(
        protein_g=inputs["protein_g"],
        carb_g=inputs["carb_g"],
        fat_g=inputs["fat_g"],
    )

    # Adaptive thermogenesis uses the *previous* adapt state
    adapt_kcal = adaptation.kcal_term(state.adapt, rmr_kcal)

    expenditure = rmr_kcal + activity_kcal + tef_kcal + adapt_kcal
    delta_e = effective_intake - expenditure

    # --- Partition: what share of ΔE flows to/from fat vs lean ---
    p = partition.adjusted_p(
        fat_mass_kg=state.fat_mass_kg,
        protein_g=inputs["protein_g"],
        weight_kg=state.total_mass_kg,
        delta_e_kcal=delta_e,
        protein_protection=parameters["protein_protection"],
    )

    delta_fat = p * delta_e / KCAL_PER_KG_FAT
    delta_lean = (1 - p) * delta_e / KCAL_PER_KG_LEAN

    # --- Update slow compartments ---
    new_glycogen = glycogen.update(state.glycogen_g, inputs["carb_g"])
    new_adapt = adaptation.update(state.adapt, delta_e_kcal=delta_e, rmr_kcal=rmr_kcal)

    new_state = BodyState(
        fat_mass_kg=max(2.0, state.fat_mass_kg + delta_fat),
        lean_mass_kg=max(20.0, state.lean_mass_kg + delta_lean),
        glycogen_g=new_glycogen,
        adapt=new_adapt,
    )

    diagnostics = {
        "effective_intake_kcal": effective_intake,
        "rmr_kcal": rmr_kcal,
        "activity_kcal": activity_kcal,
        "activity_source": activity_source,
        "tef_kcal": tef_kcal,
        "adapt_kcal": adapt_kcal,
        "expenditure_kcal": expenditure,
        "delta_e_kcal": delta_e,
        "partition_p": p,
        "delta_fat_kg": delta_fat,
        "delta_lean_kg": delta_lean,
        "predicted_weight_kg": new_state.predicted_weight_kg(inputs["sodium_mg"]),
    }
    return new_state, diagnostics
