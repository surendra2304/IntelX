"""INTELX Central Model Gateway for Role-Based Routing, Structured Output, and Cost Accounting."""

import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from intelx.core.errors import StructuredOutputError
from intelx.core.settings import Settings, get_settings
from intelx.models.ai_universe_provider import AIUniverseProvider
from intelx.models.providers import (
    AnthropicProvider,
    BaseLLMProvider,
    MockProvider,
    OpenAICompatibleProvider,
)
from intelx.models.types import ModelResult, Usage

logger = logging.getLogger(__name__)


class ModelGateway:
    """Central gateway routing all agent LLM requests with schema validation, AI-Universe support, and fallback."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._mock_provider = MockProvider()
        self._openai_provider: OpenAICompatibleProvider | None = None
        self._anthropic_provider: AnthropicProvider | None = None
        self._ai_universe_provider: AIUniverseProvider | None = None
        self._run_usage: dict[str, Usage] = {}

    def get_usage(self, run_id: str | None) -> Usage:
        """Retrieve aggregated token and cost usage for a run."""
        if not run_id:
            return Usage(input_tokens=0, output_tokens=0, usd_cost=0.0)
        return self._run_usage.get(run_id, Usage(input_tokens=0, output_tokens=0, usd_cost=0.0))

    def _get_provider(self) -> tuple[str, BaseLLMProvider]:
        """Resolve active LLM provider backend based on settings."""
        if self.settings.MOCK_MODE:
            return "mock", self._mock_provider

        provider_name = (self.settings.LLM_PROVIDER or "mock").lower()
        if provider_name in ("inference", "ai_universe", "aiuniverse"):
            if self._ai_universe_provider is None:
                self._ai_universe_provider = AIUniverseProvider()
            return "inference", self._ai_universe_provider
        elif provider_name in (
            "openai_compatible",
            "openai",
            "groq",
            "vllm",
            "ollama",
            "openrouter",
        ):
            if self._openai_provider is None:
                self._openai_provider = OpenAICompatibleProvider()
            return provider_name, self._openai_provider
        elif provider_name == "anthropic":
            if self._anthropic_provider is None:
                self._anthropic_provider = AnthropicProvider()
            return "anthropic", self._anthropic_provider

        return "mock", self._mock_provider

    async def _execute_with_fallback(
        self,
        messages: list[dict[str, str]],
        *,
        model_name: str,
        role: str,
        schema_model: type[BaseModel] | None,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, Usage, str]:
        """Attempt primary provider with automated fallback chain: AI-Universe -> OpenAI/Anthropic -> Mock."""
        primary_name, primary_provider = self._get_provider()

        # Attempt 1: Primary provider
        try:
            text_out, usage = await primary_provider.complete(
                messages=messages,
                model=model_name,
                role=role,
                schema_model=schema_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return text_out, usage, primary_name
        except Exception as e:
            logger.warning(
                f"Primary provider [{primary_name}] failed for role [{role}]: {e}. "
                "Executing fallback chain..."
            )

        # Attempt 2: Secondary direct LLM provider (if primary was AI-Universe and LLM keys exist)
        if primary_name == "ai_universe":
            if self.settings.LLM_API_KEY:
                try:
                    if self._openai_provider is None:
                        self._openai_provider = OpenAICompatibleProvider()
                    logger.info(
                        "Falling back from AI-Universe to secondary OpenAI-Compatible provider"
                    )
                    text_out, usage = await self._openai_provider.complete(
                        messages=messages,
                        model=model_name,
                        role=role,
                        schema_model=schema_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    return text_out, usage, "openai_compatible"
                except Exception as e2:
                    logger.warning(f"Secondary LLM provider fallback failed: {e2}")

        # Attempt 3: Tertiary Mock provider fallback
        logger.info(f"Falling back to Mock provider for role [{role}]")
        text_out, usage = await self._mock_provider.complete(
            messages=messages,
            model="mock-gpt-4o",
            role=role,
            schema_model=schema_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return text_out, usage, "mock"

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        role: str,
        schema_model: type[BaseModel] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        run_id: str | None = None,
    ) -> ModelResult:
        """Execute role-routed LLM completion with fallback chain, schema validation, and retry."""
        model_name = self.settings.get_model_for_role(role)
        log_suffix = f" (run={run_id})" if run_id else ""
        logger.info(f"LLM request role=[{role}] model=[{model_name}]{log_suffix}")

        # 1. Completion attempt with fallback chain
        text_output, usage, active_provider = await self._execute_with_fallback(
            messages=messages,
            model_name=model_name,
            role=role,
            schema_model=schema_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        parsed_instance: Any | None = None

        if schema_model is not None:
            parsed_instance, validation_err = self._try_parse_schema(text_output, schema_model)
            if parsed_instance is None:
                # 2. Structured Output Self-Correction: Retry ONCE with error feedback
                logger.warning(
                    f"Schema validation failed for {schema_model.__name__}: {validation_err}. "
                    "Initiating retry..."
                )
                correction_prompt = (
                    f"Your previous response failed validation for {schema_model.__name__}:\n"
                    f"Errors: {validation_err}\n"
                    "Please respond with valid JSON strictly matching the schema definition."
                )
                correction_messages = list(messages) + [
                    {"role": "assistant", "content": text_output},
                    {"role": "user", "content": correction_prompt},
                ]

                retry_text, retry_usage, retry_provider = await self._execute_with_fallback(
                    messages=correction_messages,
                    model_name=model_name,
                    role=role,
                    schema_model=schema_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                active_provider = retry_provider

                # Accumulate usage from retry
                usage = Usage(
                    input_tokens=usage.input_tokens + retry_usage.input_tokens,
                    output_tokens=usage.output_tokens + retry_usage.output_tokens,
                    usd_cost=round(usage.usd_cost + retry_usage.usd_cost, 6),
                )
                text_output = retry_text

                parsed_instance, retry_err = self._try_parse_schema(retry_text, schema_model)
                if parsed_instance is None:
                    err_msg = (
                        f"Model output failed schema validation for {schema_model.__name__} "
                        f"after retry: {retry_err}"
                    )
                    raise StructuredOutputError(
                        err_msg,
                        details={
                            "role": role,
                            "model": model_name,
                            "provider": active_provider,
                            "raw_text": retry_text,
                            "error": str(retry_err),
                        },
                    )

        if run_id:
            cur = self._run_usage.get(run_id, Usage(input_tokens=0, output_tokens=0, usd_cost=0.0))
            self._run_usage[run_id] = Usage(
                input_tokens=cur.input_tokens + usage.input_tokens,
                output_tokens=cur.output_tokens + usage.output_tokens,
                usd_cost=round(cur.usd_cost + usage.usd_cost, 6),
            )

        return ModelResult(
            text=text_output,
            parsed=parsed_instance,
            usage=usage,
            provider=active_provider,
            model=model_name,
        )

    @staticmethod
    def _try_parse_schema(
        raw_text: str, schema_model: type[BaseModel]
    ) -> tuple[BaseModel | None, str | None]:
        """Attempt to extract JSON and validate against target Pydantic schema."""
        cleaned_text = raw_text.strip()
        # Strip markdown code fences if wrapped in ```json ... ```
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[len("```json") :].strip()
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[len("```") :].strip()
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3].strip()

        try:
            # First try parsing as JSON dict
            data = json.loads(cleaned_text)
            validated = schema_model.model_validate(data)
            return validated, None
        except (json.JSONDecodeError, ValidationError) as e:
            return None, str(e)
        except Exception as e:
            return None, str(e)


_global_gateway: ModelGateway | None = None


def get_model_gateway() -> ModelGateway:
    """Singleton accessor for central ModelGateway instance."""
    global _global_gateway
    if _global_gateway is None:
        _global_gateway = ModelGateway()
    return _global_gateway
