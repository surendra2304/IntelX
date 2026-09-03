from __future__ import annotations
import json, re

SECRET_KEYS = re.compile(r"(?i)(api[_-]?key|token|password|secret|private[_-]?key)")

def redact(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if SECRET_KEYS.search(str(k)) else redact(v)) for k,v in value.items()}
    if isinstance(value, list): return [redact(v) for v in value]
    if isinstance(value, str):
        value=re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-~+/]+=*", "Bearer [REDACTED]", value)
        return value
    return value

def safe_json(value): return json.dumps(redact(value), sort_keys=True, default=str)
