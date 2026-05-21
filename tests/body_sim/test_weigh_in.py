import datetime

import pytest

from body_sim import weigh_in


def test_controlled_morning_after_cutoff():
    dt = datetime.datetime(2026, 5, 22, 9, 30)
    assert weigh_in.classify_protocol(dt) == "controlled_morning"


def test_uncontrolled_before_cutoff_even_if_morning():
    dt = datetime.datetime(2026, 5, 20, 9, 30)
    assert weigh_in.classify_protocol(dt) == "uncontrolled"


def test_uncontrolled_evening_after_cutoff():
    dt = datetime.datetime(2026, 5, 22, 19, 0)
    assert weigh_in.classify_protocol(dt) == "uncontrolled"


def test_boundary_hours_inclusive():
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 7, 0)) == "controlled_morning"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 11, 0)) == "controlled_morning"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 6, 59)) == "uncontrolled"
    assert weigh_in.classify_protocol(datetime.datetime(2026, 5, 22, 11, 1)) == "uncontrolled"


def test_boundary_date_inclusive():
    dt = datetime.datetime(2026, 5, 21, 9, 0)
    assert weigh_in.classify_protocol(dt) == "controlled_morning"
