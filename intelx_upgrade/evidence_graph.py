from __future__ import annotations
from dataclasses import dataclass, field

@dataclass(frozen=True,slots=True)
class Edge:
    left:str
    relation:str
    right:str

class ProvenanceGraph:
    """In-memory graph mirroring Finding -> Claim -> Evidence -> Document -> Source."""
    def __init__(self):
        self.nodes:dict[str,dict]={}
        self.edges:list[Edge]=[]

    def add_node(self,node_id:str,node_type:str,**attrs):
        if node_id in self.nodes:
            raise ValueError(f"duplicate node {node_id}")
        self.nodes[node_id]={"type":node_type,**attrs}

    def connect(self,left:str,relation:str,right:str):
        if left not in self.nodes or right not in self.nodes:
            raise KeyError("both graph endpoints must exist")
        edge=Edge(left,relation,right)
        if edge not in self.edges:self.edges.append(edge)

    def parents(self,node_id:str,relation:str|None=None)->list[str]:
        return [e.left for e in self.edges if e.right==node_id and (relation is None or e.relation==relation)]

    def children(self,node_id:str,relation:str|None=None)->list[str]:
        return [e.right for e in self.edges if e.left==node_id and (relation is None or e.relation==relation)]

    def validate_claim(self,claim_id:str)->bool:
        evidence=self.children(claim_id,"supported_by")
        return bool(evidence) and all(self.nodes[e]["type"]=="evidence" for e in evidence)
