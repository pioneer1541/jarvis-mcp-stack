#!/usr/bin/env python3
"""
Eval runner for the MCP project:
- fixed question set
- per-question timing
- heuristic auto-scoring
- JSON report output
- optional HTML rendering (pure standard library)

Default dataset: `evaluation/daily100_report.example.json` (uses its `rows[*].q` only).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple


BAD_PHRASES = [
    "我需要更多上下文",
    "请补充",
    "我没抓到可靠",
    "请再具体",
    "我暂时没拿到可靠结果",
    "没在资料库内容中找到",
    "新闻检索完成，但可用内容较少",
    "我这次没有抓到可用新闻",
    "未找到",
    "超时",
    "失败",
]

# Default targets (override via CLI).
DEFAULT_TARGETS = {
    "pass_rate_min": 0.95,
    "avg_ms_max": 4000,
    "p95_ms_max": 8000,
}

DEFAULT_HA_AGENT_ID = os.environ.get("HA_CONVERSATION_AGENT_ID", "conversation.ollama_conversation").strip()
DEFAULT_HA_LANGUAGE = os.environ.get("HA_CONVERSATION_LANGUAGE", "zh-CN").strip()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _extract_questions(obj: Any) -> List[str]:
    # Accept formats:
    # 1) {"questions": ["..."]}
    # 2) ["..."]
    # 3) daily100_report-like: {"rows":[{"q":"..."}]}
    if isinstance(obj, dict):
        if isinstance(obj.get("questions"), list):
            return [str(x or "").strip() for x in obj.get("questions") if str(x or "").strip()]
        if isinstance(obj.get("rows"), list):
            out = []
            for it in obj.get("rows") or []:
                if not isinstance(it, dict):
                    continue
                q = str(it.get("q") or "").strip()
                if q:
                    out.append(q)
            return out
    if isinstance(obj, list):
        return [str(x or "").strip() for x in obj if str(x or "").strip()]
    return []


def _http_post_json(url: str, payload: Dict[str, Any], timeout_sec: float) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        raw = resp.read()
    obj = json.loads(raw.decode("utf-8", errors="ignore"))
    return obj if isinstance(obj, dict) else {}


def _extract_ha_speech_text(resp: Dict[str, Any]) -> str:
    # gateway returns:
    # {"success":true,"tool":"ha_assist_context","status_code":200,
    #  "result":{"response":{"speech":{"plain":{"speech":"..."}}}}}
    try:
        result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
        response = result.get("response") if isinstance(result.get("response"), dict) else {}
        speech = response.get("speech") if isinstance(response.get("speech"), dict) else {}
        plain = speech.get("plain") if isinstance(speech.get("plain"), dict) else {}
        return str(plain.get("speech") or "").strip()
    except Exception:
        return ""


def _is_helpful_answer(final_text: str, route: str) -> Tuple[bool, str]:
    t = str(final_text or "").strip()
    r = str(route or "").strip()
    if r == "clarify":
        return False, "clarify"
    if len(t) < 6:
        return False, "too_short"
    for kw in BAD_PHRASES:
        if kw and (kw in t):
            return False, "bad_phrase:" + kw
    return True, "ok"


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _percentile_ms(values: List[int], p: float) -> int:
    if not values:
        return 0
    if p <= 0:
        return int(min(values))
    if p >= 100:
        return int(max(values))
    vs = sorted(int(x) for x in values)
    k = (len(vs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(vs) - 1)
    if f == c:
        return int(vs[f])
    d0 = vs[f] * (c - k)
    d1 = vs[c] * (k - f)
    return int(round(d0 + d1))


def _compute_deltas(cur: Dict[str, Any], prev: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k in ["pass_rate", "avg_ms", "p50_ms", "p95_ms", "total", "pass"]:
        if k not in cur:
            continue
        cv = cur.get(k)
        pv = prev.get(k)
        if isinstance(cv, (int, float)) and isinstance(pv, (int, float)):
            out[k] = cv - pv
        else:
            # allow int/float conversion
            try:
                out[k] = float(cv) - float(pv)
            except Exception:
                out[k] = None
    # route_counts delta (top-level)
    rc_cur = cur.get("route_counts") if isinstance(cur.get("route_counts"), dict) else {}
    rc_prev = prev.get("route_counts") if isinstance(prev.get("route_counts"), dict) else {}
    rc_delta = {}
    for rk in set(list(rc_cur.keys()) + list(rc_prev.keys())):
        rc_delta[str(rk)] = _safe_int(rc_cur.get(rk), 0) - _safe_int(rc_prev.get(rk), 0)
    out["route_counts"] = rc_delta
    return out


def _evaluate_targets(summary: Dict[str, Any], targets: Dict[str, Any]) -> Dict[str, Any]:
    pr = _safe_float(summary.get("pass_rate"), 0.0)
    avg = _safe_int(summary.get("avg_ms"), 0)
    p95 = _safe_int(summary.get("p95_ms"), 0)
    pass_ok = pr >= _safe_float(targets.get("pass_rate_min"), DEFAULT_TARGETS["pass_rate_min"])
    avg_ok = avg <= _safe_int(targets.get("avg_ms_max"), DEFAULT_TARGETS["avg_ms_max"])
    p95_ok = p95 <= _safe_int(targets.get("p95_ms_max"), DEFAULT_TARGETS["p95_ms_max"])
    return {
        "pass_rate_ok": bool(pass_ok),
        "avg_ms_ok": bool(avg_ok),
        "p95_ms_ok": bool(p95_ok),
        "ok": bool(pass_ok and avg_ok and p95_ok),
    }


def render_report_html(report: Dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    rows = report.get("rows") if isinstance(report.get("rows"), list) else []
    cmp = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    targets = cmp.get("targets") if isinstance(cmp.get("targets"), dict) else {}
    deltas = cmp.get("deltas") if isinstance(cmp.get("deltas"), dict) else {}
    gates = cmp.get("gates") if isinstance(cmp.get("gates"), dict) else {}

    def esc(s: Any) -> str:
        return html.escape(str(s or ""), quote=True)

    css = """
    :root { --bg:#0b0c10; --panel:#12141b; --muted:#9aa3b2; --text:#e9eef7; --ok:#43d19e; --bad:#ff6b6b; --line:#242838; }
    html,body{background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; margin:0;}
    a{color:inherit}
    .wrap{max-width:1200px;margin:0 auto;padding:24px;}
    .top{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
    .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;flex:1;min-width:280px}
    .k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
    .v{font-size:24px;font-weight:700;margin-top:6px}
    .row{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px}
    .pill{display:inline-block;padding:4px 10px;border-radius:999px;border:1px solid var(--line);color:var(--muted);font-size:12px}
    .pill.ok{color:var(--ok);border-color:rgba(67,209,158,.35)}
    .pill.bad{color:var(--bad);border-color:rgba(255,107,107,.35)}
    table{width:100%;border-collapse:collapse;margin-top:18px;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
    th,td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
    th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;text-align:left}
    tr:last-child td{border-bottom:none}
    .small{color:var(--muted);font-size:12px}
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
    """

    hdr = f"""
    <h1 style="margin:0 0 6px 0">MCP Eval Report</h1>
    <div class="small">generated_at: <span class="mono">{esc(report.get("generated_at"))}</span> | gateway: <span class="mono">{esc(report.get("gateway"))}</span></div>
    """

    pass_rate = summary.get("pass_rate")
    pass_rate_str = f"{float(pass_rate or 0.0)*100:.1f}%" if pass_rate is not None else ""
    ok_cls = "ok" if float(pass_rate or 0.0) >= 0.95 else "bad"

    def fmt_delta(v: Any, kind: str = "float") -> str:
        if v is None:
            return ""
        if kind == "ms":
            try:
                vv = int(round(float(v)))
            except Exception:
                return ""
            return ("+" if vv > 0 else "") + str(vv) + "ms"
        try:
            vv = float(v)
        except Exception:
            return ""
        if kind == "rate":
            # v is 0..1
            return ("+" if vv > 0 else "") + f"{vv*100:.1f}pp"
        return ("+" if vv > 0 else "") + f"{vv:.3f}"

    pr_delta = fmt_delta(deltas.get("pass_rate"), "rate")
    avg_delta = fmt_delta(deltas.get("avg_ms"), "ms")
    p95_delta = fmt_delta(deltas.get("p95_ms"), "ms")
    pr_tgt = _safe_float(targets.get("pass_rate_min"), DEFAULT_TARGETS["pass_rate_min"])
    avg_tgt = _safe_int(targets.get("avg_ms_max"), DEFAULT_TARGETS["avg_ms_max"])
    p95_tgt = _safe_int(targets.get("p95_ms_max"), DEFAULT_TARGETS["p95_ms_max"])

    cards = f"""
    <div class="top">
      <div class="card">
        <div class="k">Pass Rate</div>
        <div class="v">{esc(pass_rate_str)}</div>
        <div class="row">
          <span class="pill {ok_cls}">pass {esc(summary.get("pass"))} / {esc(summary.get("total"))}</span>
          <span class="pill">delta {esc(pr_delta)}</span>
          <span class="pill">target ≥ {esc(f'{pr_tgt*100:.1f}%')}</span>
        </div>
      </div>
      <div class="card">
        <div class="k">Latency</div>
        <div class="v">{esc(summary.get("avg_ms"))} ms</div>
        <div class="row">
          <span class="pill">p50 {esc(summary.get("p50_ms"))} ms</span>
          <span class="pill">p95 {esc(summary.get("p95_ms"))} ms</span>
          <span class="pill">avg delta {esc(avg_delta)}</span>
          <span class="pill">p95 delta {esc(p95_delta)}</span>
          <span class="pill">targets avg ≤ {esc(avg_tgt)}ms, p95 ≤ {esc(p95_tgt)}ms</span>
        </div>
      </div>
      <div class="card">
        <div class="k">Gates</div>
        <div class="v">{esc('OK' if gates.get('ok') else 'CHECK')}</div>
        <div class="row">
          <span class="pill {('ok' if gates.get('pass_rate_ok') else 'bad')}">pass_rate</span>
          <span class="pill {('ok' if gates.get('avg_ms_ok') else 'bad')}">avg_ms</span>
          <span class="pill {('ok' if gates.get('p95_ms_ok') else 'bad')}">p95_ms</span>
        </div>
      </div>
    </div>
    """

    # Table
    trs = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ok = bool(r.get("ok"))
        trs.append(
            "<tr>"
            + f"<td class='mono'>{esc(r.get('idx'))}</td>"
            + f"<td><span class='pill {'ok' if ok else 'bad'}'>{'OK' if ok else 'FAIL'}</span></td>"
            + f"<td class='mono'>{esc(r.get('ms'))}</td>"
            + f"<td class='mono'>{esc(r.get('route'))}</td>"
            + f"<td>{esc(r.get('q'))}</td>"
            + f"<td class='small'>{esc(r.get('reason'))}</td>"
            + f"<td class='small'>{esc(r.get('a_preview'))}</td>"
            + "</tr>"
        )

    routes = summary.get("route_counts") or {}
    route_lines = []
    for k, v in sorted(routes.items(), key=lambda x: (-int(x[1] or 0), str(x[0] or ""))):
        route_lines.append(f"{k or '(empty)'}: {v}")

    routes_block = "<div class='card' style='margin-top:16px'><div class='k'>Route Counts</div><div class='small mono'>" + esc(" | ".join(route_lines)) + "</div></div>"

    table = (
        "<table>"
        "<thead><tr>"
        "<th>#</th><th>OK</th><th>ms</th><th>route</th><th>question</th><th>score_reason</th><th>answer_preview</th>"
        "</tr></thead>"
        "<tbody>"
        + "\n".join(trs)
        + "</tbody></table>"
    )

    return (
        "<!doctype html><html><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'/>"
        "<title>MCP Eval Report</title>"
        f"<style>{css}</style>"
        "</head><body><div class='wrap'>"
        + hdr
        + cards
        + routes_block
        + table
        + "</div></body></html>"
    )


def run(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="evaluation/daily100_report.example.json", help="questions dataset (rows[*].q or questions[])")
    ap.add_argument("--gateway", default=os.environ.get("GATEWAY_BASE_URL", "http://127.0.0.1:19100").rstrip("/"))
    ap.add_argument(
        "--invoke",
        default="answer_question",
        choices=["answer_question", "ha_assist_context"],
        help="gateway invoke route: answer_question (direct MCP skill) or ha_assist_context (simulate HA conversation.process)",
    )
    ap.add_argument("--mode", default="local_first", help="answer_question mode (default local_first); ignored for ha_assist_context")
    ap.add_argument("--ha-agent-id", default=DEFAULT_HA_AGENT_ID, help="HA conversation agent_id for ha_assist_context")
    ap.add_argument("--ha-language", default=DEFAULT_HA_LANGUAGE, help="HA conversation language for ha_assist_context")
    ap.add_argument("--timeout-sec", type=float, default=25.0)
    ap.add_argument("--sleep-ms", type=int, default=0, help="optional delay between calls")
    ap.add_argument("--limit", type=int, default=0, help="optional: only run first N questions (0=all)")
    ap.add_argument("--prev-json", default="", help="optional previous report json for delta. default: out-json if exists")
    ap.add_argument("--history-dir", default="evaluation/history", help="where to store timestamped previous reports")
    ap.add_argument("--target-pass-rate", type=float, default=DEFAULT_TARGETS["pass_rate_min"])
    ap.add_argument("--target-avg-ms", type=int, default=DEFAULT_TARGETS["avg_ms_max"])
    ap.add_argument("--target-p95-ms", type=int, default=DEFAULT_TARGETS["p95_ms_max"])
    ap.add_argument("--fail-on-gates", action="store_true", help="exit non-zero if comparison.gates.ok is false")
    ap.add_argument("--out-json", default="evaluation/daily100_eval_latest.json")
    ap.add_argument("--out-html", default="evaluation/daily100_eval_latest.html")
    args = ap.parse_args(argv)

    # Load previous report (before overwriting) and optionally archive it.
    prev_path = str(args.prev_json or "").strip()
    prev_obj = None
    if not prev_path:
        if str(args.out_json or "").strip() and os.path.exists(str(args.out_json)):
            prev_path = str(args.out_json)
    if prev_path and os.path.exists(prev_path):
        try:
            prev_obj = _load_json(prev_path)
        except Exception:
            prev_obj = None

    archived_prev_json = ""
    archived_prev_html = ""
    if (not str(args.prev_json or "").strip()) and prev_obj and str(args.history_dir or "").strip():
        try:
            os.makedirs(str(args.history_dir), exist_ok=True)
            ts = _now_iso().replace(":", "").replace("-", "")
            base = os.path.splitext(os.path.basename(str(args.out_json)))[0] or "eval"
            archived_prev_json = os.path.join(str(args.history_dir), f"{base}.{ts}.json")
            _dump_json(archived_prev_json, prev_obj)
            if str(args.out_html or "").strip() and os.path.exists(str(args.out_html)):
                archived_prev_html = os.path.join(str(args.history_dir), f"{base}.{ts}.html")
                shutil.copyfile(str(args.out_html), archived_prev_html)
        except Exception:
            archived_prev_json = ""
            archived_prev_html = ""

    ds = _load_json(args.dataset)
    qs = _extract_questions(ds)
    limit = int(args.limit or 0)
    if limit > 0:
        qs = qs[:limit]
    else:
        if len(qs) != 100:
            print(f"ERROR: expected 100 questions, got {len(qs)} from {args.dataset}", file=sys.stderr)
            return 2

    invoke = str(args.invoke or "answer_question").strip()
    url = str(args.gateway).rstrip("/") + "/invoke/" + invoke

    rows = []
    lat_ms = []
    route_counts: Dict[str, int] = {}
    pass_cnt = 0

    for i, q in enumerate(qs, start=1):
        t0 = time.time()
        err = ""
        resp: Dict[str, Any] = {}
        try:
            if invoke == "ha_assist_context":
                payload = {"text": q, "language": str(args.ha_language or DEFAULT_HA_LANGUAGE), "agent_id": str(args.ha_agent_id or DEFAULT_HA_AGENT_ID)}
            else:
                payload = {"text": q, "mode": str(args.mode or "local_first")}
            resp = _http_post_json(url, payload, timeout_sec=float(args.timeout_sec))
        except urllib.error.HTTPError as e:
            err = f"http_{getattr(e, 'code', '')}"
        except Exception as e:
            err = str(e)
        t1 = time.time()

        ms = int(round((t1 - t0) * 1000.0))
        lat_ms.append(ms)

        status_code = int(resp.get("status_code") or 0) if isinstance(resp, dict) else 0
        result = resp.get("result") if isinstance(resp, dict) else {}
        result = result if isinstance(result, dict) else {}
        if invoke == "ha_assist_context":
            route = "ha_assist_context"
            final_text = _extract_ha_speech_text(resp)
        else:
            meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
            route = str(meta.get("route") or "").strip()
            final_text = str(result.get("final_text") or resp.get("final_text") or "").strip()

        route_counts[route] = int(route_counts.get(route, 0)) + 1
        ok, reason = _is_helpful_answer(final_text, route)
        if err:
            ok = False
            reason = "error:" + err
        elif status_code and status_code >= 400:
            ok = False
            reason = "status_code:" + str(status_code)
        if ok:
            pass_cnt += 1

        rows.append(
            {
                "idx": i,
                "q": q,
                "route": route,
                "ok": bool(ok),
                "reason": reason,
                "ms": ms,
                "a_preview": (final_text[:220] if final_text else ""),
                "status_code": status_code,
                "conversation_id": (str(result.get("conversation_id") or "") if invoke == "ha_assist_context" else ""),
            }
        )

        if int(args.sleep_ms or 0) > 0:
            time.sleep(float(args.sleep_ms) / 1000.0)

    total = len(rows)
    pass_rate = (float(pass_cnt) / float(total)) if total else 0.0
    avg_ms = int(round(statistics.mean(lat_ms))) if lat_ms else 0
    p50 = _percentile_ms(lat_ms, 50)
    p95 = _percentile_ms(lat_ms, 95)

    report = {
        "generated_at": _now_iso(),
        "dataset": str(args.dataset),
        "gateway": str(args.gateway),
        "config": {
            "invoke": invoke,
            "mode": str(args.mode),
            "ha_agent_id": str(args.ha_agent_id),
            "ha_language": str(args.ha_language),
            "timeout_sec": float(args.timeout_sec),
            "sleep_ms": int(args.sleep_ms or 0),
            "limit": int(args.limit or 0),
        },
        "summary": {
            "total": total,
            "pass": pass_cnt,
            "pass_rate": round(pass_rate, 4),
            "avg_ms": avg_ms,
            "p50_ms": p50,
            "p95_ms": p95,
            "route_counts": route_counts,
        },
        "rows": rows,
    }

    # Comparison vs previous + targets
    targets = {
        "pass_rate_min": float(args.target_pass_rate),
        "avg_ms_max": int(args.target_avg_ms),
        "p95_ms_max": int(args.target_p95_ms),
    }
    prev_summary = {}
    if isinstance(prev_obj, dict) and isinstance(prev_obj.get("summary"), dict):
        prev_summary = prev_obj.get("summary") or {}
    deltas = _compute_deltas(report["summary"], prev_summary) if prev_summary else {}
    gates = _evaluate_targets(report["summary"], targets)
    report["comparison"] = {
        "prev_path": (archived_prev_json or (prev_path if (prev_path and os.path.exists(prev_path)) else "")),
        "prev_html": archived_prev_html,
        "prev_summary": prev_summary,
        "deltas": deltas,
        "targets": targets,
        "gates": gates,
    }

    _dump_json(args.out_json, report)
    if str(args.out_html or "").strip():
        os.makedirs(os.path.dirname(args.out_html) or ".", exist_ok=True)
        with open(args.out_html, "w", encoding="utf-8") as f:
            f.write(render_report_html(report))

    print(json.dumps({"out_json": args.out_json, "out_html": args.out_html, "summary": report["summary"]}, ensure_ascii=False, indent=2))
    if bool(args.fail_on_gates) and (not gates.get("ok")):
        print("EVAL_GATES_FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
