"""
IntelX/routers/threat_intel_knowledge_base.py — IntelX Threat Intelligence Knowledge Base.

Builds and queries a structured knowledge base of threat intelligence:
TTPs (Tactics, Techniques, Procedures), IoCs, threat actor profiles,
attack patterns, and historical incident data with graph-based relationships.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class TTP:
    """A Tactic, Technique, and Procedure."""
    ttp_id: str
    tactic: str  # MITRE ATT&CK tactic
    technique_id: str
    technique_name: str
    procedure: str = ""
    description: str = ""
    detection: list[str] = field(default_factory=list)
    mitigation: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    first_seen: float = 0.0
    last_updated: float = 0.0


@dataclass
class ThreatActorProfile:
    """A detailed threat actor profile."""
    actor_profile_id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    motivation: str = ""
    ttps: list[str] = field(default_factory=list)
    iocs: list[str] = field(default_factory=list)
    target_sectors: list[str] = field(default_factory=list)
    geo_targets: list[str] = field(default_factory=list)
    sophistication: int = 1
    infrastructure: list[str] = field(default_factory=list)
    first_observed: float = 0.0
    last_active: float = 0.0
    confidence: float = 0.5


@dataclass
class IncidentRecord:
    """A historical incident record."""
    incident_id: str
    title: str
    description: str = ""
    incident_type: str = ""
    severity: str = "medium"
    affected_entities: list[str] = field(default_factory=list)
    ttps_used: list[str] = field(default_factory=list)
    actors_involved: list[str] = field(default_factory=list)
    iocs: list[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    status: str = "analyzed"
    lessons_learned: list[str] = field(default_factory=list)


@dataclass
class KnowledgeQuery:
    """A knowledge base query."""
    query_id: str
    search_type: str  # ttp, actor, incident, ioc, technique
    search_terms: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    limit: int = 10
    created_at: float = 0.0


@dataclass
class KnowledgeResult:
    """Result of a knowledge base query."""
    query_id: str
    results: list[dict] = field(default_factory=list)
    total_found: int = 0
    response_time_ms: float = 0.0
    search_type: str = ""


@dataclass
class RelationshipGraph:
    """A graph of relationships between threat intel entities."""
    graph_id: str
    nodes: list[str] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    communities: list[list[str]] = field(default_factory=list)


class ThreatIntelKnowledgeBase:
    """Threat intelligence knowledge base engine."""

    def __init__(self):
        self._ttps: dict[str, TTP] = {}
        self._actors: dict[str, ThreatActorProfile] = {}
        self._incidents: dict[str, IncidentRecord] = {}
        self._queries: list[KnowledgeQuery] = []
        self._graphs: dict[str, RelationshipGraph] = {}

        # Register default TTPs
        self._register_default_ttps()

    def _register_default_ttps(self):
        """Register default TTPs from MITRE ATT&CK."""
        defaults = [
            ("TA0001", "Initial Access", "T1566", "Phishing", "Phishing for foothold"),
            ("TA0001", "Initial Access", "T1190", "Exploit Public-Facing Application", "Exploit vulnerabilities"),
            ("TA0002", "Execution", "T1059", "Command and Scripting Interpreter", "Execute commands"),
            ("TA0003", "Persistence", "T1547", "Boot or Logon Autostart Execution", "Persist via autostart"),
            ("TA0004", "Privilege Escalation", "T1068", "Exploitation for Privilege Escalation", "Escalate privileges"),
            ("TA0005", "Defense Evasion", "T1070", "Indicator Removal", "Remove indicators"),
            ("TA0006", "Credential Access", "T1003", "OS Credential Dumping", "Dump credentials"),
            ("TA0007", "Discovery", "T1087", "Account Discovery", "Discover accounts"),
            ("TA0008", "Lateral Movement", "T1021", "Remote Services", "Move laterally"),
            ("TA0009", "Collection", "T1560", "Archive Collected Data", "Collect and archive"),
            ("TA0010", "Exfiltration", "T1041", "Exfiltration Over C2 Channel", "Exfiltrate data"),
            ("TA0040", "Command and Control", "T1071", "Application Layer Protocol", "C2 communication"),
        ]

        for tactic, tactic_name, tech_id, tech_name, proc in defaults:
            ttp = TTP(
                ttp_id=hashlib.md5(
                    f"ttp:{tech_id}:{time.time()}".encode()
                ).hexdigest()[:12],
                tactic=tactic,
                technique_id=tech_id,
                technique_name=tech_name,
                procedure=proc,
                description=f"{tech_name} ({tactic_name})",
                detection=[f"Detect {tech_name} activity"],
                mitigation=[f"Prevent {tech_name}"],
                first_seen=time.time(),
                last_updated=time.time(),
            )
            self._ttps[ttp.ttp_id] = ttp

    def add_ttp(
        self,
        tactic: str,
        technique_id: str,
        technique_name: str,
        procedure: str = "",
        description: str = "",
    ) -> TTP:
        """Add a TTP to the knowledge base."""
        ttp = TTP(
            ttp_id=hashlib.md5(
                f"ttp:{technique_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            tactic=tactic,
            technique_id=technique_id,
            technique_name=technique_name,
            procedure=procedure,
            description=description,
            first_seen=time.time(),
            last_updated=time.time(),
        )
        self._ttps[ttp.ttp_id] = ttp
        return ttp

    def add_actor_profile(
        self,
        name: str,
        aliases: list[str] | None = None,
        motivation: str = "",
        ttps: list[str] | None = None,
        iocs: list[str] | None = None,
    ) -> ThreatActorProfile:
        """Add a threat actor profile."""
        profile = ThreatActorProfile(
            actor_profile_id=hashlib.md5(
                f"actor:{name}:{time.time()}".encode()
            ).hexdigest()[:12],
            name=name,
            aliases=aliases or [],
            motivation=motivation,
            ttps=ttps or [],
            iocs=iocs or [],
            first_observed=time.time(),
            last_active=time.time(),
        )
        self._actors[profile.actor_profile_id] = profile
        return profile

    def add_incident(
        self,
        title: str,
        description: str = "",
        incident_type: str = "",
        severity: str = "medium",
        affected_entities: list[str] | None = None,
        ttps_used: list[str] | None = None,
    ) -> IncidentRecord:
        """Add an incident record."""
        incident = IncidentRecord(
            incident_id=hashlib.md5(
                f"incident:{title}:{time.time()}".encode()
            ).hexdigest()[:12],
            title=title,
            description=description,
            incident_type=incident_type,
            severity=severity,
            affected_entities=affected_entities or [],
            ttps_used=ttps_used or [],
            start_time=time.time(),
            end_time=time.time(),
        )
        self._incidents[incident.incident_id] = incident
        return incident

    def query(
        self,
        search_type: str,
        search_terms: list[str],
        limit: int = 10,
    ) -> KnowledgeResult:
        """Query the knowledge base."""
        start = time.time()
        query_id = hashlib.md5(
            f"query:{search_type}:{time.time()}".encode()
        ).hexdigest()[:12]

        results = []

        if search_type == "ttp":
            for ttp in self._ttps.values():
                if any(term.lower() in ttp.technique_name.lower() or term in ttp.technique_id for term in search_terms):
                    results.append({
                        "type": "ttp",
                        "id": ttp.ttp_id,
                        "name": ttp.technique_name,
                        "tactic": ttp.tactic,
                        "technique_id": ttp.technique_id,
                        "description": ttp.description,
                    })

        elif search_type == "actor":
            for actor in self._actors.values():
                if any(term.lower() in actor.name.lower() or term.lower() in str(actor.aliases).lower() for term in search_terms):
                    results.append({
                        "type": "actor",
                        "id": actor.actor_profile_id,
                        "name": actor.name,
                        "aliases": actor.aliases,
                        "motivation": actor.motivation,
                        "sophistication": actor.sophistication,
                    })

        elif search_type == "incident":
            for incident in self._incidents.values():
                if any(term.lower() in incident.title.lower() or term.lower() in incident.description.lower() for term in search_terms):
                    results.append({
                        "type": "incident",
                        "id": incident.incident_id,
                        "title": incident.title,
                        "severity": incident.severity,
                        "incident_type": incident.incident_type,
                    })

        elif search_type == "ioc":
            ioc_results = []
            for actor in self._actors.values():
                for ioc in actor.iocs:
                    if any(term.lower() in ioc.lower() for term in search_terms):
                        ioc_results.append({
                            "type": "ioc",
                            "ioc": ioc,
                            "actor": actor.name,
                        })
            results = ioc_results

        elif search_type == "technique":
            for ttp in self._ttps.values():
                if any(term.lower() in ttp.technique_name.lower() for term in search_terms):
                    results.append({
                        "type": "technique",
                        "id": ttp.ttp_id,
                        "name": ttp.technique_name,
                        "tactic": ttp.tactic,
                    })

        results = results[:limit]

        latency = (time.time() - start) * 1000

        result = KnowledgeResult(
            query_id=query_id,
            results=results,
            total_found=len(results),
            response_time_ms=latency,
            search_type=search_type,
        )

        self._queries.append(KnowledgeQuery(
            query_id=query_id,
            search_type=search_type,
            search_terms=search_terms,
            limit=limit,
            created_at=time.time(),
        ))

        return result

    def build_relationship_graph(self) -> RelationshipGraph:
        """Build a relationship graph of threat intel entities."""
        nodes = list(self._ttps.keys()) + list(self._actors.keys()) + list(self._incidents.keys())
        edges = []

        # Connect actors to TTPs
        for actor in self._actors.values():
            for ttp_id in actor.ttps:
                if ttp_id in self._ttps:
                    edges.append({
                        "source": actor.actor_profile_id,
                        "target": ttp_id,
                        "relationship": "uses",
                    })

        # Connect incidents to actors
        for incident in self._incidents.values():
            for actor_name in incident.actors_involved:
                for actor in self._actors.values():
                    if actor.name == actor_name:
                        edges.append({
                            "source": incident.incident_id,
                            "target": actor.actor_profile_id,
                            "relationship": "involves",
                        })

        # Connect incidents to TTPs
        for incident in self._incidents.values():
            for ttp_id in incident.ttps_used:
                if ttp_id in self._ttps:
                    edges.append({
                        "source": incident.incident_id,
                        "target": ttp_id,
                        "relationship": "employs",
                    })

        # Community detection (simple clustering)
        communities = [nodes[:len(nodes)//3], nodes[len(nodes)//3:2*len(nodes)//3], nodes[2*len(nodes)//3:]]

        graph = RelationshipGraph(
            graph_id=hashlib.md5(
                f"graph:{time.time()}".encode()
            ).hexdigest()[:12],
            nodes=nodes,
            edges=edges,
            communities=[c for c in communities if c],
        )

        self._graphs[graph.graph_id] = graph
        return graph

    def get_report(self) -> dict:
        """Get threat intel knowledge base report."""
        return {
            "total_ttps": len(self._ttps),
            "total_actors": len(self._actors),
            "total_incidents": len(self._incidents),
            "total_queries": len(self._queries),
            "total_graphs": len(self._graphs),
            "ttps_by_tactic": {
                t: sum(1 for ttp in self._ttps.values() if ttp.tactic == t)
                for t in set(ttp.tactic for ttp in self._ttps.values())
            },
            "actors_by_motivation": {
                m: sum(1 for a in self._actors.values() if a.motivation == m)
                for m in set(a.motivation for a in self._actors.values())
            },
        }


# Module-level singleton
threat_kb = ThreatIntelKnowledgeBase()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/intelex/threat-kb/ttps")
async def add_ttp(payload: dict):
    """Add a TTP to the knowledge base."""
    ttp = threat_kb.add_ttp(
        tactic=payload["tactic"],
        technique_id=payload["technique_id"],
        technique_name=payload["technique_name"],
        procedure=payload.get("procedure", ""),
        description=payload.get("description", ""),
    )
    return {"ttp_id": ttp.ttp_id, "technique_name": ttp.technique_name, "tactic": ttp.tactic}


@router.post("/api/v1/intelex/threat-kb/actors")
async def add_actor_profile(payload: dict):
    """Add a threat actor profile."""
    profile = threat_kb.add_actor_profile(
        name=payload["name"],
        aliases=payload.get("aliases", []),
        motivation=payload.get("motivation", ""),
        ttps=payload.get("ttps", []),
        iocs=payload.get("iocs", []),
    )
    return {"actor_profile_id": profile.actor_profile_id, "name": profile.name}


@router.post("/api/v1/intelex/threat-kb/incidents")
async def add_incident(payload: dict):
    """Add an incident record."""
    incident = threat_kb.add_incident(
        title=payload["title"],
        description=payload.get("description", ""),
        incident_type=payload.get("incident_type", ""),
        severity=payload.get("severity", "medium"),
        affected_entities=payload.get("affected_entities", []),
        ttps_used=payload.get("ttps_used", []),
    )
    return {"incident_id": incident.incident_id, "title": incident.title, "severity": incident.severity}


@router.post("/api/v1/intelex/threat-kb/query")
async def query(payload: dict):
    """Query the knowledge base."""
    result = threat_kb.query(
        search_type=payload["search_type"],
        search_terms=payload["search_terms"],
        limit=payload.get("limit", 10),
    )
    return {
        "query_id": result.query_id,
        "total_found": result.total_found,
        "response_time_ms": result.response_time_ms,
        "results": result.results,
    }


@router.post("/api/v1/intelex/threat-kb/relationship-graph")
async def build_relationship_graph():
    """Build relationship graph."""
    graph = threat_kb.build_relationship_graph()
    return {
        "graph_id": graph.graph_id,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "communities": len(graph.communities),
    }


@router.get("/api/v1/intelex/threat-kb/report")
async def get_report():
    """Get threat intel knowledge base report."""
    return threat_kb.get_report()
