"""Opt-in, bounded verification diagnostics; never acceptance evidence.

Only fixed aggregate labels are retained. Nested inclusive durations overlap;
exclusive durations attribute time to the nearest measured phase. The collector
does not read project files, record paths, persist state or change gate outcomes.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter_ns


PHASES = frozenset({
    "root_gate", "historical_gate", "history_context", "history_attempt",
    "history_completion", "history_resolution", "snapshot_validation",
    "source_hashing", "json_parsing", "source_inventory", "progress_projection",
})
COUNTERS = frozenset({
    "history_context_requests", "history_context_cache_hits",
    "history_attempt_requests", "history_attempt_cache_hits",
    "history_completion_requests", "history_completion_cache_hits",
    "snapshot_hash_requests", "snapshot_hash_cache_hits", "snapshot_hash_bytes",
    "source_hash_requests", "source_hash_cache_hits", "source_hash_bytes",
    "json_parse_requests", "json_cache_hits", "json_parse_bytes",
    "section_index_builds", "section_index_cache_hits", "path_checks",
    "snapshot_files_validated", "timing_depth_limited",
})
MAX_DEPTH = 128
MAX_COUNT = (1 << 63) - 1
_active = ContextVar("sdd_verification_metrics", default=None)
_frames = ContextVar("sdd_verification_metrics_frames", default=())


class Observation:
    def __init__(self, enabled):
        self.enabled = enabled
        self.started = perf_counter_ns() if enabled else 0
        self.finished = None
        self.counters = {}
        self.timings = {}
        self.saturated = False

    def increment(self, name, amount):
        current = self.counters.get(name, 0)
        value = current + amount
        self.counters[name] = min(value, MAX_COUNT)
        self.saturated |= value > MAX_COUNT

    def snapshot(self):
        """Return a detached, fixed-cardinality report with no source identifiers."""
        elapsed = ((self.finished if self.finished is not None else perf_counter_ns()) - self.started
                   if self.enabled else 0)
        return {
            "version": 1,
            "enabled": self.enabled,
            "elapsed_seconds": round(max(0, elapsed) / 1_000_000_000, 9),
            "counters": dict(sorted(self.counters.items())),
            "phases": {name: {
                "calls": values[0], "errors": values[1],
                "inclusive_seconds": round(values[2] / 1_000_000_000, 9),
                "exclusive_seconds": round(values[3] / 1_000_000_000, 9),
            } for name, values in sorted(self.timings.items())},
            "saturated": self.saturated,
            "qualification": "Diagnostic aggregates only; nested inclusive timings overlap. No test execution or acceptance is implied.",
        }


@contextmanager
def collect(enabled=True):
    """Measure one synchronous invocation; nested checkers share its collector."""
    observation = Observation(bool(enabled))
    token = _active.set(observation if enabled else None)
    frames = _frames.set(())
    try:
        yield observation
    finally:
        if enabled:
            observation.finished = perf_counter_ns()
        _frames.reset(frames)
        _active.reset(token)


def count(name, amount=1):
    observation = _active.get()
    if observation is None:
        return
    if name not in COUNTERS:
        raise ValueError("unknown verification metric")
    if type(amount) is not int or amount < 0:
        raise ValueError("verification metric increment must be a nonnegative integer")
    observation.increment(name, amount)


@contextmanager
def phase(name):
    observation = _active.get()
    if observation is None:
        yield
        return
    if name not in PHASES:
        raise ValueError("unknown verification phase")
    parents = _frames.get()
    if len(parents) >= MAX_DEPTH:
        count("timing_depth_limited")
        yield
        return
    frame = [perf_counter_ns(), 0]
    token = _frames.set(parents + (frame,))
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        duration = max(0, perf_counter_ns() - frame[0])
        values = observation.timings.setdefault(name, [0, 0, 0, 0])
        values[0] += 1
        values[1] += int(failed)
        values[2] += duration
        values[3] += max(0, duration - frame[1])
        _frames.reset(token)
        if parents:
            parents[-1][1] += duration


def timed(name):
    """Instrument a synchronous helper without changing its result or errors."""
    if name not in PHASES:
        raise ValueError("unknown verification phase")
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            with phase(name):
                return function(*args, **kwargs)
        return measured
    return decorate
