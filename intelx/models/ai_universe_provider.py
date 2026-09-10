"""AI-Universe Multi-Agent Intelligence Provider Adapter for INTELX."""

import json
import logging
import time
import uuid
from typing import Any

import httpx
from pydantic import BaseModel

from intelx.core.errors import ProviderError
from intelx.core.settings import get_settings
from intelx.models.providers import BaseLLMProvider, compute_model_pricing
from intelx.models.types import Usage

logger = logging.getLogger(__name__)


# Role mapping to AI-Universe multi-agent personas
AI_UNIVERSE_ROLE_MAP: dict[str, str] = {
    "planner": "Strategist",
    "extractor": "Coder",
    "verifier": "Fact Checker + Critic",
    "analyst": "Data Analyst",
    "critic": "Critic",
    "synthesizer": "Synthesizer",
}


class AIUniverseProvider(BaseLLMProvider):
    """Adapter routing INTELX agent intelligence requests through AI-Universe multi-agent framework."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (
            base_url or settings.AI_UNIVERSE_BASE_URL or "http://localhost:9000"
        ).rstrip("/")
        self.api_key = api_key or settings.AI_UNIVERSE_API_KEY
        self.timeout_seconds = timeout_seconds
        self.last_metadata: dict[str, Any] = {}

    def _map_persona(self, role: str) -> str:
        """Map INTELX agent role to AI-Universe persona."""
        return AI_UNIVERSE_ROLE_MAP.get(role.lower().strip(), "Strategist")

    def _extract_context(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Extract structured context from message chain."""
        full_content = "\n\n".join(m.get("content", "") for m in messages)

        # Extract basic elements if detectable
        lines = full_content.splitlines()
        question = lines[0] if lines else "Intelligence request"
        for line in lines:
            if "OBJECTIVE:" in line or "RESEARCH QUESTION:" in line:
                question = line.split(":", 1)[-1].strip()
                break

        return {
            "question": question,
            "raw_prompt_length": len(full_content),
            "message_count": len(messages),
        }

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
        """Submit intelligence task to AI-Universe multi-agent debate endpoint."""
        persona = self._map_persona(role)
        req_id = f"intelx-{uuid.uuid4().hex[:12]}"
        endpoint = f"{self.base_url}/v1/intelx/research"

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "INTELX-Engine/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key

        payload = {
            "request_id": req_id,
            "role": role.lower().strip(),
            "ai_universe_persona": persona,
            "model": model,
            "context": self._extract_context(messages),
            "messages": messages,
            "constraints": {
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        }

        if schema_model is not None:
            payload["schema_name"] = schema_model.__name__
            payload["schema_json"] = schema_model.model_json_schema()

        t0 = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)

                # Fallback to non-versioned endpoint if 404
                if resp.status_code == 404:
                    alt_endpoint = f"{self.base_url}/intelx/research"
                    resp = await client.post(alt_endpoint, json=payload, headers=headers)

                if resp.status_code == 401 or resp.status_code == 403:
                    raise ProviderError(
                        f"AI-Universe authentication failure (HTTP {resp.status_code}): {resp.text}"
                    )
                elif resp.status_code >= 400:
                    raise ProviderError(
                        f"AI-Universe returned error (HTTP {resp.status_code}): {resp.text}"
                    )

                data = resp.json()
        except httpx.RequestError as e:
            logger.warning(f"AI-Universe network connection failed: {e}")
            raise ProviderError(f"AI-Universe connection error: {e}") from e
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise ProviderError(f"AI-Universe unexpected error: {e}") from e

        latency = time.time() - t0

        # Parse response payload
        raw_response = data.get("response", "")
        if isinstance(raw_response, (dict, list)):
            text_output = json.dumps(raw_response)
        else:
            text_output = str(raw_response)

        # Anti-Mock Guardrail: Detect static canned templates from un-updated backends
        canned_markers = (
            "Comprehensive Research Assessment on:",
            "Key Finding: Strong convergence across 0 extracted verbatim spans",
            "Synthesized findings for '",
            "Patterns indicate high consistency across peer-reviewed",
        )
        is_canned = any(marker in text_output for marker in canned_markers)
        if is_canned:
            logger.info(
                f"[AI-Universe] Detected canned mock response for role=[{role}]. "
                "Executing live reasoning /ask bypass for genuine intelligence synthesis..."
            )
            real_answer = await self._execute_ask_bypass(
                messages=messages,
                headers=headers,
                schema_model=schema_model,
            )
            if real_answer:
                text_output = real_answer
                logger.info(f"[AI-Universe] Live reasoning /ask bypass succeeded for role=[{role}]")

        # Unwrap markdown code blocks if present
        stripped = text_output.strip()
        if stripped.startswith("```"):
            import re
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
            if m:
                text_output = m.group(1).strip()

        confidence = data.get("confidence", 0.90)
        dissent = data.get("dissent")
        provenance = data.get("provenance", {})

        self.last_metadata = {
            "request_id": req_id,
            "role": role,
            "persona": persona,
            "confidence": confidence,
            "dissent": dissent,
            "provenance": provenance,
            "latency_seconds": round(latency, 3),
            "provider": "ai_universe",
        }

        # Calculate token accounting
        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        in_tokens = max(1, prompt_chars // 4)
        out_tokens = max(1, len(text_output) // 4)
        usd_cost = compute_model_pricing(model, in_tokens, out_tokens)

        logger.info(
            f"[AI-Universe] Dispatched role=[{role}] persona=[{persona}] "
            f"confidence=[{confidence}] latency=[{latency:.2f}s]"
        )

        return text_output, Usage(
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            usd_cost=usd_cost,
        )

    async def _execute_ask_bypass(
        self,
        messages: list[dict[str, str]],
        headers: dict[str, str],  # kept for API compat; ignored — we build dedicated ask headers below
        schema_model: type[BaseModel] | None = None,
    ) -> str | None:
        """Query Inference live multi-model LLM reasoning endpoint to produce genuine intelligence."""
        import re

        settings = get_settings()
        # Build dedicated headers for the /ask endpoint — Inference requires X-API-Key
        inference_key = settings.INFERENCE_API_KEY or "inference_api"
        ask_headers = {
            "Content-Type": "application/json",
            "User-Agent": "INTELX-Engine/1.0",
            "X-API-Key": inference_key,
        }

        prompt_parts = []
        for m in messages:
            r = m.get("role", "user").upper()
            c = m.get("content", "")
            prompt_parts.append(f"[{r}]:\n{c}")

        full_prompt = "\n\n".join(prompt_parts)
        if schema_model is not None:
            full_prompt += (
                f"\n\nMANDATORY: Respond ONLY with a valid JSON object strictly matching this schema:\n"
                f"{json.dumps(schema_model.model_json_schema(), indent=2)}\n"
                f"Do NOT include markdown formatting or extra text outside the JSON object."
            )

        ask_payload = {
            "question": full_prompt,
            "mode": "fast",
            "require_evidence": False,
        }

        ask_url = f"{self.base_url}/ask"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                logger.info(f"[AI-Universe] Calling /ask bypass at {ask_url} with key={inference_key[:8]}...")
                resp = await client.post(ask_url, json=ask_payload, headers=ask_headers)
                if resp.status_code == 404:
                    alt = f"{self.base_url}/v1/ask"
                    logger.info(f"[AI-Universe] /ask 404 — trying fallback {alt}")
                    resp = await client.post(alt, json=ask_payload, headers=ask_headers)

                if resp.status_code == 200:
                    data = resp.json()
                    answer = str(data.get("answer") or "").strip()
                    if answer.startswith("```"):
                        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", answer)
                        if m:
                            answer = m.group(1).strip()
                    logger.info(f"[AI-Universe] /ask bypass answered ({len(answer)} chars)")
                    return answer
                else:
                    logger.warning(
                        f"[AI-Universe] Inference /ask returned HTTP {resp.status_code}: {resp.text[:300]}"
                    )
        except Exception as e:
            logger.warning(f"[AI-Universe] Failed live reasoning /ask bypass: {e}", exc_info=True)
        return None
