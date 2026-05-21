import datetime

import pytest

from body_sim import weigh_in


def test_controlled_morning_after_cutoff():
    dt = datetime.datetime(2026, 5, 22, 9, 30)
    assert weigh_in.classify_protocol(dt) == "controlled_morning"


def test_uncontrolled_before_cutoff_even_if_morning():
    dt = datetime.datetime(2026, 5, 20, 9, 30)
    assert weigh_in.classify_protocol(dt) == "uncontrolled"


def test_evening_after_cutoff_is_controlled_evening():
    """Evening in the 19:00-22:00 window after cutoff is controlled_evening
    (foodlog-dwt extension). Outside that window remains uncontrolled."""
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 19, 0)) == "controlled_evening"
    # Midday afternoon is still uncontrolled
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 15, 0)) == "uncontrolled"
    # Very late evening is uncontrolled
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 23, 30)) == "uncontrolled"


def test_boundary_hours_inclusive():
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 7, 0)) == "controlled_morning"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 11, 0)) == "controlled_morning"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 6, 59)) == "uncontrolled"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 11, 1)) == "uncontrolled"


def test_boundary_date_inclusive():
    dt = datetime.datetime(2026, 5, 21, 9, 0)
    assert weigh_in.classify_protocol(dt) == "controlled_morning"


def test_controlled_evening_after_cutoff():
    dt = datetime.datetime(2026, 6, 1, 20, 0)
    assert weigh_in.classify_protocol(dt) == "controlled_evening"


def test_evening_boundary_hours_inclusive():
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 19, 0)) == "controlled_evening"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 22, 0)) == "controlled_evening"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 18, 59)) == "uncontrolled"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 22, 1)) == "uncontrolled"


def test_midday_is_uncontrolled():
    assert weigh_in.classify_protocol(datetime.datetime(2026, 6, 1, 14, 0)) == "uncontrolled"
