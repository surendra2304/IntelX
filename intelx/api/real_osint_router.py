"""
intelx/api/real_osint_router.py — FastAPI router wiring real OSINT engine modules.

Exposes the IntelX real_*.py modules as HTTP endpoints:
- GET  /v1/real-osint/intelx/search?selector=...      — Intelligence X search
- GET  /v1/real-osint/intelx/phonebook?selector=...    — Intelligence X phonebook
- GET  /v1/real-osint/intelx/buckets                   — List IntelX buckets
- POST /v1/real-osint/intelx/search                   — Search with filters
- GET  /v1/real-osint/intelbase/email?email=...        — IntelBase email lookup
- GET  /v1/real-osint/intelbase/username?username=...  — IntelBase username lookup
- POST /v1/real-osint/shadowdragon/emails              — Generate email candidates
- POST /v1/real-osint/shadowdragon/dorks               — Generate Google dorks
- POST /v1/real-osint/shadowdragon/checklist           — Generate OSINT checklist
- GET  /v1/real-osint/shadowdragon/sources             — List OSINT sources
- POST /v1/real-osint/shadowdragon/forensics           — Image forensics (ELA + metadata)
- GET  /v1/real-osint/maltego/graph                    — Maltego graph info
- POST /v1/real-osint/maltego/graph/build              — Build Maltego graph
- POST /v1/real-osint/maltego/graph/analyze            — Analyze Maltego graph
- POST /v1/real-osint/maltego/transform                — Run Maltego transform
- POST /v1/real-osint/maltego/alert                    — Create Horizon alert
- GET  /v1/real-osint/maltego/training                 — List training modules
- GET  /v1/real-osint/maltego/alerts                   — List alerts
- POST /v1/real-osint/maltego/malnet                   — MalNet IDS correlation
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, HTTPException, Query

real_osint_router = APIRouter(tags=["Real OSINT Engines"])


# ─── Import with fallback ────────────────────────────────────────────────────

def _import_osint():
    """Import IntelX OSINT modules with dual-path fallback."""
    osint: dict[str, Any] = {}
    try:
        from IntelX.app.agents.real_intelx_osint import (
            IntelXSelector, IntelXBucket, IntelXSearchEngine, IntelXSearchQuery,
            IntelXPhonebook, IntelBaseEmailLookup, IntelBaseUsernameLookup,
            EmailPermutator, GoogleDorkAssistant, ImageForensics,
            OSINTChecklistGenerator, OpenSourcesToolkit, IntelXOSINTEngine,
        )
        osint["selector"] = IntelXSelector
        osint["bucket"] = IntelXBucket
        osint["search_engine"] = IntelXSearchEngine
        osint["search_query"] = IntelXSearchQuery
        osint["phonebook"] = IntelXPhonebook
        osint["email_lookup"] = IntelBaseEmailLookup
        osint["username_lookup"] = IntelBaseUsernameLookup
        osint["permutator"] = EmailPermutator
        osint["dork_assistant"] = GoogleDorkAssistant
        osint["image_forensics"] = ImageForensics
        osint["checklist_gen"] = OSINTChecklistGenerator
        osint["toolkit"] = OpenSourcesToolkit
        osint["engine"] = IntelXOSINTEngine
    except Exception:
        pass

    graph: dict[str, Any] = {}
    try:
        from IntelX.app.agents.real_maltego_graph import (
            MaltegoEntity, MaltegoRelationship, MaltegoGraph,
            MaltegoTransformRegistry, MaltegoGraphAnalyzer,
            MalNetEngine, HorizonMonitorEngine, ShadowDragonTrainingCatalog,
            MaltegoOSINTEngine,
        )
        graph["entity"] = MaltegoEntity
        graph["relationship"] = MaltegoRelationship
        graph["graph"] = MaltegoGraph
        graph["registry"] = MaltegoTransformRegistry
        graph["analyzer"] = MaltegoGraphAnalyzer
        graph["malnet"] = MalNetEngine
        graph["horizon"] = HorizonMonitorEngine
        graph["training"] = ShadowDragonTrainingCatalog
        graph["engine"] = MaltegoOSINTEngine
    except Exception:
        pass

    return osint, graph


_OSINT_MODS: dict[str, Any] = {}
_GRAPH_MODS: dict[str, Any] = {}


def get_osint_mods() -> dict[str, Any]:
    if not _OSINT_MODS:
        _OSINT_MODS.update(_import_osint()[0])
    return _OSINT_MODS


def get_graph_mods() -> dict[str, Any]:
    if not _GRAPH_MODS:
        _GRAPH_MODS.update(_import_osint()[1])
    return _GRAPH_MODS


# ─── Intelligence X ──────────────────────────────────────────────────────────

@real_osint_router.get("/v1/real-osint/intelx/buckets")
def intelx_buckets():
    """List all available Intelligence X buckets."""
    mods = get_osint_mods()
    if "bucket" not in mods:
        raise HTTPException(503, "IntelX OSINT module not available")
    return {
        "status": "ok",
        "all_buckets": mods["bucket"].all_buckets(),
        "pro_buckets": mods["bucket"].pro_buckets(),
    }


@real_osint_router.get("/v1/real-osint/intelx/search")
def intelx_search(
    selector: str = Query(..., description="Selector to search (email, domain, IP, etc.)"),
    limit: int = Query(100, ge=1, le=1000),
    sort: str = Query("relevance", pattern="^(relevance|newest|oldest)$"),
):
    """Search Intelligence X by selector."""
    mods = get_osint_mods()
    if "search_engine" not in mods:
        raise HTTPException(503, "IntelX OSINT module not available")

    selector_type = mods["selector"].classify(selector)
    engine = mods["search_engine"]()
    results = engine.search_by_selector(selector, limit=limit, sort_order=sort)
    return {
        "status": "ok",
        "selector": selector,
        "selector_type": selector_type,
        "result_count": len(results),
        "results": [
            {
                "id": r.result_id, "bucket": r.bucket, "score": r.score,
                "size_bytes": r.size, "date": r.date, "media_type": r.media_type,
            }
            for r in results[:20]
        ],
    }


@real_osint_router.post("/v1/real-osint/intelx/search")
def intelx_search_post(body: dict):
    """Search Intelligence X with full query parameters."""
    mods = get_osint_mods()
    if "search_engine" not in mods:
        raise HTTPException(503, "IntelX OSINT module not available")

    selector = body.get("selector", "")
    buckets = body.get("buckets", [])
    sort_order = body.get("sort_order", "relevance")
    limit = body.get("limit", 100)

    engine = mods["search_engine"]()
    query = mods["search_query"](
        selector=selector, buckets=buckets, sort_order=sort_order, limit=limit
    )
    results = engine.search(query)
    return {
        "status": "ok",
        "selector": selector,
        "result_count": len(results),
        "unique_buckets": engine.get_unique_buckets(),
        "results": [
            {"id": r.result_id, "bucket": r.bucket, "score": r.score}
            for r in results[:20]
        ],
    }


@real_osint_router.get("/v1/real-osint/intelx/phonebook")
def intelx_phonebook(
    selector: str = Query(...),
    lookup_type: str = Query("all", pattern="^(all|domains|emails|urls)$"),
):
    """Perform Intelligence X phonebook lookup."""
    mods = get_osint_mods()
    if "phonebook" not in mods:
        raise HTTPException(503, "IntelX OSINT module not available")

    phonebook = mods["phonebook"]()
    result = phonebook.lookup(selector, lookup_type)
    return {
        "status": "ok",
        "selector": selector,
        "lookup_type": lookup_type,
        "result": result,
    }


# ─── IntelBase ────────────────────────────────────────────────────────────────

@real_osint_router.get("/v1/real-osint/intelbase/email")
def intelbase_email(email: str = Query(...)):
    """Lookup an email on IntelBase (580+ platforms)."""
    mods = get_osint_mods()
    if "email_lookup" not in mods:
        raise HTTPException(503, "IntelBase module not available")

    lookup = mods["email_lookup"]().lookup(email)
    return {
        "status": "ok",
        "query": email,
        "platform_count": lookup.platform_count,
        "breach_count": lookup.breach_count,
        "infostealer_count": lookup.infostealer_count,
        "assessment": {
            "authenticity": lookup.assessment.authenticity,
            "exposure": lookup.assessment.exposure,
            "ownership_score": lookup.assessment.ownership_score,
            "overall_risk": lookup.assessment.overall_risk,
        },
        "accounts": [
            {"platform": a.platform, "username": a.username, "last_seen": a.last_seen}
            for a in lookup.accounts[:20]
        ],
    }


@real_osint_router.get("/v1/real-osint/intelbase/username")
def intelbase_username(username: str = Query(...)):
    """Lookup a username on IntelBase (620+ platforms)."""
    mods = get_osint_mods()
    if "username_lookup" not in mods:
        raise HTTPException(503, "IntelBase module not available")

    lookup = mods["username_lookup"]().lookup(username)
    return {
        "status": "ok",
        "query": username,
        "platform_count": lookup.platform_count,
        "breach_count": lookup.breach_count,
        "assessment": {
            "authenticity": lookup.assessment.authenticity,
            "exposure": lookup.assessment.exposure,
            "overall_risk": lookup.assessment.overall_risk,
        },
        "accounts": [
            {"platform": a.platform, "username": a.username}
            for a in lookup.accounts[:20]
        ],
    }


# ─── ShadowDragon Tradecraft ─────────────────────────────────────────────────

@real_osint_router.post("/v1/real-osint/shadowdragon/emails")
def shadowdragon_emails(body: dict):
    """Generate email candidates from a name."""
    mods = get_osint_mods()
    if "permutator" not in mods:
        raise HTTPException(503, "ShadowDragon module not available")

    first = body.get("first_name", "John")
    last = body.get("last_name", "Smith")
    org = body.get("org_domain", "")
    locale = body.get("locale", "en")

    perm = mods["permutator"]()
    candidates = perm.generate(first, last, org_domain=org, locale=locale)
    scored = perm.score(candidates)
    return {
        "status": "ok",
        "candidate_count": len(scored),
        "candidates": [
            {"email": c.email, "format": c.format, "confidence": c.confidence}
            for c in scored[:30]
        ],
    }


@real_osint_router.post("/v1/real-osint/shadowdragon/dorks")
def shadowdragon_dorks(body: dict):
    """Generate Google dorks from a research goal."""
    mods = get_osint_mods()
    if "dork_assistant" not in mods:
        raise HTTPException(503, "ShadowDragon module not available")

    goal = body.get("research_goal", "")
    dork_type = body.get("dork_type", "all")

    dork = mods["dork_assistant"]()
    results = dork.generate(goal, dork_type=dork_type)
    return {
        "status": "ok",
        "dork_count": len(results),
        "dorks": results,
    }


@real_osint_router.post("/v1/real-osint/shadowdragon/checklist")
def shadowdragon_checklist(body: dict):
    """Generate an OSINT investigation checklist."""
    mods = get_osint_mods()
    if "checklist_gen" not in mods:
        raise HTTPException(503, "ShadowDragon module not available")

    target_type = body.get("target_type", "person")
    custom = body.get("custom_steps", [])

    gen = mods["checklist_gen"]()
    result = gen.generate(target_type, custom_steps=custom)
    return {
        "status": "ok",
        "target_type": target_type,
        "total_steps": result["total_steps"],
        "steps": result["steps"],
    }


@real_osint_router.get("/v1/real-osint/shadowdragon/sources")
def shadowdragon_sources(category: str = Query("all")):
    """List curated OSINT sources by category."""
    mods = get_osint_mods()
    if "toolkit" not in mods:
        raise HTTPException(503, "ShadowDragon module not available")

    toolkit = mods["toolkit"]()
    sources = toolkit.get_sources(category)
    return {
        "status": "ok",
        "category": category,
        "source_count": len(sources),
        "sources": sources,
    }


@real_osint_router.post("/v1/real-osint/shadowdragon/forensics")
def shadowdragon_forensics(body: dict):
    """Analyze an image for ELA and metadata."""
    mods = get_osint_mods()
    if "image_forensics" not in mods:
        raise HTTPException(503, "ShadowDragon module not available")

    image_b64 = body.get("image_base64", "")
    if not image_b64:
        raise HTTPException(400, "image_base64 required")

    try:
        image_data = base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(400, "Invalid base64 image data")

    forensics = mods["image_forensics"]()
    ela = forensics.compute_ela(image_data)
    metadata = forensics.extract_metadata(image_data)
    return {
        "status": "ok",
        "ela": {
            "edited_regions": ela["edited_regions"],
            "total_regions": len(ela["regions"]),
        },
        "metadata": metadata,
    }


# ─── Maltego Graph ────────────────────────────────────────────────────────────

@real_osint_router.get("/v1/real-osint/maltego/graph")
def maltego_graph_info():
    """Return Maltego graph engine status."""
    mods = get_graph_mods()
    if "engine" not in mods:
        raise HTTPException(503, "Maltego module not available")

    engine = mods["engine"]()
    return {
        "status": "ok",
        "entity_count": engine.graph.entity_count,
        "relationship_count": engine.graph.relationship_count,
        "registered_transforms": len(engine.registry.transforms),
        "training_modules": len(engine.training.modules),
    }


@real_osint_router.post("/v1/real-osint/maltego/graph/build")
def maltego_graph_build(body: dict):
    """Build a Maltego graph from entities."""
    mods = get_graph_mods()
    if "graph" not in mods:
        raise HTTPException(503, "Maltego module not available")

    person_name = body.get("person_name", "Unknown")
    email = body.get("email", "")
    company = body.get("company", "")

    engine = mods["engine"]()
    graph = engine.create_person_graph(person_name, email=email, company=company)
    return {
        "status": "ok",
        "entity_count": graph.entity_count,
        "relationship_count": graph.relationship_count,
        "export": graph.export_graph(),
    }


@real_osint_router.post("/v1/real-osint/maltego/graph/analyze")
def maltego_graph_analyze(body: dict):
    """Analyze a Maltego graph."""
    mods = get_graph_mods()
    if "analyzer" not in mods:
        raise HTTPException(503, "Maltego module not available")

    engine = mods["engine"]()
    engine.create_person_graph(
        body.get("person_name", "Unknown"),
        email=body.get("email", ""),
    )
    analysis = engine.analyze_graph()
    return {"status": "ok", "analysis": analysis}


@real_osint_router.post("/v1/real-osint/maltego/transform")
def maltego_transform(body: dict):
    """Run a Maltego transform on a graph entity."""
    mods = get_graph_mods()
    if "registry" not in mods:
        raise HTTPException(503, "Maltego module not available")

    transform_id = body.get("transform_id", "person.to.company")
    engine = mods["engine"]()
    engine.create_person_graph(body.get("person_name", "Unknown"))
    person = engine.graph.get_entities_by_type("person")[0]
    outputs = engine.run_transform_chain([transform_id], person.entity_id)
    return {
        "status": "ok",
        "transform_id": transform_id,
        "output_count": len(outputs),
        "outputs": [
            {"type": o.entity_type, "value": o.entity_value}
            for o in outputs
        ],
    }


@real_osint_router.post("/v1/real-osint/maltego/alert")
def maltego_alert(body: dict):
    """Create a Horizon Monitor alert."""
    mods = get_graph_mods()
    if "horizon" not in mods:
        raise HTTPException(503, "Horizon Monitor module not available")

    subject = body.get("subject", "")
    alert_type = body.get("alert_type", "username")

    engine = mods["engine"]()
    alert = engine.create_alert(subject, alert_type=alert_type)
    return {
        "status": "ok",
        "alert_id": alert.alert_id,
        "subject": alert.subject,
        "severity": alert.severity,
        "match_count": alert.match_count,
    }


@real_osint_router.get("/v1/real-osint/maltego/alerts")
def maltego_alerts():
    """List all Horizon Monitor alerts and stats."""
    mods = get_graph_mods()
    if "horizon" not in mods:
        raise HTTPException(503, "Horizon Monitor module not available")

    engine = mods["engine"]()
    engine.create_alert("test_user")
    engine.create_alert("threat keyword")
    stats = engine.get_alert_stats()
    return {"status": "ok", "stats": stats}


@real_osint_router.get("/v1/real-osint/maltego/training")
def maltego_training(level: str = "beginner"):
    """List ShadowDragon training modules and learning paths."""
    mods = get_graph_mods()
    if "training" not in mods:
        raise HTTPException(503, "Training catalog not available")

    catalog = mods["training"]()
    path = catalog.recommend_learning_path(level)
    return {
        "status": "ok",
        "total_hours": catalog.get_total_training_hours(),
        "total_modules": len(catalog.modules),
        "learning_path": [
            {"id": m.module_id, "title": m.title, "duration": m.duration}
            for m in path
        ],
    }


@real_osint_router.post("/v1/real-osint/maltego/malnet")
def malnet_correlate(body: dict):
    """Correlate indicators against MalNet IDS data."""
    mods = get_graph_mods()
    if "malnet" not in mods:
        raise HTTPException(503, "MalNet module not available")

    engine = mods["malnet"]()
    result = engine.correlate(
        ip=body.get("ip", ""),
        domain=body.get("domain", ""),
        hash_val=body.get("hash", ""),
    )
    return {"status": "ok", "correlation": result}
