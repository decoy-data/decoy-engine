"""Decoy acceptance test-flight suite.

Deliberately-run, multi-job acceptance suite that proves Phase-5 strategies
compose, post-run distribution is intact, and relationships hold. Not part of
the default regression loop; invoke via:

  pytest testflight -m testflight
  python scripts/test_flight.py

See testflight/_spec.py for the data model (JobSpec / InvariantSpec), and
testflight/_runner.py for the seven-step runner contract.
"""

from ._assert import assert_job_passed as assert_job_passed
from ._report import format_job_section as format_job_section
from ._report import render_report as render_report
from ._runner import INVARIANT_FAILED_CATEGORY as INVARIANT_FAILED_CATEGORY
from ._runner import InvariantResult as InvariantResult
from ._runner import JobResult as JobResult
from ._runner import failure_text as failure_text
