"""Thermic effect of food (TEF) per macronutrient.

Coefficients reflect the energy cost of digesting and metabolizing each macro:
protein is most expensive (~25%), carbs intermediate (~8%), fat cheapest (~3%).
Source: Westerterp 2004, Nutr Metab.
"""

from body_sim.config import TEF_COEFFICIENTS

KCAL_PER_G_PROTEIN = 4.0
KCAL_PER_G_CARB = 4.0
KCAL_PER_G_FAT = 9.0


def tef_kcal(protein_g: float, carb_g: float, fat_g: float) -> float:
    """Thermic effect of food given macronutrient intake in grams.

    Returns:
        TEF in kcal/day.
    """
    protein_kcal = protein_g * KCAL_PER_G_PROTEIN
    carb_kcal = carb_g * KCAL_PER_G_CARB
    fat_kcal = fat_g * KCAL_PER_G_FAT
    return (
        TEF_COEFFICIENTS["protein"] * protein_kcal
        + TEF_COEFFICIENTS["carb"] * carb_kcal
        + TEF_COEFFICIENTS["fat"] * fat_kcal
    )
