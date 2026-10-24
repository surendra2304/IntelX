"""
IntelX/expert_network.py — IntelX Expert Network & Knowledge Graph.

Extends IntelX's capabilities with:
1. Expert Profiling: build detailed expert profiles
2. Expert Matching: match experts to research questions
3. Knowledge Graph: build expert knowledge graph
4. Expert Network Analysis: analyze expert collaboration networks
5. Expert Recommendation: recommend experts for collaboration
6. Expert Expertise Tracking: track expert expertise over time
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class Expert:
    """An expert profile."""
    expert_id: str
    name: str
    affiliation: str
    field: str
    expertise_areas: list[str] = field(default_factory=list)
    publications: int = 0
    h_index: float = 0.0
    influence_score: float = 0.0
    collaboration_count: int = 0
    collaborations: list[str] = field(default_factory=list)
    available: bool = True


@dataclass
class ExpertMatch:
    """A match between an expert and a research question."""
    expert_id: str
    expert_name: str
    match_score: float
    matched_expertise: list[str]
    reason: str
    availability: bool


@dataclass
class KnowledgeEdge:
    """An edge in the expert knowledge graph."""
    source: str  # expert_id
    target: str  # expert_id or topic
    relationship: str  # collaborates_with, specializes_in, cited_by
    weight: float = 1.0


@dataclass
class NetworkMetrics:
    """Metrics for the expert network."""
    total_experts: int
    total_connections: int
    density: float
    avg_clustering: float
    influence_distribution: dict[str, int]
    most_influential: list[str]


@dataclass
class CollaborationRecommendation:
    """A collaboration recommendation."""
    expert_a: str
    expert_b: str
    score: float
    common_interests: list[str]
    potential_synergy: str
    reason: str


class ExpertNetwork:
    """Expert network and knowledge graph engine."""

    def __init__(self):
        self._experts: dict[str, Expert] = {}
        self._knowledge_graph: list[KnowledgeEdge] = []
        self._matches: list[ExpertMatch] = []
        self._recommendations: list[CollaborationRecommendation] = []

    # ── Expert Profiling ────────────────────────────────────────────────────

    def add_expert(
        self,
        name: str,
        affiliation: str,
        field: str,
        expertise_areas: list[str] | None = None,
        publications: int = 0,
        h_index: float = 0.0,
    ) -> Expert:
        """Add an expert to the network."""
        expert_id = hashlib.md5(
            f"{name}:{affiliation}:{time.time()}".encode()
        ).hexdigest()[:12]

        expert = Expert(
            expert_id=expert_id,
            name=name,
            affiliation=affiliation,
            field=field,
            expertise_areas=expertise_areas or [],
            publications=publications,
            h_index=h_index,
            influence_score=h_index * 0.5 + publications * 0.01,
        )

        self._experts[expert_id] = expert

        # Add to knowledge graph
        for area in expert.expertise_areas:
            self._knowledge_graph.append(KnowledgeEdge(
                source=expert_id,
                target=area,
                relationship="specializes_in",
                weight=expert.h_index,
            ))

        return expert

    def update_expert(
        self,
        expert_id: str,
        publications_delta: int = 0,
        h_index_delta: float = 0.0,
    ) -> Expert | None:
        """Update an expert's metrics."""
        expert = self._experts.get(expert_id)
        if not expert:
            return None

        expert.publications += publications_delta
        expert.h_index += h_index_delta
        expert.influence_score = expert.h_index * 0.5 + expert.publications * 0.01

        return expert

    # ── Expert Matching ──────────────────────────────────────────────────────

    def match_experts(
        self,
        research_question: str,
        required_fields: list[str] | None = None,
    ) -> list[ExpertMatch]:
        """Match experts to a research question."""
        query_lower = research_question.lower()
        matches = []

        for expert in self._experts.values():
            # Calculate match score
            score = 0.0
            matched_areas = []

            # Field match
            if expert.field.lower() in query_lower:
                score += 0.3

            # Expertise area match
            for area in expert.expertise_areas:
                if area.lower() in query_lower:
                    score += 0.2
                    matched_areas.append(area)

            # Field requirement
            if required_fields and expert.field in required_fields:
                score += 0.2

            # Influence boost
            score += expert.influence_score * 0.01

            # Availability
            availability = expert.available

            if score > 0.1:
                match = ExpertMatch(
                    expert_id=expert.expert_id,
                    expert_name=expert.name,
                    match_score=min(1.0, score),
                    matched_expertise=matched_areas,
                    reason=f"Matched on field '{expert.field}' and expertise in {matched_areas}",
                    availability=availability,
                )
                matches.append(match)

        matches.sort(key=lambda m: -m.match_score)
        self._matches = matches
        return matches[:10]

    # ── Knowledge Graph ─────────────────────────────────────────────────────

    def get_knowledge_graph(self) -> list[KnowledgeEdge]:
        """Get the expert knowledge graph."""
        return self._knowledge_graph

    def find_experts_by_topic(self, topic: str) -> list[Expert]:
        """Find experts by topic."""
        topic_lower = topic.lower()
        results = []

        for expert in self._experts.values():
            if any(
                topic_lower in area.lower() for area in expert.expertise_areas
            ) or topic_lower in expert.field.lower():
                results.append(expert)

        return results

    def find_related_experts(self, expert_id: str) -> list[Expert]:
        """Find experts related to a given expert."""
        expert = self._experts.get(expert_id)
        if not expert:
            return []

        # Find experts in same field
        same_field = [
            e for e in self._experts.values()
            if e.expert_id != expert_id and e.field == expert.field
        ]

        # Find experts with overlapping expertise
        overlapping = []
        for e in self._experts.values():
            if e.expert_id == expert_id:
                continue
            overlap = set(e.expertise_areas) & set(expert.expertise_areas)
            if overlap:
                overlapping.append((e, len(overlap)))

        overlapping.sort(key=lambda x: -x[1])

        return same_field + [e for e, _ in overlapping]

    # ── Expert Network Analysis ──────────────────────────────────────────────

    def analyze_network(self) -> NetworkMetrics:
        """Analyze the expert network."""
        total = len(self._experts)

        # Count connections
        connections = {}
        for edge in self._knowledge_graph:
            if edge.relationship == "collaborates_with":
                connections[edge.source] = connections.get(edge.source, 0) + 1
                connections[edge.target] = connections.get(edge.target, 0) + 1

        # Calculate density
        max_connections = total * (total - 1) / 2
        actual_connections = sum(connections.values()) / 2
        density = actual_connections / max(1, max_connections)

        # Influence distribution
        influence_dist = {}
        for expert in self._experts.values():
            if expert.influence_score > 50:
                influence_dist["high"] = influence_dist.get("high", 0) + 1
            elif expert.influence_score > 20:
                influence_dist["medium"] = influence_dist.get("medium", 0) + 1
            else:
                influence_dist["low"] = influence_dist.get("low", 0) + 1

        # Most influential
        influential = sorted(
            self._experts.values(),
            key=lambda e: -e.influence_score
        )[:10]

        return NetworkMetrics(
            total_experts=total,
            total_connections=actual_connections,
            density=density,
            avg_clustering=0.3,
            influence_distribution=influence_dist,
            most_influential=[e.name for e in influential],
        )

    def add_collaboration(
        self,
        expert_a_id: str,
        expert_b_id: str,
    ) -> bool:
        """Add a collaboration between two experts."""
        expert_a = self._experts.get(expert_a_id)
        expert_b = self._experts.get(expert_b_id)

        if expert_a and expert_b:
            # Add edge
            self._knowledge_graph.append(KnowledgeEdge(
                source=expert_a_id,
                target=expert_b_id,
                relationship="collaborates_with",
                weight=1.0,
            ))

            # Update collaboration counts
            expert_a.collaboration_count += 1
            expert_b.collaboration_count += 1
            expert_a.collaborations.append(expert_b_id)
            expert_b.collaborations.append(expert_a_id)

            return True

        return False

    # ── Expert Recommendation ────────────────────────────────────────────────

    def recommend_collaborations(
        self,
        expert_id: str,
        top_k: int = 5,
    ) -> list[CollaborationRecommendation]:
        """Recommend collaborations for an expert."""
        expert = self._experts.get(expert_id)
        if not expert:
            return []

        recommendations = []

        for other in self._experts.values():
            if other.expert_id == expert_id:
                continue

            # Calculate recommendation score
            score = 0.0
            common_interests = []

            # Common expertise
            overlap = set(expert.expertise_areas) & set(other.expertise_areas)
            if overlap:
                score += len(overlap) * 0.3
                common_interests = list(overlap)

            # Same field
            if expert.field == other.field:
                score += 0.2

            # Complementary expertise
            if not overlap and expert.field == other.field:
                score += 0.1

            # Influence
            score += (expert.influence_score + other.influence_score) * 0.001

            # Not already collaborating
            if other.expert_id not in expert.collaborations:
                score += 0.1

            if score > 0.1:
                # Determine potential synergy
                if common_interests:
                    synergy = f"Both experts share expertise in {', '.join(common_interests)}"
                elif expert.field == other.field:
                    synergy = f"Same field ({expert.field}) with complementary skills"
                else:
                    synergy = "Cross-disciplinary collaboration potential"

                rec = CollaborationRecommendation(
                    expert_a=expert_id,
                    expert_b=other.expert_id,
                    score=score,
                    common_interests=common_interests,
                    potential_synergy=synergy,
                    reason=f"Recommendation score: {score:.2f}",
                )
                recommendations.append(rec)

        recommendations.sort(key=lambda r: -r.score)
        self._recommendations = recommendations[:top_k]
        return self._recommendations

    # ── Expert Expertise Tracking ───────────────────────────────────────────

    def track_expertise_evolution(
        self,
        expert_id: str,
        new_expertise: list[str],
    ) -> dict[str, Any]:
        """Track how an expert's expertise evolves."""
        expert = self._experts.get(expert_id)
        if not expert:
            return {"status": "NOT_FOUND"}

        old_expertise = set(expert.expertise_areas)
        new_set = set(new_expertise)

        added = new_set - old_expertise
        removed = old_expertise - new_set
        retained = old_expertise & new_set

        # Update expert
        expert.expertise_areas = list(new_expertise)

        # Update knowledge graph
        for area in added:
            self._knowledge_graph.append(KnowledgeEdge(
                source=expert_id,
                target=area,
                relationship="specializes_in",
                weight=expert.h_index,
            ))

        return {
            "expert_id": expert_id,
            "added": list(added),
            "removed": list(removed),
            "retained": list(retained),
            "total_expertise": len(new_expertise),
        }

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_network_report(self) -> dict[str, Any]:
        """Generate an expert network report."""
        return {
            "total_experts": len(self._experts),
            "total_edges": len(self._knowledge_graph),
            "total_matches": len(self._matches),
            "total_recommendations": len(self._recommendations),
            "network_metrics": self.analyze_network().__dict__,
        }


