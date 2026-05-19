"""Forbes partition fraction and protein-protection modifier.

Forbes 1987 + Hall 2008. The fraction `p` of energy imbalance that flows
into/out of fat mass (vs lean mass) is a monotonic function of current fat mass.
The protein-protection modifier increases lean-mass preservation during caloric
deficit when protein intake is adequate.
"""

from body_sim.config import DEFAULT_PARAMETERS

FORBES_C = 10.4  # kg, calibrated for adult population
PROTEIN_PROTECTION_THRESHOLD_G_PER_KG = 1.6


def forbes_p(fat_mass_kg: float) -> float:
    """Forbes partition fraction: share of ΔE that goes to/from fat mass.

    Higher fat mass → larger p (more of imbalance moves fat, less moves lean).
    Returned value is in (0, 1).
    """
    return fat_mass_kg / (fat_mass_kg + FORBES_C)


def adjusted_p(
    fat_mass_kg: float,
    protein_g: float,
    weight_kg: float,
    delta_e_kcal: float,
    protein_protection: float | None = None,
) -> float:
    """Forbes p with protein-protection modifier applied in deficit.

    Args:
        fat_mass_kg: current fat mass
        protein_g: today's protein intake in grams
        weight_kg: current total body weight
        delta_e_kcal: today's energy imbalance (negative = deficit)
        protein_protection: optional override of the personalized parameter

    Returns:
        Adjusted p, capped at [0, 1].
    """
    if protein_protection is None:
        protein_protection = DEFAULT_PARAMETERS["protein_protection"]
    p = forbes_p(fat_mass_kg)
    if delta_e_kcal >= 0:
        return p  # surplus: no protection effect
    protein_per_kg = protein_g / weight_kg if weight_kg > 0 else 0.0
    if protein_per_kg < PROTEIN_PROTECTION_THRESHOLD_G_PER_KG:
        return p
    return min(1.0, p * (1.0 + protein_protection))
