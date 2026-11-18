"""The one retry executor for connector failures.

``run_retrying`` is the only engine code that sleeps on a connector failure or catches a
``TransientError`` to call again (sentry ``tests/sentry/test_one_retry_owner.py``). Its callers
are pinned by exact ``(path, function)`` (``tests/sentry/test_retry_callers.py``), so a new
caller adds a row to the table below and to the pinned set in the same change.

Which layer retries which operation (written once, so two layers never multiply attempts):

| Operation | Retried by |
|---|---|
| S3 ordinary request (head, list page, ``get_object`` start, unconditional ``put_object``, ``upload_part``) | botocore standard mode, 2 attempts |
| S3 body read failing mid-stream | this executor: resume from the offset with ``Range`` and ``IfMatch`` on the single-request client |
| GCS reads and ordinary writes | google-api-core ``Retry`` |
| S3 and GCS conditional writes and deletes | never (a resend after an applied write turns a win into a loss) |
| SFTP ``stat``, ``listdir``, read reopen, temporary-file upload from a seekable source | this executor, at the operation (F02-E3 onward) |
| SFTP rename, lock create, pointer swap, delete | never blindly; one state-checked resend (F02-E4) |
| ``FileSink.write`` from a consumed iterator | never (the chunks cannot be replayed) |

Pattern: bounded exponential backoff with jitter, as the AWS Architecture Blog "Exponential
Backoff And Jitter" describes it, with an overall deadline.
"""

from __future__ import annotations

import itertools
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from decoy_engine.progress import RetryInfo, get_active_channel
from decoy_engine.sdk import TransientError

T = TypeVar("T")

__all__ = ["DEFAULT_POLICY", "RetryPolicy", "run_retrying"]


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_s: float = 1.0
    factor: float = 2.0
    jitter: float = 0.25
    cap_s: float = 20.0
    deadline_s: float = 120.0


DEFAULT_POLICY = RetryPolicy()

# Each call is one operation with its own attempt floor in the progress channel.
_operation_ids = itertools.count(1)


def _delay(policy: RetryPolicy, completed: int, rand: Callable[[], float]) -> float:
    base = min(policy.cap_s, policy.base_s * policy.factor ** (completed - 1))
    return base * (1 + policy.jitter * (2 * rand() - 1))


def run_retrying(
    op: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    rand: Callable[[], float] = random.random,
) -> T:
    """Call ``op`` and retry a ``TransientError`` with bounded backoff; anything else leaves.

    Stops after ``policy.attempts`` calls, or when the next sleep would pass ``deadline_s``
    from the first call, and re-raises the last ``TransientError`` (already value-free). The
    sleep and policy resolve at call time so a test can shorten them.
    """
    chosen = policy or DEFAULT_POLICY
    pause = sleep or time.sleep
    started = clock()
    operation = next(_operation_ids)
    completed = 0
    while True:
        try:
            return op()
        except TransientError as err:
            last = err
        completed += 1
        delay = _delay(chosen, completed, rand) if completed < chosen.attempts else None
        if delay is None or clock() - started + delay > chosen.deadline_s:
            get_active_channel().retry_report(
                RetryInfo("operation", completed, completed - 1, "exhausted"), operation=operation
            )
            raise last
        get_active_channel().retry_report(
            RetryInfo("operation", completed + 1, completed, "scheduled", delay_s=delay),
            operation=operation,
        )
        pause(delay)
