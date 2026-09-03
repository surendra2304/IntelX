from __future__ import annotations
from dataclasses import dataclass
import re

@dataclass(frozen=True,slots=True)
class Conflict:
    left_claim:str
    right_claim:str
    reason:str
    severity:str
    shared_terms:tuple[str,...]=()

class ContradictionEngine:
    NEG={"not","never","false","no","without","failed","cannot","didn't","did","wasn't","isn't"}
    CONTRARY_WORDS={
        "reliable": {"unreliable","not reliable"},
        "safe": {"unsafe","not safe"},
        "possible": {"impossible","not possible"},
        "increases": {"decreases","drops","declines"},
        "increased": {"decreased","dropped","declined"},
        "supports": {"contradicts","refutes"},
        "works": {"fails","does not work"},
    }

    def tokens(self,text:str)->set[str]:
        return {x.lower() for x in re.findall(r"[A-Za-z0-9']{3,}",text)}

    def normalized(self,text:str)->str:
        return re.sub(r"\s+"," ",text.lower()).strip()

    def detect(self, claims)->list[Conflict]:
        out=[]
        for i,a in enumerate(claims):
            for b in claims[i+1:]:
                if a.plan_item_id!=b.plan_item_id: continue
                ta,tb=self.tokens(a.statement),self.tokens(b.statement)
                shared=tuple(sorted((ta&tb)-self.NEG))
                if len(shared)<1: continue
                aa=self.normalized(a.statement); bb=self.normalized(b.statement)
                opposite=False
                reason="opposing language"
                for positive, opposites in self.CONTRARY_WORDS.items():
                    if positive in aa and any(x in bb for x in opposites): opposite=True; reason=f"{positive} vs contrary assertion"
                    if positive in bb and any(x in aa for x in opposites): opposite=True; reason=f"{positive} vs contrary assertion"
                neg_a=any(re.search(r"\bnot\s+"+re.escape(x)+r"\b",aa) for x in shared)
                neg_b=any(re.search(r"\bnot\s+"+re.escape(x)+r"\b",bb) for x in shared)
                opposite = opposite or (neg_a != neg_b)
                if opposite:
                    out.append(Conflict(a.id,b.id,reason,"high",shared[:10]))
        return out
