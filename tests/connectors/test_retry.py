"""F02-E1: the one retry executor (AT-E1-1, -2, -4, -5, -8, -12)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict

import pytest

from decoy_engine import progress
from decoy_engine.connectors import _retry
from decoy_engine.connectors._retry import DEFAULT_POLICY, RetryPolicy, run_retrying
from decoy_engine.progress import RetryInfo
from decoy_engine.sdk import PermanentError, TransientError

CANARY = "zz-canary-host-key-bucket"


def _transient() -> TransientError:
    return TransientError("S3 transient network or service error", kind="transient")


def _flaky(failures: int, kind_error=_transient):
    calls: list[int] = []

    def op() -> str:
        calls.append(1)
        if len(calls) <= failures:
            raise kind_error()
        return "done"

    return op, calls


def test_transient_twice_then_success_sleeps_with_jitter() -> None:  # AT-E1-1
    op, calls = _flaky(2)
    sleeps: list[float] = []
    # rand() == 1.0 gives the top of the jitter band, +25 percent.
    assert run_retrying(op, sleep=sleeps.append, rand=lambda: 1.0) == "done"
    assert len(calls) == 3
    assert sleeps == pytest.approx([1.0 * 1.25, 2.0 * 1.25])
    low: list[float] = []
    op2, _ = _flaky(2)
    run_retrying(op2, sleep=low.append, rand=lambda: 0.0)
    assert low == pytest.approx([0.75, 1.5])
    mid: list[float] = []
    op3, _ = _flaky(2)
    run_retrying(op3, sleep=mid.append, rand=lambda: 0.5)
    assert mid == pytest.approx([1.0, 2.0])


@pytest.mark.parametrize(
    "make",
    [
        lambda: PermanentError("x", kind="rejected"),
        lambda: PermanentError("x", kind="source_changed"),
        lambda: PermanentError("x", kind="host_key_rejected"),
        lambda: PermanentError("x", kind="digest_mismatch"),
        lambda: ValueError("x"),
    ],
    ids=["permanent", "source_changed", "host_key_rejected", "digest_mismatch", "value_error"],
)
def test_anything_but_transient_leaves_after_one_call(make) -> None:  # AT-E1-2
    op, calls = _flaky(5, make)
    with pytest.raises(type(make())):
        run_retrying(op, sleep=lambda s: None)
    assert len(calls) == 1


def test_exhausted_attempts_reraise_the_last_error() -> None:
    op, calls = _flaky(99)
    with pytest.raises(TransientError) as info:
        run_retrying(op, sleep=lambda s: None)
    assert len(calls) == DEFAULT_POLICY.attempts == 3
    assert info.value.kind == "transient"


def test_deadline_stops_before_a_sleep_that_would_pass_it() -> None:  # AT-E1-4
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    op, calls = _flaky(99)
    policy = RetryPolicy(deadline_s=3.0)
    with pytest.raises(TransientError) as info:
        run_retrying(op, policy=policy, sleep=sleep, clock=lambda: now[0], rand=lambda: 0.5)
    # A 3.0 s deadline allows the sleeps of 1.0 and 2.0 s (3.0 is not past 3.0), so all three
    # attempts run and the last error leaves after the attempts, not the deadline.
    assert sleeps == [1.0, 2.0]
    assert len(calls) == 3
    assert info.value.__cause__ is None and info.value.__context__ is None
    now[0] = 0.0
    sleeps.clear()
    op2, calls2 = _flaky(99)
    with pytest.raises(TransientError) as info2:
        run_retrying(
            op2,
            policy=RetryPolicy(deadline_s=2.5),
            sleep=sleep,
            clock=lambda: now[0],
            rand=lambda: 0.5,
        )
    assert sleeps == [1.0] and len(calls2) == 2
    assert info2.value.__cause__ is None and info2.value.__context__ is None


def test_retries_are_reported_as_operation_events() -> None:  # AT-E1-5
    seen: list[progress.ProgressEvent] = []
    op, _ = _flaky(99, lambda: TransientError(f"S3 {CANARY}", kind="transient"))
    with progress.use_progress(progress.CallbackSink(seen.append)):
        with pytest.raises(TransientError):
            run_retrying(op, sleep=lambda s: None, rand=lambda: 0.5)
    retries = [e.retry for e in seen if e.kind == "retry"]
    assert [(r.attempt, r.retries_completed, r.state) for r in retries] == [
        (2, 1, "scheduled"),
        (3, 2, "scheduled"),
        (3, 2, "exhausted"),
    ]
    assert all(r.scope == "operation" for r in retries)
    assert [r.delay_s for r in retries] == [1.0, 2.0, None]
    dumped = json.dumps([asdict(e) for e in seen], default=str)
    assert CANARY not in dumped


def test_sdk_docstring_defaults_equal_the_policy() -> None:  # AT-E1-8
    from decoy_engine.sdk import TransientError as T

    doc = " ".join((T.__doc__ or "").split())
    match = re.search(
        r"defaults: (\d+) attempts, ([\d.]+)s base, ([\d.]+)x backoff, \+/- (\d+)% jitter", doc
    )
    assert match, doc
    attempts, base, factor, jitter = match.groups()
    assert int(attempts) == DEFAULT_POLICY.attempts
    assert float(base) == DEFAULT_POLICY.base_s
    assert float(factor) == DEFAULT_POLICY.factor
    assert int(jitter) / 100 == DEFAULT_POLICY.jitter


def test_each_report_carries_its_own_operation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    ids: list[tuple[int, int | None]] = []
    original = progress.ProgressChannel.retry_report

    def spy(self, retry, **kw):
        ids.append((retry.attempt, kw.get("operation")))
        return original(self, retry, **kw)

    monkeypatch.setattr(progress.ProgressChannel, "retry_report", spy)
    with progress.use_progress(progress.CallbackSink(lambda e: None)):
        a, _ = _flaky(2)
        run_retrying(a, sleep=lambda s: None)
        b, _ = _flaky(1)
        run_retrying(b, sleep=lambda s: None)
        c, _ = _flaky(99)
        with pytest.raises(TransientError):
            run_retrying(c, sleep=lambda s: None)
    # A: 2, 3. B: 2. C: scheduled 2, scheduled 3, then the exhausted report.
    assert [attempt for attempt, _ in ids] == [2, 3, 2, 2, 3, 3]
    ops = [op for _, op in ids]
    assert None not in ops
    assert ops[0] == ops[1] and ops[3] == ops[4] == ops[5]
    assert len({ops[0], ops[2], ops[3]}) == 3


def test_each_operation_has_its_own_attempt_floor() -> None:  # AT-E1-12
    seen: list[progress.ProgressEvent] = []
    with progress.use_progress(progress.CallbackSink(seen.append)) as channel:
        a, _ = _flaky(2)
        run_retrying(a, sleep=lambda s: None)
        b, _ = _flaky(1)
        run_retrying(b, sleep=lambda s: None)
        assert channel.rejected_reports == 0
        retries = [e.retry for e in seen if e.kind == "retry"]
        assert [r.attempt for r in retries] == [2, 3, 2]
        # Inside one operation a report going backwards is still refused.
        assert channel.retry_report(RetryInfo("operation", 3, 2, "running"), operation=900)
        assert not channel.retry_report(RetryInfo("operation", 2, 1, "running"), operation=900)
        assert channel.rejected_reports == 1
        # No id: the old per-scope floor, unchanged.
        assert channel.retry_report(RetryInfo("route", 2, 1, "running"))
        assert not channel.retry_report(RetryInfo("route", 1, 0, "running"))
        assert channel.rejected_reports == 2


def test_the_module_exposes_one_default_policy() -> None:
    assert RetryPolicy() == _retry.DEFAULT_POLICY
