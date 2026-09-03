from __future__ import annotations
from dataclasses import dataclass
import re

@dataclass(frozen=True,slots=True)
class Query:
    text:str
    plan_item_id:str
    purpose:str
    priority:int
    source_angle:str

class QueryPortfolioPlanner:
    """Builds diverse queries instead of repeatedly issuing one generic search."""
    STOP={"what","are","the","and","for","with","from","that","this","about","does","into"}

    def keywords(self,question:str)->list[str]:
        words=[w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}",question)]
        return list(dict.fromkeys(w for w in words if w not in self.STOP))[:12]

    def build(self,plan_item_id:str,question:str)->list[Query]:
        k=self.keywords(question)
        base=" ".join(k)
        variants=[
            ("direct",base,80),
            ("primary",base+" official report study dataset",95),
            ("counterevidence",base+" criticism limitations contradictory evidence",90),
            ("recent",base+" 2026 latest update",75),
            ("historical",base+" history prior results",60),
            ("technical",base+" methodology measurements benchmark",85),
        ]
        return [Query(t,pid,purpose,priority,angle) for purpose,t,priority in variants
                for pid in [plan_item_id] for angle in [purpose]]

    def dedupe(self,queries:list[Query])->list[Query]:
        seen=set(); out=[]
        for q in sorted(queries,key=lambda x:x.priority,reverse=True):
            key=re.sub(r"\W+"," ",q.text.lower()).strip()
            if key not in seen:
                seen.add(key); out.append(q)
        return out
