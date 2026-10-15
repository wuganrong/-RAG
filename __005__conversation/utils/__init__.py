"""Conversation domain helpers."""

from __future__ import annotations

# 3. 本地应用
from __005__conversation.utils.service import chunks_format, conversation_to_dict
from __005__conversation.utils.step_tracker import StepDef, StepTracker
from __005__conversation.utils.stream_completion import (
    completion_stream_generator,
    completion_with_all_stream_generator,
    completion_with_model_stream_generator,
)

__all__ = [
    "StepDef",
    "StepTracker",
    "chunks_format",
    "completion_stream_generator",
    "completion_with_all_stream_generator",
    "completion_with_model_stream_generator",
    "conversation_to_dict",
]
