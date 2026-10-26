"""Robin-style investigation lifecycle owned by IntelX, with durable case history."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from threading import RLock
from typing import Callable
import uuid


def sibling(name: str):
    key = f"intelx_research_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, Path(__file__).with_name(name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


@dataclass
class Investigation:
    investigation_id: str
    query: str
    preset: str
    refined_query: str = ""
    search_id: str = ""
    custom_instructions: str = ""
    use_cloud_model: bool = False
    status: str = "running"
    stages: list[dict] = field(default_factory=list)
    search_stats: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    summary: str = ""
    pivots: list[str] = field(default_factory=list)
    intel: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0


class InvestigationStore:
    """Transactional storage; generated IDs only, no user-controlled filenames."""

    def __init__(self, directory: str) -> None:
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.path = str(Path(directory) / "investigations.sqlite3")
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, started REAL, query TEXT, body TEXT)")

    def save(self, record: Investigation) -> None:
        stored = asdict(record)
        # Match Robin's saved-case privacy boundary: raw page text stays in the
        # request/session process only; durable cases retain report + citations.
        for source in stored.get("sources", []):
            source["text"] = ""
        stored["raw_evidence_persisted"] = False
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO cases VALUES (?, ?, ?, ?)",
                       (record.investigation_id, record.started_at, record.query, json.dumps(stored)))

    def get(self, case_id: str) -> dict:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT body FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not row:
            raise KeyError(case_id)
        return json.loads(row[0])

    def list(self, query: str = "", limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT body FROM cases WHERE instr(lower(query), lower(?)) > 0 ORDER BY started DESC LIMIT ?",
                              (query, limit)).fetchall()
        return [{k: record[k] for k in ("investigation_id", "query", "preset", "status", "started_at")}
                for record in (json.loads(row[0]) for row in rows)]

    def delete(self, case_id: str) -> bool:
        with sqlite3.connect(self.path) as db:
            return bool(db.execute("DELETE FROM cases WHERE id = ?", (case_id,)).rowcount)


class InvestigationEngine:
    PRESETS = {"threat_intel", "ransomware_malware", "personal_identity", "corporate_espionage"}

    def __init__(self, threat_engine, directory: str, endpoints: list[str] | None = None,
                 collector=None, ingest: Callable | None = None, analyzer=None) -> None:
        config = sibling("real_robin_config")
        if endpoints is None:
            endpoints = [url for _, url in config.DEFAULT_SEARCH_ENGINES]
        policy = sibling("real_onion_research").OnionResearchEngine(endpoints)
        self.policy = policy
        self.collector = collector or sibling("real_research_transport").ResearchCollector(policy)
        self.endpoints = tuple(endpoints or [])
        if len(self.endpoints) > 32:
            raise ValueError("at most 32 onion search endpoints may be configured")
        for endpoint in self.endpoints:
            if len(endpoint) > 2048 or endpoint.count("{query}") != 1:
                raise ValueError("each endpoint needs one query placeholder")
            policy.validate(endpoint.replace("{query}", "test"))
        self.threat_engine = threat_engine
        self.ingest = ingest or threat_engine.ingest_research
        self.analyzer = analyzer
        if self.analyzer is None:
            try:
                self.analyzer = sibling("real_robin_llm").GroqResearchAnalyzer.from_environment()
            except (ValueError, ImportError):
                self.analyzer = None
        self.presets = config.DEFAULT_PRESETS
        self.store = InvestigationStore(directory)
        self._sessions: dict[str, dict] = {}
        self._session_lock = RLock()
        self.session_ttl = 3600
        self.max_sessions = 200

    @staticmethod
    def terms(text: str) -> set[str]:
        words = {word.casefold() for word in re.findall(r"[\w@.:-]+", text) if len(word) > 2}
        # Let a natural-language question such as "which CVE" match a complete
        # identifier while retaining the whole exact IOC for precise pivots.
        for word in tuple(words):
            words.update(part for part in re.split(r"[-_.:]+", word) if len(part) > 2)
        return words

    @staticmethod
    def refine(query: str) -> str:
        # Local no-model fallback follows Robin's five-word ceiling without
        # adding topics; exact technical tokens are retained preferentially.
        tokens = re.findall(r"(?:[a-fA-F0-9]{64}|CVE-\d{4}-\d{4,7}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|[a-zA-Z0-9.-]+\.onion|https?://[^\s]+|[\w'-]+)", query)
        stop = {"what", "when", "where", "who", "which", "why", "how", "is", "are", "was", "were", "the", "a", "an", "and", "or", "not", "for", "of", "to", "in", "on", "with", "about", "please", "find", "search"}
        special = [t for t in tokens if t.lower().startswith("cve-") or "@" in t or t.lower().endswith(".onion") or t.startswith("http") or re.fullmatch(r"[a-fA-F0-9]{64}", t)]
        ordinary = [t for t in tokens if t.lower() not in stop and t not in special]
        chosen = list(dict.fromkeys((special + ordinary)[:5]))
        return " ".join(chosen) or " ".join(query.split()[:5])

    def refine_query(self, query: str, use_cloud_model: bool = False) -> str:
        refined = self.analyzer.refine(query) if use_cloud_model and self.analyzer else None
        return refined or self.refine(query)

    def search(self, query: str, preset: str, user_chose_preset: bool,
               max_results: int = 30, per_host_limit: int = 3, threads: int = 4,
               allow_clearweb: bool = False, use_cloud_model: bool = False) -> dict:
        """Federated Robin search stage. Preset consent is explicit."""
        query = " ".join(query.split())
        if not user_chose_preset or preset not in self.PRESETS:
            return {"status": "preset_not_selected", "results": [],
                    "message": "Select one research domain before starting a Robin search."}
        if not query or len(query) > 2000 or not 1 <= max_results <= 100 or not 1 <= per_host_limit <= 100 or not 1 <= threads <= 16:
            raise ValueError("invalid query or search budgets")
        if not self.endpoints:
            return {"status": "not_configured", "results": [], "search_stats": {"engines_queried": 0}}
        outcomes = []
        with ThreadPoolExecutor(max_workers=threads) as pool:
            outcomes = list(pool.map(lambda endpoint: self.collector.search(endpoint, query, allow_clearweb=allow_clearweb), self.endpoints))
        stats = {"engines_queried": len(self.endpoints),
                 "engines_answered": sum(item.get("status") == "ok" for item in outcomes),
                 "engines_empty": sum(item.get("status") == "empty" for item in outcomes),
                 "engines_failed": sum(item.get("status") not in {"ok", "empty"} for item in outcomes),
                 "engines": [{k: v for k, v in item.items() if k != "results"} for item in outcomes]}
        raw = [hit for outcome in outcomes for hit in outcome.get("results", [])]
        research = sibling("real_onion_research")
        batch = self.policy.process([research.ResearchHit(str(hit.get("title", "")), str(hit.get("url", ""))) for hit in raw],
                                    per_host_limit=per_host_limit, allow_clearweb=allow_clearweb)
        stats.update({k: v for k, v in asdict(batch).items() if k != "hits"})
        if not any(item.get("status") in {"ok", "empty"} for item in outcomes):
            status = "engines_unreachable"
        elif not batch.hits:
            status = "no_results"
        else:
            status = "ok"
        search_id = uuid.uuid4().hex
        results = [{"id": f"r{i+1}-{uuid.uuid4().hex[:8]}", "title": hit.title, "url": hit.url}
                   for i, hit in enumerate(batch.hits[:max_results])]
        now = time.monotonic()
        with self._session_lock:
            for key in list(self._sessions):
                if now - self._sessions[key]["created_monotonic"] > self.session_ttl:
                    del self._sessions[key]
            while len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions, key=lambda k: self._sessions[k]["created_monotonic"])
                del self._sessions[oldest]
            self._sessions[search_id] = {"created_monotonic": now, "query": query, "preset": preset,
                "allow_clearweb": allow_clearweb, "use_cloud_model": use_cloud_model,
                "results": results, "search_stats": stats,
                "filtered_ids": set(), "sources": []}
        return {"status": status, "search_id": search_id, "query": query,
                "search_stats": stats, "results": results}

    def filter(self, search_id: str, query: str, max_scrape: int = 10,
               use_cloud_model: bool | None = None) -> dict:
        """Select relevant results; only returned IDs may be scraped."""
        if not 1 <= max_scrape <= 100 or len(query) > 2000:
            raise ValueError("invalid filter limits")
        with self._session_lock:
            session = self._sessions.get(search_id)
            if not session: raise KeyError(search_id)
            results = list(session["results"])
            use_cloud = session["use_cloud_model"] if use_cloud_model is None else use_cloud_model
        if not results:
            return {"search_id": search_id, "status": "nothing_relevant", "results": []}
        chosen = self.analyzer.filter_results(query, results) if use_cloud and self.analyzer else None
        if chosen is None:
            terms = self.terms(query)
            ranked = sorted(((len(terms & self.terms(item["title"]+" "+item["url"])), index)
                             for index,item in enumerate(results)), key=lambda x:(-x[0],x[1]))
            chosen = [index for score,index in ranked if score > 0]
        filtered = [results[index] for index in chosen[:max_scrape] if 0 <= index < len(results)]
        with self._session_lock:
            session = self._sessions.get(search_id)
            if session is None: raise KeyError(search_id)
            session["filtered_ids"] = [item["id"] for item in filtered]
        return {"search_id": search_id, "status": "ok" if filtered else "nothing_relevant", "results": filtered}

    def scrape(self, search_id: str, result_ids: list[str] | None = None,
               threads: int = 4, content_chars: int = 12000,
               allow_clearweb: bool | None = None) -> dict:
        """Fetch only explicitly filtered result IDs, revalidating every redirect."""
        if not 1 <= threads <= 16 or not 500 <= content_chars <= 100000:
            raise ValueError("invalid scrape limits")
        with self._session_lock:
            session = self._sessions.get(search_id)
            if not session: raise KeyError(search_id)
            filtered_ids = list(session["filtered_ids"])
            allowed_ids = set(filtered_ids)
            by_id = {row["id"]: row for row in session["results"]}
            permission = session["allow_clearweb"] if allow_clearweb is None else bool(allow_clearweb)
        selected_ids = list(dict.fromkeys(result_ids if result_ids is not None else filtered_ids))
        if any(item not in allowed_ids for item in selected_ids):
            raise ValueError("scrape accepts only IDs returned by the relevance filter")
        if not selected_ids:
            return {"search_id": search_id, "status": "nothing_readable", "sources": []}
        selected = [by_id[item] for item in selected_ids]
        with ThreadPoolExecutor(max_workers=threads) as pool:
            pages = list(pool.map(lambda row: self.collector.fetch(row["url"], allow_clearweb=permission), selected))
        sources = []
        for hit, page in zip(selected, pages):
            sources.append({"url": page.url, "title": hit["title"], "status": page.status,
                            "text": page.text[:content_chars] if page.status == "ok" else "",
                            "links": getattr(page, "links", [])})
        with self._session_lock:
            session = self._sessions.get(search_id)
            if session is None: raise KeyError(search_id)
            session["sources"] = sources
        docs = [{"url": src["url"], "title": src["title"], "text": src["text"]}
                for src in sources if src["status"] == "ok" and src["text"]]
        return {"search_id": search_id, "status": "ok" if docs else "nothing_readable", "sources": sources}

    def health(self) -> dict:
        ready = None
        if hasattr(self.collector, "health"):
            try: ready = self.collector.health()
            except Exception: ready = {"proxy_ready": False}
        llm = self.analyzer.health if self.analyzer else {"configured": False, "models": []}
        return {"configured_engines": len(self.endpoints), "tor": ready, "llm": llm,
                "local_fallback": "deterministic extractive analysis"}

    def list_models(self) -> dict:
        if self.analyzer:
            return {"configured": True, "models": list(self.analyzer.models), "source": "operator configured"}
        return {"configured": False, "models": [], "source": "no cloud LLM key; local extractive pipeline remains available"}

    def run(self, query: str, preset: str, user_chose_preset: bool = False,
            custom_instructions: str = "", use_cloud_model: bool = False,
            max_results: int = 30, max_scrape: int = 10,
            threads: int = 4, content_chars: int = 12000, per_host_limit: int = 3,
            allow_clearweb: bool = False, on_stage: Callable | None = None) -> dict:
        if not query.strip() or len(query) > 2000 or preset not in self.PRESETS or not user_chose_preset:
            raise ValueError("query and an explicitly selected research preset are required")
        custom_instructions = " ".join(custom_instructions.split())
        if len(custom_instructions) > 5000:
            raise ValueError("custom instructions exceed 5000 characters")
        if not (1 <= max_scrape <= max_results <= 100 and 1 <= threads <= 16 and
                500 <= content_chars <= 100000 and 1 <= per_host_limit <= 100):
            raise ValueError("invalid investigation budgets")
        inv = Investigation(uuid.uuid4().hex, query, preset, custom_instructions=custom_instructions,
                            use_cloud_model=use_cloud_model)
        stage = "refine"
        def emit(name: str):
            nonlocal stage
            stage = name
            inv.stages.append({"stage": name, "timestamp": time.time()})
            if on_stage: on_stage(name, inv.investigation_id)
        try:
            emit("refine")
            inv.refined_query = self.refine_query(query, use_cloud_model)
            emit("search")
            found = self.search(inv.refined_query, preset, True, max_results, per_host_limit, threads,
                                allow_clearweb, use_cloud_model)
            inv.search_id = found.get("search_id", "")
            inv.search_stats = found.get("search_stats", {})
            if found["status"] == "engines_unreachable": inv.status = "engines_unreachable"
            elif found["status"] == "not_configured": inv.status = "not_configured"
            elif found["status"] == "no_results": inv.status = "no_results"
            else:
                emit("filter")
                filtered = self.filter(inv.search_id, inv.refined_query, max_scrape, use_cloud_model)
                if not filtered["results"]:
                    inv.status = "nothing_relevant"
                else:
                    emit("scrape")
                    scraped = self.scrape(inv.search_id, [item["id"] for item in filtered["results"]],
                                          threads, content_chars, allow_clearweb)
                    inv.sources = scraped["sources"]
                    docs = [{k: src[k] for k in ("url", "title", "text")} for src in inv.sources
                            if src["status"] == "ok" and src["text"]]
                    if not docs: inv.status = "nothing_readable"
                    else:
                        emit("analyze")
                        inv.intel = self.ingest(docs, per_host_limit=per_host_limit,
                                                allow_clearweb=allow_clearweb)
                        emit("summarize")
                        guidance = self.presets[preset][1]
                        if custom_instructions:
                            guidance += "\n\nOperator-supplied focus (not a source claim): " + custom_instructions
                        inv.summary = ((self.analyzer.summarize(query, preset, guidance, docs)
                                        if use_cloud_model and self.analyzer else None) or self.summarize(query, preset, docs))
                        emit("pivots")
                        pivots = self.analyzer.pivots(query, docs) if use_cloud_model and self.analyzer else None
                        artifacts = sorted(set(re.findall(r"\bCVE-\d{4}-\d{4,7}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
                                                          " ".join(d["text"] for d in docs))))
                        link_pivots = [link.get("url", "") for source in inv.sources for link in source.get("links", [])]
                        inv.pivots = pivots if pivots is not None else ([f'"{artifact}"' for artifact in artifacts[:5] or link_pivots[:5]])
                        inv.status = "ok"
        except Exception as error:
            inv.status = "failed"
            inv.stages.append({"stage": stage, "error_type": type(error).__name__})
        finally:
            inv.finished_at = time.time()
            self.store.save(inv)
        return asdict(inv)

    def summarize(self, query: str, preset: str, docs: list[dict]) -> str:
        lines = [f"## Query\n{query}", f"## Domain\n{preset}",
                 "## Evidence\nExtractive observations only; source claims are unverified."]
        terms = self.terms(query)
        for doc in docs:
            sentences = re.split(r"(?<=[.!?])\s+|\n+", doc["text"])
            scored = sorted(enumerate(sentences), key=lambda pair: (-len(terms & self.terms(pair[1])), pair[0]))
            extracts = [s[:600] for _, s in scored[:3] if s.strip()]
            lines.append(f"### {doc['url']}\n" + "\n".join(f"> {s}" for s in extracts))
        lines.append("## Next steps\nCorroborate each observation with independent, authorized sources before acting.")
        return "\n\n".join(lines)

    def followup(self, case_id: str, question: str, use_cloud_model: bool = False) -> dict:
        if not question.strip() or len(question) > 2000:
            raise ValueError("question required (maximum 2000 characters)")
        record = self.store.get(case_id)
        if use_cloud_model and self.analyzer:
            answer = self.analyzer.followup(question, record)
            if answer:
                return {"investigation_id": case_id, "question": question, "answer": answer,
                        "sources": [source["url"] for source in record["sources"]]}
        terms = self.terms(question)
        evidence = []
        for source in record["sources"]:
            text = source.get("text", "")
            if not text:
                marker = "### " + source["url"]
                offset = record.get("summary", "").find(marker)
                if offset >= 0:
                    remainder = record["summary"][offset+len(marker):]
                    remainder = re.split(r"\n### |\n## ", remainder, maxsplit=1)[0]
                    text = "\n".join(line[2:] if line.startswith("> ") else line
                                       for line in remainder.splitlines())
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
                score = len(terms & self.terms(sentence))
                if score:
                    evidence.append((score, source["url"], sentence[:1000]))
        evidence.sort(key=lambda row: -row[0])
        return {"investigation_id": case_id, "question": question,
                "answer": "\n".join(f"{s} [{url}]" for _, url, s in evidence[:5]) or
                          "No matching evidence in the saved sources.",
                "sources": list(dict.fromkeys(url for _, url, _ in evidence[:5]))}

    def save_external(self, query: str, preset: str, summary: str, sources: list[dict],
                      pivots: list[str] | None = None, allow_clearweb: bool = False) -> dict:
        """Save a host-prepared report with validated, bounded source metadata."""
        if preset not in self.PRESETS or not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("valid query and preset required")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 200000:
            raise ValueError("summary must contain 1-200000 characters")
        if not isinstance(sources, list) or len(sources) > 100:
            raise ValueError("at most 100 source records allowed")
        safe_sources = []
        for item in sources:
            if not isinstance(item, dict): raise ValueError("sources must be objects")
            url = self.policy.validate(str(item.get("url", "")), allow_clearweb=allow_clearweb)
            title = " ".join(str(item.get("title", "")).split())[:200]
            safe_sources.append({"url": url, "title": title, "status": "metadata_only", "text": "", "links": []})
        pivots = pivots or []
        if not isinstance(pivots, list) or len(pivots) > 10 or any(not isinstance(p, str) or len(p) > 200 for p in pivots):
            raise ValueError("at most ten bounded pivot strings allowed")
        now = time.time()
        record = Investigation(uuid.uuid4().hex, query, preset, status="host_report_saved",
                               sources=safe_sources, summary=summary, pivots=pivots,
                               started_at=now, finished_at=now)
        self.store.save(record)
        return asdict(record)

    def export(self, case_id: str, format: str = "markdown") -> str:
        record = self.store.get(case_id)
        if format == "json":
            return json.dumps(record, indent=2)
        if format != "markdown":
            raise ValueError("format must be markdown or json")
        return record["summary"] or f"## {record['query']}\nStatus: {record['status']}"
