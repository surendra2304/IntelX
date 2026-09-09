"""INTELX Analyst Agent: Synthesis, Timeline Generation, and Cross-Claim Graph Reasoning."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from intelx.agents.base import BaseAgent
from intelx.db.models import Claim
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class TimelineEntry(BaseModel):
    """Chronological event anchored to evidentiary claims."""

    date: str | None = None
    event: str
    claim_ids: list[str] = Field(default_factory=list)


class EntityRelationItem(BaseModel):
    """Semantic subject-predicate-object link grounded in claim evidence."""

    subject: str
    predicate: str
    object: str
    claim_id: str | None = None


class ThemeItem(BaseModel):
    """High-level analytical theme grouping related evidence claims."""

    label: str
    claim_ids: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Synthesized analytical structure emitted by AnalystAgent."""

    timeline: list[TimelineEntry] = Field(default_factory=list)
    entity_relations: list[EntityRelationItem] = Field(default_factory=list)
    themes: list[ThemeItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    @classmethod
    def _validate_raw(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "entity_relations" not in data or not data["entity_relations"]:
                data["entity_relations"] = data.get("relationships") or data.get("relations") or []
            if "themes" not in data or not data["themes"]:
                data["themes"] = data.get("key_themes") or data.get("topics") or []
            if "timeline" not in data:
                data["timeline"] = data.get("events") or data.get("chronology") or []
            if "gaps" not in data:
                data["gaps"] = data.get("knowledge_gaps") or data.get("limitations") or []
        return data

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "AnalysisResult":
        obj = cls._validate_raw(obj)
        return super().model_validate(obj, *args, **kwargs)


class AnalystAgent(BaseAgent):
    """Agent performing pure deductive reasoning and relational synthesis over verified claims."""

    SYSTEM_PROMPT = (
        "You are the INTELX Senior Intelligence Analyst.\n"
        "Your task is to structure verified evidence claims into coherent timelines, "
        "relational graphs, overarching themes, and identified knowledge gaps.\n\n"
        "STRICT ANALYTICAL CONSTRAINT:\n"
        "Perform pure reasoning ONLY over the supplied claims.\n"
        "You are FORBIDDEN from introducing external facts, speculative leaps, or assumptions "
        "not explicitly supported by the provided evidence."
    )

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        super().__init__(role="analyst", name="AnalystAgent", gateway=gateway)

    async def execute(
        self,
        claims: list[Claim | dict[str, Any]],
        entities: list[Any] | None = None,
        events: list[Any] | None = None,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> AnalysisResult:
        """Synthesize evidentiary claims into structured analytical models."""
        formatted_claims = []
        for c in claims:
            if isinstance(c, dict):
                formatted_claims.append(
                    {"id": c.get("id"), "text": c.get("text"), "confidence": c.get("confidence")}
                )
            else:
                formatted_claims.append({"id": c.id, "text": c.text, "confidence": c.confidence})

        user_prompt = (
            f"EVIDENTIARY CLAIMS CORPUS ({len(formatted_claims)} claims):\n"
            f"{json.dumps(formatted_claims, indent=2)}\n\n"
            "Synthesize the supplied claims into timelines, entity relations, themes, "
            "and identify critical intelligence gaps."
        )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        result = await self.gateway.complete(
            messages=messages,
            role=self.role,
            schema_model=AnalysisResult,
            run_id=run_id,
        )

        return result.parsed
