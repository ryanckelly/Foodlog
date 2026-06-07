"""Weigh-in protocol classification.

Scheme B (foodlog-aou, 2026-06-06): a weigh-in is ``controlled_morning`` iff it
falls on or after ``WEIGH_IN_PROTOCOL_CUTOFF`` — the date the user committed to a
consistent once-daily morning routine (post-void, pre-breakfast, consistent
clothing). Everything before the cutoff is ``uncontrolled``. **Time-of-day is
deliberately not consulted.**

Why no clock window (this is the important part — see the warning in
``body_sim/CLAUDE.md`` before changing it):

- The user takes exactly one disciplined weigh-in per day. A clock window adds
  no signal over the cutoff gate for that pattern.
- The previous implementation compared a *naive-UTC* ``measured_at`` against a
  07:00–11:00 window written with *local-time* intent. The user's 08:00–09:00
  Atlantic weigh-ins land at 11:00–12:00 UTC — just past the window — so every
  real weigh-in was mislabeled ``uncontrolled``, silently feeding the Phase-2
  fit the loose ``sigma_obs_uncontrolled`` for the user's *cleanest* data.
- An empirical A/B (timezone-corrected window vs. cutoff-only) produced
  identical labels on all real data; the window only ever mattered for
  hypothetical off-time post-cutoff readings, which don't occur.

The trade made by scheme B: a stray off-time / clothed reading taken *after* the
cutoff is trusted as ``controlled_morning`` by default. Such readings are
dropped at the source via ``pipeline.EXCLUDED_BODY_COMP_IDS`` (manual), not by a
clock window. **If the weigh-in routine changes (different time of day, or
multiple weigh-ins per day), revisit this** — either exclude the off-protocol
rows or set a new cutoff. See ``body_sim/CLAUDE.md`` § "Weigh-in protocol
metadata".

This metadata is soft. ``controlled_evening`` is retained in the ``Protocol``
type for backward compatibility with rollup code that still recognizes
pre-existing rows, but ``classify_protocol`` never emits it.

Used by:
- ``foodlog.services.health_sync._sync_body_composition`` to tag new rows
- ``body_sim.tag_weigh_ins`` to backfill existing rows
- ``body_sim.pipeline.rollup_body_comp`` to expose a daily-aggregate flag
- ``foodlog-adu`` Phase-2 fit to set per-observation sigma_obs
"""

import datetime
from typing import Literal

Protocol = Literal["controlled_morning", "controlled_evening", "uncontrolled"]

# Date the user committed to a consistent once-daily morning weigh-in routine.
# Pre-cutoff readings are NOT trusted — there's no record of whether they
# followed the same post-void / pre-breakfast / consistent-clothing discipline.
WEIGH_IN_PROTOCOL_CUTOFF: datetime.date = datetime.date(2026, 5, 21)


def classify_protocol(measured_at: datetime.datetime) -> Protocol:
    """Return the protocol label for a weigh-in datetime (scheme B: cutoff-only)."""
    if measured_at.date() < WEIGH_IN_PROTOCOL_CUTOFF:
        return "uncontrolled"
    return "controlled_morning"
