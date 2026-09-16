"""The coordinator for Track A's future instruction-processing pipeline.

At this stage, it only stores valid model choices. Generation and edit checking
are placeholders whose inputs and outputs still need team agreement at Sync 0.
"""

# Keep type hints as text instead of looking up their classes immediately.
# This lets us describe the planned inputs/outputs before Track B adds its schemas.
from __future__ import annotations

from typing import TYPE_CHECKING

from pipeline.llms import AVAILABLE_MODELS

# TYPE_CHECKING is false when the program runs. Editors/type-checking tools can
# use these names, but importing this file will not try to load the missing schemas.
if TYPE_CHECKING:
    from schemas.instruction_packet import ClinicalOrders, InstructionPacket


class PipelineOrchestrator:
    """Track A entrypoint; no clinical processing is implemented in Phase 0."""

    # Python calls __init__ when someone creates PipelineOrchestrator().
    # The * means callers must name these options, e.g. llm1_model="gpt4o".
    # If they omit the options, the defaults below are used.
    def __init__(
        self, *, llm1_model: str = "gpt52", llm2_model: str = "gpt4o"
    ) -> None:
        """Store role selections without reading credentials or creating clients."""
        # Reject choices outside the menu in llms.py before storing them.
        # Error messages name the invalid role without echoing the supplied value.
        if llm1_model not in AVAILABLE_MODELS:
            raise ValueError("Unsupported llm1_model; select an AVAILABLE_MODELS alias.")
        if llm2_model not in AVAILABLE_MODELS:
            raise ValueError("Unsupported llm2_model; select an AVAILABLE_MODELS alias.")

        # self refers to this particular orchestrator. These attributes remember
        # its choices; storing a model name does not connect to or call that model.
        self.llm1_model = llm1_model
        self.llm2_model = llm2_model

    def generate(
        self,
        composite_template_text: str,
        orders: ClinicalOrders,
        *,
        module_version: str,
    ) -> InstructionPacket:
        """Eventually prepare a new instruction packet for clinician review.

        composite_template_text: The source instruction text supplied by the caller.
        orders: The structured visit details defined by Track B's ClinicalOrders.
        module_version: Which version of the source module is being used; the
            caller must supply this by name, e.g. module_version="v1.0.0".

        The return hint, InstructionPacket, describes the future result containing
        inputs, outputs, and checks. Type hints describe the intended contract;
        they do not validate the inputs or create a packet automatically.
        """
        # This method is a stub: a reserved place for later implementation.
        # Stop explicitly so callers cannot mistake unfinished work for a usable
        # handout. No text is processed and no model is called here.
        raise NotImplementedError(
            "Generation is unavailable: agree the shared contract at Sync Point 0 "
            "before implementing the Phase 1 mock pipeline."
        )

    def recheck_edits(
        self, packet: InstructionPacket, edited_en: str
    ) -> InstructionPacket:
        """Eventually check a clinician's edits and return a new pending revision.

        packet: The existing instruction packet being reviewed.
        edited_en: The English text after the clinician's changes.

        The future implementation must rerun the relevant checks without changing
        the original packet. Checking an edit must not approve it for publication.
        """
        # Rechecking is also unfinished. An explicit error prevents the caller
        # from assuming that the edited text has already passed the safety checks.
        raise NotImplementedError(
            "Edit rechecking is unavailable: agree the shared contract at "
            "Sync Point 0 before implementing edit evaluation."
        )
