"""Измерение длительности операций без изменения их результата"""

import time
from contextlib import contextmanager
from contextvars import ContextVar

from utils.logger import log_debug, log_info

_attempt_timings = ContextVar('attempt_timings', default=None)


@contextmanager
def measure_time(operation, *, summary=False):
    """Пишет длительность даже при исключении внутри операции"""
    # У каждой попытки свой набор замеров, в том числе в потоках Flask
    token = _attempt_timings.set({}) if summary else None
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        timings = _attempt_timings.get()
        if summary:
            _attempt_timings.reset(token)
            parts = [f"{name}: {duration:.2f} мс ({count})"
                     for name, (duration, count) in timings.items()]
            details = '; '.join(parts)
            log_info(f"Время: {operation} — {elapsed_ms:.2f} мс; этапы: {details}")
        else:
            if timings is not None:
                duration, count = timings.get(operation, (0, 0))
                timings[operation] = (duration + elapsed_ms, count + 1)
            log_debug(f"Время: {operation} — {elapsed_ms:.2f} мс")
