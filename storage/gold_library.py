"""Track B review records, serialized in memory for the Phase 1 integration.

Each entry is an independent JSON record. The UI supplies a session-owned list
so records are neither written to disk nor shared between browser sessions.
"""

from datetime import datetime, timezone

from schemas.instruction_packet import InstructionPacket, get_physician_annotation

# Compatibility store for command-line/component callers. The UI passes its own.
_IN_MEMORY_LIBRARY: list[str] = []


def save_to_gold_library(packet: InstructionPacket, *, library: list[str] | None = None) -> None:
    """Append a serialized snapshot without changing the caller's packet."""
    target = _IN_MEMORY_LIBRARY if library is None else library
    snapshot = packet.model_copy(deep=True)
    if not snapshot.physician_decision:
        snapshot.physician_decision = get_physician_annotation(snapshot)
    if not snapshot.reviewed_at:
        snapshot.reviewed_at = datetime.now(timezone.utc).isoformat()
    target.append(snapshot.model_dump_json())


save_gold_record = save_to_gold_library


def load_gold_records(*, library: list[str] | None = None) -> list[InstructionPacket]:
    """Return fresh objects so edits to a loaded record cannot change history."""
    source = _IN_MEMORY_LIBRARY if library is None else library
    return [InstructionPacket.model_validate_json(record) for record in source]
