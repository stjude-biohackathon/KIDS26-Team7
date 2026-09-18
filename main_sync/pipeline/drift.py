"""Synthetic Scenario C injections; never used to alter a patient handout silently."""
import re
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from pipeline.evaluator import evaluate_text, extract_safety_values, red_flag_lines

DRIFT_MODES = ('Contradictory Advice', 'Altered Fever Threshold', 'Altered Medication Dose', 'Omitted Red Flag')
CONTRADICTION = 'Withhold anti-emetic medications until patient vomits 5 times.'


def evaluate_injected_text(source: str, candidate: str, orders):
    """Evaluate changed content, without accepting a drift-mode label as evidence."""
    metrics = evaluate_text(candidate, orders)
    judge = metrics.safety_judge
    omitted = [line for line in red_flag_lines(source) if line not in candidate]
    contradictions = [CONTRADICTION] if CONTRADICTION in candidate and CONTRADICTION not in source else []
    if omitted or contradictions or metrics.verbatim_mismatches:
        judge.overall_verdict = 'FLAGGED_FOR_REVIEW'
        judge.factual_drift_detected = True
        judge.omitted_red_flags = omitted
        judge.contradictory_advice = contradictions
        judge.explanation = 'Synthetic negative-test evaluation found changed values, omitted warnings, or contradictory advice.'
    return metrics


def inject_drift(packet, mode: str):
    if mode not in DRIFT_MODES:
        raise ValueError('Unknown synthetic drift scenario.')
    if not packet.clinical_orders.patient_id.startswith('SYN-'):
        raise ValueError('Drift simulation requires a synthetic fixture.')
    original = packet.simplified_en
    text = original
    if mode == 'Contradictory Advice':
        text += '\n' + CONTRADICTION
    elif mode == 'Omitted Red Flag':
        warnings = red_flag_lines(original)
        if warnings:
            text = text.replace(warnings[0], '', 1)
    else:
        fields = ([m.dose for m in packet.clinical_orders.medications]
                  if mode == 'Altered Medication Dose' else
                  [packet.clinical_orders.urgent_fever_threshold, packet.clinical_orders.emergency_fever_threshold])
        for field in fields:
            kind = 'dose' if mode == 'Altered Medication Dose' else 'temperature'
            values = extract_safety_values(field, kind)
            if not values:
                continue
            value = values[0]
            pattern = r'(?<![\w.,/+\-])' + re.escape(value) + r'(?!\w|\s*/|\.\d)'
            match = re.search(r'\d+(?:\.\d+)?', value)
            number = Decimal(match.group())
            replacement = value[:match.start()] + format(number * 2 if kind == 'dose' else number + Decimal('4.1'), 'f') + value[match.end():]
            text, count = re.subn(pattern, lambda _: replacement, text)
            if count and kind == 'dose':
                break
    if text == original or not text.strip():
        raise ValueError('This scenario has no matching content to alter; choose another fixture.')
    revision = packet.model_copy(deep=True)
    revision.parent_packet_id = packet.packet_id
    revision.packet_id = str(uuid4())
    revision.created_at = datetime.now(timezone.utc).isoformat()
    revision.simplified_en = text
    revision.is_simulation = True
    revision.status = 'PENDING'
    revision.clinician_notes = None
    revision.edited_by_physician = False
    revision.physician_decision = revision.reviewed_at = None
    revision.rejection_reason = revision.rejection_category = None
    revision.evaluation_metrics = evaluate_injected_text(original, text, revision.clinical_orders)
    return revision
