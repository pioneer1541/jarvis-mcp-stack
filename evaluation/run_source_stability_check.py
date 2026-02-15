#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _safe_call(fn, *args, **kwargs):
    t0 = time.time()
    try:
        out = fn(*args, **kwargs)
        return {"ok": True, "out": out, "elapsed_ms": int((time.time() - t0) * 1000), "error": ""}
    except Exception as e:
        return {"ok": False, "out": None, "elapsed_ms": int((time.time() - t0) * 1000), "error": str(e)}


def _count_nonempty_str_list(v):
    if not isinstance(v, list):
        return 0
    n = 0
    for it in v:
        if str(it or "").strip():
            n += 1
    return n


def run(app_mod, criteria, loops):
    news_topics = ["热门", "本地新闻", "科技新闻", "AI新闻", "世界新闻"]
    finance_cases = [
        "特斯拉今天股价怎样",
        "AAPL 股价",
        "比特币今天价格",
        "澳元兑人民币汇率",
        "黄金价格今天多少"
    ]

    news_rows = []
    for i in range(loops):
        for tp in news_topics:
            res = _safe_call(app_mod.skill_news_brief, tp, 10)
            facts_n = _count_nonempty_str_list((res.get("out") or {}).get("facts") if isinstance(res.get("out"), dict) else [])
            news_rows.append({
                "topic": tp,
                "ok": bool(res.get("ok")),
                "elapsed_ms": int(res.get("elapsed_ms") or 0),
                "facts_count": facts_n,
                "error": str(res.get("error") or "")
            })

    finance_rows = []
    for i in range(loops):
        for q in finance_cases:
            res = _safe_call(app_mod.skill_answer_question, q, "local_first")
            out = res.get("out") if isinstance(res.get("out"), dict) else {}
            ft = str((out.get("final_text") if isinstance(out, dict) else "") or "").strip()
            finance_rows.append({
                "query": q,
                "ok": bool(res.get("ok")),
                "elapsed_ms": int(res.get("elapsed_ms") or 0),
                "has_answer": bool(len(ft) >= 6),
                "route": str(((out.get("meta") or {}).get("route") if isinstance(out, dict) else "") or ""),
                "error": str(res.get("error") or "")
            })

    news_total = len(news_rows)
    news_timeout = 0
    news_empty = 0
    for r in news_rows:
        if (not r.get("ok")) or ("timeout" in str(r.get("error") or "").lower()):
            news_timeout += 1
        if int(r.get("facts_count") or 0) == 0:
            news_empty += 1

    fin_total = len(finance_rows)
    fin_timeout = 0
    fin_noanswer = 0
    for r in finance_rows:
        if (not r.get("ok")) or ("timeout" in str(r.get("error") or "").lower()):
            fin_timeout += 1
        if not bool(r.get("has_answer")):
            fin_noanswer += 1

    news_timeout_rate = (float(news_timeout) / float(news_total)) if news_total else 0.0
    news_empty_rate = (float(news_empty) / float(news_total)) if news_total else 0.0
    fin_timeout_rate = (float(fin_timeout) / float(fin_total)) if fin_total else 0.0
    fin_noanswer_rate = (float(fin_noanswer) / float(fin_total)) if fin_total else 0.0

    th = criteria.get("thresholds") if isinstance(criteria, dict) else {}
    ok = True
    if news_timeout_rate > float(th.get("news_timeout_rate_max") or 1.0):
        ok = False
    if news_empty_rate > float(th.get("news_empty_rate_max") or 1.0):
        ok = False
    if fin_timeout_rate > float(th.get("finance_timeout_rate_max") or 1.0):
        ok = False
    if fin_noanswer_rate > float(th.get("finance_noanswer_rate_max") or 1.0):
        ok = False

    return {
        "ts": int(time.time()),
        "ok": ok,
        "summary": {
            "news_total": news_total,
            "news_timeout": news_timeout,
            "news_empty": news_empty,
            "news_timeout_rate": round(news_timeout_rate, 4),
            "news_empty_rate": round(news_empty_rate, 4),
            "finance_total": fin_total,
            "finance_timeout": fin_timeout,
            "finance_noanswer": fin_noanswer,
            "finance_timeout_rate": round(fin_timeout_rate, 4),
            "finance_noanswer_rate": round(fin_noanswer_rate, 4)
        },
        "thresholds": th,
        "samples": {
            "news": news_rows[:20],
            "finance": finance_rows[:20]
        }
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--loops", type=int, default=2)
    args = ap.parse_args()

    criteria = _load_json(args.criteria)

    root = "/app"
    if os.path.isdir(root) and (root not in sys.path):
        sys.path.insert(0, root)
    import app as app_mod

    report = run(app_mod, criteria, max(1, int(args.loops)))
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps(report.get("summary") or {}, ensure_ascii=False))
    if not bool(report.get("ok")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
