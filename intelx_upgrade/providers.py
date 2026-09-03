from __future__ import annotations
from dataclasses import dataclass

class ProviderError(RuntimeError): pass

@dataclass(frozen=True, slots=True)
class ProviderHealth:
    name: str
    available: bool
    reason: str = ""

class ProviderRouter:
    def __init__(self, providers):
        self.providers=providers

    async def call(self, role, request):
        errors=[]
        for provider in self.providers:
            try:
                health=provider.health()
                if not health.available: continue
                return await provider.generate(role, request)
            except Exception as exc:
                errors.append(f"{provider.name}:{exc}")
        raise ProviderError("all providers failed safely: " + " | ".join(errors))
