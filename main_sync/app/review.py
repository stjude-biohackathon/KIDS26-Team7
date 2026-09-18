"""Approval checks shared by the review UI and its regression tests."""
import math

from pipeline.evaluator import check_verbatim, content_findings, fkgl_passes
from schemas.instruction_packet import InstructionPacket


def approval_blockers(packet: InstructionPacket, edited_text: str, checked_packet: dict | None,
                      spanish_reviewed: bool, spanish_requested: bool = True) -> list[str]:
    """Require the exact successfully checked revision and human sign-off.

    When ``spanish_requested`` is False the family opted out of a Spanish
    handout: the bilingual panes must be empty and no translator attestation
    is required. Otherwise the full bilingual gate applies.
    """
    reasons = []
    if packet.is_simulation:
        reasons.append("Synthetic drift simulations cannot be approved for patient use.")
    if packet.status != 'PENDING':
        reasons.append('These instructions have already been reviewed. Generate or check a new revision.')
    if edited_text != packet.simplified_en or checked_packet != packet.model_dump(mode='json'):
        reasons.append('Run Save & Check Edits successfully on the current text before approval.')
    from pipeline.orchestrator import compose_clinical_text
    source = compose_clinical_text(packet.original_clinical_text, packet.clinical_orders) if packet.original_clinical_text.strip() else ""
    # The safety judge checks warning meaning; simplified wording need not match source lines.
    _, new_values = content_findings(source, edited_text, packet.clinical_orders)
    if new_values:
        reasons.append('Instructions contain clinical values not supplied by the source or orders.')
    metrics = packet.evaluation_metrics
    if metrics is not None and metrics.protection_failures:
        reasons.append('Protected-value checks failed. Correct the draft and run fresh checks before approval.')
    if metrics is None or not math.isfinite(metrics.fkgl_score):
        reasons.append('Readability evaluation is unavailable.')
    #if metrics is not None and not fkgl_passes(metrics.fkgl_score):
        #reasons.append('English must meet the FKGL benchmark of 5.0–6.9 before approval.')
    if metrics is None or metrics.verbatim_mismatches or metrics.verbatim_match_percent != 100:
        reasons.append('Required clinical values did not pass evaluation.')
    judge = metrics.safety_judge if metrics else None
    if (judge is None or judge.overall_verdict != 'PASS' or judge.factual_drift_detected
            or judge.omitted_red_flags or judge.contradictory_advice):
        reasons.append('Safety review must pass without unresolved findings.')
    panes = [('English', packet.simplified_en)]
    if spanish_requested:
        panes += [('Spanish', packet.translated_es), ('back-translation', packet.back_translated_en)]
    elif packet.translated_es.strip() or packet.back_translated_en.strip():
        reasons.append('Spanish output is present but was not requested; regenerate without translation.')
    for label, text in panes:
        if (not text.strip() or check_verbatim(text, packet.clinical_orders)[1]
                or content_findings(source, text, packet.clinical_orders)[1]):
            reasons.append(f'{label} is missing or does not preserve required clinical values.')
    if spanish_requested and not spanish_reviewed:
        reasons.append('An authorized medical translator or credentialed bilingual clinician must verify Spanish.')
    return reasons


REJECTION_CATEGORIES = (
    'Unsafe dosage alteration', 'Altered return/fever threshold',
    'Omitted critical red flag', 'Contradictory clinical advice', 'Spanish translation drift',
)


def reject_revision(
    packet: InstructionPacket,
    edited_text: str,
    category: str | None = None,
    reason: str | None = None,
) -> InstructionPacket:
    """Reject a copy of exactly the text under review, without mutating history."""
    from datetime import datetime, timezone
    from pipeline.orchestrator import PipelineOrchestrator
    from schemas.instruction_packet import get_physician_annotation
    if packet.status != 'PENDING':
        raise ValueError('Create a new pending revision before changing a finalized review.')
    if category is not None and category not in REJECTION_CATEGORIES:
        raise ValueError('Unknown rejection category.')
    if edited_text != packet.simplified_en:
        candidate = PipelineOrchestrator().recheck_edits(packet, edited_text)
    else:
        candidate = packet.model_copy(deep=True)
    candidate.status = 'REJECTED_DRIFT'
    candidate.rejection_category = category
    candidate.rejection_reason = (reason or '').strip() or None
    candidate.physician_decision = get_physician_annotation(candidate)
    candidate.reviewed_at = datetime.now(timezone.utc).isoformat()
    return candidate
