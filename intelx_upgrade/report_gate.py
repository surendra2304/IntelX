from __future__ import annotations
from dataclasses import dataclass
import re

@dataclass(frozen=True,slots=True)
class ReportGate:
    complete:bool
    unsupported:list[str]
    unresolved:list[str]
    citations:int

class FinalReportGate:
    CIT=re.compile(r"\[(?:S|C):([A-Za-z0-9_-]+)\]")

    def check(self,report:str,claim_support:dict[str,bool],unresolved:list[str])->ReportGate:
        tokens=self.CIT.findall(report)
        unsupported=[]
        for cid,supported in claim_support.items():
            if not supported and cid in report:
                unsupported.append(cid)
        bad=sorted(set(x for x in tokens if x not in claim_support))
        unsupported.extend(bad)
        return ReportGate(not unsupported and not unresolved,unsupported,list(unresolved),len(tokens))

    def bounded_repair(self,report:str,valid_ids:set[str])->str:
        return self.CIT.sub(lambda m:m.group(0) if m.group(1) in valid_ids else "",report)
