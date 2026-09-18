"""Track A's pipeline: the Phase 1 deterministic offline path plus Phase 2's
live multi-LLM path (`generate_live`/`recheck_edits_live`)."""

from __future__ import annotations

from datetime import datetime, timezone
from string import Template
from uuid import uuid4

from pipeline import live_llm
from pipeline.evaluator import check_verbatim, evaluate_text, content_findings, fkgl_passes
from pipeline.protection import ProtectionError, numeric_findings
from pipeline.llms import AVAILABLE_MODELS, get_client
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


def compose_clinical_text(template: str, orders: ClinicalOrders) -> str:
    """Bind vetted wording and append supplied order fields when needed."""
    text = _bind_template(template, orders)
    if check_verbatim(text, orders)[1]:
        text += "\n\nSTRUCTURED ORDERS\n" + live_llm.format_orders(orders)
    return text


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


def _enforce_deterministic_safety_gate(
    metrics: EvaluationMetrics, spanish: str, back: str, orders: ClinicalOrders,
    source: str = "", english: str = "", require_bilingual: bool = True,
) -> EvaluationMetrics:
    """Let regex parity checks veto the live judge, never the other way round.

    The Safety Judge is a model and may return PASS on output that dropped a
    dose, threshold, or phone number. Numeric/unit parity is a hard sign-off
    block, so a deterministic mismatch in any pane forces FLAGGED_FOR_REVIEW.
    """
    blocking = []
    if metrics.protection_failures:
        blocking.append("Protected-value validation failed")
    # Rephrasing warnings is permitted; the judge audits semantic preservation.
    _, unexpected = content_findings(source, english, orders)
    if not fkgl_passes(metrics.fkgl_score):
        blocking.append("English FKGL must be within 5.0–6.9")
    if unexpected:
        blocking.append("English contains unsupplied safety values")
    if metrics.verbatim_mismatches:
        blocking.append("English verbatim mismatch")
    for label, text in (("Spanish", spanish), ("Back-translation", back)):
        if not text:
            # English-only reviews legitimately omit the bilingual panes.
            if require_bilingual:
                blocking.append(f"{label} pane unavailable")
        elif check_verbatim(text, orders)[1] or content_findings(source, text, orders)[1]:
            blocking.append(f"{label} verbatim mismatch")
    if blocking:
        metrics.safety_judge.overall_verdict = "FLAGGED_FOR_REVIEW"
        metrics.safety_judge.explanation += (
            " Deterministic safety gate overrides the judge verdict: "
            + "; ".join(blocking)
            + "."
        )
    return metrics


