from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class MedicationOrder(BaseModel):
    """Structured details for a prescribed medication."""

    name: str
    dose: str
    route: str = "oral"
    frequency: str = ""
    special_instructions: Optional[str] = ""


class ClinicalOrders(BaseModel):
    """Structured clinical inputs and patient orders."""

    patient_id: str
    age: Optional[str] = None
    diagnosis: str
    medications: List[MedicationOrder] = Field(default_factory=list)
    urgent_fever_threshold: str = "100.4°F"
    emergency_fever_threshold: str = "101.0°F"
    daytime_phone: str = ""
    after_hours_phone: str = ""
    emergency_phone: str = "911"
    order_id: str = ""
    order_version: str = "v1.0.0"


class SafetyJudgeResult(BaseModel):
    """LLM2 Safety Judge audit evaluation."""

    overall_verdict: str = "PASS"  # PASS | NEEDS_REVIEW | FLAGGED_FOR_REVIEW
    factual_drift_detected: bool = False
    omitted_red_flags: List[str] = Field(default_factory=list)
    contradictory_advice: List[str] = Field(default_factory=list)
    clinical_risk_score: float = 0.0
    explanation: str = ""


class EvaluationMetrics(BaseModel):
    """Automated quality gate metrics and judge findings."""

    fkgl_score: float = 0.0
    verbatim_matches: List[str] = Field(default_factory=list)
    verbatim_mismatches: List[str] = Field(default_factory=list)
    verbatim_match_percent: float = 100.0
    protection_failures: List[str] = Field(default_factory=list)
    safety_judge: Optional[SafetyJudgeResult] = None


class InstructionPacket(BaseModel):
    """Canonical data container binding inputs, simplified outputs, telemetry, and review governance."""

    packet_id: str
    parent_packet_id: Optional[str] = None
    is_simulation: bool = False
    condition: str
    module_version: str = "v1.0.0"
    order_version: str = "v1.0.0"
    original_clinical_text: str = ""
    clinical_orders: ClinicalOrders
    simplified_en: str = ""
    translated_es: str = ""
    back_translated_en: str = ""
    evaluation_metrics: Optional[EvaluationMetrics] = None
    status: str = "PENDING"  # PENDING | APPROVED | EDITED_AND_APPROVED | REJECTED_DRIFT
    physician_decision: Optional[str] = None
    rejection_reason: Optional[str] = None
    rejection_category: Optional[str] = None
    edited_by_physician: bool = False
    clinician_notes: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reviewed_at: Optional[str] = None


def get_physician_annotation(packet: InstructionPacket) -> str:
    """Returns standardized physician verification banner text based on packet status."""
    if packet.status == "APPROVED":
        return "Approved by physician"
    if packet.status == "EDITED_AND_APPROVED":
        return "Edited and approved by physician"
    if packet.status == "REJECTED_DRIFT":
        return "Rejected by physician"
    return "Pending physician review"
