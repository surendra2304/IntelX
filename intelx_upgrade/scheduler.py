from __future__ import annotations
import asyncio
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int=2
    base_delay: float=0.25
    retryable_errors: tuple[str,...]=("timeout","429","503")

def retryable(exc: Exception, policy: RetryPolicy)->bool:
    s=str(exc).lower()
    return any(x in s for x in policy.retryable_errors)

async def bounded_call(fn, policy=RetryPolicy()):
    for i in range(policy.attempts+1):
        try: return await fn()
        except asyncio.CancelledError: raise
        except Exception as exc:
            if i >= policy.attempts or not retryable(exc, policy): raise
            await asyncio.sleep(min(5.0, policy.base_delay*(2**i)))