def _reviewable_call(stage, operation):
    """Keep a rejected model draft only when protection supplied a safe preview."""
    try:
        return operation(), []
    except ProtectionError as exc:
        if exc.draft_text is None:
            raise
        return exc.draft_text, [f"{stage}: {finding}" for finding in exc.findings]


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
        revision.parent_packet_id = packet.packet_id
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

    def generate_live(
        self,
        composite_template_text: str,
        orders: ClinicalOrders,
        *,
        module_version: str,
        condition: str,
        translate: bool = True,
    ) -> InstructionPacket:
        """Phase 2: run the real LLM1/LLM2 pipeline instead of binding templates.

        LLM1 simplifies supplied clinical wording with protected values masked.
        Restored English must score FKGL 5.0–6.9 before Spanish translation. LLM2 (`self.llm2_model`) back-translates the Spanish pane
        and runs the Safety Judge audit. FKGL/verbatim telemetry is still
        computed locally by `pipeline.evaluator`, per specs/01 Section 2.2 —
        only the Safety Judge verdict comes from the live LLM2 call.

        When ``translate`` is False, the Spanish translation and back-translation
        steps are skipped entirely and both panes remain empty; the family does
        not need a Spanish handout, so no unauthorized translation is produced.

        Readability, protection, and judge failures return pending review-only
        drafts with their measured findings. Transport and configuration
        failures without a usable model response still raise.
        """
        if not all(value.strip() for value in (
            composite_template_text, module_version, condition, orders.order_version
        )):
            raise ValueError("Source text, condition, and module/order versions are required.")
        saved_orders = orders.model_copy(deep=True)

        llm1_client, llm1_deployment = get_client(self.llm1_model)
        source = compose_clinical_text(composite_template_text, saved_orders)
        previous_fkgl = None
        previous_protection_failure = False
        # A bounded retry loop avoids hanging or publishing an unmeasured draft.
        for attempt in range(1, 4):
            english, failures = _reviewable_call("English simplification", lambda: live_llm.simplify_to_plain_language(
                llm1_client, llm1_deployment, source, saved_orders,
                previous_fkgl=previous_fkgl,
                previous_protection_failure=previous_protection_failure,
            ))
            metrics = evaluate_text(english, saved_orders)
            if not failures:
                failures = [f"English simplification: {finding}" for finding in numeric_findings(source, english)]
            if failures:
                if attempt < 3:
                    # Give LLM1 another chance to preserve every marker. The
                    # final failed draft remains visible if all attempts fail.
                    previous_fkgl = metrics.fkgl_score
                    previous_protection_failure = True
                    continue
                break
            if fkgl_passes(metrics.fkgl_score):
                break
            previous_fkgl = metrics.fkgl_score
            previous_protection_failure = False
        # If all three attempts miss the readability target, keep the third
        # draft. The deterministic gate below marks it FLAGGED_FOR_REVIEW, and
        # approval remains blocked by the measured FKGL score.
        spanish, back, metrics = self._complete_live_review(
            composite_template_text, source, english, saved_orders, metrics, failures, translate,
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
            evaluation_metrics=metrics,
            status="PENDING",
        )

    def recheck_edits_live(
        self, packet: InstructionPacket, edited_en: str, *, translate: bool = True
    ) -> InstructionPacket:
        """Phase 2: re-translate/re-judge a physician's edit via live LLMs.

        Returns a new pending revision; the caller keeps the original packet
        (same contract as `recheck_edits`). Unlike the offline path, the
        bilingual panes are regenerated rather than left empty — unless
        ``translate`` is False, in which case the English-only review keeps
        both bilingual panes empty.
        """
        if not edited_en.strip():
            raise ValueError("Edited instruction text must not be empty.")
        revision = packet.model_copy(deep=True)
        revision.parent_packet_id = packet.packet_id
        revision.packet_id = str(uuid4())
        revision.created_at = datetime.now(timezone.utc).isoformat()
        revision.simplified_en = edited_en

        source = compose_clinical_text(revision.original_clinical_text, revision.clinical_orders)
        failures = [f"English recheck: {finding}" for finding in numeric_findings(source, edited_en)]
        metrics = evaluate_text(edited_en, revision.clinical_orders)
        revision.translated_es, revision.back_translated_en, metrics = self._complete_live_review(
            revision.original_clinical_text, source, edited_en, revision.clinical_orders,
            metrics, failures, translate,
        )
        revision.evaluation_metrics = metrics

        revision.status = "PENDING"
        revision.edited_by_physician = True
        revision.physician_decision = None
        revision.rejection_reason = None
        revision.rejection_category = None
        revision.clinician_notes = None
        revision.reviewed_at = None
        return revision

    def _complete_live_review(self, original, source, english, orders, metrics, failures, translate):
        """Run every requested stage and preserve all failures for clinician review."""
        failures = list(failures)
        for value in metrics.verbatim_mismatches:
            if not any(value in finding for finding in failures):
                failures.append(f"English: missing or changed safety token: {value}.")
        for value in content_findings(source, english, orders)[1]:
            if not any(value in finding for finding in failures):
                failures.append(f"English: unexpected safety token: {value}.")
        spanish = back = ""
        llm2_client, llm2_deployment = get_client(self.llm2_model)
        if translate:
            llm1_client, llm1_deployment = get_client(self.llm1_model)
            spanish, stage_failures = _reviewable_call(
                "Spanish translation",
                lambda: live_llm.translate_to_spanish(
                    llm1_client, llm1_deployment, english,
                ),
            )
            failures.extend(stage_failures)
            back, stage_failures = _reviewable_call(
                "English back-translation",
                lambda: live_llm.back_translate_to_english(
                    llm2_client, llm2_deployment, spanish,
                ),
            )
            failures.extend(stage_failures)
        metrics.protection_failures = failures
        metrics.safety_judge = live_llm.judge_safety(
            llm2_client, llm2_deployment, original, english, orders,
        )
        metrics = _enforce_deterministic_safety_gate(
            metrics, spanish, back, orders, source=source, english=english,
            require_bilingual=translate,
        )
        return spanish, back, metrics
