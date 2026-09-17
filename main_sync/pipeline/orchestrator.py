"""Track A's deterministic, offline pipeline for the Sync 1 mock loop."""

from __future__ import annotations

from datetime import datetime, timezone
from string import Template
from uuid import uuid4

from pipeline.evaluator import check_verbatim, evaluate_text
from pipeline.llms import AVAILABLE_MODELS
from schemas.instruction_packet import ClinicalOrders, EvaluationMetrics, InstructionPacket


def _bind_template(template: str, orders: ClinicalOrders) -> str:
    """Insert order values without generating or rewriting any surrounding words."""
    if not template.strip():
        raise ValueError("A supplied template must not be empty.")
    values = {
        key: value for key, value in orders.model_dump().items()
        if isinstance(value, str)
    }
    for index, medication in enumerate(orders.medications):
        for key, value in medication.model_dump().items():
            values[f"medication_{index}_{key}"] = value or ""
    try:
        # substitute(), unlike safe_substitute(), rejects unfilled placeholders.
        # Dollar signs inside inserted values are not interpreted a second time.
        return Template(template).substitute(values)
    except (KeyError, ValueError):
        raise ValueError("Template contains an unknown or malformed placeholder.") from None


def _evaluate_outputs(
    english: str, spanish: str, back: str, orders: ClinicalOrders
) -> EvaluationMetrics:
    """English owns the FKGL score; all supplied panes must preserve order values."""
    metrics = evaluate_text(english, orders)
    for label, text in (("Spanish", spanish), ("Back-translation", back)):
        if not text:
            metrics.safety_judge.explanation += f" {label} mock unavailable."
        elif check_verbatim(text, orders)[1]:
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
        if not all(value.strip() for value in (
            composite_template_text, module_version, condition, orders.order_version
        )):
            raise ValueError("Source text, condition, and module/order versions are required.")
        # Copy nested medication records too: later loader/UI edits must not
        # silently change the inputs recorded in a previously created packet.
        saved_orders = orders.model_copy(deep=True)
        english = _bind_template(
            composite_template_text if simplified_template_text is None else simplified_template_text,
            saved_orders,
        )
        # Bilingual output is supplied demo content, not a real translation.
        # Keep absent outputs empty and explicitly label their absence in checks.
        spanish = (
            _bind_template(spanish_template_text, saved_orders)
            if spanish_template_text is not None else ""
        )
        back = (
            _bind_template(back_translation_template_text, saved_orders)
            if back_translation_template_text is not None else ""
        )
        return InstructionPacket(
            packet_id=str(uuid4()),
            condition=condition,
            module_version=module_version,
            order_version=saved_orders.order_version,
            original_clinical_text=composite_template_text,
            clinical_orders=saved_orders,
            simplified_en=english,
            translated_es=spanish,
            back_translated_en=back,
            evaluation_metrics=_evaluate_outputs(english, spanish, back, saved_orders),
            status="PENDING",
        )

    def recheck_edits(
        self, packet: InstructionPacket, edited_en: str
    ) -> InstructionPacket:
        """Return a new pending revision; the caller keeps the original packet.

        English edits invalidate the previous bilingual output and human review.
        Phase 1 cannot translate new wording, so those panes become unavailable.
        """
        revision = packet.model_copy(deep=True)
        revision.packet_id = str(uuid4())
        revision.created_at = datetime.now(timezone.utc).isoformat()
        revision.simplified_en = edited_en
        revision.translated_es = ""
        revision.back_translated_en = ""
        revision.evaluation_metrics = _evaluate_outputs(
            edited_en, "", "", revision.clinical_orders
        )
        revision.evaluation_metrics.safety_judge.explanation += (
            " Previous translations invalidated by edit recheck."
        )
        revision.status = "PENDING"
        revision.edited_by_physician = True
        revision.physician_decision = None
        revision.rejection_reason = None
        revision.rejection_category = None
        revision.clinician_notes = None
        revision.reviewed_at = None
        return revision
