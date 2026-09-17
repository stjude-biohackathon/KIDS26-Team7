"""Track B Storage package: In-memory data loaders and versioned library persistence."""

from .gold_library import save_to_gold_library, save_gold_record, load_gold_records
from .github_loader import load_mock_templates_and_orders, fetch_remote_templates_and_orders

__all__ = [
    "save_to_gold_library",
    "save_gold_record",
    "load_gold_records",
    "load_mock_templates_and_orders",
    "fetch_remote_templates_and_orders",
]
