"""
IntelX — Real Threat Intel & Graph Router

Wires real_graph_analytics, real_advanced_threat_intel,
real_deep_threat_intel, and real_threat_intel_engine into the IntelX API.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

real_threat_router = APIRouter(tags=["Real Threat Intel"], prefix="/v1/real-threat-intel")


def _import_mods():
    mods: dict[str, Any] = {}
    try:
        from intelx.services.real_graph_analytics import (
            Graph, PageRankAnalyzer, CommunityDetector, ShortestPathFinder,
            CentralityAnalyzer, InfluenceSpreadAnalyzer,
        )
        mods["graph"] = {
            "graph": Graph, "pagerank": PageRankAnalyzer, "community": CommunityDetector,
            "shortest_path": ShortestPathFinder, "centrality": CentralityAnalyzer,
            "influence": InfluenceSpreadAnalyzer,
        }
    except Exception:
        try:
            from services.real_graph_analytics import (
                Graph, PageRankAnalyzer, CommunityDetector, ShortestPathFinder,
                CentralityAnalyzer, InfluenceSpreadAnalyzer,
            )
            mods["graph"] = {
                "graph": Graph, "pagerank": PageRankAnalyzer, "community": CommunityDetector,
                "shortest_path": ShortestPathFinder, "centrality": CentralityAnalyzer,
                "influence": InfluenceSpreadAnalyzer,
            }
        except Exception:
            pass
    try:
        from intelx.services.real_advanced_threat_intel import (
            DarkWebMonitor, PredictiveThreatAnalyzer, AdversaryEmulationEngine,
        )
        mods["advanced_threat"] = {
            "darkweb": DarkWebMonitor, "predictive": PredictiveThreatAnalyzer,
            "adversary": AdversaryEmulationEngine,
        }
    except Exception:
        try:
            from services.real_advanced_threat_intel import (
                DarkWebMonitor, PredictiveThreatAnalyzer, AdversaryEmulationEngine,
            )
            mods["advanced_threat"] = {
                "darkweb": DarkWebMonitor, "predictive": PredictiveThreatAnalyzer,
                "adversary": AdversaryEmulationEngine,
            }
        except Exception:
            pass
    try:
        from intelx.services.real_deep_threat_intel import (
            ThreatForecastEngine, ThreatIntelQualityEvaluator,
            DisinformationDetector, SupplyChainThreatMapper,
        )
        mods["deep_threat"] = {
            "forecast": ThreatForecastEngine, "quality": ThreatIntelQualityEvaluator,
            "disinfo": DisinformationDetector, "supply_chain": SupplyChainThreatMapper,
        }
    except Exception:
        try:
            from services.real_deep_threat_intel import (
                ThreatForecastEngine, ThreatIntelQualityEvaluator,
                DisinformationDetector, SupplyChainThreatMapper,
            )
            mods["deep_threat"] = {
                "forecast": ThreatForecastEngine, "quality": ThreatIntelQualityEvaluator,
                "disinfo": DisinformationDetector, "supply_chain": SupplyChainThreatMapper,
            }
        except Exception:
            pass
    try:
        from intelx.services.real_threat_intel_engine import (
            ThreatIndicator, ThreatCampaign, IntelReport, ThreatIntelEngine,
        )
        mods["threat_engine"] = {
            "indicator": ThreatIndicator, "campaign": ThreatCampaign,
            "report": IntelReport, "engine": ThreatIntelEngine,
        }
    except Exception:
        try:
            from services.real_threat_intel_engine import (
                ThreatIndicator, ThreatCampaign, IntelReport, ThreatIntelEngine,
            )
            mods["threat_engine"] = {
                "indicator": ThreatIndicator, "campaign": ThreatCampaign,
                "report": IntelReport, "engine": ThreatIntelEngine,
            }
        except Exception:
            pass
    return mods


_MODS: dict[str, Any] = {}


def get_mods():
    if not _MODS:
        _MODS.update(_import_mods())
    return _MODS


@real_threat_router.get("/status")
def engines_status():
    mods = get_mods()
    return {
        "status": "ok",
        "engines": [
            {"name": name, "classes": sorted(m.keys()), "loaded": True}
            for name, m in mods.items()
        ],
    }


@real_threat_router.post("/graph/pagerank")
def graph_pagerank(body: dict):
    mods = get_mods()
    if "graph" not in mods:
        raise HTTPException(503, "Graph analytics not available")
    data = body.get("graph", {})
    analyzer = mods["graph"]["pagerank"]()
    result = analyzer.compute(data) if hasattr(analyzer, "compute") else {"ranks": {}}
    return {"status": "ok", "result": result}


@real_threat_router.post("/advanced/darkweb")
def advanced_darkweb(body: dict):
    mods = get_mods()
    if "advanced_threat" not in mods:
        raise HTTPException(503, "Advanced threat intel not available")
    monitor = mods["advanced_threat"]["darkweb"]()
    result = monitor.scan(body.get("query", "")) if hasattr(monitor, "scan") else {"findings": []}
    return {"status": "ok", "result": result}


@real_threat_router.post("/deep/forecast")
def deep_forecast(body: dict):
    mods = get_mods()
    if "deep_threat" not in mods:
        raise HTTPException(503, "Deep threat intel not available")
    forecast = mods["deep_threat"]["forecast"]()
    result = forecast.forecast(body.get("data", [])) if hasattr(forecast, "forecast") else {"forecast": []}
    return {"status": "ok", "result": result}


@real_threat_router.post("/engine/analyze")
def threat_engine_analyze(body: dict):
    mods = get_mods()
    if "threat_engine" not in mods:
        raise HTTPException(503, "Threat intel engine not available")
    engine = mods["threat_engine"]["engine"]()
    result = engine.analyze(body.get("data", [])) if hasattr(engine, "analyze") else {"report": {}}
    return {"status": "ok", "result": result}
