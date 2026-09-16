"""Quality-gate interface proposal; no metrics are fabricated by the scaffold."""

# Keep type hints from being evaluated when Python loads this file. This lets
# the function mention shared schema classes before Track B supplies them.
from __future__ import annotations

from typing import TYPE_CHECKING

# TYPE_CHECKING is false while the program runs. These imports tell code-checking
# tools which types we expect without making the unfinished schema a runtime dependency.
if TYPE_CHECKING:
    from schemas.instruction_packet import ClinicalOrders, EvaluationMetrics


def evaluate_text(text: str, orders: ClinicalOrders) -> EvaluationMetrics:
    """Define the future readability and exact-value checks.

    ``text`` is the instruction wording to check. ``orders`` contains the source
    clinical values that wording must preserve. The ``-> EvaluationMetrics``
    hint describes the planned result: a shared record of the check outcomes.
    Type hints describe the interface; they do not run or enforce the checks.

    This scaffold does not calculate or return any metrics yet.
    """
    # Stop explicitly until the team agrees on the result format at Sync Point 0.
    # Returning made-up scores here could make unfinished checks look successful.
    raise NotImplementedError(
        "Evaluation is unavailable: agree EvaluationMetrics at Sync Point 0 "
        "before implementing the Phase 1 quality gates."
    )
