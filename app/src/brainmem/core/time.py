"""逻辑时间源。所有"现在"从这里取，测试可注入，禁止散落 time.time()。"""
import time
from typing import Protocol

SECONDS_PER_DAY = 86400.0


class TimeSource(Protocol):
    def now_day(self) -> float: ...
    def now_real(self) -> int: ...


class SystemClock:
    """真实时钟：逻辑天 = Unix 秒 / 86400（从 epoch 起）。"""

    def now_day(self) -> float:
        return time.time() / SECONDS_PER_DAY

    def now_real(self) -> int:
        return int(time.time())


class FakeClock:
    """可注入的假时钟，用于确定性测试。"""

    def __init__(self, start_day: float = 0.0):
        self._day = float(start_day)

    def now_day(self) -> float:
        return self._day

    def now_real(self) -> int:
        return int(self._day * SECONDS_PER_DAY)

    def advance_days(self, days: float) -> None:
        self._day += float(days)

    def advance_minutes(self, minutes: float) -> None:
        self._day += float(minutes) / 1440.0

    def set_day(self, day: float) -> None:
        self._day = float(day)
