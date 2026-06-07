import datetime

import pytest

from body_sim import weigh_in


# Scheme B (foodlog-aou): the protocol label is gated SOLELY by the cutoff date.
# Every reading on/after WEIGH_IN_PROTOCOL_CUTOFF is the user's trusted daily
# routine reading -> "controlled_morning". Time-of-day is NOT consulted: the
# user takes one disciplined morning weigh-in a day, and the rare off-time /
# clothed reading is dropped via pipeline.EXCLUDED_BODY_COMP_IDS, not by a clock
# window. This replaces the old 07:00-11:00 window, which compared a naive-UTC
# timestamp against a local-time-intent window and mislabeled every real
# weigh-in as uncontrolled.


def test_controlled_after_cutoff_morning():
    dt = datetime.datetime(2026, 5, 22, 9, 30)
    assert weigh_in.classify_protocol(dt) == "controlled_morning"


def test_uncontrolled_before_cutoff_even_if_morning():
    dt = datetime.datetime(2026, 5, 20, 9, 30)
    assert weigh_in.classify_protocol(dt) == "uncontrolled"


def test_cutoff_date_itself_is_controlled():
    dt = datetime.datetime(2026, 5, 21, 9, 0)
    assert weigh_in.classify_protocol(dt) == "controlled_morning"


def test_time_of_day_does_not_matter_after_cutoff():
    """The defining property of scheme B: post-cutoff, ANY time-of-day is the
    trusted routine reading. No clock window, so no timezone/DST sensitivity."""
    for hour in (0, 6, 7, 9, 11, 12, 15, 19, 20, 22, 23):
        dt = datetime.datetime(2026, 5, 22, hour, 30)
        assert weigh_in.classify_protocol(dt) == "controlled_morning", (
            f"hour={hour} should be controlled post-cutoff under scheme B"
        )


def test_no_controlled_evening_emitted():
    """classify_protocol never emits controlled_evening under scheme B; the
    evening window was part of the abandoned diurnal design. (The literal value
    is retained in the Protocol type only for backward compat with rollup code
    that still recognizes pre-existing controlled_evening rows.)"""
    for hour in (19, 20, 21, 22):
        dt = datetime.datetime(2026, 6, 1, hour, 0)
        assert weigh_in.classify_protocol(dt) != "controlled_evening"
        assert weigh_in.classify_protocol(dt) == "controlled_morning"


def test_just_before_cutoff_is_uncontrolled():
    dt = datetime.datetime(2026, 5, 20, 23, 59)
    assert weigh_in.classify_protocol(dt) == "uncontrolled"
