"""
CLEAR — Clinician Review Dashboard & Streamlit UI/UX (Track C)
Authoritative Implementation adhering to specs/03_TRACK_C_CLINICIAN_UI_UX.md.
"""

from __future__ import annotations

import copy
import hashlib
from html import escape
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Ensure project root is in sys.path for top-level imports across execution modes
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import streamlit as st

from app.review import approval_blockers, reject_revision, REJECTION_CATEGORIES
from pipeline.drift import DRIFT_MODES, inject_drift

# Safe imports: Try canonical modules first, fall back to mock components
try:
    from schemas.instruction_packet import (
        ClinicalOrders,
        EvaluationMetrics,
        InstructionPacket,
        MedicationOrder,
        SafetyJudgeResult,
        get_physician_annotation,
    )
except ImportError:
    try:
        from app.mock_components import (
            ClinicalOrders,
            EvaluationMetrics,
            InstructionPacket,
            MedicationOrder,
            SafetyJudgeResult,
            get_physician_annotation,
        )
    except ImportError:
        from mock_components import (
            ClinicalOrders,
            EvaluationMetrics,
            InstructionPacket,
            MedicationOrder,
            SafetyJudgeResult,
            get_physician_annotation,
        )

try:
    from app.mock_components import (
        MOCK_MODULES,
        MOCK_ORDERS,
        evaluate_text_verbatim_and_fkgl,
        generate_handout_pdf,
        load_gold_records,
        run_mock_pipeline,
        save_to_gold_library,
    )
except ImportError:
    from mock_components import (
        MOCK_MODULES,
        MOCK_ORDERS,
        evaluate_text_verbatim_and_fkgl,
        generate_handout_pdf,
        load_gold_records,
        run_mock_pipeline,
        save_to_gold_library,
    )

# Optional live module hooks for Phase 2/3 sync points
try:
    from storage.github_loader import (
        fetch_remote_templates_and_orders,
        get_last_load_status,
        is_github_app_configured,
    )
    HAS_LIVE_LOADER = True
except ImportError:
    HAS_LIVE_LOADER = False

try:
    from pipeline.orchestrator import PipelineOrchestrator, compose_clinical_text
    from pipeline.llms import describe_model_error
    HAS_LIVE_PIPELINE = True
except ImportError:
    HAS_LIVE_PIPELINE = False

    def describe_model_error(alias, exc):  # type: ignore[misc]
        return f"{alias}: live pipeline module unavailable ({type(exc).__name__})."

try:
    from storage.gold_library import save_gold_record as live_save_gold, load_gold_records as live_load_gold
    HAS_LIVE_STORAGE = True
except ImportError:
    HAS_LIVE_STORAGE = False

try:
    from exporters.pdf_generator import create_bilingual_pdf as live_pdf_gen
    HAS_LIVE_PDF = True
except ImportError:
    HAS_LIVE_PDF = False


# ---------------------------------------------------------------------------
# In-Memory Data Source Resolution (specs/03 Section 2.1)
# ---------------------------------------------------------------------------
def _is_live_data_configured() -> bool:
    """True only when GitHub App credentials are actually present."""
    if not HAS_LIVE_LOADER:
        return False
    try:
        return is_github_app_configured()
    except Exception:
        return False


