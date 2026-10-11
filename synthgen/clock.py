"""Injectable clock for deterministic tests.

Production code calls clock.now()/clock.today(); tests monkeypatch these to
freeze time so seeded generation becomes byte-stable.
"""
from datetime import date, datetime


class _Clock:
    @staticmethod
    def now() -> datetime:
        return datetime.now()

    @staticmethod
    def today() -> date:
        return date.today()


clock = _Clock()
