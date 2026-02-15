#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time


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
]


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _contains_digit_evidence(text):
    t = str(text or "")
    if not t:
        return False
    if re.search(r"(?:A\$|AU\$|US\$|USD|AUD|CNY|RMB|¥|\$)\s?\d", t, flags=re.IGNORECASE):
        return True
    if re.search(r"\d[\d,]*(?:\.\d+)?", t):
        return True
    return False


def _is_helpful_answer(result):
    if not isinstance(result, dict):
        return False, "non_dict"
    final_text = str(result.get("final_text") or "").strip()
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    route = str(meta.get("route") or "")
    if route == "clarify":
        return False, "clarify"
    weather_markers = ["天气", "降雨", "下雨", "气温", "°C", "最低：", "最高：", "本周："]
    if (route == "weather") and ("天气" in final_text):
        return True, "ok"
    if any(k in final_text for k in weather_markers):
        return True, "ok"
    if len(final_text) < 6:
        return False, "too_short"
    for kw in BAD_PHRASES:
        if kw in final_text:
            return False, "fallback_or_no_info"
    return True, "ok"


def _count_step_markers(text):
    t = str(text or "")
    if not t:
        return 0
    cnt = 0
    cnt += len(re.findall(r"(?:^|[；;。\n])\s*[1-9][\)\.]", t))
    cnt += len(re.findall(r"\b步骤\b", t))
    return cnt


def _looks_like_parking_range_text(text):
    t = str(text or "")
    if not t:
        return False
    if not (("停车" in t) or ("parking" in t.lower())):
        return False
    if re.search(r"(?:A\$|AUD|\$)\s*\d+", t, flags=re.IGNORECASE):
        return True
    if re.search(r"\d+\s*[-~到]\s*(?:A\$|AUD|\$)?\s*\d+", t, flags=re.IGNORECASE):
        return True
    return False


def _hard_case_check(case_type, ret):
    result = {"ok": False, "reason": "unknown"}
    final_text = str((ret.get("final_text") if isinstance(ret, dict) else "") or "")
    next_actions = (ret.get("next_actions") if isinstance(ret, dict) and isinstance(ret.get("next_actions"), list) else [])
    facts = (ret.get("facts") if isinstance(ret, dict) and isinstance(ret.get("facts"), list) else [])
    meta = ret.get("meta") if isinstance(ret, dict) and isinstance(ret.get("meta"), dict) else {}
    if case_type == "rag_contract":
        steps = _count_step_markers(final_text)
        facts_len = len([x for x in facts if str(x or "").strip()])
        has_contract_hint = ("合同" in final_text) or ("条款" in final_text) or any(("合同" in str(x)) or ("条款" in str(x)) for x in facts)
        ok = ((steps >= 2) and (len(next_actions) >= 2)) or ((facts_len >= 2) and has_contract_hint)
        result["ok"] = ok
        result["reason"] = "steps={0},next={1},facts={2},hint={3}".format(steps, len(next_actions), facts_len, has_contract_hint)
        return result
    if case_type == "parking_fee":
        has_range = _looks_like_parking_range_text(final_text) or any(_looks_like_parking_range_text(str(x)) for x in facts)
        ok = has_range and (len(next_actions) >= 2)
        if (len(next_actions) == 0):
            ok = has_range
        result["ok"] = ok
        result["reason"] = "range={0},next={1}".format(has_range, len(next_actions))
        return result
    if case_type == "btc_price":
        conf = str(meta.get("evidence_confidence") or "")
        has_num = _contains_digit_evidence(final_text)
        has_asset = ("BTC" in final_text) or ("BTC-USD" in final_text)
        has_guidance = ("BTC-USD" in final_text) or ("^GSPC" in final_text) or ("^IXIC" in final_text) or ("XAUUSD" in final_text) or ("AUDCNY" in final_text)
        if conf == "low":
            ok = (not has_num) and has_guidance
        elif conf == "":
            ok = has_asset or has_guidance
        else:
            ok = has_asset
        result["ok"] = ok
        result["reason"] = "confidence={0},digits={1},asset={2},guidance={3}".format(conf, has_num, has_asset, has_guidance)
        return result
    if case_type == "calendar_afternoon":
        ok = (("下午" in final_text) or ("日程" in final_text) or ("安排" in final_text))
        result["ok"] = ok
        result["reason"] = "afternoon_hint={0}".format(ok)
        return result
    if case_type == "calendar_timepoint":
        ok = (("日程" in final_text) or ("没有日程" in final_text) or ("13:00" in final_text) or ("13点" in final_text))
        result["ok"] = ok
        result["reason"] = "timepoint_hint={0}".format(ok)
        return result
    if case_type == "calendar_availability":
        ok = (("有空" in final_text) or ("没有排到日程" in final_text) or ("已有安排" in final_text))
        result["ok"] = ok
        result["reason"] = "availability_hint={0}".format(ok)
        return result
    if case_type == "bills_risk":
        ok = (("到期" in final_text) or ("逾期" in final_text) or ("账单" in final_text) or ("风险" in final_text))
        result["ok"] = ok
        result["reason"] = "bills_risk_hint={0}".format(ok)
        return result
    if case_type == "datetime_payday":
        ok = (("发薪" in final_text) or ("发工资" in final_text) or ("每月" in final_text))
        result["ok"] = ok
        result["reason"] = "payday_hint={0}".format(ok)
        return result
    if case_type == "chitchat_anxiety":
        ok = (("呼吸" in final_text) or ("减压" in final_text) or ("5 分钟" in final_text) or ("焦虑" in final_text))
        result["ok"] = ok
        result["reason"] = "anxiety_hint={0}".format(ok)
        return result
    result["ok"] = True
    result["reason"] = "skip"
    return result