@st.cache_data(show_spinner=False)
def _load_templates_and_orders():
    """Fetch clinical templates/orders once per cache lifetime; zero disk writes.

    Returns `(modules, orders, status)` where `status` reports what actually
    happened (specs/05 FIX-B3), so the UI can show real provenance instead of
    inferring "live" from credential presence alone.
    """
    if HAS_LIVE_LOADER:
        modules, orders = fetch_remote_templates_and_orders()
        return modules, orders, get_last_load_status()
    return MOCK_MODULES, MOCK_ORDERS, {
        "source": "mock",
        "error": "Live loader module is unavailable in this environment.",
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Streamlit Page Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="CLEAR — Clinician Review Dashboard",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for clinical styling and comparative review columns
st.markdown(
    """
    <style>
    /* Reduce padding between top of page and title */
    .block-container {
        padding-top: 2.5rem;
    }
    .front-page-heading {
        text-align: center;
        margin: 0 auto 1rem auto;
    }
    .front-page-heading h2 {
        margin-top: 0;
        padding-top: 0.25rem;
    }
    .reportview-container {
        background-color: #F8FAFC;
    }
    .metric-badge-pass {
        display: inline-block;
        padding: 4px 8px;
        background-color: #DEF7EC;
        color: #03543F;
        border-radius: 4px;
        font-weight: 600;
        font-size: 13px;
        margin-right: 6px;
    }
    .metric-badge-warn {
        display: inline-block;
        padding: 4px 8px;
        background-color: #FEF08A;
        color: #713F12;
        border-radius: 4px;
        font-weight: 600;
        font-size: 13px;
        margin-right: 6px;
    }
    .metric-badge-danger {
        display: inline-block;
        padding: 4px 8px;
        background-color: #FDE8E8;
        color: #9B1C1C;
        border-radius: 4px;
        font-weight: 600;
        font-size: 13px;
        margin-right: 6px;
    }
    .col-header {
        font-size: 15px;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 8px;
        padding-bottom: 4px;
        border-bottom: 2px solid #E2E8F0;
    }
    .clinical-box {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        padding: 12px;
        font-size: 13px;
        line-height: 1.5;
        height: 65vh;
        overflow-y: auto;
        white-space: pre-wrap;
    }
    .clinical-box-full {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        padding: 12px;
        font-size: 13px;
        line-height: 1.5;
        height: 70vh;
        overflow-y: auto;
        white-space: pre-wrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------------------------
if "current_packet" not in st.session_state:
    st.session_state["current_packet"] = None
if "clean_backup_packet" not in st.session_state:
    st.session_state["clean_backup_packet"] = None
if "edits_checked_banner" not in st.session_state:
    st.session_state["edits_checked_banner"] = False
if "pdf_bytes" not in st.session_state:
    st.session_state["pdf_bytes"] = None
if "txt_clinician_en" not in st.session_state:
    st.session_state["txt_clinician_en"] = ""
if "live_pipeline_notice" not in st.session_state:
    st.session_state["live_pipeline_notice"] = False
if "live_data_notice" not in st.session_state:
    st.session_state["live_data_notice"] = False
if "live_pipeline_reason" not in st.session_state:
    st.session_state["live_pipeline_reason"] = ""


# ---------------------------------------------------------------------------
# Rejection Modal Dialog (Governance Requirement 2.4)
# ---------------------------------------------------------------------------
@st.dialog("Reject & Log Clinical Drift", dismissible=False)
def reject_packet_dialog(packet: InstructionPacket):
    st.warning("You are rejecting this instruction set due to detected clinical drift or safety violation.")
    
    drift_category = st.selectbox(
        "Drift Taxonomy Categorization *",
        options=list(REJECTION_CATEGORIES),
        index=0,
    )
    explanation = st.text_area(
        "Clinical Rationale / Notes for Audit Log *",
        placeholder="Detail specific omissions, altered numbers, or dangerous phrasing observed...",
        height=120,
    )
    
    col_sub, col_cancel = st.columns([1, 1])
    with col_sub:
        if st.button("Confirm Rejection", type="primary"):
            if not explanation.strip():
                st.error("Please provide an explanation for the audit log.")
                return
            
            try:
                candidate = reject_revision(
                    packet, st.session_state.get("txt_clinician_en", packet.simplified_en),
                    drift_category, explanation,
                )
                pdf_data = live_pdf_gen(candidate)
                live_save_gold(candidate)
            except Exception:
                st.error("Rejection could not be saved. Check the text and retry; the original review is unchanged.")
            else:
                st.session_state["current_packet"] = candidate
                st.session_state["pdf_bytes"] = pdf_data
                st.session_state["checked_packet"] = None
                st.session_state["reject_dialog_packet_id"] = None
                st.session_state["edits_checked_banner"] = False
                st.rerun()

    with col_cancel:
        if st.button("Cancel"):
            st.session_state["reject_dialog_packet_id"] = None
            st.rerun()


# ---------------------------------------------------------------------------
# Sidebar: Model, Protocol, & Orders Configuration (specs/03 Section 2.1)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("CLEAR Controls")
    st.caption("Bilingual Pediatric Discharge Instruction Review")

    st.caption("LLM1 simplifies English to FKGL 5.0–6.9. LLM2 checks safety. Spanish translation and English back-translation run only when requested for the family.")
    st.subheader("1. AI Model Selection")
    model_options = ["gpt52", "gpt4o", "gpt56luna", "kimik3", "copus5", "local1", "local2"]
    
    selected_llm1 = st.selectbox(
        "LLM 1 (Simplification & Spanish):",
        options=model_options,
        index=model_options.index("gpt4o"),
        help="Simplifies English to FKGL 5.0–6.9, optionally translates it to Spanish with protected clinical values.",
    )
    selected_llm2 = st.selectbox(
        "LLM 2 (Safety Judge & Back-EN):",
        options=model_options,
        index=model_options.index("gpt4o"),
        help="Independent model evaluating factual drift and back-translating Spanish to English.",
    )

    st.divider()
    if st.button("Refresh Protocols", help="Reload source instructions and orders; clear the current review"):
        _load_templates_and_orders.clear()
        st.session_state["review_inputs"] = None
        st.rerun()
    live_templates, live_orders, load_status = _load_templates_and_orders()
    if load_status.get("error"):
        st.error("Clinical data loading failed. " + load_status["error"])
        st.stop()
    for warning in load_status.get("warnings", []):
        st.caption("Source data notice: " + warning)

    st.subheader("2. Protocol & Module Version")
    
    available_conditions = [
        name for name, versions in live_templates.items()
        if name in live_orders and any(text.strip() for text in versions.values())
    ]
    if not available_conditions:
        st.session_state["live_data_notice"] = True
        st.warning("Live clinical data unavailable: no matching protocols and orders with usable content.")
        st.stop()
    condition = st.selectbox(
        "Clinical Module:",
        options=available_conditions,
        format_func=lambda x: {
            "sickle_cell_pain": "Sickle Cell Acute Pain",
            "fever_neutropenia": "Fever & Neutropenia (Oncology)",
            "chemo_nausea_hydration": "Post-Chemo Nausea & Hydration",
        }.get(x, x),
    )

    base_order = live_orders[condition]
    module_versions = [v for v, text in live_templates[condition].items() if text.strip()]
    col_mv, col_ov = st.columns(2)
    with col_mv:
        module_version = st.selectbox("Module Ver:", options=module_versions, index=0, key=f"module_version_{condition}")
    with col_ov:
        order_version = st.selectbox("Order Set Ver:", options=[base_order.order_version], index=0,
                                     format_func=lambda v: f"{v} ({base_order.order_id})",
                                     key=f"order_version_{condition}_{base_order.order_id}")

    st.info(f"Active Protocol: `{condition}` | `{module_version}` | `{order_version}`")

    st.divider()
    st.subheader("3. Clinical Orders Customization")

    # Load base order for the selected condition (live-fetched or mock fallback)
    # The loader currently exposes one actual order set per condition.
    # Do not offer invented historical versions or substitute another condition.
    order_widget_key = hashlib.sha256(base_order.model_dump_json().encode()).hexdigest()
    
    patient_id = st.text_input("Synthetic Patient ID:", value=base_order.patient_id, key=f"patient_id_{condition}_{order_widget_key}")
    age = st.text_input("Patient Age:", value=base_order.age or "8 years old", key=f"age_{condition}_{order_widget_key}")
    diagnosis = st.text_input("Module:", value=base_order.diagnosis, key=f"diagnosis_{condition}_{order_widget_key}")

    # Dynamic Medications
    with st.expander("Prescribed Medications", expanded=False):
        med_list: List[MedicationOrder] = []
        for i, m in enumerate(base_order.medications):
            st.markdown(f"**Medication {i+1}**")
            m_name = st.text_input(f"Name #{i+1}:", value=m.name, key=f"med_name_{condition}_{order_widget_key}_{i}")
            m_dose = st.text_input(f"Dose #{i+1}:", value=m.dose, key=f"med_dose_{condition}_{order_widget_key}_{i}")
            m_freq = st.text_input(f"Frequency #{i+1}:", value=m.frequency, key=f"med_freq_{condition}_{order_widget_key}_{i}")
            m_route = st.text_input(f"Route #{i+1}:", value=m.route, key=f"med_route_{condition}_{order_widget_key}_{i}")
            m_spec = st.text_input(f"Instructions #{i+1}:", value=m.special_instructions, key=f"med_spec_{condition}_{order_widget_key}_{i}")
            med_list.append(
                MedicationOrder(
                    name=m_name,
                    dose=m_dose,
                    frequency=m_freq,
                    route=m_route,
                    special_instructions=m_spec,
                )
            )

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        fever_urg = st.text_input(
            "Urgent Fever:", key=f"urgent_{condition}_{order_widget_key}",
            value=base_order.urgent_fever_threshold or "100.4°F",
        )
    with col_t2:
        fever_emg = st.text_input(
            "Emergency Fever:", key=f"emergency_{condition}_{order_widget_key}",
            value=base_order.emergency_fever_threshold or "101.0°F",
        )

    daytime_phone = st.text_input(
        "Daytime Phone:", key=f"daytime_{condition}_{order_widget_key}",
        value=base_order.daytime_phone or "901-595-3300",
    )
    after_hours_phone = st.text_input(
        "After-Hours Phone:", key=f"after_hours_{condition}_{order_widget_key}",
        value=base_order.after_hours_phone or "901-595-3300",
    )
    emergency_phone = st.text_input(
        "Emergency Phone:", key=f"emergency_phone_{condition}_{order_widget_key}",
        value=base_order.emergency_phone or "911",
    )

    active_orders = ClinicalOrders(
        order_id=base_order.order_id,
        order_version=order_version,
        patient_id=patient_id,
        age=age,
        diagnosis=diagnosis,
        medications=med_list,
        urgent_fever_threshold=fever_urg,
        emergency_fever_threshold=fever_emg,
        daytime_phone=daytime_phone,
        after_hours_phone=after_hours_phone,
        emergency_phone=emergency_phone,
    )

    st.divider()
    st.subheader("4. Scenario C Drift Simulator")
    with st.expander("Negative Safety Test Injections", expanded=False):
        drift_mode = st.selectbox(
            "Simulate Safety Failure:",
            options=["None", *DRIFT_MODES],
            index=0,
            help="Inject synthetic hallucinations to test automated regex locks and Safety Judge alarms.",
        )

MODULE_DISPLAY_NAMES = {
    "sickle_cell_pain": "Sickle Cell Acute Pain",
    "fever_neutropenia": "Fever & Neutropenia (Oncology)",
    "chemo_nausea_hydration": "Post-Chemo Nausea & Hydration",
}


def _run_generation(want_spanish: bool) -> None:
    """Run the pipeline for the current sidebar selections and store the result."""
    with st.spinner("Processing plain-language simplification and quality gates..."):
        raw_template = live_templates[condition][module_version]
        live_checked = False
        live_failed = False
        live_reason = ""
        data_unavailable = False
        try:
            if not active_orders.patient_id.startswith("SYN-"):
                raise ValueError("This prototype requires a synthetic patient ID beginning with SYN-.")
            orchestrator = PipelineOrchestrator(llm1_model=selected_llm1, llm2_model=selected_llm2)
            if drift_mode != "None":
                # Scenario C never contacts models or alters upstream data.
                baseline = orchestrator.generate(
                    compose_clinical_text(raw_template, active_orders), active_orders,
                    module_version=module_version, condition=condition,
                )
                packet = inject_drift(baseline, drift_mode)
            else:
                packet = orchestrator.generate_live(
                    raw_template, active_orders, module_version=module_version, condition=condition,
                    translate=want_spanish,
                )
                live_checked = True
        except Exception as exc:
            st.session_state["current_packet"] = None
            st.session_state["checked_packet"] = None
            st.session_state["pdf_bytes"] = None
            st.error("Generation failed. Nothing was published. " + describe_model_error(selected_llm1, exc))
            st.stop()
        st.session_state["reject_dialog_packet_id"] = None
        st.session_state["edit_check_error"] = None
        st.session_state["live_pipeline_notice"] = live_failed
        st.session_state["live_pipeline_reason"] = live_reason
        st.session_state["live_data_notice"] = data_unavailable
        st.session_state["checked_packet"] = (
            packet.model_dump(mode="json") if live_checked and not packet.evaluation_metrics.protection_failures else None
        )
        st.session_state["current_packet"] = packet
        st.session_state["spanish_requested"] = want_spanish
        st.session_state["clean_backup_packet"] = copy.deepcopy(packet)
        st.session_state["edits_checked_banner"] = False
        st.session_state["pdf_bytes"] = None
        # Initialize text area safely before widget is instantiated
        st.session_state["txt_clinician_en"] = packet.simplified_en
        st.rerun()


# ---------------------------------------------------------------------------
# Main Content Area (uichanges.md front-page layout)
# ---------------------------------------------------------------------------
# A review belongs to the exact inputs used to generate it. Sidebar changes
# return to the source preview before any older result can be approved.
review_inputs = hashlib.sha256(json.dumps({
    "condition": condition, "module_version": module_version,
    "source": live_templates[condition][module_version],
    "orders": active_orders.model_dump(mode="json"),
    "models": [selected_llm1, selected_llm2], "drift": drift_mode,
}, sort_keys=True).encode()).hexdigest()
if st.session_state.get("review_inputs") != review_inputs:
    st.session_state["review_inputs"] = review_inputs
    for key in ("current_packet", "checked_packet", "pdf_bytes", "clean_backup_packet",
                "reject_dialog_packet_id", "edit_check_error"):
        st.session_state[key] = None
    st.session_state["edits_checked_banner"] = False
    st.session_state["spanish_requested"] = False
    st.session_state["txt_clinician_en"] = ""

st.markdown(
    "<div class='front-page-heading'>"
    "<h2>Bilingual Pediatric Discharge Instruction Review</h2>"
    f"<p><strong>Patient MRN:</strong> {escape(active_orders.patient_id)} "
    f"({escape(active_orders.age or 'N/A')})</p>"
    f"<p><strong>Module:</strong> "
    f"{escape(MODULE_DISPLAY_NAMES.get(condition, condition))}</p>"
    "</div>",
    unsafe_allow_html=True,
)

packet: Optional[InstructionPacket] = st.session_state.get("current_packet")

def _compose_original_display(orders: ClinicalOrders, template_text: str, template_version: str) -> str:
    text = (
        f"=== CLINICAL ORDERS ===\n"
        f"Patient MRN: {orders.patient_id} ({orders.age or 'N/A'})\n"
        f"Module: {orders.diagnosis}\n\n"
        f"MEDICATIONS:\n"
    )
    for med in orders.medications:
        text += f"• {med.name}: {med.dose} {med.route} {med.frequency}\n  Note: {med.special_instructions}\n"
    text += (
        f"\nSAFETY LIMITS:\n"
        f"• Urgent Fever: {orders.urgent_fever_threshold or ''}\n"
        f"• Emergency Fever: {orders.emergency_fever_threshold or ''}\n\n"
        f"CONTACTS:\n"
        f"• Daytime Phone: {orders.daytime_phone or ''}\n"
        f"• After-Hours Phone: {orders.after_hours_phone or ''}\n"
        f"• Emergency Phone: {orders.emergency_phone or ''}\n\n"
        f"=== PROTOCOL TEMPLATE ({template_version}) ===\n"
        f"{template_text}"
    )
    return text


if packet is None:
    # ------------------------------------------------------------------
    # Front page: generate controls + full-width original instructions
    # ------------------------------------------------------------------
    _, centered_controls, _ = st.columns([1, 3, 1])
    with centered_controls:
        gen_col, es_col = st.columns([1.2, 2])
        with gen_col:
            generate_clicked = st.button("Generate Simplified Instructions", type="primary", width="stretch")
        with es_col:
            want_spanish = st.checkbox(
                "Include Spanish translation (with English back-translation) for family",
                key="chk_want_spanish",
                help="When checked, the simplified English is translated to Spanish and back-translated for verification.",
            )
    if generate_clicked:
        _run_generation(want_spanish)

    try:
        preview_source = compose_clinical_text(live_templates[condition][module_version], active_orders)
    except Exception:
        preview_source = live_templates[condition][module_version]
    st.markdown(
        f"<div class='clinical-box-full'>{escape(_compose_original_display(active_orders, preview_source, module_version))}</div>",
        unsafe_allow_html=True,
    )
else:
    if packet.is_simulation:
        st.error("SYNTHETIC DRIFT SIMULATION — not for patient use. Review and reject this test instruction set.")

    spanish_requested = st.session_state.get("spanish_requested", bool(packet.translated_es.strip()))
    metrics = packet.evaluation_metrics or EvaluationMetrics()

    # ------------------------------------------------------------------
    # Metrics row (shown in place of the generate button)
    # ------------------------------------------------------------------
    m_col1, m_col2, m_col3, m_col4 = st.columns([1, 1, 1, 1])
    with m_col1:
        st.metric(
            label="FKGL Readability",
            value=f"{round(metrics.fkgl_score, 1):.1f}",
            delta="Target: 5.0–6.9" if 5.0 <= metrics.fkgl_score <= 6.9 else "Out of Range",
            delta_color="normal" if 5.0 <= metrics.fkgl_score <= 6.9 else "inverse",
            help="Flesch-Kincaid Grade Level calculated via textstat. Pediatric discharge goal is 5th–6th grade.",
        )
    with m_col2:
        if metrics.protection_failures:
            verbatim_help = "\n".join(metrics.protection_failures)
        elif metrics.verbatim_mismatches:
            verbatim_help = "Missing safety tokens: " + ", ".join(metrics.verbatim_mismatches)
        else:
            verbatim_help = "All safety-critical values preserved verbatim."
        st.metric(
            label="Verbatim Score",
            value="FAILED" if metrics.protection_failures else f"{round(metrics.verbatim_match_percent):d}%",
            delta="Protected values failed" if metrics.protection_failures else ("All locked" if not metrics.verbatim_mismatches else f"{len(metrics.verbatim_mismatches)} missing"),
            delta_color="inverse" if metrics.protection_failures or metrics.verbatim_mismatches else "normal",
            help=verbatim_help,
        )
    with m_col3:
        judge = metrics.safety_judge
        verdict = judge.overall_verdict if judge else "UNAVAILABLE"
        st.metric(
            label="Judge Review",
            value={"PASS": "PASS", "NEEDS_REVIEW": "REVIEW", "FLAGGED_FOR_REVIEW": "FLAGGED"}.get(verdict, verdict),
            delta=None,
            help=(judge.explanation.strip() if judge and judge.explanation.strip() else "Independent LLM2 factual safety verdict."),
        )
    with m_col4:
        annotation = get_physician_annotation(packet)
        if packet.status == "APPROVED":
            st.success(annotation)
        elif packet.status == "EDITED_AND_APPROVED":
            st.info(annotation)
        elif packet.status == "REJECTED_DRIFT":
            st.error(annotation)
        else:
            st.warning(annotation)
        if st.button("New Generation", help="Discard this review and return to the generate page"):
            st.session_state["current_packet"] = None
            st.session_state["checked_packet"] = None
            st.session_state["pdf_bytes"] = None
            st.session_state["edits_checked_banner"] = False
            st.session_state["reject_dialog_packet_id"] = None
            st.rerun()

    if metrics.protection_failures:
        st.error("DRAFT — NOT FOR PATIENT USE. Protected values failed validation. Review the draft and failed safety tokens below; approval is blocked.")
        st.markdown("**Failed safety tokens**")
        for finding in metrics.protection_failures:
            st.text(finding)
        st.caption("Only intact markers were restored. Missing values were not inserted; unresolved markers require clinician correction. Later model stages were skipped.")

    if not 5.0 <= metrics.fkgl_score <= 6.9:
        st.error(
            "DRAFT — NOT FOR PATIENT USE. The readability score did not meet "
            "the FKGL target of 5.0–6.9. The draft remains visible for review, "
            "but approval is blocked."
        )

    judge = metrics.safety_judge
    if (not metrics.protection_failures and judge is not None and
            (judge.overall_verdict != "PASS" or judge.factual_drift_detected or
             judge.omitted_red_flags or judge.contradictory_advice)):
        st.error(
            "DRAFT — NOT FOR PATIENT USE. The safety review did not pass. "
            "The simplified version remains visible for clinician review, but "
            "approval is blocked."
        )

    if metrics.safety_judge and metrics.safety_judge.factual_drift_detected:
        st.warning("Safety Alert: " + metrics.safety_judge.explanation)

    # Re-evaluation notice banner if edits were recently checked
    if st.session_state.get("edits_checked_banner", False):
        st.info("**Edits re-evaluated and checked.** Status remains `PENDING`. Click **'Approve & publish'** when ready to finalize.")

    orig_text = _compose_original_display(
        packet.clinical_orders, packet.original_clinical_text, packet.module_version
    )

    # ------------------------------------------------------------------
    # Comparative panes: 2 boxes (English-only) or 4 boxes (with Spanish)
    # Fixed equal widths: 50% each in English-only mode, 25% with Spanish.
    # ------------------------------------------------------------------
    if spanish_requested:
        col1, col2, col3, col4 = st.columns(4)
    else:
        col1, col2 = st.columns(2)
        col3 = col4 = None

    with col1:
        st.markdown("<div class='col-header'>Original Clinical Orders</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='clinical-box'>{escape(orig_text)}</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='col-header'>Simplified English (Clinician Edit)</div>", unsafe_allow_html=True)
        # Interactive text area with two-way binding
        # Invariant: Read directly from session state; never mutate key downstream
        st.text_area(
            "Inline Clinical Editor:",
            key="txt_clinician_en",
            height=420,
            help="Edit plain-language text directly. Click 'Save and check edits' to re-verify.",
        )

    if col3 is not None:
        with col3:
            st.markdown("<div class='col-header'>Spanish Handout (LLM 1)</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='clinical-box'>{escape(packet.translated_es)}</div>", unsafe_allow_html=True)
        with col4:
            st.markdown("<div class='col-header'>Back-Translated English (LLM 2)</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='clinical-box'>{escape(packet.back_translated_en)}</div>", unsafe_allow_html=True)
        st.caption("Back-translation allows English-speaking clinicians to inspect and verify Spanish translation fidelity.")

    st.divider()

    # ---------------------------------------------------------
    # Action Footer & Review Governance (specs/03 Section 2.4)
    # ---------------------------------------------------------
    st.subheader("Physician Action & Review Governance")

    if st.session_state.get("edit_check_error"):
        st.error(st.session_state["edit_check_error"])
    # A new or edited revision requires a fresh human attestation.
    review_key = hashlib.sha256(packet.model_dump_json().encode()).hexdigest()
    if spanish_requested:
        spanish_reviewed = st.checkbox(
            "I am an authorized medical translator or credentialed bilingual clinician and have verified this Spanish translation.",
            key=f"spanish_review_{review_key}",
        )
    else:
        spanish_reviewed = False
        st.caption("English-only review: no Spanish translation was requested for this family.")

    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([1.2, 1.2, 1.2, 1.5])

    # 1. Save and check edits
    with btn_col1:
        if st.button("Save & Check Edits", width="stretch", help="Re-runs readability and verbatim checks while keeping status PENDING"):
            edited_text = st.session_state.get("txt_clinician_en", packet.simplified_en)

            if not edited_text.strip():
                st.error("Enter English instructions before checking edits.")
                st.stop()
            # Invalidate earlier checks before any external request can fail.
            st.session_state["checked_packet"] = None
            st.session_state["pdf_bytes"] = None
            try:
                orchestrator = PipelineOrchestrator(llm1_model=selected_llm1, llm2_model=selected_llm2)
                if packet.is_simulation:
                    raise ValueError("Drift simulations cannot be approved; generate normal instructions for live review.")
                packet = orchestrator.recheck_edits_live(packet, edited_text, translate=spanish_requested)
            except Exception as exc:
                # Local checks can still run, but cannot certify a translation.
                try:
                    packet = PipelineOrchestrator().recheck_edits(packet, edited_text)
                except Exception:
                    st.session_state["edits_checked_banner"] = False
                    st.error("Recheck failed. No approval is available; retry the checks.")
                    st.stop()
                st.session_state["edit_check_error"] = (
                    "Instruction recheck failed; approval remains blocked. "
                    + describe_model_error(selected_llm1, exc)
                )
                st.session_state["edits_checked_banner"] = False
            else:
                protection_failed = bool(packet.evaluation_metrics.protection_failures)
                st.session_state["checked_packet"] = None if protection_failed else packet.model_dump(mode="json")
                st.session_state["edit_check_error"] = None
                st.session_state["edits_checked_banner"] = not protection_failed
            st.session_state["current_packet"] = packet
            st.rerun()


    # 2. Approve & publish (Sole Approval Gate)
    with btn_col2:
        if st.button("Approve & Publish", type="primary", width="stretch"):
            edited_text = st.session_state.get("txt_clinician_en", packet.simplified_en)
            blockers = approval_blockers(
                packet, edited_text, st.session_state.get("checked_packet"), spanish_reviewed,
                spanish_requested=spanish_requested,
            )
            if blockers:
                for reason in blockers:
                    st.error(reason)
            else:
                candidate = packet.model_copy(deep=True)
                backup = st.session_state.get("clean_backup_packet")
                was_edited = candidate.edited_by_physician or (
                    backup is not None and edited_text != backup.simplified_en
                )
                candidate.status = "EDITED_AND_APPROVED" if was_edited else "APPROVED"
                candidate.edited_by_physician = was_edited
                candidate.physician_decision = get_physician_annotation(candidate)
                candidate.reviewed_at = datetime.now(timezone.utc).isoformat()
                review_note = (
                    "Reviewer attested to authorized Spanish verification for this revision."
                    if spanish_requested else "English-only review; Spanish translation was not requested."
                )
                candidate.clinician_notes = ((candidate.clinician_notes or "") + "\n" + review_note).strip()
                try:
                    # Build first: a failed export must not persist an approval.
                    pdf_data = live_pdf_gen(candidate) if HAS_LIVE_PDF else generate_handout_pdf(candidate)
                    if HAS_LIVE_STORAGE:
                        live_save_gold(candidate)
                    else:
                        save_to_gold_library(candidate)
                except Exception:
                    st.error("Publishing failed. The instructions remain pending; retry after resolving the export or storage error.")
                else:
                    st.session_state["current_packet"] = candidate
                    st.session_state["pdf_bytes"] = pdf_data
                    st.session_state["edits_checked_banner"] = False
                    st.rerun()

    # 3. Reject & log drift
    with btn_col3:
        if st.button("Reject & Log Drift", width="stretch", disabled=packet.status != "PENDING"):
            st.session_state["reject_dialog_packet_id"] = packet.packet_id
        if st.session_state.get("reject_dialog_packet_id") == packet.packet_id:
            reject_packet_dialog(packet)

    # 4. PDF Download Button (Available once reviewed)
    with btn_col4:
        pdf_data = st.session_state.get("pdf_bytes")
        if pdf_data is not None:
            st.download_button(
                label=f"Download PDF Handout ({packet.status})",
                data=pdf_data,
                file_name=f"discharge_handout_{packet.packet_id}.pdf",
                mime="application/pdf",
                width="stretch",
            )
        else:
            st.button("PDF Handout (Locked until approved/rejected)", disabled=True, width="stretch")


# ---------------------------------------------------------------------------
# Library Explorer (specs/03 Section 2.5)
# ---------------------------------------------------------------------------
st.divider()
with st.expander("View versioned library records", expanded=False):
    st.caption("Records are private to this session and disappear when it ends. No clinical records are written to disk.")
    if HAS_LIVE_STORAGE:
        records = live_load_gold()
    else:
        records = load_gold_records()

    if not records:
        st.info("No instructions saved to library yet. Approved or rejected instructions will appear here.")
    else:
        table_rows = []
        for r in reversed(records):
            table_rows.append({
                "Record ID": r.packet_id,
                "Parent Record": r.parent_packet_id or "—",
                "PDF Annotation": get_physician_annotation(r),
                "Simulation": r.is_simulation,
                "Timestamp": r.created_at[:19].replace("T", " ") if r.created_at else "",
                "Module": MODULE_DISPLAY_NAMES.get(r.condition, r.condition),
                "Status": r.status,
                "Physician Decision": r.physician_decision or get_physician_annotation(r),
                "FKGL Grade": r.evaluation_metrics.fkgl_score if r.evaluation_metrics else 0.0,
                "Verbatim Match %": f"{r.evaluation_metrics.verbatim_match_percent}%" if r.evaluation_metrics else "100%",
                "Rejection Category": r.rejection_category or "—",
                "Rejection Reason": r.rejection_reason or "—",
                "Reviewed At": r.reviewed_at[:19].replace("T", " ") if r.reviewed_at else "—",
            })
        st.dataframe(table_rows, width="stretch")
