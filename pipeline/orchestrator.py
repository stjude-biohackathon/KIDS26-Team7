"""Track A's deterministic, offline pipeline for the Sync 1 mock loop."""

from __future__ import annotations

from datetime import datetime, timezone
from string import Template
from uuid import uuid4

from pipeline.evaluator import check_verbatim, evaluate_text
from pipeline.llms import AVAILABLE_MODELS
from schemas.instruction_packet import ClinicalOrders, EvaluationMetrics, InstructionPacket

# This file coordinates the work: fill the blanks, run checks, and package the
# results. evaluator.py does the scoring. Neither file calls an LLM at Sync 1.


def _bind_template(template: str, orders: ClinicalOrders) -> str:
    """Insert order values without generating or rewriting any surrounding words."""
    # A template is a fill-in-the-blank string, such as "Example: $medication_0_dose."
    # If the order's dose is "5 mg", the result is exactly "Example: 5 mg."
    if not template.strip():
        raise ValueError("A supplied template must not be empty.")
    # model_dump() turns the order object into a dictionary of names and values.
    # Collect its text fields first, such as the fever thresholds and phone numbers.
    values = {
        key: value for key, value in orders.model_dump().items()
        if isinstance(value, str)
    }
    # Medications are a list. Give each field a name the template can use:
    # medication_0_dose for the first drug, medication_1_dose for the second, etc.
    for index, medication in enumerate(orders.medications):
        for key, value in medication.model_dump().items():
            values[f"medication_{index}_{key}"] = value or ""
    try:
        # substitute(), unlike safe_substitute(), rejects unfilled placeholders.
        # Dollar signs inside inserted values are not interpreted a second time.
        return Template(template).substitute(values)
    except (KeyError, ValueError):
        # Stop if a blank cannot be filled. Do not return an unfinished handout
        # or copy the caller's template/values into the error message.
        raise ValueError("Template contains an unknown or malformed placeholder.") from None


def _evaluate_outputs(
    english: str, spanish: str, back: str, orders: ClinicalOrders
) -> EvaluationMetrics:
    """English owns the FKGL score; all supplied panes must preserve order values."""
    # Start with the English reading-level score and exact-value checklist.
    metrics = evaluate_text(english, orders)
    # Also check the numbers/units in each supplied bilingual example. This does
    # not establish that the Spanish is correct or that the meanings agree.
    for label, text in (("Spanish", spanish), ("Back-translation", back)):
        if not text:
            metrics.safety_judge.explanation += f" {label} mock unavailable."
        elif check_verbatim(text, orders)[1]:
            # check_verbatim returns (found_values, missing_values), so [1] selects
            # the missing list. A nonempty list adds a warning to the packet.
            metrics.safety_judge.overall_verdict = "FLAGGED_FOR_REVIEW"
            metrics.safety_judge.explanation += f" {label} verbatim mismatch."
    return metrics


class PipelineOrchestrator:
    """Bind supplied wording and run local checks; no model requests in Phase 1."""

    # Python calls __init__ when someone creates PipelineOrchestrator().
    # The * means callers must name these options, e.g. llm1_model="gpt4o".
    # If they omit the options, the defaults below are used.
    def __init__(
        self, *, llm1_model: str = "gpt52", llm2_model: str = "gpt4o"
    ) -> None:
        """Store role selections without reading credentials or creating clients."""
        # Reject choices outside the menu in llms.py before storing them.
        # Error messages name the invalid role without echoing the supplied value.
        if llm1_model not in AVAILABLE_MODELS:
            raise ValueError("Unsupported llm1_model; select an AVAILABLE_MODELS alias.")
        if llm2_model not in AVAILABLE_MODELS:
            raise ValueError("Unsupported llm2_model; select an AVAILABLE_MODELS alias.")

        # self refers to this particular orchestrator. These attributes remember
        # its choices; storing a model name does not connect to or call that model.
        self.llm1_model = llm1_model
        self.llm2_model = llm2_model

    def generate(
        self,
        composite_template_text: str,
        orders: ClinicalOrders,
        *,
        module_version: str,
        condition: str,
        simplified_template_text: str | None = None,
        spanish_template_text: str | None = None,
        back_translation_template_text: str | None = None,
    ) -> InstructionPacket:
        """Prepare a pending packet using caller-supplied, versioned wording.

        The three optional templates are mock outputs provided by the caller.
        They are never produced by an AI here. If no simpler template is given,
        the English pane uses the source wording with order values inserted.
        """
        # 1. Require a source, a condition name, and version labels so the packet
        # records which inputs were selected. This does not verify their approval.
        if not all(value.strip() for value in (
            composite_template_text, module_version, condition, orders.order_version
        )):
            raise ValueError("Source text, condition, and module/order versions are required.")
        # 2. Save an independent copy of the orders, including the medications.
        # Changing the caller's order object later will not change this copy.
        saved_orders = orders.model_copy(deep=True)
        # 3. Fill in the supplied English template. We do not shorten sentences
        # or replace medical terms. Simpler wording must already be supplied.
        english = _bind_template(
            composite_template_text if simplified_template_text is None else simplified_template_text,
            saved_orders,
        )
        # 4. Fill in the two supplied bilingual templates separately. Neither is
        # generated from the other. Missing templates leave empty output fields;
        # _evaluate_outputs also adds a message explaining what is missing.
        spanish = (
            _bind_template(spanish_template_text, saved_orders)
            if spanish_template_text is not None else ""
        )
        back = (
            _bind_template(back_translation_template_text, saved_orders)
            if back_translation_template_text is not None else ""
        )
        # 5. Put the source, outputs, versions, and check results into one packet
        # for the UI. uuid4() gives each new packet its own identifier.
        return InstructionPacket(
            packet_id=str(uuid4()),
            condition=condition,
            module_version=module_version,
            order_version=saved_orders.order_version,
            original_clinical_text=composite_template_text,  # Preserve the exact input string.
            clinical_orders=saved_orders,
            simplified_en=english,
            translated_es=spanish,
            back_translated_en=back,
            evaluation_metrics=_evaluate_outputs(english, spanish, back, saved_orders),
            status="PENDING",  # Generating/checking a packet never approves it.
        )

    def recheck_edits(
        self, packet: InstructionPacket, edited_en: str
    ) -> InstructionPacket:
        """Return a new pending revision; the caller keeps the original packet.

        English edits invalidate the previous bilingual output and human review.
        Phase 1 cannot translate new wording, so those panes become unavailable.
        """
        # Work on a separate copy so the caller can keep the original for comparison.
        # The caller must retain both objects; this function does not save a history.
        revision = packet.model_copy(deep=True)
        revision.packet_id = str(uuid4())
        revision.created_at = datetime.now(timezone.utc).isoformat()
        revision.simplified_en = edited_en
        # The old Spanish may no longer describe the edited English. Clear it and
        # its back-translation instead of displaying them as current translations.
        revision.translated_es = ""
        revision.back_translated_en = ""
        # Check the new English against the ORIGINAL orders. For example, changing
        # the example dose to 15 mg does not change the expected order value of 5 mg.
        revision.evaluation_metrics = _evaluate_outputs(
            edited_en, "", "", revision.clinical_orders
        )
        revision.evaluation_metrics.safety_judge.explanation += (
            " Previous translations invalidated by edit recheck."
        )
        # The earlier review applies to the earlier wording. Reset it in this
        # revision, while remembering that a clinician edited the text.
        revision.status = "PENDING"
        revision.edited_by_physician = True
        revision.physician_decision = None
        revision.rejection_reason = None
        revision.rejection_category = None
        revision.clinician_notes = None
        revision.reviewed_at = None
        return revision
