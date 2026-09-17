"""Model aliases from the detailed Track A/C specs; live routing is Phase 2.

Importing this module never reads secrets or creates an external client.
Provider deployment names and credentials must be resolved in Phase 2.
"""

AVAILABLE_MODELS: tuple[str, ...] = (
    "gpt52",
    "gpt4o",
    "gpt56luna",
    "kimik3",
    "copus5",
    "local1",
    "local2",
)
