"""Weigh-in protocol classification.

A weigh-in is ``controlled_morning`` if it falls in the consistent morning
routine (07:00–11:00 inclusive, post-void, pre-breakfast) on or after the
cutoff date the user committed to the protocol. Everything else is
``uncontrolled`` — variable hydration / gut state, possibly clothed,
possibly post-meal.

This metadata is soft. Excluded outliers (clothes-on, off-time evening
weigh-ins) are handled by ``pipeline.EXCLUDED_BODY_COMP_IDS`` and don't
appear here.

Used by:
- ``foodlog.services.health_sync._sync_body_composition`` to tag new rows
- ``body_sim.tag_weigh_ins`` to backfill existing rows
- ``body_sim.pipeline.rollup_body_comp`` to expose a daily-aggregate flag
- (future) ``foodlog-adu`` to set per-observation sigma_obs
"""

import datetime
from typing import Literal

Protocol = Literal["controlled_morning", "controlled_evening", "uncontrolled"]

# Date the user committed to consistent morning weigh-ins. Same morning slot
# applied retroactively is NOT trusted — there's no record of whether the
# pre-cutoff morning weigh-ins followed the same post-void / pre-breakfast
# discipline.
WEIGH_IN_PROTOCOL_CUTOFF: datetime.date = datetime.date(2026, 5, 21)

MORNING_HOUR_LO: int = 7
MORNING_HOUR_HI: int = 11
EVENING_HOUR_LO: int = 19
EVENING_HOUR_HI: int = 22


def _in_window(hour: int, minute: int, lo: int, hi: int) -> bool:
    """Return True if (hour:minute) falls in [lo:00, hi:00] inclusive on both ends."""
    if hour < lo or hour > hi:
        return False
    if hour == hi and minute > 0:
        return False
    return True


def classify_protocol(measured_at: datetime.datetime) -> Protocol:
    """Return the protocol label for a weigh-in datetime."""
    if measured_at.date() < WEIGH_IN_PROTOCOL_CUTOFF:
        return "uncontrolled"
    hour = measured_at.hour
    minute = measured_at.minute
    if _in_window(hour, minute, MORNING_HOUR_LO, MORNING_HOUR_HI):
        return "controlled_morning"
    if _in_window(hour, minute, EVENING_HOUR_LO, EVENING_HOUR_HI):
        return "controlled_evening"
    return "uncontrolled"
