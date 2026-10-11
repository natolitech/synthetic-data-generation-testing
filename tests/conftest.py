"""Shared fixtures: seeded Faker + frozen clock for determinism."""

from datetime import datetime

import pytest
from faker import Faker

from synthgen.clock import _Clock


FROZEN = datetime(2026, 6, 15, 12, 0, 0)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Free the shared clock so seeded generation is byte-deterministic."""
    monkeypatch.setattr(_Clock, "now", staticmethod(lambda: FROZEN))
    monkeypatch.setattr(_Clock, "today", staticmethod(lambda: FROZEN.date()))
    return FROZEN


@pytest.fixture
def fake():
    Faker.seed(42)
    return Faker()


@pytest.fixture(autouse=True)
def _seed_random():
    import random
    random.seed(42)
