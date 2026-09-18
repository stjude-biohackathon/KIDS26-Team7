"""Approval checks shared by the review UI and its regression tests."""
import math

from pipeline.evaluator import check_verbatim, content_findings
from schemas.instruction_packet import InstructionPacket


def approval_blockers(packet: InstructionPacket, edited_text: str, checked_packet: dict | None,
                      spanish_reviewed: bool) -> list[str]:
    """Require the exact successfully checked revision and human sign-off."""
    reasons = []
    if packet.is_simulation:
        reasons.append("Synthetic drift simulations cannot be approved for patient use.")
    if packet.status != 'PENDING':
        reasons.append('This packet has already been reviewed. Generate or check a new revision.')
    if edited_text != packet.simplified_en or checked_packet != packet.model_dump(mode='json'):
        reasons.append('Run Save & Check Edits successfully on the current text before approval.')
    from pipeline.orchestrator import compose_clinical_text
    source = compose_clinical_text(packet.original_clinical_text, packet.clinical_orders) if packet.original_clinical_text.strip() else ""
    missing_warnings, new_values = content_findings(source, edited_text, packet.clinical_orders)
    if missing_warnings:
        reasons.append('Required source warning text was removed or changed; retain it or revise the vetted source.')
    if new_values:
        reasons.append('Instructions contain clinical values not supplied by the source or orders.')
    metrics = packet.evaluation_metrics
    if metrics is None or not math.isfinite(metrics.fkgl_score):
        reasons.append('Readability evaluation is unavailable.')
    if metrics is None or metrics.verbatim_mismatches or metrics.verbatim_match_percent != 100:
        reasons.append('Required clinical values did not pass evaluation.')
    judge = metrics.safety_judge if metrics else None
    if (judge is None or judge.overall_verdict != 'PASS' or judge.factual_drift_detected
            or judge.omitted_red_flags or judge.contradictory_advice):
        reasons.append('Safety review must pass without unresolved findings.')
    for label, text in [('English', packet.simplified_en), ('Spanish', packet.translated_es),
                        ('back-translation', packet.back_translated_en)]:
        if (not text.strip() or check_verbatim(text, packet.clinical_orders)[1]
                or content_findings(source, text, packet.clinical_orders)[1]):
            reasons.append(f'{label} is missing or does not preserve required clinical values.')
    if not spanish_reviewed:
        reasons.append('An authorized medical translator or credentialed bilingual clinician must verify Spanish.')
    return reasons


REJECTION_CATEGORIES = (
    'Unsafe dosage alteration', 'Altered return/fever threshold',
    'Omitted critical red flag', 'Contradictory clinical advice', 'Spanish translation drift',
)


def reject_revision(packet: InstructionPacket, edited_text: str, category: str, reason: str) -> InstructionPacket:
    """Reject a copy of exactly the text under review, without mutating history."""
    from datetime import datetime, timezone
    from pipeline.orchestrator import PipelineOrchestrator
    from schemas.instruction_packet import get_physician_annotation
    if packet.status != 'PENDING':
        raise ValueError('Create a new pending revision before changing a finalized review.')
    if category not in REJECTION_CATEGORIES or not reason.strip():
        raise ValueError('A rejection requires a valid category and explanation.')
    if edited_text != packet.simplified_en:
        candidate = PipelineOrchestrator().recheck_edits(packet, edited_text)
    else:
        candidate = packet.model_copy(deep=True)
    candidate.status = 'REJECTED_DRIFT'
    candidate.rejection_category = category
    candidate.rejection_reason = reason.strip()
    candidate.physician_decision = get_physician_annotation(candidate)
    candidate.reviewed_at = datetime.now(timezone.utc).isoformat()
    return candidate
