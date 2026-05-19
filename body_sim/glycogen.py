"""Glycogen-bound water compartment.

Carbohydrate intake is stored as glycogen in muscle and liver. Glycogen binds
approximately 3.5 g of water per gram. This is the dominant cause of short-term
weight fluctuations from diet changes (the 'I lost 3 lbs in two days on keto'
phenomenon is mostly water from glycogen depletion).

We model glycogen as a leaky integrator: a fraction of dietary carbs goes into
storage; a fraction of stored glycogen is oxidized per day.
"""

from body_sim.config import GLYCOGEN_WATER_G_PER_G

# Literature defaults
ALPHA = 0.3        # fraction of dietary carbs into short-term glycogen
BETA = 0.4         # fraction of glycogen oxidized per day
INITIAL_GLYCOGEN_G = 400.0
MAX_GLYCOGEN_G = 600.0


def water_kg_from_glycogen(glycogen_g: float) -> float:
    """Bound water in kg given current glycogen stores."""
    return GLYCOGEN_WATER_G_PER_G * glycogen_g / 1000.0


def update(current_glycogen_g: float, carb_g: float) -> float:
    """One-day glycogen update.

    Args:
        current_glycogen_g: glycogen store at start of day
        carb_g: dietary carb intake during the day

    Returns:
        Glycogen store at end of day, bounded [0, MAX_GLYCOGEN_G].
    """
    new = current_glycogen_g + ALPHA * carb_g - BETA * current_glycogen_g
    return max(0.0, min(MAX_GLYCOGEN_G, new))
