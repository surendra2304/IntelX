"""
IntelX/intelx/services/supply_chain_threat_mapper.py — IntelX Supply Chain Threat Mapper.

Supply chain threat mapping, vendor risk assessment, third-party dependency analysis,
and supply chain attack path identification.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class SupplyChainNode:
    """A node in the supply chain."""
    node_id: str
    name: str
    type: str = "vendor"  # vendor, dependency, service, internal, customer
    risk_level: str = "low"  # low, medium, high, critical
    trust_score: float = 0.5
    dependencies: list[str] = field(default_factory=list)
    criticality: float = 0.5


@dataclass
class AttackPath:
    """A potential attack path through the supply chain."""
    path_id: str
    entry_point: str
    target: str
    path_nodes: list[str] = field(default_factory=list)
    likelihood: float = 0.0
    impact: str = "medium"
    description: str = ""


@dataclass
class SupplyChainRiskReport:
    """A supply chain risk assessment report."""
    report_id: str
    total_nodes: int = 0
    critical_nodes: int = 0
    total_paths: int = 0
    high_risk_paths: int = 0
    risk_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)


class SupplyChainThreatMapper:
    """Engine for supply chain threat mapping and risk assessment."""

    def __init__(self) -> None:
        self._nodes: dict[str, SupplyChainNode] = {}
        self._paths: list[AttackPath] = []
        self._reports: list[SupplyChainRiskReport] = []

    def add_node(self, name: str, node_type: str = "vendor",
                 risk_level: str = "low", trust_score: float = 0.5,
                 criticality: float = 0.5) -> SupplyChainNode:
        """Add a supply chain node."""
        node_id = f"node_{uuid.uuid4().hex[:12]}"
        node = SupplyChainNode(
            node_id=node_id, name=name, type=node_type,
            risk_level=risk_level, trust_score=trust_score,
            criticality=criticality,
        )
        self._nodes[node_id] = node
        return node

    def add_dependency(self, source_id: str, target_id: str) -> None:
        """Add a dependency between nodes."""
        source = self._nodes.get(source_id)
        target = self._nodes.get(target_id)
        if not source or not target:
            raise HTTPException(status_code=404, detail="Node not found")
        source.dependencies.append(target_id)

    def map_attack_path(self, entry_point: str, target: str,
                        likelihood: float = 0.3) -> AttackPath:
        """Map a potential attack path."""
        path_id = f"path_{uuid.uuid4().hex[:12]}"
        path = AttackPath(
            path_id=path_id, entry_point=entry_point, target=target,
            likelihood=likelihood,
        )
        path.path_nodes = self._find_path(entry_point, target)

        entry_node = self._nodes.get(entry_point)
        target_node = self._nodes.get(target)
        if entry_node and target_node:
            path.impact = "critical" if target_node.criticality > 0.7 else "medium"
            path.description = f"Path from {entry_node.name} to {target_node.name}"

        self._paths.append(path)
        return path

    def _find_path(self, start: str, end: str, max_depth: int = 5) -> list[str]:
        """Find a path between two nodes using BFS."""
        if start == end:
            return [start]
        visited: set[str] = set()
        queue: list[list[str]] = [[start]]
        visited.add(start)

        while queue and max_depth > 0:
            path = queue.pop(0)
            node = self._nodes.get(path[-1])
            if not node:
                continue
            for dep in node.dependencies:
                if dep == end:
                    return path + [dep]
                if dep not in visited:
                    visited.add(dep)
                    queue.append(path + [dep])
            max_depth -= 1
        return []

    def assess_risk(self) -> SupplyChainRiskReport:
        """Assess supply chain risk."""
        report_id = f"scrisk_{uuid.uuid4().hex[:12]}"
        report = SupplyChainRiskReport(report_id=report_id)
        report.total_nodes = len(self._nodes)
        report.critical_nodes = sum(1 for n in self._nodes.values() if n.criticality > 0.7)
        report.total_paths = len(self._paths)
        report.high_risk_paths = sum(1 for p in self._paths if p.likelihood > 0.5)
        report.risk_score = (
            (report.critical_nodes / max(1, report.total_nodes)) * 0.4 +
            (report.high_risk_paths / max(1, report.total_paths)) * 0.3 +
            (1.0 - sum(n.trust_score for n in self._nodes.values()) / max(1, report.total_nodes)) * 0.3
        ) * 100

        report.recommendations = [
            "Reduce dependencies on critical nodes",
            "Add monitoring for high-risk paths",
            "Implement vendor security requirements",
            "Add alternative suppliers for critical components",
        ]

        self._reports.append(report)
        return report

    def get_nodes(self, risk_level: str | None = None) -> list[dict[str, Any]]:
        """Get supply chain nodes."""
        nodes = list(self._nodes.values())
        if risk_level:
            nodes = [n for n in nodes if n.risk_level == risk_level]
        return [
            {"name": n.name, "type": n.type, "risk_level": n.risk_level,
             "criticality": n.criticality, "dependencies": len(n.dependencies)}
            for n in nodes
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_nodes": len(self._nodes),
            "total_paths": len(self._paths),
            "total_reports": len(self._reports),
            "engine_status": "operational",
        }


engine = SupplyChainThreatMapper()


@router.post("/intelx/supplychain/nodes")
async def add_node(name: str, node_type: str = "vendor", risk_level: str = "low",
                   trust_score: float = 0.5, criticality: float = 0.5):
    """Add a supply chain node."""
    node = engine.add_node(name, node_type, risk_level, trust_score, criticality)
    return {"node_id": node.node_id, "name": node.name, "criticality": node.criticality}


@router.post("/intelx/supplychain/dependencies")
async def add_dependency(source_id: str, target_id: str):
    """Add a dependency between nodes."""
    engine.add_dependency(source_id, target_id)
    return {"source": source_id, "target": target_id, "status": "linked"}


@router.post("/intelx/supplychain/paths")
async def map_attack_path(entry_point: str, target: str, likelihood: float = 0.3):
    """Map a potential attack path."""
    path = engine.map_attack_path(entry_point, target, likelihood)
    return {
        "path_id": path.path_id,
        "path_length": len(path.path_nodes),
        "likelihood": path.likelihood,
        "impact": path.impact,
    }


@router.post("/intelx/supplychain/risk")
async def assess_risk():
    """Assess supply chain risk."""
    report = engine.assess_risk()
    return {
        "report_id": report.report_id,
        "risk_score": report.risk_score,
        "critical_nodes": report.critical_nodes,
        "high_risk_paths": report.high_risk_paths,
    }


@router.get("/intelx/supplychain/nodes")
async def get_nodes(risk_level: str | None = None):
    """Get supply chain nodes."""
    return {"nodes": engine.get_nodes(risk_level)}


@router.get("/intelx/supplychain/report")
async def supplychain_report():
    """Get supply chain mapper report."""
    return engine.get_report()
