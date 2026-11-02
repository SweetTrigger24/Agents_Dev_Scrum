from typing import Any
from pydantic import BaseModel, Field


class EchoOutput(BaseModel):
    """Schema đầu ra riêng của action mẫu 'echo' phục vụ demo và kiểm thử."""

    received_instruction: str
    received_action: str
    received_context: dict[str, Any] = Field(default_factory=dict)
    reply: str
