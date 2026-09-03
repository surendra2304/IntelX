from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True,slots=True)
class AuthorityRule:
    suffix:str
    score:float
    tier:str

class AuthorityRegistry:
    def __init__(self):
        self.rules=[
            AuthorityRule(".gov",1.0,"primary"),
            AuthorityRule(".edu",0.92,"primary"),
            AuthorityRule("who.int",0.98,"primary"),
            AuthorityRule("un.org",0.96,"primary"),
            AuthorityRule("reuters.com",0.88,"secondary"),
        ]

    def classify(self,host:str)->tuple[float,str]:
        h=host.lower().rstrip(".")
        for r in self.rules:
            if h==r.suffix or h.endswith(r.suffix):
                return r.score,r.tier
        return 0.55,"unknown"

    def is_primary(self,host:str)->bool:
        return self.classify(host)[1]=="primary"
