"""
Track B: Versioned Library Storage.
Appends reviewed packets to versioned_instructions.jsonl with status, timestamp, and audit trail.
Adheres strictly to specs/02_TRACK_B_DATA_AND_STORAGE.md.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from schemas.instruction_packet import (
    InstructionPacket,
    get_physician_annotation,
)

DEFAULT_GOLD_LIBRARY_PATH = "data/gold_library/versioned_instructions.jsonl"


def save_to_gold_library(
    packet: InstructionPacket,
    file_path: Optional[str] = None,
) -> None:
    """
    Serializes InstructionPacket to JSON and appends as a single line with UTC timestamp.
    Ensures immutability and audit logging for physician review decisions.
    """
    target_path = file_path or DEFAULT_GOLD_LIBRARY_PATH
    parent_dir = os.path.dirname(target_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    # Ensure physician decision and review timestamp are populated
    if not packet.physician_decision:
        packet.physician_decision = get_physician_annotation(packet)
    if not packet.reviewed_at:
        packet.reviewed_at = datetime.now(timezone.utc).isoformat()

    json_record = packet.model_dump_json()
    with open(target_path, "a", encoding="utf-8") as f:
        f.write(json_record + "\n")


# Alias for compatibility with app/clinician_ui.py
save_gold_record = save_to_gold_library


def load_gold_records(
    file_path: Optional[str] = None,
) -> List[InstructionPacket]:
    """
    Reads JSONL records from the versioned library and returns parsed InstructionPacket objects.
    Returns empty list if the file does not exist or contains no records.
    """
    target_path = file_path or DEFAULT_GOLD_LIBRARY_PATH
    if not os.path.exists(target_path):
        return []

    records: List[InstructionPacket] = []
    with open(target_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                packet = InstructionPacket.model_validate_json(line_str)
                records.append(packet)
            except Exception as e:
                # Corrupt line handling without crashing the entire viewer
                continue

    return records
