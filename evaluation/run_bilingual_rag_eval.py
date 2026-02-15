#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Tuple

import requests


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _extract_top_score(facts: List[str]) -> float:
    if not isinstance(facts, list) or len(facts) <= 0:
        return 0.0
    s0 = str(facts[0] or "").strip()
    m = re.match(r"^\[(\d+(?:\.\d+)?)\]\s+", s0)
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except Exception:
        return 0.0


def _detect_lang(q: str) -> str:
    t = str(q or "")
    if re.search(r"[\u4e00-\u9fff]", t):
        return "zh"
    if re.search(r"[A-Za-z]", t):
        return "en"
    return "other"


def _post_json(url: str, obj: Dict[str, Any], timeout_sec: float) -> Dict[str, Any]:
    r = requests.post(url, json=obj, timeout=timeout_sec)
    r.raise_for_status()
    out = r.json() if hasattr(r, "json") else {}
    return out if isinstance(out, dict) else {}


def run(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Bilingual RAG smoke evaluation (memory_search via gateway).")
    ap.add_argument("--cases", default="evaluation/bilingual50_cases.example.json")
    ap.add_argument("--gateway", default=os.environ.get("GATEWAY_BASE_URL", "http://127.0.0.1:19100"))
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--score-threshold", type=float, default=0.2)
    ap.add_argument("--timeout-sec", type=float, default=25.0)
    ap.add_argument("--out", default="evaluation/bilingual50_report.json")
    args = ap.parse_args(argv)

    cases = _load_json(args.cases)
    queries = cases.get("memory_search_cases") if isinstance(cases, dict) else None
    if not isinstance(queries, list) or len(queries) != 50:
        print("ERROR: expected 50 queries in memory_search_cases (see evaluation/bilingual50_cases.example.json)", file=sys.stderr)
        return 2

    gw = str(args.gateway or "").rstrip("/")
    url = gw + "/invoke/memory_search"

    rows = []
    ok_cnt = 0
    bilingual_cnt = 0
    en_rewrite_cnt = 0
    top_scores: List[float] = []
    hit_counts: List[int] = []

    for q in queries:
        query = str(q or "").strip()
        if not query:
            continue
        payload = {"query": query, "top_k": int(args.top_k), "score_threshold": float(args.score_threshold)}
        t0 = time.time()
        try:
            resp = _post_json(url, payload, timeout_sec=float(args.timeout_sec))
            t1 = time.time()
        except Exception as e:
            rows.append(
                {
                    "query": query,
                    "lang": _detect_lang(query),
                    "ok": False,
                    "error": str(e),
                }
            )
            continue

        result = resp.get("result") if isinstance(resp, dict) else {}
        result = result if isinstance(result, dict) else {}
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        facts = result.get("facts") if isinstance(result.get("facts"), list) else []

        hit_count = int(meta.get("hit_count") or 0)
        top_score = float(_extract_top_score([str(x) for x in facts]))
        q_en = str(meta.get("query_en") or "").strip()
        bilingual = bool(meta.get("bilingual"))
        if bilingual:
            bilingual_cnt += 1
        if q_en:
            en_rewrite_cnt += 1

        ok = (hit_count > 0) and (top_score >= float(args.score_threshold))
        if ok:
            ok_cnt += 1

        if hit_count >= 0:
            hit_counts.append(hit_count)
        if top_score > 0:
            top_scores.append(top_score)

        rows.append(
            {
                "query": query,
                "lang": _detect_lang(query),
                "query_en": q_en,
                "bilingual": bilingual,
                "hit_count": hit_count,
                "top_score": top_score,
                "top_fact": (str(facts[0])[:240] if facts else ""),
                "latency_ms": int((t1 - t0) * 1000),
                "ok": ok,
            }
        )

    total = len(rows)
    ok_rate = (float(ok_cnt) / float(total)) if total else 0.0
    avg_top_score = (sum(top_scores) / float(len(top_scores))) if top_scores else 0.0
    avg_hit_count = (sum(hit_counts) / float(len(hit_counts))) if hit_counts else 0.0

    report = {
        "ok": True,
        "generated_at": _now_iso(),
        "gateway": gw,
        "config": {"top_k": int(args.top_k), "score_threshold": float(args.score_threshold)},
        "summary": {
            "total": int(total),
            "pass": int(ok_cnt),
            "pass_rate": round(ok_rate, 4),
            "avg_top_score": round(avg_top_score, 4),
            "avg_hit_count": round(avg_hit_count, 4),
            "bilingual_meta_true": int(bilingual_cnt),
            "query_en_nonempty": int(en_rewrite_cnt),
        },
        "rows": rows,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Console summary
    print("bilingual50_eval")
    print("out:", args.out)
    print("total:", total, "pass:", ok_cnt, "pass_rate:", round(ok_rate, 4))
    print("avg_top_score:", round(avg_top_score, 4), "avg_hit_count:", round(avg_hit_count, 4))
    print("query_en_nonempty:", en_rewrite_cnt, "bilingual_meta_true:", bilingual_cnt)

    # Show failures (first 10)
    fails = [r for r in rows if not bool(r.get("ok"))]
    if fails:
        print("\nfailures (up to 10):")
        for r in fails[:10]:
            print("-", r.get("query"))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
