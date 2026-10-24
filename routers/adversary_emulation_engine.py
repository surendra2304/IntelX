"""
IntelX/routers/adversary_emulation_engine.py — IntelX Adversary Emulation Engine.

Emulates adversary behavior using MITRE ATT&CK tactics, techniques, and
procedures. Generates emulation plans, executes attack simulations, and
provides detection gap analysis with remediation recommendations.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AdversaryProfile:
    """A profile describing an adversary."""
    profile_id: str
    name: str = ""
    description: str = ""
    tactics: list[str] = field(default_factory=list)
    techniques: list[str] = field(default_factory=list)
    threat_level: str = "APT"  # opportunistic, commodity, APT
    sophistication: str = "advanced"  # low, medium, high, advanced
    resource_level: str = "high"  # low, medium, high
    motivation: str = ""  # financial, espionage, disruption, ideological
    origin: str = ""


@dataclass
class ATTACKTechnique:
    """A MITRE ATT&CK technique."""
    technique_id: str
    technique_name: str = ""
    tactic: str = ""
    procedure: str = ""
    detection: str = ""
    mitigation: str = ""
    platform: str = ""
    privilege_required: str = ""


@dataclass
class EmulationPlan:
    """A plan for emulating adversary behavior."""
    plan_id: str
    profile_id: str
    name: str = ""
    description: str = ""
    phases: list[dict] = field(default_factory=list)
    estimated_duration_hours: float = 0.0
    status: str = "planned"  # planned, approved, executing, completed
    created_at: float = 0.0


@dataclass
class EmulationPhase:
    """A phase in an emulation plan."""
    phase_id: str
    plan_id: str
    phase_number: int = 1
    phase_name: str = ""
    tactic: str = ""
    techniques: list[str] = field(default_factory=list)
    objectives: list[str] = field(default_factory=list)
    estimated_duration_minutes: int = 30
    status: str = "pending"  # pending, executing, completed, skipped
    executed_at: float = 0.0


@dataclass
class DetectionGap:
    """A detection gap identified during emulation."""
    gap_id: str
    plan_id: str
    technique_id: str = ""
    tactic: str = ""
    description: str = ""
    severity: str = "medium"  # low, medium, high, critical
    detection_possible: bool = False
    remediation: str = ""
    detected: bool = False


@dataclass
class AttackSimulation:
    """A simulation of an attack technique."""
    simulation_id: str
    plan_id: str
    technique_id: str
    technique_name: str = ""
    procedure: str = ""
    executed: bool = False
    outcome: str = ""
    detected: bool = False
    detection_time_ms: float = 0.0
    executed_at: float = 0.0


class AdversaryEmulationEngine:
    """Adversary emulation engine."""

    def __init__(self):
        self._profiles: dict[str, AdversaryProfile] = {}
        self._techniques: dict[str, ATTACKTechnique] = {}
        self._plans: dict[str, EmulationPlan] = {}
        self._phases: list[EmulationPhase] = []
        self._gaps: list[DetectionGap] = []
        self._simulations: list[AttackSimulation] = []

        # Register known techniques
        self._register_techniques()

    def _register_techniques(self):
        """Register known ATT&CK techniques."""
        techniques = [
            ("T1595", "Active Scanning", "Reconnaissance", "Scanning target IP ranges", "Network monitoring", "Restrict outbound traffic", "Windows/Linux/macOS"),
            ("T1078", "Valid Accounts", "Initial Access", "Using compromised credentials", "Authentication logging", "Enforce MFA", "Windows/Linux/macOS"),
            ("T1027", "Obfuscated Files", "Defense Evasion", "Encrypting or encoding files", "File integrity monitoring", "Use AV/EDR", "Windows/Linux/macOS"),
            ("T1059", "Command and Scripting", "Execution", "Running scripts on target", "Command logging", "Restrict script execution", "Windows/Linux/macOS"),
            ("T1003", "OS Credential Dumping", "Credential Access", "Dumping LSASS memory", "Process monitoring", "Protect LSASS memory", "Windows"),
            ("T1071", "Application Layer Protocol", "Command and Control", "Communication over HTTPS", "Network traffic analysis", "Use proxy/firewall", "Windows/Linux/macOS"),
            ("T1486", "Data Encrypted for Impact", "Impact", "Encrypting data for ransom", "File monitoring", "Maintain backups", "Windows/Linux/macOS"),
            ("T1055", "Process Injection", "Defense Evasion", "Injecting code into processes", "Process monitoring", "Use EDR", "Windows"),
        ]
        for tid, name, tactic, procedure, detection, mitigation, platform in techniques:
            self._techniques[tid] = ATTACKTechnique(
                technique_id=tid,
                technique_name=name,
                tactic=tactic,
                procedure=procedure,
                detection=detection,
                mitigation=mitigation,
                platform=platform,
            )

    def create_profile(
        self,
        name: str,
        description: str = "",
        threat_level: str = "APT",
        sophistication: str = "advanced",
        motivation: str = "",
        origin: str = "",
    ) -> AdversaryProfile:
        """Create an adversary profile."""
        tactics = ["Reconnaissance", "Initial Access", "Execution", "Persistence", "Credential Access", "Defense Evasion", "Command and Control", "Impact"]
        techniques = [tid for tid in list(self._techniques.keys())[:5]]

        profile = AdversaryProfile(
            profile_id=hashlib.md5(
                f"profile:{name}:{time.time()}".encode()
            ).hexdigest()[:12],
            name=name,
            description=description,
            tactics=tactics,
            techniques=techniques,
            threat_level=threat_level,
            sophistication=sophistication,
            resource_level="high" if sophistication in ("advanced", "high") else "medium",
            motivation=motivation,
            origin=origin,
        )
        self._profiles[profile.profile_id] = profile
        return profile

    def create_plan(self, profile_id: str, name: str, description: str = "") -> EmulationPlan:
        """Create an emulation plan."""
        profile = self._profiles.get(profile_id)
        if not profile:
            raise HTTPException(404, f"Profile {profile_id} not found")

        plan = EmulationPlan(
            plan_id=hashlib.md5(
                f"plan:{profile_id}:{name}:{time.time()}".encode()
            ).hexdigest()[:12],
            profile_id=profile_id,
            name=name,
            description=description,
            created_at=time.time(),
        )

        # Create phases from tactics
        for i, tactic in enumerate(profile.tactics[:6]):
            phase = EmulationPhase(
                phase_id=hashlib.md5(
                    f"phase:{plan.plan_id}:{i}:{time.time()}".encode()
                ).hexdigest()[:12],
                plan_id=plan.plan_id,
                phase_number=i + 1,
                phase_name=f"Phase {i+1}: {tactic}",
                tactic=tactic,
                techniques=[
                    tid for tid, tech in self._techniques.items()
                    if tech.tactic == tactic
                ][:3],
                objectives=[f"Emulate {tactic} behavior", f"Test detection for {tactic}"],
                estimated_duration_minutes=30 + i * 15,
            )
            self._phases.append(phase)
            plan.phases.append({
                "phase_id": phase.phase_id,
                "phase_name": phase.phase_name,
                "tactic": phase.tactic,
                "techniques": phase.techniques,
            })

        plan.estimated_duration_hours = sum(p.estimated_duration_minutes for p in self._phases if p.plan_id == plan.plan_id) / 60

        self._plans[plan.plan_id] = plan
        return plan

    def execute_phase(self, phase_id: str) -> EmulationPhase:
        """Execute an emulation phase."""
        phase = None
        for p in self._phases:
            if p.phase_id == phase_id:
                phase = p
                break

        if not phase:
            raise HTTPException(404, f"Phase {phase_id} not found")

        phase.status = "executing"

        # Simulate each technique
        for technique_id in phase.techniques:
            tech = self._techniques.get(technique_id)
            if not tech:
                continue

            simulation = AttackSimulation(
                simulation_id=hashlib.md5(
                    f"simulation:{phase_id}:{technique_id}:{time.time()}".encode()
                ).hexdigest()[:12],
                plan_id=phase.plan_id,
                technique_id=technique_id,
                technique_name=tech.technique_name,
                procedure=tech.procedure,
                executed=True,
                outcome=f"Simulated {tech.procedure}",
                detected=False,
                detection_time_ms=0.0,
                executed_at=time.time(),
            )

            self._simulations.append(simulation)

            # Check for detection gap
            gap = DetectionGap(
                gap_id=hashlib.md5(
                    f"gap:{phase_id}:{technique_id}:{time.time()}".encode()
                ).hexdigest()[:12],
                plan_id=phase.plan_id,
                technique_id=technique_id,
                tactic=phase.tactic,
                description=f"Detection gap for {tech.technique_name}: {tech.procedure}",
                severity="high" if phase.tactic in ("Credential Access", "Impact") else "medium",
                detection_possible=False,
                remediation=tech.mitigation,
                detected=False,
            )
            self._gaps.append(gap)

        phase.status = "completed"
        phase.executed_at = time.time()
        return phase

    def get_gap_analysis(self, plan_id: str) -> list[DetectionGap]:
        """Get detection gap analysis for a plan."""
        gaps = [g for g in self._gaps if g.plan_id == plan_id]
        return gaps

    def get_report(self) -> dict:
        """Get adversary emulation report."""
        total_simulations = len(self._simulations)
        detected = sum(1 for s in self._simulations if s.detected)

        return {
            "total_profiles": len(self._profiles),
            "total_techniques_registered": len(self._techniques),
            "total_plans": len(self._plans),
            "total_phases": len(self._phases),
            "total_simulations": total_simulations,
            "total_detection_gaps": len(self._gaps),
            "detected_simulations": detected,
            "undetected_simulations": total_simulations - detected,
            "detection_rate": detected / max(1, total_simulations),
            "critical_gaps": sum(1 for g in self._gaps if g.severity == "critical"),
            "high_severity_gaps": sum(1 for g in self._gaps if g.severity == "high"),
            "completed_plans": sum(1 for p in self._plans.values() if p.status == "completed"),
            "techniques_by_tactic": {
                tactic: sum(1 for t in self._techniques.values() if t.tactic == tactic)
                for tactic in set(t.tactic for t in self._techniques.values())
            },
            "recent_simulations": [
                {
                    "technique": s.technique_name,
                    "detected": s.detected,
                    "outcome": s.outcome[:80],
                }
                for s in self._simulations[-10:]
            ],
            "recent_gaps": [
                {
                    "technique": g.technique_id,
                    "tactic": g.tactic,
                    "severity": g.severity,
                    "remediation": g.remediation[:80],
                }
                for g in self._gaps[-10:]
            ],
        }


# Module-level singleton
emulation_engine = AdversaryEmulationEngine()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/intelex/emulation/profiles")
async def create_profile(payload: dict):
    """Create an adversary profile."""
    profile = emulation_engine.create_profile(
        name=payload["name"],
        description=payload.get("description", ""),
        threat_level=payload.get("threat_level", "APT"),
        sophistication=payload.get("sophistication", "advanced"),
        motivation=payload.get("motivation", ""),
        origin=payload.get("origin", ""),
    )
    return {"profile_id": profile.profile_id, "name": profile.name, "threat_level": profile.threat_level}


@router.post("/api/v1/intelex/emulation/plans")
async def create_plan(payload: dict):
    """Create an emulation plan."""
    plan = emulation_engine.create_plan(
        profile_id=payload["profile_id"],
        name=payload["name"],
        description=payload.get("description", ""),
    )
    return {"plan_id": plan.plan_id, "name": plan.name, "phases": len(plan.phases), "duration_hours": plan.estimated_duration_hours}


@router.post("/api/v1/intelex/emulation/phases/{phase_id}/execute")
async def execute_phase(phase_id: str):
    """Execute an emulation phase."""
    phase = emulation_engine.execute_phase(phase_id)
    return {"phase_id": phase.phase_id, "phase_name": phase.phase_name, "status": phase.status}


@router.get("/api/v1/intelex/emulation/plans/{plan_id}/gaps")
async def get_gap_analysis(plan_id: str):
    """Get detection gap analysis."""
    gaps = emulation_engine.get_gap_analysis(plan_id)
    return {
        "plan_id": plan_id,
        "total_gaps": len(gaps),
        "critical_gaps": sum(1 for g in gaps if g.severity == "critical"),
        "gaps": [
            {"technique": g.technique_id, "severity": g.severity, "remediation": g.remediation}
            for g in gaps[:10]
        ],
    }


@router.get("/api/v1/intelex/emulation/report")
async def get_report():
    """Get adversary emulation report."""
    return emulation_engine.get_report()
