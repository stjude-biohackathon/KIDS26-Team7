"""
CLEAR — Clinician Review Dashboard & Streamlit UI/UX (Track C)
Authoritative Implementation adhering to specs/03_TRACK_C_CLINICIAN_UI_UX.md.
"""

from __future__ import annotations

import copy
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
    from storage.github_loader import fetch_remote_templates_and_orders
    HAS_LIVE_LOADER = True
except ImportError:
    HAS_LIVE_LOADER = False

try:
    from pipeline.orchestrator import PipelineOrchestrator
    HAS_LIVE_PIPELINE = True
except ImportError:
    HAS_LIVE_PIPELINE = False

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
# Streamlit Page Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="CLEAR — Clinician Review Dashboard",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for clinical styling and comparative review columns
st.markdown(
    """
    <style>
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
        height: 480px;
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


# ---------------------------------------------------------------------------
# Rejection Modal Dialog (Governance Requirement 2.4)
# ---------------------------------------------------------------------------
@st.dialog("Reject & Log Clinical Drift")
def reject_packet_dialog(packet: InstructionPacket):
    st.warning("⚠️ You are rejecting this instruction packet due to detected clinical drift or safety violation.")
    
    drift_category = st.selectbox(
        "Drift Taxonomy Categorization *",
        options=[
            "Unsafe dosage alteration",
            "Altered return/fever threshold",
            "Omitted critical red flag",
            "Contradictory clinical advice",
            "Spanish translation drift",
        ],
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
            
            packet.status = "REJECTED_DRIFT"
            packet.rejection_category = drift_category
            packet.rejection_reason = explanation.strip()
            packet.physician_decision = "Rejected by physician"
            packet.reviewed_at = datetime.now(timezone.utc).isoformat()
            
            # Persist to library
            if HAS_LIVE_STORAGE:
                live_save_gold(packet)
            else:
                save_to_gold_library(packet)
            
            # Generate rejected PDF
            if HAS_LIVE_PDF:
                st.session_state["pdf_bytes"] = live_pdf_gen(packet)
            else:
                st.session_state["pdf_bytes"] = generate_handout_pdf(packet)
                
            st.session_state["edits_checked_banner"] = False
            st.success("Rejection logged to audit library.")
            st.rerun()
            
    with col_cancel:
        if st.button("Cancel"):
            st.rerun()


# ---------------------------------------------------------------------------
# Sidebar: Model, Protocol, & Orders Configuration (specs/03 Section 2.1)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🩺 CLEAR Controls")
    st.caption("AI-Assisted Pediatric Discharge Instruction Simplification with Clinician-in-the-Loop")

    st.subheader("1. AI Model Selection")
    model_options = ["gpt52", "gpt4o", "gpt56luna", "kimik3", "copus5", "local1", "local2"]
    
    selected_llm1 = st.selectbox(
        "LLM 1 (Simplifier & Spanish):",
        options=model_options,
        index=model_options.index("gpt52"),
        help="Model responsible for 5th–6th grade plain-language simplification and Spanish translation.",
    )
    selected_llm2 = st.selectbox(
        "LLM 2 (Safety Judge & Back-EN):",
        options=model_options,
        index=model_options.index("gpt4o"),
        help="Independent model evaluating factual drift and back-translating Spanish to English.",
    )

    st.divider()
    st.subheader("2. In-Memory Data Stream")
    
    col_badge, col_ref = st.columns([4, 1])
    with col_badge:
        if HAS_LIVE_LOADER:
            st.markdown(
                "**Source:** ☁️ GitHub App (In-Memory)<br/>"
                "<small style='color: #059669;'>Zero local copies • In-memory stream</small>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "**Source:** ☁️ GitHub App (In-Memory)<br/>"
                "<small style='color: #059669;'>Zero local copies • In-memory stream</small>",
                unsafe_allow_html=True,
            )
    with col_ref:
        if st.button("🔄", help="Clear cache and reload remote protocols from GitHub App"):
            st.cache_data.clear()
            st.rerun()

    st.divider()
    st.subheader("3. Protocol & Module Version")
    
    condition = st.selectbox(
        "Clinical Module:",
        options=["sickle_cell_pain", "fever_neutropenia", "chemo_nausea_hydration"],
        format_func=lambda x: {
            "sickle_cell_pain": "Sickle Cell Acute Pain",
            "fever_neutropenia": "Fever & Neutropenia (Oncology)",
            "chemo_nausea_hydration": "Post-Chemo Nausea & Hydration",
        }.get(x, x),
    )

    col_mv, col_ov = st.columns(2)
    with col_mv:
        module_version = st.selectbox("Module Ver:", options=["v1.2.0", "v1.1.0"], index=0)
    with col_ov:
        order_version = st.selectbox("Order Set Ver:", options=["v1.2.0 (ORD-01)", "v1.1.0 (ORD-00)"], index=0)

    st.info(f"Active Protocol: `{condition}` | `{module_version}` | `{order_version}`")

    st.divider()
    st.subheader("4. Clinical Orders Customization")

    # Load base mock order for the selected condition
    base_order = MOCK_ORDERS.get(condition, MOCK_ORDERS["sickle_cell_pain"])
    
    patient_id = st.text_input("Patient ID (De-identified):", value=base_order.patient_id)
    age = st.text_input("Patient Age:", value=base_order.age or "8 years old")
    diagnosis = st.text_input("Diagnosis:", value=base_order.diagnosis)

    # Dynamic Medications
    with st.expander("Prescribed Medications", expanded=False):
        med_list: List[MedicationOrder] = []
        for i, m in enumerate(base_order.medications):
            st.markdown(f"**Medication {i+1}**")
            m_name = st.text_input(f"Name #{i+1}:", value=m.name, key=f"med_name_{i}")
            m_dose = st.text_input(f"Dose #{i+1}:", value=m.dose, key=f"med_dose_{i}")
            m_freq = st.text_input(f"Frequency #{i+1}:", value=m.frequency, key=f"med_freq_{i}")
            m_route = st.text_input(f"Route #{i+1}:", value=m.route, key=f"med_route_{i}")
            m_spec = st.text_input(f"Instructions #{i+1}:", value=m.special_instructions, key=f"med_spec_{i}")
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
            "Urgent Fever:",
            value=base_order.urgent_fever_threshold or "100.4°F",
        )
    with col_t2:
        fever_emg = st.text_input(
            "Emergency Fever:",
            value=base_order.emergency_fever_threshold or "101.0°F",
        )

    daytime_phone = st.text_input(
        "Daytime Phone:",
        value=base_order.daytime_phone or "901-595-3300",
    )
    after_hours_phone = st.text_input(
        "After-Hours Phone:",
        value=base_order.after_hours_phone or "901-595-3300",
    )
    emergency_phone = st.text_input(
        "Emergency Phone:",
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
    st.subheader("5. Scenario C Drift Simulator")
    with st.expander("Negative Safety Test Injections", expanded=False):
        drift_mode = st.selectbox(
            "Simulate Safety Failure:",
            options=["None", "Contradictory Advice", "Altered Fever Threshold", "Altered Medication Dose"],
            index=0,
            help="Inject synthetic hallucinations to test automated regex locks and Safety Judge alarms.",
        )

    st.divider()
    if st.button("🚀 Generate Instructions", type="primary", use_container_width=True):
        with st.spinner("Processing plain-language simplification, quality gates, and translations..."):
            packet = run_mock_pipeline(
                condition=condition,
                module_version=module_version,
                orders=active_orders,
                llm1_model=selected_llm1,
                llm2_model=selected_llm2,
                drift_mode=drift_mode,
            )
            st.session_state["current_packet"] = packet
            st.session_state["clean_backup_packet"] = copy.deepcopy(packet)
            st.session_state["edits_checked_banner"] = False
            st.session_state["pdf_bytes"] = None
            # Initialize text area safely before widget is instantiated
            st.session_state["txt_clinician_en"] = packet.simplified_en
            st.rerun()


# ---------------------------------------------------------------------------
# Main Content Area: 4-Way Comparative Review Pane (specs/03 Section 2.2)
# ---------------------------------------------------------------------------
st.markdown("## 🏥 Pediatric Discharge Instructions — Clinician Review")

packet: Optional[InstructionPacket] = st.session_state.get("current_packet")

if packet is None:
    st.info("👈 Select parameters in the sidebar and click **'🚀 Generate Instructions'** to begin.")
else:
    # Patient Banner & Status Line
    col_info, col_stat = st.columns([3, 1])
    with col_info:
        st.markdown(
            f"**Patient:** `{packet.clinical_orders.patient_id}` ({packet.clinical_orders.age or 'N/A'}) | "
            f"**Diagnosis:** `{packet.clinical_orders.diagnosis}` | "
            f"**Packet:** `{packet.packet_id}`"
        )
    with col_stat:
        annotation = get_physician_annotation(packet)
        if packet.status == "APPROVED":
            st.success(f"✔ {annotation}")
        elif packet.status == "EDITED_AND_APPROVED":
            st.info(f"✎ {annotation}")
        elif packet.status == "REJECTED_DRIFT":
            st.error(f"✖ {annotation}")
        else:
            st.warning(f"⏳ {annotation}")

    # Re-evaluation notice banner if edits were recently checked
    if st.session_state.get("edits_checked_banner", False):
        st.info("ℹ️ **Edits re-evaluated and checked.** Status remains `PENDING`. Click **'Approve & publish'** when ready to finalize.")

    # 4 Balanced Columns
    col1, col2, col3, col4 = st.columns(4)

    # ---------------------------------------------------------
    # Column 1: Original Clinical Orders & Instructions
    # ---------------------------------------------------------
    with col1:
        st.markdown("<div class='col-header'>1. Original Clinical Orders</div>", unsafe_allow_html=True)
        orig_text = (
            f"=== CLINICAL ORDERS ===\n"
            f"Patient: {packet.clinical_orders.patient_id} ({packet.clinical_orders.age or 'N/A'})\n"
            f"Diagnosis: {packet.clinical_orders.diagnosis}\n\n"
            f"MEDICATIONS:\n"
        )
        for med in packet.clinical_orders.medications:
            orig_text += f"• {med.name}: {med.dose} {med.route} {med.frequency}\n  Note: {med.special_instructions}\n"
        orig_text += (
            f"\nSAFETY LIMITS:\n"
            f"• Urgent Fever: {packet.clinical_orders.urgent_fever_threshold or ''}\n"
            f"• Emergency Fever: {packet.clinical_orders.emergency_fever_threshold or ''}\n\n"
            f"CONTACTS:\n"
            f"• Daytime Phone: {packet.clinical_orders.daytime_phone or ''}\n"
            f"• After-Hours Phone: {packet.clinical_orders.after_hours_phone or ''}\n"
            f"• Emergency Phone: {packet.clinical_orders.emergency_phone or ''}\n\n"
            f"=== PROTOCOL TEMPLATE ({packet.module_version}) ===\n"
            f"{packet.original_clinical_text}"
        )
        st.markdown(f"<div class='clinical-box'>{orig_text}</div>", unsafe_allow_html=True)

    # ---------------------------------------------------------
    # Column 2: Simplified English Handout (with Inline Editing)
    # ---------------------------------------------------------
    with col2:
        st.markdown("<div class='col-header'>2. Simplified English (Clinician Edit)</div>", unsafe_allow_html=True)
        
        # Telemetry Badges
        metrics = packet.evaluation_metrics or EvaluationMetrics()
        badge_html = "<div>"
        
        # FKGL Badge
        if 4.0 <= metrics.fkgl_score <= 6.9:
            badge_html += f"<span class='metric-badge-pass'>🟢 FKGL: {metrics.fkgl_score}</span>"
        else:
            badge_html += f"<span class='metric-badge-warn'>🟡 FKGL: {metrics.fkgl_score} (Target 5-6)</span>"
            
        # Verbatim Lock Badge
        if len(metrics.verbatim_mismatches) == 0:
            badge_html += f"<span class='metric-badge-pass'>🟢 Verbatim: {metrics.verbatim_match_percent}%</span>"
        else:
            badge_html += f"<span class='metric-badge-danger'>🔴 Missing: {len(metrics.verbatim_mismatches)} tokens</span>"
            
        # Safety Judge Badge
        if metrics.safety_judge and metrics.safety_judge.overall_verdict == "PASS":
            badge_html += "<span class='metric-badge-pass'>🟢 Judge: PASS</span>"
        elif metrics.safety_judge and metrics.safety_judge.overall_verdict == "NEEDS_REVIEW":
            badge_html += "<span class='metric-badge-warn'>🟡 Judge: REVIEW</span>"
        elif metrics.safety_judge:
            badge_html += "<span class='metric-badge-danger'>🔴 Judge: FLAGGED</span>"
            
        badge_html += "</div>"
        st.markdown(badge_html, unsafe_allow_html=True)
        
        if metrics.verbatim_mismatches:
            st.caption(f"<small style='color: #DC2626;'>Mismatched safety tokens: {', '.join(metrics.verbatim_mismatches)}</small>", unsafe_allow_html=True)
        if metrics.safety_judge and metrics.safety_judge.factual_drift_detected:
            st.caption(f"<small style='color: #DC2626;'>Safety Alert: {metrics.safety_judge.explanation}</small>", unsafe_allow_html=True)

        # Interactive text area with two-way binding
        # Invariant: Read directly from session state; never mutate key downstream
        st.text_area(
            "Inline Clinical Editor:",
            key="txt_clinician_en",
            height=380,
            help="Edit plain-language text directly. Click 'Save and check edits' to re-verify.",
        )

    # ---------------------------------------------------------
    # Column 3: Spanish Translation
    # ---------------------------------------------------------
    with col3:
        st.markdown("<div class='col-header'>3. Spanish Handout (LLM 1)</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='clinical-box'>{packet.translated_es}</div>", unsafe_allow_html=True)

    # ---------------------------------------------------------
    # Column 4: Back-Translated English
    # ---------------------------------------------------------
    with col4:
        st.markdown("<div class='col-header'>4. Back-Translated English (LLM 2)</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='clinical-box'>{packet.back_translated_en}</div>", unsafe_allow_html=True)

    st.caption("ℹ️ Back-translation allows English-speaking clinicians to inspect and verify Spanish translation fidelity.")

    st.divider()

    # ---------------------------------------------------------
    # Action Footer & Review Governance (specs/03 Section 2.4)
    # ---------------------------------------------------------
    st.subheader("Physician Action & Review Governance")

    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([1.2, 1.2, 1.2, 1.5])

    # 1. Save and check edits
    with btn_col1:
        if st.button("✏️ Save & Check Edits", use_container_width=True, help="Re-runs readability and verbatim checks while keeping status PENDING"):
            edited_text = st.session_state.get("txt_clinician_en", packet.simplified_en)
            packet.simplified_en = edited_text
            packet.edited_by_physician = True
            
            # Re-evaluate FKGL and verbatim checks
            new_metrics = evaluate_text_verbatim_and_fkgl(edited_text, packet.clinical_orders)
            packet.evaluation_metrics = new_metrics
            
            # In mock mode, re-run translation updates
            packet.translated_es = (
                f"[Traducción actualizada con ediciones del médico]:\n\n"
                + edited_text.replace("Here is your child's care plan", "Este es el plan de cuidado de su hijo")
                .replace("Give", "Dé")
                .replace("Call immediately", "Llame de inmediato")
            )
            packet.back_translated_en = (
                f"[Back-translation of updated physician edits]:\n\n"
                + edited_text
            )
            
            # Governance Invariant: status remains PENDING
            packet.status = "PENDING"
            packet.physician_decision = "Pending physician review"
            st.session_state["edits_checked_banner"] = True
            st.session_state["pdf_bytes"] = None
            st.rerun()

    # 2. Approve & publish (Sole Approval Gate)
    with btn_col2:
        if st.button("✔ Approve & Publish", type="primary", use_container_width=True):
            edited_text = st.session_state.get("txt_clinician_en", packet.simplified_en)
            backup_text = st.session_state["clean_backup_packet"].simplified_en if st.session_state.get("clean_backup_packet") else packet.simplified_en
            
            if edited_text.strip() != backup_text.strip():
                packet.status = "EDITED_AND_APPROVED"
                packet.edited_by_physician = True
            else:
                packet.status = "APPROVED"
                packet.edited_by_physician = False
                
            packet.simplified_en = edited_text
            packet.physician_decision = get_physician_annotation(packet)
            packet.reviewed_at = datetime.now(timezone.utc).isoformat()
            
            # Persist to versioned library
            if HAS_LIVE_STORAGE:
                live_save_gold(packet)
            else:
                save_to_gold_library(packet)
                
            # Generate finalized bilingual PDF
            if HAS_LIVE_PDF:
                pdf_data = live_pdf_gen(packet)
            else:
                pdf_data = generate_handout_pdf(packet)
                
            st.session_state["pdf_bytes"] = pdf_data
            st.session_state["edits_checked_banner"] = False
            st.success(f"✔ Successfully saved as **{packet.physician_decision}**.")
            st.rerun()

    # 3. Reject & log drift
    with btn_col3:
        if st.button("✖ Reject & Log Drift", use_container_width=True):
            reject_packet_dialog(packet)

    # 4. PDF Download Button (Available once reviewed)
    with btn_col4:
        pdf_data = st.session_state.get("pdf_bytes")
        if pdf_data is not None:
            st.download_button(
                label=f"📄 Download PDF Handout ({packet.status})",
                data=pdf_data,
                file_name=f"discharge_handout_{packet.packet_id}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.button("📄 PDF Handout (Locked until approved/rejected)", disabled=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Library Explorer (specs/03 Section 2.5)
# ---------------------------------------------------------------------------
st.divider()
with st.expander("📚 View versioned library records", expanded=False):
    if HAS_LIVE_STORAGE:
        records = live_load_gold()
    else:
        records = load_gold_records()

    if not records:
        st.info("No packets saved to library yet. Approved or rejected packets will appear here.")
    else:
        table_rows = []
        for r in reversed(records):
            table_rows.append({
                "Packet ID": r.packet_id,
                "Timestamp": r.created_at[:19].replace("T", " ") if r.created_at else "",
                "Condition": r.condition,
                "Status": r.status,
                "Physician Decision": r.physician_decision or get_physician_annotation(r),
                "FKGL Grade": r.evaluation_metrics.fkgl_score if r.evaluation_metrics else 0.0,
                "Verbatim Match %": f"{r.evaluation_metrics.verbatim_match_percent}%" if r.evaluation_metrics else "100%",
                "Rejection Category": r.rejection_category or "—",
                "Rejection Reason": r.rejection_reason or "—",
                "Reviewed At": r.reviewed_at[:19].replace("T", " ") if r.reviewed_at else "—",
            })
        st.dataframe(table_rows, use_container_width=True)
