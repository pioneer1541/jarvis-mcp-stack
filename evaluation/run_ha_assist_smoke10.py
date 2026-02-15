#!/usr/bin/env python3
"""
Home Assistant conversation.process smoke eval via gateway (方案1):
- POST /invoke/ha_assist_context
- 10 different topics
- timing + heuristic scoring
- JSON (+ optional HTML) report

Pure standard library.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _http_post_json(url: str, payload: Dict[str, Any], timeout_sec: float) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        raw = resp.read()
    obj = json.loads(raw.decode("utf-8", errors="ignore"))
    return obj if isinstance(obj, dict) else {}


def _extract_speech_text(resp: Dict[str, Any]) -> str:
    # gateway returns:
    # {"success":true,"tool":"ha_assist_context","status_code":200,"result":{"response":{"speech":{"plain":{"speech":"..."}}}}}
    try:
        result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
        response = result.get("response") if isinstance(result.get("response"), dict) else {}
        speech = response.get("speech") if isinstance(response.get("speech"), dict) else {}
        plain = speech.get("plain") if isinstance(speech.get("plain"), dict) else {}
        return str(plain.get("speech") or "").strip()
    except Exception:
        return ""


def _score_case(speech: str, case: Dict[str, Any]) -> Tuple[bool, str]:
    t = str(speech or "").strip()
    if not t:
        return False, "empty_speech"
    must_all = case.get("must_all") if isinstance(case.get("must_all"), list) else []
    must_any = case.get("must_any") if isinstance(case.get("must_any"), list) else []
    for k in must_all:
        kk = str(k or "").strip()
        if kk and (kk not in t):
            return False, "missing_all:" + kk
    if must_any:
        ok = False
        for k in must_any:
            kk = str(k or "").strip()
            if kk and (kk in t):
                ok = True
                break
        if not ok:
            return False, "missing_any"
    return True, "ok"


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


def render_html(report: Dict[str, Any]) -> str:
    def esc(x: Any) -> str:
        return html.escape(str(x or ""), quote=True)

    css = """
    :root { --bg:#0b0c10; --panel:#12141b; --muted:#9aa3b2; --text:#e9eef7; --ok:#43d19e; --bad:#ff6b6b; --line:#242838; }
    html,body{background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; margin:0;}
    .wrap{max-width:1200px;margin:0 auto;padding:24px;}
    .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;}
    .k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
    .v{font-size:24px;font-weight:700;margin-top:6px}
    .row{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
    .pill{display:inline-block;padding:4px 10px;border-radius:999px;border:1px solid var(--line);color:var(--muted);font-size:12px}
    .pill.ok{color:var(--ok);border-color:rgba(67,209,158,.35)}
    .pill.bad{color:var(--bad);border-color:rgba(255,107,107,.35)}
    table{width:100%;border-collapse:collapse;margin-top:16px;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
    th,td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
    th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;text-align:left}
    tr:last-child td{border-bottom:none}
    .small{color:var(--muted);font-size:12px}
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
    """
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    rows = report.get("rows") if isinstance(report.get("rows"), list) else []
    ok_cls = "ok" if float(summary.get("pass_rate") or 0.0) >= 0.9 else "bad"
    head = f"""
    <div class="card">
      <div class="k">HA Assist Smoke10</div>
      <div class="row small">
        <span>generated_at: <span class="mono">{esc(report.get("generated_at"))}</span></span>
        <span>gateway: <span class="mono">{esc(report.get("gateway"))}</span></span>
        <span>agent_id: <span class="mono">{esc(report.get("agent_id"))}</span></span>
      </div>
      <div class="row">
        <span class="pill {ok_cls}">pass {esc(summary.get("pass"))}/{esc(summary.get("total"))} ({esc(round(float(summary.get("pass_rate") or 0.0)*100,1))}%)</span>
        <span class="pill">avg {esc(summary.get("avg_ms"))}ms</span>
        <span class="pill">p95 {esc(summary.get("p95_ms"))}ms</span>
      </div>
    </div>
    """
    trs = []
    for r in rows:
        ok = bool(r.get("ok"))
        trs.append(
            "<tr>"
            + f"<td class='mono'>{esc(r.get('id'))}</td>"
            + f"<td>{esc(r.get('topic'))}</td>"
            + f"<td><span class='pill {'ok' if ok else 'bad'}'>{'OK' if ok else 'FAIL'}</span></td>"
            + f"<td class='mono'>{esc(r.get('ms'))}</td>"
            + f"<td>{esc(r.get('text'))}</td>"
            + f"<td class='small'>{esc(r.get('reason'))}</td>"
            + f"<td class='small'>{esc(r.get('speech_preview'))}</td>"
            + "</tr>"
        )
    table = (
        "<table><thead><tr>"
        "<th>id</th><th>topic</th><th>ok</th><th>ms</th><th>prompt</th><th>reason</th><th>speech</th>"
        "</tr></thead><tbody>"
        + "\n".join(trs)
        + "</tbody></table>"
    )
    return "<!doctype html><html><head><meta charset='utf-8'/>" f"<style>{css}</style>" "</head><body><div class='wrap'>" + head + table + "</div></body></html>"


def run(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="evaluation/ha_smoke10_cases.example.json")
    ap.add_argument("--gateway", default=os.environ.get("GATEWAY_BASE_URL", "http://127.0.0.1:19100").rstrip("/"))
    ap.add_argument("--timeout-sec", type=float, default=25.0)
    ap.add_argument("--sleep-ms", type=int, default=0)
    ap.add_argument("--out-json", default="evaluation/ha_smoke10_report.json")
    ap.add_argument("--out-html", default="evaluation/ha_smoke10_report.html")
    args = ap.parse_args(argv)

    cfg = _load_json(args.cases)
    agent_id = str((cfg.get("agent_id") if isinstance(cfg, dict) else "") or "").strip()
    language = str((cfg.get("language") if isinstance(cfg, dict) else "") or "zh-CN").strip()
    cases = cfg.get("cases") if isinstance(cfg, dict) else None
    if not agent_id or (not isinstance(cases, list)) or len(cases) != 10:
        print("ERROR: expected 10 cases with agent_id (see evaluation/ha_smoke10_cases.example.json)", file=sys.stderr)
        return 2

    url = str(args.gateway).rstrip("/") + "/invoke/ha_assist_context"

    rows = []
    lat = []
    pass_cnt = 0
    topic_counts: Dict[str, int] = {}
    topic_pass: Dict[str, int] = {}

    for c in cases:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        topic = str(c.get("topic") or "").strip()
        text = str(c.get("text") or "").strip()
        if not cid or not text:
            continue

        topic_counts[topic] = int(topic_counts.get(topic, 0)) + 1

        payload = {"text": text, "language": language, "agent_id": agent_id}
        t0 = time.time()
        err = ""
        resp = {}
        try:
            resp = _http_post_json(url, payload, timeout_sec=float(args.timeout_sec))
        except urllib.error.HTTPError as e:
            err = f"http_{getattr(e, 'code', '')}"
        except Exception as e:
            err = str(e)
        t1 = time.time()
        ms = int(round((t1 - t0) * 1000.0))
        lat.append(ms)

        speech = _extract_speech_text(resp)
        ok, reason = _score_case(speech, c)
        status_code = int(resp.get("status_code") or 0) if isinstance(resp, dict) else 0
        if err:
            ok = False
            reason = "error:" + err
        elif status_code and status_code >= 400:
            ok = False
            reason = "status_code:" + str(status_code)

        if ok:
            pass_cnt += 1
            topic_pass[topic] = int(topic_pass.get(topic, 0)) + 1

        rows.append(
            {
                "id": cid,
                "topic": topic,
                "text": text,
                "ok": bool(ok),
                "reason": reason,
                "ms": ms,
                "status_code": status_code,
                "conversation_id": (((resp.get("result") or {}).get("conversation_id") if isinstance(resp, dict) and isinstance(resp.get("result"), dict) else "") or ""),
                "speech_preview": (speech[:240] if speech else ""),
            }
        )

        if int(args.sleep_ms or 0) > 0:
            time.sleep(float(args.sleep_ms) / 1000.0)

    total = len(rows)
    pass_rate = (float(pass_cnt) / float(total)) if total else 0.0
    avg_ms = int(round(statistics.mean(lat))) if lat else 0
    p50 = _percentile_ms(lat, 50)
    p95 = _percentile_ms(lat, 95)

    report = {
        "generated_at": _now_iso(),
        "gateway": str(args.gateway),
        "agent_id": agent_id,
        "language": language,
        "config": {"timeout_sec": float(args.timeout_sec), "sleep_ms": int(args.sleep_ms or 0)},
        "summary": {
            "total": total,
            "pass": pass_cnt,
            "pass_rate": round(pass_rate, 4),
            "avg_ms": avg_ms,
            "p50_ms": p50,
            "p95_ms": p95,
            "topic_counts": topic_counts,
            "topic_pass": topic_pass,
        },
        "rows": rows,
    }

    _dump_json(args.out_json, report)
    if str(args.out_html or "").strip():
        os.makedirs(os.path.dirname(args.out_html) or ".", exist_ok=True)
        with open(args.out_html, "w", encoding="utf-8") as f:
            f.write(render_html(report))

    print(json.dumps({"out_json": args.out_json, "out_html": args.out_html, "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
