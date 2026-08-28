"""INTELX LLM Provider Implementations (Mock, OpenAI-compatible, Anthropic)."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from intelx.core.errors import ProviderError
from intelx.core.settings import get_settings
from intelx.models.types import Usage

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract interface for LLM provider backends."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        role: str,
        schema_model: type[BaseModel] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> tuple[str, Usage]:
        """Execute completion and return raw text output and token usage."""
        pass


class MockProvider(BaseLLMProvider):
    """Deterministic, offline mock provider for zero-API-key development and CI."""

    MOCK_COST_PER_TOKEN = 0.000001

    @classmethod
    def _generate_canned_role_data(cls, role: str) -> dict[str, Any]:
        """Generate role-specific canned data matching typical agent schemas."""
        normalized_role = role.strip().lower()

        if normalized_role == "planner":
            return {
                "objective": "Deconstruct research query into structured sub-investigations",
                "subquestions": [
                    "What are the foundational technological principles?",
                    "What are the current commercial applications and market bottlenecks?",
                    "What empirical evidence exists regarding future scalability?",
                ],
                "stages": ["DISCOVERY", "EXTRACTION", "SYNTHESIS"],
                "source_strategy": {
                    "connector_kinds": ["web_search", "file_ingest"],
                    "domain_hints": ["nature.com", "arxiv.org"],
                    "time_range": "past_2_years",
                    "expected_source_count": 5,
                },
                "completion_criteria": {
                    "min_sources_per_subquestion": 2,
                    "min_independent_corroborations": 2,
                },
                "budget_allocation": {
                    "scout_pct": 0.15,
                    "retrieve_pct": 0.20,
                    "extract_pct": 0.25,
                    "verify_pct": 0.20,
                    "analyze_pct": 0.10,
                    "synthesize_pct": 0.10,
                },
            }
        elif normalized_role == "scout":
            return {
                "candidates": [
                    {
                        "location": "https://nature.com/articles/s41586-quantum-breakthrough",
                        "title": "Quantum Error Correction Demonstrations",
                        "reason": "Primary peer-reviewed empirical evidence",
                        "expected_relevance": 0.95,
                    },
                    {
                        "location": "https://arxiv.org/abs/2608.12345",
                        "title": "Scalable Surface Code Topologies",
                        "reason": "Technical theoretical bounds",
                        "expected_relevance": 0.90,
                    },
                ]
            }
        elif normalized_role == "extractor":
            return {
                "claims": [
                    {
                        "text": "Initial research indicates measurable efficiency improvements.",
                        "subject": "System Efficiency",
                        "predicate": "improves",
                        "object": "Baseline Performance",
                        "claim_type": "FACT",
                        "entities": ["System Efficiency", "Baseline Performance"],
                        "quote": "measurable efficiency improvements",
                        "relative_span": {"start": 0, "end": 35},
                        "preliminary_confidence": 0.95,
                        "rationale": "Direct assertion in source text",
                    },
                ],
                "entities": [
                    {"name": "System Efficiency", "type": "TECH", "aliases": ["Efficiency"]},
                ],
                "events": [],
            }
        elif normalized_role == "verifier":
            return {
                "verdict": "VERIFIED",
                "confidence": 0.92,
                "reasoning": "Direct citation and primary data confirm the stated proposition.",
                "contradictions": [],
            }
        elif normalized_role == "analyst":
            return {
                "key_themes": ["Scalability", "Cost Efficiency", "Supply Chain Constraints"],
                "gaps": ["Independent third-party benchmark data is limited."],
                "confidence_score": 0.88,
            }
        elif normalized_role == "critic":
            return {
                "approved": True,
                "critique": "Analysis is well-supported by primary evidence.",
                "suggested_improvements": [],
            }
        elif normalized_role == "synthesizer":
            return {
                "executive_summary": "Comprehensive evidence supports positive trajectory.",
                "primary_findings": [
                    "High confidence in core architectural scalability.",
                    "Supply chain dependencies remain a key execution risk.",
                ],
                "confidence_assessment": "HIGH",
            }

        return {"status": "success", "role": role, "result": "Deterministic mock output"}

    @classmethod
    def _generate_dummy_for_type(cls, annotation: Any, name: str) -> Any:
        """Recursively construct dummy values matching field annotations."""
        if annotation is None:
            return f"mock_{name}"

        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin is list:
            elem_type = args[0] if args else str
            return [cls._generate_dummy_for_type(elem_type, name)]
        elif origin is dict:
            return {"key": "value"}
        elif origin is set:
            return {f"mock_{name}"}
        elif annotation is str or (isinstance(annotation, type) and issubclass(annotation, str)):
            return f"mock_{name}"
        elif annotation is int or (isinstance(annotation, type) and issubclass(annotation, int)):
            return 1
        elif annotation is float or (
            isinstance(annotation, type) and issubclass(annotation, float)
        ):
            return 0.95
        elif annotation is bool or (isinstance(annotation, type) and issubclass(annotation, bool)):
            return True
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return cls._create_mock_instance(annotation, "sub_model")

        return f"mock_{name}"

    @classmethod
    def _create_mock_instance(cls, schema_model: type[BaseModel], role: str) -> BaseModel:
        """Create a valid Pydantic model instance from canned role data or field defaults."""
        canned = cls._generate_canned_role_data(role)
        try:
            return schema_model.model_validate(canned)
        except Exception:
            # Fall back to inspecting fields and constructing dummy values
            dummy_data: dict[str, Any] = {}
            for name, field in schema_model.model_fields.items():
                if field.default is not PydanticUndefined:
                    dummy_data[name] = field.default
                elif field.default_factory is not None:
                    dummy_data[name] = field.default_factory()
                else:
                    dummy_data[name] = cls._generate_dummy_for_type(field.annotation, name)

            return schema_model.model_validate(dummy_data)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        role: str,
        schema_model: type[BaseModel] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> tuple[str, Usage]:
        """Generate deterministic mock output and fake token usage."""
        msg_len = sum(len(m.get("content", "")) for m in messages)
        input_tokens = max(50, msg_len // 4)

        if schema_model is not None:
            instance = self._create_mock_instance(schema_model, role)
            text_output = instance.model_dump_json(indent=2)
        else:
            canned_dict = self._generate_canned_role_data(role)
            text_output = f"Mock research synthesis for role [{role}]: {json.dumps(canned_dict)}"

        output_tokens = max(20, len(text_output) // 4)
        usd_cost = (input_tokens + output_tokens) * self.MOCK_COST_PER_TOKEN

        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usd_cost=round(usd_cost, 6),
        )
        return text_output, usage


class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI and OpenAI-compatible gateway adapter (Groq, vLLM, Ollama, OpenRouter)."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.settings = get_settings()
        self.base_url = base_url or self.settings.LLM_BASE_URL
        self.api_key = api_key or self.settings.LLM_API_KEY or "dummy-key"
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import openai

                self._client = openai.AsyncOpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                )
            except ImportError as exc:
                err_msg = (
                    "openai package is required for OpenAICompatibleProvider. "
                    "Install via 'pip install openai'."
                )
                raise ProviderError(err_msg) from exc
        return self._client

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        role: str,
        schema_model: type[BaseModel] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> tuple[str, Usage]:
        """Execute OpenAI-compatible chat completion with exponential retry backoff."""
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if schema_model is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_model.__name__,
                    "schema": schema_model.model_json_schema(),
                },
            }

        max_attempts = 3
        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.chat.completions.create(**kwargs)
                text_output = response.choices[0].message.content or ""
                raw_usage = getattr(response, "usage", None)

                input_tokens = getattr(raw_usage, "prompt_tokens", 0) if raw_usage else 0
                output_tokens = getattr(raw_usage, "completion_tokens", 0) if raw_usage else 0
                usd_cost = (input_tokens * 0.000005) + (output_tokens * 0.000015)

                usage = Usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    usd_cost=round(usd_cost, 6),
                )
                return text_output, usage
            except Exception as e:
                last_exception = e
                if attempt < max_attempts:
                    sleep_time = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        f"OpenAI attempt {attempt}/{max_attempts} failed: {e}. Retrying..."
                    )
                    await asyncio.sleep(sleep_time)

        raise ProviderError(
            f"OpenAICompatibleProvider failed after {max_attempts} attempts: {last_exception}",
            details={"model": model, "error": str(last_exception)},
        )


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude API adapter with tool-forced structured outputs."""

    def __init__(self, api_key: str | None = None) -> None:
        self.settings = get_settings()
        self.api_key = api_key or self.settings.LLM_API_KEY
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic

                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except ImportError as exc:
                err_msg = (
                    "anthropic package is required for AnthropicProvider. "
                    "Install via 'pip install anthropic'."
                )
                raise ProviderError(err_msg) from exc
        return self._client

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        role: str,
        schema_model: type[BaseModel] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> tuple[str, Usage]:
        """Execute Anthropic completion with tool-forced structured JSON."""
        client = self._get_client()

        system_prompt = ""
        user_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_prompt += m.get("content", "") + "\n"
            else:
                user_messages.append(m)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt.strip():
            kwargs["system"] = system_prompt.strip()

        if schema_model is not None:
            tool_name = schema_model.__name__
            kwargs["tools"] = [
                {
                    "name": tool_name,
                    "description": f"Output schema for {tool_name}",
                    "input_schema": schema_model.model_json_schema(),
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

        max_attempts = 3
        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.messages.create(**kwargs)
                text_output = ""
                if schema_model is not None:
                    for block in response.content:
                        if getattr(block, "type", "") == "tool_use":
                            text_output = json.dumps(block.input, indent=2)
                            break
                if not text_output:
                    for block in response.content:
                        if getattr(block, "type", "") == "text":
                            text_output += block.text

                raw_usage = getattr(response, "usage", None)
                input_tokens = getattr(raw_usage, "input_tokens", 0) if raw_usage else 0
                output_tokens = getattr(raw_usage, "output_tokens", 0) if raw_usage else 0
                usd_cost = (input_tokens * 0.000003) + (output_tokens * 0.000015)

                usage = Usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    usd_cost=round(usd_cost, 6),
                )
                return text_output, usage
            except Exception as e:
                last_exception = e
                if attempt < max_attempts:
                    sleep_time = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        f"Anthropic attempt {attempt}/{max_attempts} failed: {e}. Retrying..."
                    )
                    await asyncio.sleep(sleep_time)

        raise ProviderError(
            f"AnthropicProvider failed after {max_attempts} attempts: {last_exception}",
            details={"model": model, "error": str(last_exception)},
        )
