from __future__ import annotations
from dataclasses import dataclass
from .models import Source, Claim

@dataclass(frozen=True,slots=True)
class Delta:
    kind:str
    identifier:str
    before:str|None
    after:str|None

class DeltaResearch:
    def compare_sources(self,old:list[Source],new:list[Source])->list[Delta]:
        om={s.canonical_url or s.url:s for s in old}; nm={s.canonical_url or s.url:s for s in new}
        out=[]
        for u in sorted(nm.keys()-om.keys()): out.append(Delta("source_added",u,None,nm[u].content_hash))
        for u in sorted(om.keys()-nm.keys()): out.append(Delta("source_removed",u,om[u].content_hash,None))
        for u in sorted(nm.keys()&om.keys()):
            if nm[u].content_hash!=om[u].content_hash:
                out.append(Delta("source_changed",u,om[u].content_hash,nm[u].content_hash))
        return out

    def compare_claims(self,old:list[Claim],new:list[Claim])->list[Delta]:
        om={c.id:c for c in old}; nm={c.id:c for c in new}; out=[]
        for cid in sorted(nm.keys()-om.keys()): out.append(Delta("claim_added",cid,None,nm[cid].statement))
        for cid in sorted(om.keys()-nm.keys()): out.append(Delta("claim_removed",cid,om[cid].statement,None))
        for cid in sorted(nm.keys()&om.keys()):
            if nm[cid].statement!=om[cid].statement or nm[cid].disputed!=om[cid].disputed:
                out.append(Delta("claim_changed",cid,om[cid].statement,nm[cid].statement))
        return out
