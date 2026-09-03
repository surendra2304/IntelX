from __future__ import annotations
from dataclasses import is_dataclass,asdict
import json

def to_jsonable(value):
    if is_dataclass(value): return {k:to_jsonable(v) for k,v in asdict(value).items()}
    if isinstance(value,dict): return {str(k):to_jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,set,frozenset)): return [to_jsonable(v) for v in value]
    if hasattr(value,"value") and not isinstance(value,(str,int,float,bool)): return value.value
    return value

def dumps(value)->str:
    return json.dumps(to_jsonable(value),sort_keys=True,default=str)