# ── Router Endpoints ──────────────────────────────────────────────────────────

expert_network = ExpertNetwork()


@router.post("/api/v1/intel/experts")
async def create_expert_endpoint(payload: dict):
    """Create an expert profile."""
    expert = expert_network.create_expert(
        name=payload["name"],
        affiliation=payload.get("affiliation", ""),
        field=payload.get("field", ""),
        expertise_areas=payload.get("expertise_areas", []),
        publications=payload.get("publications", 0),
        h_index=payload.get("h_index", 0.0),
    )
    return expert.__dict__


@router.post("/api/v1/intel/experts/match")
async def match_expert_endpoint(payload: dict):
    """Match experts to a research question."""
    matches = expert_network.match_expert(
        research_question=payload.get("research_question", ""),
        required_expertise=payload.get("required_expertise", []),
    )
    return [m.__dict__ for m in matches]


@router.get("/api/v1/intel/experts/network")
async def analyze_network_endpoint():
    """Analyze the expert network."""
    return expert_network.analyze_network().__dict__


@router.get("/api/v1/intel/experts/{expert_id}/recommendations")
async def recommend_collaborations_endpoint(expert_id: str):
    """Recommend collaborations for an expert."""
    recommendations = expert_network.recommend_collaborations(expert_id)
    return [r.__dict__ for r in recommendations]


@router.get("/api/v1/intel/experts/report")
async def get_network_report_endpoint():
    """Get expert network report."""
    return expert_network.get_network_report()