def evaluate(app_mod, cases, criteria):
    thresholds = criteria.get("thresholds") if isinstance(criteria.get("thresholds"), dict) else {}

    route_rows = []
    route_pass = 0
    route_cases = cases.get("route_cases") if isinstance(cases.get("route_cases"), list) else []
    for item in route_cases:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        exp = item.get("expected") if isinstance(item.get("expected"), list) else []
        if (not text) or (not exp):
            continue
        row = app_mod._debug_pick_route_for_text(text, mode="local_first")
        got = str(row.get("route") or "")
        ok = got in [str(x) for x in exp]
        if ok:
            route_pass += 1
        route_rows.append({"text": text, "expected": exp, "got": got, "ok": ok})

    helpful_rows = []
    helpful_pass = 0
    helpful_cases = cases.get("helpful_cases") if isinstance(cases.get("helpful_cases"), list) else []
    for text in helpful_cases:
        q = str(text or "").strip()
        if not q:
            continue
        ret = app_mod.skill_answer_question(q, mode="local_first")
        ok, reason = _is_helpful_answer(ret)
        if ok:
            helpful_pass += 1
        helpful_rows.append(
            {
                "text": q,
                "route": str(((ret.get("meta") or {}).get("route") if isinstance(ret, dict) else "") or ""),
                "ok": ok,
                "reason": reason,
                "final_text": str((ret.get("final_text") if isinstance(ret, dict) else "") or "")[:220],
            }
        )

    finance_rows = []
    finance_pass = 0
    finance_cases = cases.get("finance_cases") if isinstance(cases.get("finance_cases"), list) else []
    guidance_tokens = ["^GSPC", "^IXIC", "BTC-USD", "XAUUSD", "AUDCNY", "AUD/USD", "TSLA", "AAPL", "NASDAQ", "exchange rate"]
    for text in finance_cases:
        q = str(text or "").strip()
        if not q:
            continue
        ret = app_mod.skill_answer_question(q, mode="local_first")
        meta = ret.get("meta") if isinstance(ret, dict) and isinstance(ret.get("meta"), dict) else {}
        route = str(meta.get("route") or "")
        evidence_flag = bool(meta.get("evidence_found"))
        evidence_text = _contains_digit_evidence(str((ret.get("final_text") if isinstance(ret, dict) else "") or ""))
        conf = str(meta.get("evidence_confidence") or "")
        final_text = str((ret.get("final_text") if isinstance(ret, dict) else "") or "")
        has_guidance = any(tok in final_text for tok in guidance_tokens)
        has_asset_marker = any(tok in final_text.upper() for tok in ["TSLA", "AAPL", "BTC", "XAU", "DXY", "AUD", "CNY", "USD", "NASDAQ", "S&P"])
        low_ok = (not evidence_text) and has_guidance
        high_ok = evidence_text and has_asset_marker
        if conf == "low":
            ok = low_ok
        elif conf in ["high", "medium"]:
            ok = high_ok or has_guidance
        else:
            ok = high_ok or low_ok
        if ok:
            finance_pass += 1
        finance_rows.append(
            {
                "text": q,
                "route": route,
                "evidence_found": evidence_flag,
                "final_has_digits": evidence_text,
                "evidence_confidence": conf,
                "has_guidance": has_guidance,
                "ok": ok,
                "final_text": final_text[:220],
            }
        )

    hard_rows = []
    hard_pass = 0
    hard_cases = cases.get("hard_cases") if isinstance(cases.get("hard_cases"), list) else []
    for item in hard_cases:
        if not isinstance(item, dict):
            continue
        q = str(item.get("text") or "").strip()
        tp = str(item.get("type") or "").strip()
        if (not q) or (not tp):
            continue
        ret = app_mod.skill_answer_question(q, mode="local_first")
        chk = _hard_case_check(tp, ret)
        if chk.get("ok"):
            hard_pass += 1
        hard_rows.append(
            {
                "text": q,
                "type": tp,
                "ok": bool(chk.get("ok")),
                "reason": str(chk.get("reason") or ""),
                "route": str(((ret.get("meta") or {}).get("route") if isinstance(ret, dict) else "") or ""),
                "final_text": str((ret.get("final_text") if isinstance(ret, dict) else "") or "")[:220],
            }
        )

    route_total = len(route_rows)
    helpful_total = len(helpful_rows)
    finance_total = len(finance_rows)
    hard_total = len(hard_rows)

    route_acc = (float(route_pass) / float(route_total)) if route_total else 0.0
    helpful_rate = (float(helpful_pass) / float(helpful_total)) if helpful_total else 0.0
    finance_rate = (float(finance_pass) / float(finance_total)) if finance_total else 0.0
    hard_rate = (float(hard_pass) / float(hard_total)) if hard_total else 1.0

    route_min = float(thresholds.get("route_accuracy_min") or 0.0)
    helpful_min = float(thresholds.get("helpful_rate_min") or 0.0)
    finance_min = float(thresholds.get("finance_evidence_rate_min") or 0.0)

    report = {
        "ts": int(time.time()),
        "summary": {
            "route_accuracy": round(route_acc, 4),
            "helpful_rate": round(helpful_rate, 4),
            "finance_evidence_rate": round(finance_rate, 4),
            "route_pass": route_pass,
            "route_total": route_total,
            "helpful_pass": helpful_pass,
            "helpful_total": helpful_total,
            "finance_pass": finance_pass,
            "finance_total": finance_total,
            "hard_pass": hard_pass,
            "hard_total": hard_total,
            "hard_rate": round(hard_rate, 4),
        },
        "thresholds": {
            "route_accuracy_min": route_min,
            "helpful_rate_min": helpful_min,
            "finance_evidence_rate_min": finance_min,
        },
        "gates": {
            "route": route_acc >= route_min,
            "helpful": helpful_rate >= helpful_min,
            "finance": finance_rate >= finance_min,
            "hard_cases": hard_rate >= 1.0,
        },
        "details": {
            "route_rows": route_rows,
            "helpful_rows": helpful_rows,
            "finance_rows": finance_rows,
            "hard_rows": hard_rows,
        },
    }
    report["ok"] = bool(report["gates"]["route"] and report["gates"]["helpful"] and report["gates"]["finance"] and report["gates"]["hard_cases"])
    return report


def main():
    parser = argparse.ArgumentParser(description="Post-development evaluation runner")
    parser.add_argument("--cases", default="evaluation/cases.json")
    parser.add_argument("--criteria", default="evaluation/criteria.json")
    parser.add_argument("--report", default="evaluation/latest_report.json")
    args = parser.parse_args()

    sys.path.insert(0, os.getcwd())
    import app  # noqa: E402

    cases = _load_json(args.cases)
    criteria = _load_json(args.criteria)
    report = evaluate(app, cases, criteria)

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "ok": report.get("ok"),
        "summary": report.get("summary"),
        "thresholds": report.get("thresholds"),
        "gates": report.get("gates")
    }, ensure_ascii=False, indent=2))

    if not report.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
