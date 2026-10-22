"""Types and dataclasses for the INTELX model gateway."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Usage:
    """Token consumption and financial cost metrics."""

    input_tokens: int = 0
    output_tokens: int = 0
    usd_cost: float = 0.0


@dataclass
class ModelResult:
    """Unified completion result from model gateway."""

    text: str
    parsed: Any | None
    usage: Usage
    provider: str
    model: str
    metadata: dict[str, Any] = field(default_factory=dict)
