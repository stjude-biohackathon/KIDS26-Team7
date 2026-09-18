"""Session-scoped immutable review snapshots. Clinical records never touch disk."""
from datetime import datetime, timezone

from schemas.instruction_packet import InstructionPacket, get_physician_annotation


class ReviewLibrary:
    """A library owned by one session, with copies at both public boundaries."""
    def __init__(self):
        self._records: dict[str, InstructionPacket] = {}
        self._inputs: dict[str, str] = {}

    def save(self, packet: InstructionPacket) -> None:
        if packet.status in {'APPROVED', 'EDITED_AND_APPROVED'} and packet.evaluation_metrics and packet.evaluation_metrics.protection_failures:
            raise ValueError('Protected-value failures must be resolved before publishing.')
        if packet.status not in {'APPROVED', 'EDITED_AND_APPROVED', 'REJECTED_DRIFT'}:
            raise ValueError('Only reviewed packets can be saved.')
        value = packet.model_dump_json()
        if packet.packet_id in self._records:
            if value in (self._inputs[packet.packet_id], self._records[packet.packet_id].model_dump_json()):
                return
            raise ValueError('A saved review cannot be overwritten. Create a new revision.')
        saved = packet.model_copy(deep=True)
        saved.physician_decision = get_physician_annotation(saved)
        saved.reviewed_at = saved.reviewed_at or datetime.now(timezone.utc).isoformat()
        self._records[saved.packet_id] = saved
        self._inputs[saved.packet_id] = value

    def records(self) -> list[InstructionPacket]:
        return [p.model_copy(deep=True) for p in self._records.values()]


def _session_library() -> ReviewLibrary:
    import streamlit as st
    if 'review_library' not in st.session_state:
        st.session_state['review_library'] = ReviewLibrary()
    return st.session_state['review_library']


def save_to_gold_library(packet: InstructionPacket, *, library: ReviewLibrary | None = None) -> None:
    (library if library is not None else _session_library()).save(packet)


def load_gold_records(*, library: ReviewLibrary | None = None) -> list[InstructionPacket]:
    return (library if library is not None else _session_library()).records()


save_gold_record = save_to_gold_library
