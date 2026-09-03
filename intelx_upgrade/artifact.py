from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib,json,time

@dataclass(frozen=True,slots=True)
class Artifact:
    artifact_id:str
    path:str
    sha256:str
    size:int
    created_at:float

class ArtifactStore:
    def __init__(self,root:str):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
    def put(self,artifact_id:str,data:bytes,extension:str=".bin")->Artifact:
        safe="".join(c for c in artifact_id if c.isalnum() or c in "-_")
        p=(self.root/(safe+extension)).resolve()
        if p.parent!=self.root.resolve(): raise ValueError("artifact path escape")
        p.write_bytes(data)
        return Artifact(artifact_id,str(p),hashlib.sha256(data).hexdigest(),len(data),time.time())
    def manifest(self,items:list[Artifact])->str:
        return json.dumps([{"artifact_id":a.artifact_id,"path":a.path,"sha256":a.sha256,"size":a.size,"created_at":a.created_at} for a in items],sort_keys=True)
