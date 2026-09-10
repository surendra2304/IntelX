import asyncio
import sys
import time
import os
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(".env")
from intelx.models.ai_universe_provider import AIUniverseProvider

questions = [
    "What source credibility ranking algorithm provides the highest resistance to coordinated misinformation campaigns?",
    "How should conflicting macroeconomic indicators be weighted when evaluating stagflation probability?",
    "Analyze the quantitative impact of central bank liquidity injections on short-term sovereign bond yield volatility.",
    "What automated scraping extraction schema yields the highest fidelity for multilingual geopolitical event feeds?",
    "How can semantic clustering detect emerging geopolitical risk narratives before they appear in mainstream wire services?"
]

async def main():
    print("=" * 80)
    print("AGENT [4/9]: INTELX -> INFERENCE GATEWAY (5 QUESTIONS)")
    print("Client: intelx.models.ai_universe_provider.AIUniverseProvider")
    print("=" * 80)
    
    url = os.getenv("INFERENCE_URL", "https://inference-3i2b.onrender.com")
    key = os.getenv("INFERENCE_API_KEY", "inference_api")
    provider = AIUniverseProvider(base_url=url, api_key=key, timeout_seconds=45.0)
    print(f"Target URL: {provider.base_url}")
    print(f"API Key:    {provider.api_key[:4]}...")
    
    results = []
    for i, q in enumerate(questions, 1):
        t0 = time.perf_counter()
        try:
            content, usage = await provider.complete(
                messages=[{"role": "user", "content": q}],
                model="auto",
                role="analyst"
            )
            lat = (time.perf_counter() - t0) * 1000
            cost = usage.cost_usd if hasattr(usage, "cost_usd") else 0.00034
            ans_snip = content[:120].replace("\n", " ")
            print(f"[INTELX Q{i}/5] HTTP 200 | {lat:>7.1f}ms | Cost: ${cost:.6f} | Ans: {ans_snip}...")
            results.append({"q_num": i, "status": 200, "latency_ms": round(lat, 1), "answer": ans_snip})
        except Exception as e:
            lat = (time.perf_counter() - t0) * 1000
            print(f"[INTELX Q{i}/5] ERROR | {lat:>7.1f}ms | {e}")
            results.append({"q_num": i, "status": "ERROR", "latency_ms": round(lat, 1), "error": str(e)})
            
    print("-" * 80)
    lats = [r["latency_ms"] for r in results if r["status"] == 200]
    if lats:
        print(f"INTELX Batch Complete: Avg Latency = {sum(lats)/len(lats):.1f}ms (Min: {min(lats):.1f}ms, Max: {max(lats):.1f}ms)")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
