import json
import os
import re
from datetime import datetime, timedelta, date as dt_date
from typing import Any, Callable, Dict, List, Optional, Set

import requests


DEFAULT_ANSWER_ROUTE_WHITELIST = [
    "briefing_rule",
    "plan_rule",
    "productivity_rule",
    "chitchat",
    "template_web",
    "bills",
    "holiday",
    "calendar",
    "weather",
    "datetime",
    "news",
    "rag",
    "local_info_web",
    "home_health_check",
    "open_info_property",
    "open_advice_general",
    "fallback_local_first",
]


class RouterContext:
    def __init__(
        self,
        text_raw: str,
        language: str = "",
        mode: str = "local_first",
        debug: bool = False,
        last_clarify=None,
        now_dt: Optional[datetime] = None,
    ):
        self.text_raw = str(text_raw or "").strip()
        self.text_norm = re.sub(r"\s+", "", self.text_raw.lower())
        self.language = str(language or "").strip().lower()
        self.mode = str(mode or "local_first").strip().lower()
        self.now_dt = now_dt if now_dt is not None else datetime.now()
        self.debug = bool(debug)
        self.last_clarify = last_clarify


class RouteRule:
    def __init__(self, name: str, priority: int, score_fn, handle_fn, reason_fn=None):
        self.name = str(name or "").strip()
        self.priority = int(priority)
        self._score_fn = score_fn
        self._handle_fn = handle_fn
        self._reason_fn = reason_fn

    def score(self, ctx: RouterContext) -> float:
        try:
            v = float(self._score_fn(ctx))
        except Exception:
            v = 0.0
        if v < 0.0:
            v = 0.0
        if v > 1.0:
            v = 1.0
        return v

    def handle(self, ctx: RouterContext) -> dict:
        return self._handle_fn(ctx)

    def reason(self, ctx: RouterContext) -> str:
        if not callable(self._reason_fn):
            return ""
        try:
            return str(self._reason_fn(ctx) or "")
        except Exception:
            return ""


def sanitize_route_candidates(candidates: list) -> list:
    out = []
    for c in (candidates or []):
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "name": str(c.get("name") or "").strip(),
                "score": float(c.get("score") or 0.0),
                "priority": int(c.get("priority") or 0),
                "final": float(c.get("final") or 0.0),
                "reason": str(c.get("reason") or ""),
            }
        )
    return out


def skill_answer_question_core(text: str, mode: str, h) -> dict:
    rid, started = h["skill_call_begin"]("skill.answer_question", {"text": str(text or ""), "mode": str(mode or "")})
    ok = True
    q = str(text or "").strip()
    md = str(mode or "local_first").strip().lower()
    try:
        if not q:
            return h["skill_result"](
                "请告诉我你想问什么。",
                facts=[],
                sources=[],
                next_actions=[h["skill_next_action_item"]("ask_user", "请给我一个具体问题。", {})],
                meta={"skill": "answer_question", "mode": md},
            )

        ctx = h["router_context_cls"](
            text_raw=q,
            language=h["skill_detect_lang"](q, "zh"),
            mode=md,
            debug=h["skill_debug_enabled"](),
            last_clarify=h["clarify_memory_get"](),
            now_dt=h["now_local"](),
        )
        follow_route = h["consume_clarify_followup_route"](ctx)
        rules = h["build_answer_route_rules"]()
        rule_by_name = {r.name: r for r in rules}

        compound_ret = h["compose_compound_answer"](ctx, md, rule_by_name)
        if isinstance(compound_ret, dict) and str(compound_ret.get("final_text") or "").strip():
            return compound_ret

        if follow_route and (follow_route in rule_by_name):
            try:
                raw_follow = rule_by_name[follow_route].handle(ctx)
                return h["skill_wrap_any_result"](raw_follow, follow_route, md, {"from_clarify_followup": True, "candidates": []})
            except Exception as e:
                return h["skill_result"](
                    "我先给你一个简短答复：刚才的问题我重试一下。",
                    facts=[],
                    sources=[],
                    next_actions=[h["skill_next_action_item"]("suggest_retry", "请再说一次你的问题。", {})],
                    meta={"skill": "answer_question", "mode": md, "route": follow_route, "error": str(e)},
                )

        picked = h["score_and_pick_rule"](rules, ctx)
        route_whitelist = h["load_answer_route_whitelist"](h["env_get"]("SKILL_ANSWER_ROUTE_WHITELIST", ""))
        picked = h["enforce_answer_route_whitelist"](
            picked,
            rules,
            route_whitelist,
            debug=ctx.debug,
            debug_log=h["skill_debug_log"],
        )
        candidates = picked.get("candidates") or []
        candidates_safe = sanitize_route_candidates(candidates)
        chosen_name_dbg = str((picked.get("chosen") or {}).get("name") or picked.get("special") or "")
        blocked_name = str(picked.get("whitelist_blocked") or "")
        if blocked_name:
            h["skill_log_json"](
                "route_whitelist_block",
                request_id=rid,
                tool="skill.answer_question",
                data={
                    "blocked_route": blocked_name,
                    "selected_route": chosen_name_dbg,
                    "whitelist_size": len(route_whitelist),
                },
            )
        h["skill_log_json"](
            "route_pick",
            request_id=rid,
            tool="skill.answer_question",
            data={"route": chosen_name_dbg, "candidates_top": [str((x or {}).get("name") or "") for x in candidates_safe[:3]]},
        )
        if ctx.debug:
            h["skill_debug_log"]("chosen_route=" + chosen_name_dbg)

        ambiguous_short = ctx.text_norm in ["今天怎么样", "我今天怎么样", "现在怎么样", "今天如何"]
        if ambiguous_short:
            return h["clarify_result"](ctx, candidates_safe, topic_hint=q)

        if picked.get("special") == "clarify":
            return h["clarify_result"](ctx, candidates_safe, topic_hint=q)

        chosen = picked.get("chosen") or {}
        chosen_name = str(chosen.get("name") or "")
        chosen_rule = chosen.get("rule")
        if not chosen_name or chosen_rule is None:
            return h["clarify_result"](ctx, candidates_safe, topic_hint=q)

        try:
            raw = chosen_rule.handle(ctx)
            if chosen_name == "fallback_local_first":
                return h["answer_fallback_local_first"](ctx, candidates=candidates_safe)
            return h["skill_wrap_any_result"](raw, chosen_name, md, {"candidates": candidates_safe})
        except Exception as e:
            return h["skill_result"](
                "我先给你一个简短答复：当前分支处理失败，请换个说法再试。",
                facts=[],
                sources=[],
                next_actions=[h["skill_next_action_item"]("suggest_retry", "请换个说法再试。", {"route": chosen_name})],
                meta={"skill": "answer_question", "mode": md, "route": chosen_name, "error": str(e), "candidates": candidates_safe},
            )
    except Exception as e:
        ok = False
        h["skill_log_json"]("tool_call_error", request_id=rid, tool="skill.answer_question", data={"error": str(e)})
        return h["skill_result"]("当前问答服务暂时不可用。", facts=["当前问答服务暂时不可用，请稍后再试。"])
    finally:
        h["skill_call_end"]("skill.answer_question", rid, started, ok=ok)


def route_weather_request(user_text: str, route_return_data: bool, h) -> dict:
    def _fmt_temp_value(v):
        if v is None:
            return "暂无"
        try:
            fv = float(v)
            if abs(fv - int(fv)) < 0.001:
                return str(int(fv))
            return str(round(fv, 1))
        except Exception:
            return str(v)

    eid = str(h["env_get"]("HA_DEFAULT_WEATHER_ENTITY", "") or "").strip()
    if not eid:
        return {"ok": True, "route_type": "structured_weather", "final": "未配置默认天气实体。请设置环境变量 HA_DEFAULT_WEATHER_ENTITY。", "error": "missing_default_weather_entity"}
    tzinfo = h["tzinfo"]()
    now = h["now_local"]()
    base_d = dt_date(now.year, now.month, now.day)

    q = h["weather_range_from_text"](user_text, now_local=now)
    rr = h["ha_weather_forecast"](eid, "daily")
    if not rr.get("ok"):
        return {"ok": True, "route_type": "structured_weather", "final": "我现在联网查询失败了，请稍后再试。", "data": rr}
    fc = rr.get("forecast") if isinstance(rr.get("forecast"), list) else []
    label = str((q.get("label") or "")).strip()

    avail = []
    if isinstance(fc, list):
        for it in fc:
            d = h["local_date_from_forecast_item"](it, tzinfo)
            if d is None:
                continue
            if d not in avail:
                avail.append(d)
    try:
        avail = sorted(avail)
    except Exception:
        pass
    min_d = avail[0] if isinstance(avail, list) and len(avail) > 0 else None
    max_d = avail[-1] if isinstance(avail, list) and len(avail) > 0 else None

    head = ""
    if q.get("mode") == "range":
        start_d = q.get("start_date")
        if not isinstance(start_d, dt_date):
            start_d = base_d
        days_req = h["safe_int"](q.get("days"), 3)
        if days_req < 1:
            days_req = 1
        days_i = days_req
        if days_i > 6:
            days_i = 6

        note = ""
        if days_req != days_i:
            note = "（注意：该天气插件仅提供当天及未来5天，共6天预报）"
        if isinstance(max_d, dt_date):
            try:
                end_req = start_d + timedelta(days=days_i - 1)
            except Exception:
                end_req = None
            if isinstance(end_req, dt_date) and end_req > max_d:
                note = "（注意：该天气插件仅提供到 " + str(max_d) + " 的预报）"
                try:
                    days_i2 = (max_d - start_d).days + 1
                except Exception:
                    days_i2 = days_i
                if isinstance(days_i2, int) and days_i2 >= 1:
                    days_i = days_i2
        label_show = label
        if label_show and ("接下来" in label_show) and (days_req != days_i):
            if "天气" in label_show:
                label_show = "接下来" + str(days_i) + "天天气"
            else:
                label_show = "接下来" + str(days_i) + "天"
        summary = h["summarise_weather_range"](fc, start_d, days_i, tzinfo)
        if label_show:
            final = head + label_show + "：" + summary + note
        else:
            final = head + "未来" + str(days_i) + "天天气：" + summary + note
        ret = {"ok": True, "route_type": "structured_weather", "final": final}
        if route_return_data:
            ret["data"] = rr
        return ret

    ask_min = (("最低" in user_text) or ("最低温" in user_text) or ("最低气温" in user_text))
    ask_max = (("最高" in user_text) or ("最高温" in user_text) or ("最高气温" in user_text))
    off = h["safe_int"](q.get("offset"), 0)
    td = q.get("target_date")
    if not isinstance(td, dt_date):
        td = base_d
        try:
            td = base_d + timedelta(days=off)
        except Exception:
            td = base_d
    it = h["pick_daily_forecast_by_local_date"](fc, td, tzinfo)
    if it is None:
        if isinstance(min_d, dt_date) and isinstance(max_d, dt_date):
            final = head + (label + "：无预报。" if label else "天气：无预报。") + "（可用范围：" + str(min_d) + " 到 " + str(max_d) + "）"
        else:
            final = head + (label + "：无预报。" if label else "天气：无预报。") + "（该天气插件通常仅提供当天及未来5天）"
    else:
        if ask_min and (not ask_max):
            show_label = label if label else "今天"
            final = show_label + "最低气温：" + _fmt_temp_value(it.get("templow")) + "°C。"
        elif ask_max and (not ask_min):
            show_label = label if label else "今天"
            final = show_label + "最高气温：" + _fmt_temp_value(it.get("temperature")) + "°C。"
        else:
            final = head + (label + "：" if label else "天气：") + h["summarise_weather_item"](it)
    ret = {"ok": True, "route_type": "structured_weather", "final": final}
    if route_return_data:
        ret["data"] = rr
    return ret


def route_holiday_request(user_text: str, route_return_data: bool, h) -> dict:
    now = h["now_local"]()
    try:
        y = int(getattr(now, "year"))
    except Exception:
        y = int(datetime.now().year)
    rr = h["holiday_vic"](y)
    if not rr.get("ok"):
        return {"ok": True, "route_type": "structured_holiday", "final": "假期查询失败。", "data": rr}
    items = rr.get("holidays") or []
    today_d = dt_date(now.year, now.month, now.day)
    today_s = str(today_d)

    t = str(user_text or "")
    want_next = ("下一个" in t) or ("下個" in t) or ("next" in t.lower())
    want_recent = ("最近" in t) or ("上一个" in t) or ("上個" in t) or ("刚刚" in t) or ("剛剛" in t)

    if want_next:
        nx = h["holiday_next_from_list"](items, today_s)
        if not nx.get("ok"):
            final = "未找到下一个维州公众假期。"
            return {"ok": True, "route_type": "structured_holiday", "final": final, "data": rr}
        days = nx.get("days")
        if isinstance(days, int):
            final = "下一个维州公众假期：" + str(nx.get("name") or "") + "（" + str(nx.get("date") or "") + "，" + str(days) + " 天后）"
        else:
            final = "下一个维州公众假期：" + str(nx.get("name") or "") + "（" + str(nx.get("date") or "") + "）"
        ret = {"ok": True, "route_type": "structured_holiday", "final": final}
        if route_return_data:
            ret["data"] = rr
            ret["next"] = nx
        return ret
    if want_recent:
        pv = h["holiday_prev_from_list"](items, today_s)
        if not pv.get("ok"):
            final = "未找到最近的维州公众假期。"
            return {"ok": True, "route_type": "structured_holiday", "final": final, "data": rr}
        da = pv.get("days_ago")
        if isinstance(da, int):
            final = "最近的维州公众假期：" + str(pv.get("name") or "") + "（" + str(pv.get("date") or "") + "，" + str(da) + " 天前）"
        else:
            final = "最近的维州公众假期：" + str(pv.get("name") or "") + "（" + str(pv.get("date") or "") + "）"
        return {"ok": True, "route_type": "structured_holiday", "final": final, "data": rr, "recent": pv}

    return {"ok": True, "route_type": "structured_holiday", "final": "已获取维州公众假期（AU-VIC），年份 " + str(y) + "，共 " + str(len(items)) + " 天。", "data": rr}


def route_bills_request(user_text: str, h) -> Optional[dict]:
    if h["is_bills_process_intent"](user_text):
        final = h["bills_process_new"]()
        if not str(final or "").strip():
            final = "账单拉取失败：未知原因"
        return {"ok": True, "route_type": "bills_process", "final": str(final)}
    if h["is_bills_report_intent"](user_text):
        final = h["bills_report_text"]()
        if not str(final or "").strip():
            final = "账单查询失败：未知原因"
        return {"ok": True, "route_type": "bills_report", "final": str(final)}
    if h["is_bills_calendar_sync_intent"](user_text):
        final = h["bills_sync_only"]()
        if not str(final or "").strip():
            final = "账单日历同步失败：未知原因"
        return {"ok": True, "route_type": "bills_sync_calendar", "final": str(final)}
    return None


def derive_prefer_lang(user_text: str, language: str) -> str:
    lang = str(language or "").strip().lower()
    if re.search(r"[\u4e00-\u9fff]", str(user_text or "")):
        return "zh"
    if lang.startswith("zh"):
        return "zh"
    if lang.startswith("en"):
        return "en"
    return "en"


def route_llm_router_request(user_text: str, prefer_lang: str, route_return_data: bool, llm_allow: bool, h) -> Optional[dict]:
    if not llm_allow:
        return None
    dec = h["llm_route_decide"](user_text, prefer_lang)
    conf_th = h["llm_router_conf_threshold"]()
    if not isinstance(dec, dict):
        return None
    if float(dec.get("confidence") or 0.0) < conf_th:
        return None
    lb = str(dec.get("label") or "").strip().lower()
    if lb == "weather":
        return h["route_request_impl"]("天气 " + user_text, h.get("language"), False)
    if lb == "calendar":
        return h["route_request_impl"]("日程 " + user_text, h.get("language"), False)
    if lb == "holiday":
        return h["route_request_impl"]("公众假期 " + user_text, h.get("language"), False)
    if lb == "news":
        return h["route_request_impl"]("新闻 " + user_text, h.get("language"), False)
    if lb == "music":
        return h["route_request_impl"]("播放 " + user_text, h.get("language"), False)
    if lb == "bills":
        tlb = str(user_text or "").lower()
        bills_anchor = (
            ("账单" in user_text)
            or ("发票" in user_text)
            or ("水费" in user_text)
            or ("电费" in user_text)
            or ("燃气" in user_text)
            or ("物业" in user_text)
            or ("levy" in tlb)
            or ("invoice" in tlb)
            or ("bill" in tlb)
        )
        if not bills_anchor:
            lb = "web"
        else:
            if ("同步" in user_text and "日历" in user_text) or ("sync" in tlb and "calendar" in tlb):
                final = h["bills_sync_only"]()
                if not str(final or "").strip():
                    final = "账单日历同步失败：未知原因"
                return {"ok": True, "route_type": "bills_sync_calendar", "final": str(final)}
            if ("处理" in user_text) or ("拉取" in user_text) or ("process" in tlb) or ("pull" in tlb):
                final = h["bills_process_new"]()
                if not str(final or "").strip():
                    final = "账单拉取失败：未知原因"
                return {"ok": True, "route_type": "bills_process", "final": str(final)}
            final = h["bills_report_text"]()
            if not str(final or "").strip():
                final = "账单查询失败：未知原因"
            return {"ok": True, "route_type": "bills_report", "final": str(final)}
    if lb == "smalltalk":
        return {"ok": True, "route_type": "open_domain", "final": h["smalltalk_reply"](user_text, prefer_lang)}
    if lb == "poi":
        poi_final = h["poi_answer"](user_text, prefer_lang)
        if str(poi_final or "").strip():
            ret = {"ok": True, "route_type": "semi_structured_poi", "final": str(poi_final)}
            if route_return_data:
                ret["data"] = {"source": "google_places_new", "llm_router": dec}
            return ret
        return None
    if lb == "web":
        web_final, web_data = h["web_search_answer"](user_text, prefer_lang, limit=h["news_extract_limit"](user_text, 3))
        if str(web_final or "").strip():
            ret = {"ok": True, "route_type": "semi_structured_web", "final": str(web_final)}
            if route_return_data:
                ret["data"] = web_data
                ret["llm_router"] = dec
            return ret
    return None


def route_rag_and_fallback_request(user_text: str, prefer_lang: str, language: str, route_return_data: bool, llm_allow: bool, h) -> dict:
    if h["is_rag_disable_intent"](user_text):
        if prefer_lang == "en":
            return {"ok": True, "route_type": "rag_disable", "final": "OK, I won't use the home knowledge base. What would you like to ask?"}
        return {"ok": True, "route_type": "rag_disable", "final": "好的，不使用家庭资料库。你想问什么？"}

    mgmt_ret = h["rag_handle_management"](user_text, language or prefer_lang)
    if mgmt_ret:
        return mgmt_ret

    if h["is_rag_config_intent"](user_text):
        draft = h["rag_parse_config_draft"](user_text)
        h["rag_save_json_atomic"](h["rag_draft_path"](), draft)
        final = h["rag_config_draft_text"](draft, language or prefer_lang)
        return {"ok": True, "route_type": "rag_config_draft", "final": final}

    if h["is_rag_intent"](user_text):
        mode = h["rag_mode"](user_text)
        return {"ok": True, "route_type": "rag_stub", "final": h["rag_stub_answer"](user_text, language or prefer_lang, mode=mode)}

    llm_ret = route_llm_router_request(
        user_text,
        prefer_lang,
        route_return_data,
        llm_allow,
        {
            "language": language,
            "llm_route_decide": h["llm_route_decide"],
            "llm_router_conf_threshold": h["llm_router_conf_threshold"],
            "route_request_impl": h["route_request_impl"],
            "bills_sync_only": h["bills_sync_only"],
            "bills_process_new": h["bills_process_new"],
            "bills_report_text": h["bills_report_text"],
            "smalltalk_reply": h["smalltalk_reply"],
            "poi_answer": h["poi_answer"],
            "web_search_answer": h["web_search_answer"],
            "news_extract_limit": h["news_extract_limit"],
        },
    )
    if isinstance(llm_ret, dict):
        return llm_ret

    return h["default_fallback"](
        user_text,
        prefer_lang,
        route_return_data,
        is_obvious_smalltalk=h["is_obvious_smalltalk"],
        smalltalk_reply=h["smalltalk_reply"],
        is_poi_intent=h["is_poi_intent"],
        poi_answer=h["poi_answer"],
        web_search_answer=h["web_search_answer"],
        news_extract_limit=h["news_extract_limit"],
        has_strong_lookup_intent=h["has_strong_lookup_intent"],
        is_life_advice_intent=h["is_life_advice_intent"],
        life_advice_fallback=h["life_advice_fallback"],
    )


def route_request_core(text: str, language: str, llm_allow: bool, h) -> dict:
    route_return_data = str(h["env_get"]("ROUTE_RETURN_DATA", "") or "").strip().lower() in ("1", "true", "yes", "y")
    user_text = str(text or "").strip()
    if not user_text:
        return {"ok": True, "route_type": "open_domain", "final": "你可以直接说想查什么。", "hint": "empty text"}

    bills_ret = route_bills_request(
        user_text,
        {
            "is_bills_process_intent": h["is_bills_process_intent"],
            "is_bills_report_intent": h["is_bills_report_intent"],
            "is_bills_calendar_sync_intent": h["is_bills_calendar_sync_intent"],
            "bills_process_new": h["bills_process_new"],
            "bills_report_text": h["bills_report_text"],
            "bills_sync_only": h["bills_sync_only"],
        },
    )
    if isinstance(bills_ret, dict):
        return bills_ret

    if h["should_handoff_control"](user_text, h["is_home_control_like_intent"], h["is_music_control_query"]):
        return h["control_handoff_response"]()

    prefer_lang = derive_prefer_lang(user_text, language or "")
    if h["is_holiday_query"](user_text):
        return h["route_holiday_request"](
            user_text,
            route_return_data,
            {
                "now_local": h["now_local"],
                "holiday_vic": h["holiday_vic"],
                "holiday_next_from_list": h["holiday_next_from_list"],
                "holiday_prev_from_list": h["holiday_prev_from_list"],
            },
        )
    if h["is_weather_query"](user_text):
        return h["route_weather_request"](
            user_text,
            route_return_data,
            {
                "env_get": h["env_get"],
                "tzinfo": h["tzinfo"],
                "now_local": h["now_local"],
                "weather_range_from_text": h["weather_range_from_text"],
                "ha_weather_forecast": h["ha_weather_forecast"],
                "local_date_from_forecast_item": h["local_date_from_forecast_item"],
                "safe_int": h["safe_int"],
                "summarise_weather_range": h["summarise_weather_range"],
                "pick_daily_forecast_by_local_date": h["pick_daily_forecast_by_local_date"],
                "summarise_weather_item": h["summarise_weather_item"],
            },
        )
    if h["is_calendar_query"](user_text):
        return h["route_calendar_request"](
            user_text,
            route_return_data,
            {
                "env_get": h["env_get"],
                "calendar_entities_for_query": h["calendar_entities_for_query"],
                "tzinfo": h["tzinfo"],
                "now_local": h["now_local"],
                "calendar_is_delete_intent": h["calendar_is_delete_intent"],
                "calendar_is_update_intent": h["calendar_is_update_intent"],
                "calendar_range_from_text": h["calendar_range_from_text"],
                "iso_day_start_end": h["iso_day_start_end"],
                "calendar_fetch_merged_events": h["calendar_fetch_merged_events"],
                "calendar_pick_event_for_text": h["calendar_pick_event_for_text"],
                "calendar_event_summary": h["calendar_event_summary"],
                "calendar_ha_event_delete": h["calendar_ha_event_delete"],
                "calendar_ha_event_update": h["calendar_ha_event_update"],
                "calendar_is_create_intent": h["calendar_is_create_intent"],
                "calendar_build_create_event": h["calendar_build_create_event"],
                "bills_calendar_entity_id": h["bills_calendar_entity_id"],
                "bills_ha_event_create": h["bills_ha_event_create"],
                "safe_int": h["safe_int"],
                "summarise_calendar_events": h["summarise_calendar_events"],
            },
        )
    if h["news_is_query"](user_text):
        return h["route_news_request"](
            user_text,
            prefer_lang,
            route_return_data,
            {
                "news_category_from_text": h["news_category_from_text"],
                "news_time_range_from_text": h["news_time_range_from_text"],
                "news_hot": h["news_hot"],
                "news_digest": h["news_digest"],
                "news_extract_limit": h["news_extract_limit"],
            },
        )
    if h["is_music_control_query"](user_text):
        return h["route_music_request"](
            user_text,
            {
                "music_extract_target_entity": h["music_extract_target_entity"],
                "music_apply_aliases": h["music_apply_aliases"],
                "ha_call_service": h["ha_call_service"],
                "music_soft_mute": h["music_soft_mute"],
                "music_get_volume_level": h["music_get_volume_level"],
                "music_unmute_default": h["music_unmute_default"],
                "env_get": h["env_get"],
                "music_parse_volume": h["music_parse_volume"],
                "music_try_volume_updown": h["music_try_volume_updown"],
                "music_parse_volume_delta": h["music_parse_volume_delta"],
            },
        )

    return route_rag_and_fallback_request(
        user_text,
        prefer_lang,
        language or "",
        route_return_data,
        llm_allow,
        {
            "is_rag_disable_intent": h["is_rag_disable_intent"],
            "rag_handle_management": h["rag_handle_management"],
            "is_rag_config_intent": h["is_rag_config_intent"],
            "rag_parse_config_draft": h["rag_parse_config_draft"],
            "rag_save_json_atomic": h["rag_save_json_atomic"],
            "rag_draft_path": h["rag_draft_path"],
            "rag_config_draft_text": h["rag_config_draft_text"],
            "is_rag_intent": h["is_rag_intent"],
            "rag_mode": h["rag_mode"],
            "rag_stub_answer": h["rag_stub_answer"],
            "llm_route_decide": h["llm_route_decide"],
            "llm_router_conf_threshold": h["llm_router_conf_threshold"],
            "route_request_impl": h["route_request_impl"],
            "bills_sync_only": h["bills_sync_only"],
            "bills_process_new": h["bills_process_new"],
            "bills_report_text": h["bills_report_text"],
            "smalltalk_reply": h["smalltalk_reply"],
            "poi_answer": h["poi_answer"],
            "web_search_answer": h["web_search_answer"],
            "news_extract_limit": h["news_extract_limit"],
            "default_fallback": h["default_fallback"],
            "is_obvious_smalltalk": h["is_obvious_smalltalk"],
            "is_poi_intent": h["is_poi_intent"],
            "has_strong_lookup_intent": h["has_strong_lookup_intent"],
            "is_life_advice_intent": h["is_life_advice_intent"],
            "life_advice_fallback": h["life_advice_fallback"],
        },
    )


def looks_like_finance_price_query(text_norm: str) -> bool:
    t = str(text_norm or "").lower()
    keys = [
        "股价", "股票", "price", "share", "stock",
        "汇率", "exchange rate", "兑", "aud", "cny", "usd",
        "黄金", "gold", "油价", "oil",
        "指数", "index", "dxy", "纳斯达克", "nasdaq", "上证", "s&p", "sp500",
        "比特币", "bitcoin", "btc", "eth", "crypto",
    ]
    for k in keys:
        if k in t:
            return True
    return False


def finance_query_type(text_norm: str) -> str:
    t = str(text_norm or "").lower()
    if ("汇率" in t) or ("exchange rate" in t) or ("exchangerate" in t) or ("兑" in t) or ("aud/cny" in t) or ("usd/cny" in t):
        return "fx"
    if ("比特币" in t) or ("bitcoin" in t) or ("btc" in t) or ("eth" in t) or ("crypto" in t):
        return "crypto"
    if ("黄金" in t) or ("gold" in t) or ("油价" in t) or ("oil" in t):
        return "commodity"
    if ("指数" in t) or ("index" in t) or ("dxy" in t) or ("nasdaq" in t) or ("纳斯达克" in t) or ("上证" in t) or ("s&p" in t) or ("sp500" in t):
        return "index"
    if ("股价" in t) or ("股票" in t) or ("stock" in t) or ("share" in t):
        return "stock"
    return "generic"


def is_aud_usd_query(text_norm: str) -> bool:
    t = str(text_norm or "").lower().replace(" ", "")
    if ("audusd" in t) or ("aud/usd" in t) or ("澳元美元" in t) or ("澳元兑美元" in t):
        return True
    return False


def finance_guidance_by_type(qtype: str) -> str:
    tp = str(qtype or "").strip()
    if tp == "fx":
        return "当前汇率线索不稳定，先不报具体数值。你可以用规范查询：AUDCNY 或 AUD/USD latest。"
    if tp == "stock":
        return "当前股价线索不稳定，先不报具体数值。你可以补充 ticker 和市场，例如 TSLA NASDAQ 或 AAPL NASDAQ。"
    if tp == "crypto":
        return "当前币价线索不稳定，先不报具体数值。你可以用规范查询：BTC-USD 或 ETH-USD。"
    if tp == "commodity":
        return "当前大宗商品线索不稳定，先不报具体数值。你可以用规范查询：XAUUSD（gold spot per ounce）。"
    if tp == "index":
        return "当前指数线索不稳定，先不报具体数值。你可以用规范查询：^GSPC、^IXIC 或 DXY。"
    return "当前价格结果不够稳定。你可以补充资产名称、市场或币种后再试，我会返回具体数字。"


def finance_label_and_unit(text_raw: str, text_norm: str, qtype: str) -> tuple:
    t = str(text_raw or "")
    tn = str(text_norm or "").lower()
    tl = t.lower()
    if is_aud_usd_query(tn):
        return ("AUD/USD", "USD")
    if ("aud" in tn and "cny" in tn) or ("澳元兑人民币" in t) or ("audcny" in tn):
        return ("AUD/CNY", "CNY")
    if ("tesla" in tl) or ("tsla" in tn) or ("特斯拉" in t):
        return ("TSLA", "USD")
    if ("apple" in tl) or ("aapl" in tn) or ("苹果" in t):
        return ("AAPL", "USD")
    if ("btc" in tn) or ("bitcoin" in tl) or ("比特币" in t):
        return ("BTC-USD", "USD")
    if ("eth" in tn) or ("ethereum" in tl):
        return ("ETH-USD", "USD")
    if ("xau" in tn) or ("gold" in tl) or ("黄金" in t):
        return ("XAUUSD", "USD/oz")
    if ("gspc" in tn) or ("s&p" in tl) or ("sp500" in tn) or ("标普" in t):
        return ("S&P 500 (^GSPC)", "points")
    if ("ixic" in tn) or ("nasdaq" in tl) or ("纳斯达克" in t):
        return ("NASDAQ (^IXIC)", "points")
    if ("dxy" in tn) or ("美元指数" in t):
        return ("DXY", "points")
    if str(qtype or "") == "index":
        return ("Index", "points")
    if str(qtype or "") == "fx":
        return ("FX pair", "")
    if str(qtype or "") == "crypto":
        return ("Crypto", "USD")
    if str(qtype or "") == "commodity":
        return ("Commodity", "USD")
    return ("Asset", "")


def finance_confidence_level(qtype: str, label: str, evidence: str, sources: list, facts: list) -> str:
    ev = str(evidence or "").strip()
    if not ev:
        return "low"
    lbl = str(label or "").lower()
    strong_domains = {"finance.yahoo.com", "yahoo.com", "tradingview.com", "marketwatch.com", "investing.com", "bloomberg.com", "reuters.com", "google.com"}
    src_hit = 0
    for s in (sources or []):
        if not isinstance(s, dict):
            continue
        dom = str(s.get("source") or "").strip().lower()
        if dom in strong_domains:
            src_hit += 1
    corpus = ev.lower() + " | " + " | ".join([str(x or "").lower() for x in (facts or [])[:5]])
    asset_tokens = []
    if ("btc" in lbl) or ("bitcoin" in lbl):
        asset_tokens = ["btc", "bitcoin", "btc-usd"]
    elif ("xau" in lbl) or ("gold" in lbl):
        asset_tokens = ["xau", "gold", "spot", "ounce"]
    elif ("aapl" in lbl):
        asset_tokens = ["aapl", "apple", "nasdaq"]
    elif ("tsla" in lbl):
        asset_tokens = ["tsla", "tesla", "nasdaq"]
    elif ("gspc" in lbl) or ("s&p" in lbl):
        asset_tokens = ["gspc", "s&p", "sp500", "index", "points"]
    elif ("ixic" in lbl) or ("nasdaq" in lbl):
        asset_tokens = ["ixic", "nasdaq", "index", "points"]
    elif ("dxy" in lbl):
        asset_tokens = ["dxy", "index", "points"]
    elif ("aud/cny" in lbl):
        asset_tokens = ["aud", "cny", "exchange rate", "fx", "汇率"]
    elif ("aud/usd" in lbl):
        asset_tokens = ["aud", "usd", "exchange rate", "fx", "汇率"]
    else:
        asset_tokens = ["price", "quote", "last", "现价", "报价"]
    asset_hit = any(k in corpus for k in asset_tokens)
    if (src_hit >= 1) and asset_hit:
        return "high"
    if asset_hit:
        return "medium"
    return "low"


def finance_normalize_query(text_norm: str) -> str:
    t = str(text_norm or "").strip()
    tl = t.lower()
    if ("s&p" in tl) or ("sp500" in tl) or ("标普" in t):
        return "S&P 500 index level ^GSPC"
    if ("纳斯达克" in t) or ("nasdaq" in tl):
        return "NASDAQ Composite index level ^IXIC"
    if ("特斯拉" in t) or ("tesla" in tl):
        return "TSLA stock price NASDAQ"
    if ("苹果" in t) or ("apple" in tl) or ("aapl" in tl):
        return "AAPL stock price NASDAQ"
    if ("澳元兑人民币" in t) or ("audcny" in tl) or (("aud" in tl) and ("cny" in tl)) or (("澳元" in t) and ("人民币" in t)):
        return "AUD to CNY exchange rate"
    if is_aud_usd_query(tl):
        return "AUD to USD exchange rate"
    if ("黄金" in t) or ("gold" in tl):
        return "XAUUSD spot price per ounce"
    if ("比特币" in t) or ("bitcoin" in tl) or ("btc" in tl):
        return "BTC price USD"
    if ("美元指数" in t) or ("dxy" in tl):
        return "DXY index value"
    if ("eth" in tl) or ("以太坊" in t):
        return "ETH price USD"
    if ("汇率" in t) or ("exchange rate" in tl) or ("兑" in t):
        return t + " exchange rate"
    return t + " price"


def finance_value_range(qtype: str, text_norm: str) -> tuple:
    t = str(text_norm or "").lower()
    tp = str(qtype or "").strip().lower()
    if ("btc" in t) or ("bitcoin" in t) or ("比特币" in t):
        return (1000.0, 1000000.0)
    if ("eth" in t) or ("以太坊" in t):
        return (50.0, 100000.0)
    if ("gold" in t) or ("黄金" in t):
        return (100.0, 10000.0)
    if ("dxy" in t):
        return (50.0, 200.0)
    if ("s&p" in t) or ("sp500" in t) or ("nasdaq" in t) or ("纳斯达克" in t):
        return (1000.0, 100000.0)
    if ("上证" in t):
        return (1000.0, 100000.0)
    if tp == "stock":
        return (10.0, 5000.0)
    if tp == "crypto":
        return (50.0, 1000000.0)
    if tp == "commodity":
        return (100.0, 10000.0)
    if tp == "index":
        return (50.0, 100000.0)
    if tp == "fx":
        if is_aud_usd_query(t):
            return (0.2, 2.0)
        return (0.1, 20.0)
    return (0.0, 1000000000.0)


def finance_neighbor_keywords(qtype: str, text_norm: str) -> list:
    out = []
    t = str(text_norm or "").lower()
    tp = str(qtype or "").strip().lower()
    if tp == "stock":
        out.extend(["stock", "share", "price", "nasdaq", "nyse", "tsla", "aapl", "股票", "股价"])
    if tp == "crypto":
        out.extend(["btc", "bitcoin", "eth", "crypto", "coin", "币价", "比特币", "以太坊"])
    if tp == "commodity":
        out.extend(["gold", "spot", "xau", "ounce", "per oz", "per ounce", "oil", "wti", "brent", "黄金", "油价"])
    if tp == "index":
        out.extend(["dxy", "index", "level", "nasdaq", "composite", "s&p", "sp500", "gspc", "ixic", "上证", "指数"])
    if tp == "fx":
        out.extend(["exchange rate", "rate", "汇率", "兑", "aud", "usd", "cny", "rmb"])
    for k in ["tsla", "aapl", "btc", "eth", "dxy", "aud", "usd", "cny", "gold", "nasdaq", "sp500", "s&p"]:
        if k in t:
            out.append(k)
    return list(dict.fromkeys([str(x).strip().lower() for x in out if str(x).strip()]))


def finance_extract_evidence(text: str, qtype: str = "generic", text_norm: str = "") -> dict:
    src = str(text or "").strip()
    if not src:
        return {"evidence": "", "value": None, "filtered_out_count": 0}
    chunks = re.split(r"[|。；;!?！？\n]+", src)
    low, high = finance_value_range(qtype, text_norm)
    neigh = finance_neighbor_keywords(qtype, text_norm)
    cand_num = re.compile(r"(?<!\d)(\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?)(?!\d)")
    best = None
    filtered_out = 0
    tnorm = str(text_norm or "").lower()
    is_index = (str(qtype or "").lower() == "index")
    is_gold = (("gold" in tnorm) or ("黄金" in tnorm) or ("xau" in tnorm))
    is_stock = (str(qtype or "").lower() == "stock")
    is_fx = (str(qtype or "").lower() == "fx")
    is_crypto = (str(qtype or "").lower() == "crypto")
    is_commodity = (str(qtype or "").lower() == "commodity")
    strong_anchor_index = ["gspc", "ixic", "nasdaq", "s&p", "sp500", "index", "level", "dxy"]
    strong_anchor_gold = ["xau", "ounce", "per oz", "per ounce", "spot", "gold", "黄金"]
    strong_anchor_stock = ["stock", "share", "quote", "last", "price", "股价", "现价", "行情", "tsla", "aapl", "nasdaq", "nyse"]
    strong_anchor_fx = ["exchange rate", "fx", "rate", "汇率", "aud", "usd", "cny", "rmb", "兑"]
    strong_anchor_crypto = ["btc", "bitcoin", "eth", "crypto", "coin", "币价", "比特币", "以太坊"]
    strong_anchor_commodity = ["gold", "xau", "spot", "ounce", "oil", "wti", "brent", "黄金", "油价"]

    for ck in chunks:
        c = str(ck or "").strip()
        if not c:
            continue
        cl = c.lower()
        near_hit = any(k in cl for k in neigh)
        if is_index and (not any(k in cl for k in strong_anchor_index)):
            continue
        if is_gold and (not any(k in cl for k in strong_anchor_gold)):
            continue
        if is_stock and (not any(k in cl for k in strong_anchor_stock)):
            continue
        if is_fx and (not any(k in cl for k in strong_anchor_fx)):
            continue
        if is_crypto and (not any(k in cl for k in strong_anchor_crypto)):
            continue
        if is_commodity and (not any(k in cl for k in strong_anchor_commodity)):
            continue
        for m in cand_num.finditer(c):
            raw_num = str(m.group(1) or "").strip()
            if not raw_num:
                continue
            num_norm = raw_num.replace(",", "").replace(" ", "")
            try:
                v = float(num_norm)
            except Exception:
                continue
            if is_index and (v < 1000.0) and ("dxy" not in cl):
                filtered_out += 1
                continue
            if is_gold and (v > 10000.0):
                filtered_out += 1
                continue
            ctx_l = c[max(0, int(m.start()) - 14):int(m.start())].lower()
            ctx_r = c[int(m.end()):min(len(c), int(m.end()) + 14)].lower()
            ctx_both = (ctx_l + " " + ctx_r).strip()
            if re.search(r"(分钟前|小时前|天前|days?\s+ago|hours?\s+ago|mins?\s+ago|weeks?\s+ago)", ctx_both, flags=re.IGNORECASE):
                filtered_out += 1
                continue
            if re.search(r"(top|best|rank|排名|第)", ctx_l, flags=re.IGNORECASE):
                filtered_out += 1
                continue
            if re.search(r"(%|percent)", ctx_r, flags=re.IGNORECASE):
                filtered_out += 1
                continue
            if (v >= 1900.0) and (v <= 2100.0):
                if re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|as of|updated|日期)", cl, flags=re.IGNORECASE):
                    filtered_out += 1
                    continue
            if (str(qtype or "").lower() == "index") and (abs(v - 500.0) < 0.0001):
                left_ctx = c[max(0, int(m.start()) - 6):int(m.start())].lower()
                if ("s&p" in left_ctx) or ("sp" in left_ctx):
                    filtered_out += 1
                    continue
            if (v < low) or (v > high):
                filtered_out += 1
                continue
            if is_stock and (("tsla" in tnorm) or ("tesla" in tnorm) or ("aapl" in tnorm) or ("apple" in tnorm)):
                if v < 50.0:
                    filtered_out += 1
                    continue
            left = max(0, int(m.start()) - 12)
            right = min(len(c), int(m.end()) + 12)
            window = c[left:right]
            score = 0
            if near_hit:
                score += 2
            if re.search(r"(?:A\$|AU\$|US\$|\$|USD|AUD|CNY|RMB|¥|点|points?)", window, flags=re.IGNORECASE):
                score += 1
            if re.search(r"(?:exchange rate|汇率|index|spot|price|股价|指数|现价)", cl, flags=re.IGNORECASE):
                score += 1
            if re.search(r"(?:nasdaq|nyse|gspc|ixic|dxy|tsla|aapl|btc|xau)", cl, flags=re.IGNORECASE):
                score += 1
            ev = num_norm
            sym_left = c[max(0, int(m.start()) - 2):int(m.start())]
            if re.search(r"(?:\$|¥)", sym_left):
                ev = sym_left.strip()[-1:] + ev
            elif re.search(r"(?:USD|AUD|CNY|RMB)", window, flags=re.IGNORECASE):
                if str(qtype or "").lower() in ["stock", "crypto", "commodity", "fx"]:
                    ev = ev + " USD"
            if (best is None) or (score > int(best.get("score") or 0)):
                best = {"evidence": ev, "value": v, "score": score}

    if best is None:
        return {"evidence": "", "value": None, "filtered_out_count": filtered_out}
    return {"evidence": str(best.get("evidence") or "").strip(), "value": best.get("value"), "filtered_out_count": filtered_out}


def finance_extract_evidence_ai(text: str, qtype: str = "generic", text_norm: str = "", user_query: str = "") -> dict:
    src = str(text or "").strip()
    if not src:
        return {"evidence": "", "value": None, "confidence": "low", "ai_used": False}
    try:
        if str(os.environ.get("FINANCE_EVIDENCE_AI_ENABLE") or "1").strip().lower() in ["0", "false", "off", "no"]:
            return {"evidence": "", "value": None, "confidence": "low", "ai_used": False}
    except Exception:
        pass

    model = str(os.environ.get("FINANCE_EVIDENCE_MODEL") or "qwen3-vl:2b").strip()
    if not model:
        model = "qwen3-vl:2b"
    base = str(os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip().rstrip("/")
    if not base:
        base = "http://192.168.1.162:11434"

    payload_text = src
    if len(payload_text) > 2400:
        payload_text = payload_text[:2400]

    query_line = str(user_query or "").strip()
    target_label = str(qtype or "generic").strip().lower()
    prompt = (
        "Extract one best numeric market quote from the text.\n"
        "User query: " + query_line + "\n"
        "Target asset/type: " + target_label + "\n"
        "Rules:\n"
        "1) Use only numbers explicitly present in text.\n"
        "2) Prefer values near finance anchors (price/quote/stock/index/exchange rate/spot).\n"
        "3) Ignore dates, rankings, counts, percentages, and time-ago numbers.\n"
        "4) Return JSON only with keys: value, evidence, unit, confidence.\n"
        "5) If not reliable, set value null and confidence low.\n"
        "Text:\n" + payload_text
    )
    req = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    try:
        r = requests.post(base + "/api/chat", json=req, timeout=12)
        if int(getattr(r, "status_code", 0) or 0) >= 400:
            return {"evidence": "", "value": None, "confidence": "low", "ai_used": True, "error": "http_" + str(getattr(r, "status_code", ""))}
        data = r.json() if hasattr(r, "json") else {}
        msg = data.get("message") if isinstance(data, dict) else {}
        out = str((msg or {}).get("content") or "").strip()
        if not out:
            return {"evidence": "", "value": None, "confidence": "low", "ai_used": True}
        m = re.search(r"\{[\s\S]*\}", out)
        if m:
            out = str(m.group(0) or "").strip()
        obj = json.loads(out)
        vv = obj.get("value")
        ev = str(obj.get("evidence") or "").strip()
        unit = str(obj.get("unit") or "").strip()
        conf = str(obj.get("confidence") or "low").strip().lower()
        if conf not in ["low", "medium", "high"]:
            conf = "low"
        try:
            val = float(vv) if vv is not None else None
        except Exception:
            val = None
        if val is None:
            return {"evidence": "", "value": None, "confidence": conf, "ai_used": True}
        bad_unit = (unit + " " + ev).lower()
        if re.search(r"\b(hour|hours|min|mins|minute|minutes|day|days|week|weeks|month|months|year|years)\b", bad_unit):
            return {"evidence": "", "value": None, "confidence": "low", "ai_used": True, "filtered": "time_unit_noise"}
        if re.search(r"(小时前|分钟前|天前|周前|月前|年前)", bad_unit):
            return {"evidence": "", "value": None, "confidence": "low", "ai_used": True, "filtered": "time_unit_noise"}
        low, high = finance_value_range(qtype, text_norm)
        if (val < low) or (val > high):
            return {"evidence": "", "value": None, "confidence": "low", "ai_used": True, "filtered": "out_of_range"}
        tn = str(text_norm or "").lower()
        if str(qtype or "").lower() == "stock" and (("tsla" in tn) or ("tesla" in tn) or ("aapl" in tn) or ("apple" in tn)):
            if val < 50.0:
                return {"evidence": "", "value": None, "confidence": "low", "ai_used": True, "filtered": "known_ticker_floor"}
        neigh = finance_neighbor_keywords(qtype, text_norm)
        anchor_blob = (ev + " " + src).lower()
        if neigh and (not any(str(k or "").lower() in anchor_blob for k in neigh)):
            return {"evidence": "", "value": None, "confidence": "low", "ai_used": True, "filtered": "anchor_miss"}
        ev_out = str(val)
        if unit:
            ev_out = ev_out + " " + unit
        elif str(qtype or "").lower() in ["stock", "crypto", "commodity", "fx"]:
            ev_out = ev_out + " USD"
        return {"evidence": ev_out.strip(), "value": val, "confidence": conf, "ai_used": True}
    except Exception:
        return {"evidence": "", "value": None, "confidence": "low", "ai_used": True}


def clarify_route_to_utterance(route_name: str) -> str:
    mp = {
        "weather": "今天天气",
        "calendar": "今天日程",
        "news": "今天本地新闻",
        "bills": "检查账单",
        "holiday": "下一个公众假期",
        "music": "播放音乐",
        "briefing_rule": "给我一个晨间简报",
        "plan_rule": "给我一个学习计划",
        "productivity_rule": "如何提高效率",
        "rag": "在资料库里搜内容 关键词",
        "template_web": "找发票模板",
        "chitchat": "给我一个晚间简报",
        "local_info_web": "附近营业时间",
        "web": "搜索 关键词",
        "datetime": "现在几点",
        "fallback_local_first": "请补充关键词",
    }
    return str(mp.get(str(route_name or "").strip(), "今天天气"))


def score_and_pick_rule(
    rules: list,
    ctx: Any,
    min_final: float = 10.5,
    gap_threshold: float = 0.2,
    min_score: float = 0.25,
    debug_log: Optional[Callable[[str], None]] = None,
) -> dict:
    candidates = []
    for r in rules:
        sc = r.score(ctx)
        if (sc <= 0.0) and (str(getattr(r, "name", "")) != "fallback_local_first"):
            continue
        final_v = (float(getattr(r, "priority", 0)) * 10.0) + float(sc)
        candidates.append(
            {
                "name": str(getattr(r, "name", "") or ""),
                "score": sc,
                "priority": int(getattr(r, "priority", 0) or 0),
                "final": final_v,
                "reason": r.reason(ctx),
                "rule": r,
            }
        )
    candidates.sort(key=lambda x: float(x.get("final") or 0.0), reverse=True)
    top_dbg = []
    for c in candidates[:6]:
        top_dbg.append(
            {
                "name": c.get("name"),
                "score": round(float(c.get("score") or 0.0), 3),
                "priority": int(c.get("priority") or 0),
                "final": round(float(c.get("final") or 0.0), 3),
                "reason": c.get("reason") or "",
            }
        )
    if bool(getattr(ctx, "debug", False)) and callable(debug_log):
        debug_log("route_candidates=" + str(top_dbg))

    if len(candidates) == 0:
        return {"special": "clarify", "candidates": [], "chosen": None}
    top1 = candidates[0]
    top2 = candidates[1] if len(candidates) > 1 else None
    top_final = float(top1.get("final") or 0.0)
    top_score = float(top1.get("score") or 0.0)
    gap = (top_final - float(top2.get("final") or 0.0)) if top2 else 999.0
    uncertain = False
    if top_final < float(min_final):
        uncertain = True
    if top_score < float(min_score):
        uncertain = True
    if top2 and gap < float(gap_threshold):
        uncertain = True
    if uncertain:
        return {"special": "clarify", "candidates": candidates, "chosen": None}
    return {"special": "", "candidates": candidates, "chosen": top1}


def build_clarify_plan(candidates: list) -> dict:
    route_to_label = {
        "weather": "天气",
        "calendar": "日程",
        "news": "新闻",
        "bills": "账单",
        "briefing_rule": "简报",
        "plan_rule": "计划",
        "productivity_rule": "效率建议",
        "rag": "资料库",
        "template_web": "模板搜索",
        "chitchat": "日常对话",
        "local_info_web": "本地信息",
        "web": "上网搜索",
        "music": "音乐控制",
        "datetime": "时间日期",
        "fallback_local_first": "通用问题",
    }
    top = []
    for c in (candidates or []):
        if not isinstance(c, dict):
            continue
        nm = str(c.get("name") or "").strip()
        sc = float(c.get("score") or 0.0)
        if (not nm) or (sc <= 0.0):
            continue
        top.append(c)
        if len(top) >= 3:
            break

    opts = []
    seen = set()
    for c in top:
        nm = str(c.get("name") or "").strip()
        if (not nm) or (nm in seen):
            continue
        seen.add(nm)
        ut = clarify_route_to_utterance(nm)
        lb = str(route_to_label.get(nm) or nm)
        opts.append({"route": nm, "utterance": ut, "label": lb})
        if len(opts) >= 4:
            break

    if len(opts) < 2:
        for nm in ["weather", "calendar", "news", "bills", "rag", "web"]:
            if nm in seen:
                continue
            seen.add(nm)
            opts.append({"route": nm, "utterance": clarify_route_to_utterance(nm), "label": str(route_to_label.get(nm) or nm)})
            if len(opts) >= 4:
                break

    if len(opts) == 0:
        return {
            "opts": [],
            "top": [],
            "final_text": "我需要你补充一下你想查什么：比如天气、日程、新闻、账单、或在资料库里找。",
            "facts": ["示例：今天天气", "示例：今天日程", "示例：今天本地新闻", "示例：检查账单"],
            "actions": [
                {"text": "今天天气", "route": "weather"},
                {"text": "今天本地新闻", "route": "news"},
            ],
        }

    labels = [str(it.get("label") or "") for it in opts[:3] if str(it.get("label") or "").strip()]
    utterances = [str(it.get("utterance") or "") for it in opts[:2] if str(it.get("utterance") or "").strip()]

    if len(labels) >= 2 and len(utterances) >= 2:
        final_text = "你想要{0}还是{1}？你可以说“{2}”或“{3}”。".format(labels[0], labels[1], utterances[0], utterances[1])
    elif len(labels) >= 1 and len(utterances) >= 1:
        final_text = "我理解你可能在问{0}。你可以说“{1}”。".format(labels[0], utterances[0])
    else:
        final_text = "我需要你补充一下你想查什么：比如天气、日程、新闻、账单、或在资料库里找。"

    facts = []
    actions = []
    for it in opts[:4]:
        ut = str(it.get("utterance") or "").strip()
        rt = str(it.get("route") or "").strip()
        if ut:
            facts.append("示例：" + ut)
            actions.append({"text": ut, "route": rt})
    return {"opts": opts, "top": top[:3], "final_text": final_text, "facts": facts[:4], "actions": actions[:4]}


def match_clarify_followup(mem: dict, text_raw: str, now_ts: Optional[float] = None, ttl_sec: float = 60.0) -> str:
    if not isinstance(mem, dict):
        return ""
    ts = float(mem.get("ts") or 0.0)
    cur = float(now_ts if now_ts is not None else 0.0)
    if (cur <= 0.0) or ((cur - ts) > float(ttl_sec)):
        return ""
    txt = str(text_raw or "").strip().lower()
    txt_n = re.sub(r"\s+", "", txt)
    short_tokens = {"天气", "日程", "新闻", "账单", "假期", "音乐", "time", "date"}
    if (len(txt_n) > 6) and (txt_n not in short_tokens):
        return ""
    mapping = {
        "weather": ["天气", "weather", "rain", "温度"],
        "calendar": ["日程", "日历", "calendar"],
        "news": ["新闻", "news"],
        "bills": ["账单", "bill", "invoice"],
        "holiday": ["假期", "holiday"],
        "music": ["音乐", "music", "播放"],
        "datetime": ["几点", "几号", "time", "date"],
    }
    route_hit = ""
    for rn, kws in mapping.items():
        for kw in kws:
            if kw in txt_n:
                route_hit = rn
                break
        if route_hit:
            break
    if not route_hit:
        return ""
    opts = mem.get("options") or []
    allow = set([str(it.get("route") or "").strip() for it in opts if isinstance(it, dict)])
    if allow and (route_hit not in allow):
        return ""
    return route_hit


def wrap_any_result(
    raw: Any,
    route_name: str,
    mode: str,
    extra_meta: Optional[dict],
    skill_result_fn: Callable[[str, Optional[list], Optional[list], Optional[list], Optional[dict]], dict],
    extract_facts_fn: Callable[[str, int], list],
) -> dict:
    def _polish(route_nm: str, final_text: str) -> str:
        rt = str(route_nm or "").strip()
        ft = str(final_text or "").strip()
        if not ft:
            return ft
        if rt == "music":
            if len(ft) < 10:
                return "音乐控制已执行：" + ft
        if rt == "calendar":
            if "没有日程" in ft:
                return ft + " 你可以说“提醒我明天上午十点开会”。"
        if rt == "weather":
            ft = ft.replace("None°C", "暂无")
            ft = ft.replace("暂无°C", "暂无")
            ft = re.sub(r"预计降雨\s*([0-9]+(?:\.[0-9]+)?)\s*(?:。|$)", r"预计降雨 \1 mm。", ft)
            ft = re.sub(r"最高/最低:\s*([^/]+)\s*/\s*暂无", r"最高/最低: \1 / 暂无", ft)
            ft = ft.replace("最低：暂无°C", "最低：暂无")
            ft = ft.replace("最高：暂无°C", "最高：暂无")
            ft = re.sub(r"\s+/\s+", " / ", ft)
        return ft

    meta = {"skill": "answer_question", "mode": mode, "route": str(route_name or "").strip()}
    if isinstance(extra_meta, dict):
        for k, v in extra_meta.items():
            if k == "candidates" and isinstance(v, list):
                meta[k] = sanitize_route_candidates(v)
            else:
                meta[k] = v

    if isinstance(raw, dict):
        if "final_text" in raw:
            out = skill_result_fn(
                _polish(route_name, raw.get("final_text")),
                (raw.get("facts") if isinstance(raw.get("facts"), list) else []),
                (raw.get("sources") if isinstance(raw.get("sources"), list) else []),
                (raw.get("next_actions") if isinstance(raw.get("next_actions"), list) else []),
                (raw.get("meta") if isinstance(raw.get("meta"), dict) else {}),
            )
            out_meta = out.get("meta") or {}
            out_meta["route"] = str(route_name or "")
            out_meta["skill"] = "answer_question"
            out_meta["mode"] = str(mode or "")
            if isinstance(out_meta.get("candidates"), list):
                out_meta["candidates"] = sanitize_route_candidates(out_meta.get("candidates"))
            if isinstance(extra_meta, dict):
                for k, v in extra_meta.items():
                    if k == "candidates" and isinstance(v, list):
                        out_meta[k] = sanitize_route_candidates(v)
                    else:
                        out_meta[k] = v
            out["meta"] = out_meta
            return out
        final_s = _polish(route_name, str(raw.get("final_voice") or raw.get("final") or "").strip())
        facts = extract_facts_fn(final_s, 5)
        return skill_result_fn(final_s, facts[:5], [], [], meta)

    final_s = _polish(route_name, str(raw or "").strip())
    return skill_result_fn(final_s, extract_facts_fn(final_s, 5), [], [], meta)


def compose_compound_answer(
    ctx: Any,
    mode: str,
    rule_by_name: dict,
    route_request_fn: Callable[[str, str, bool], dict],
    wrap_fn: Callable[[Any, str, str, Optional[dict]], dict],
    skill_result_fn: Callable[[str, Optional[list], Optional[list], Optional[list], Optional[dict]], dict],
    debug_log: Optional[Callable[[str], None]] = None,
) -> dict:
    def _calendar_compound_query(text_raw: str) -> str:
        t = str(text_raw or "").strip()
        if ("大后天" in t) or ("大後天" in t):
            return "大后天日程"
        if ("后天" in t) or ("後天" in t):
            return "后天日程"
        if "明天" in t:
            return "明天日程"
        if ("下周" in t) or ("下星期" in t):
            return "下周日程"
        if ("本周" in t) or ("这周" in t):
            return "本周日程"
        return "今天日程"

    q = str(getattr(ctx, "text_raw", "") or "").strip()
    has_w = has_weather_intent(q)
    has_c = has_calendar_intent(q)
    has_n = has_news_intent(q)
    pair = []
    if has_w and has_c:
        pair = ["weather", "calendar"]
    elif has_n and has_c:
        pair = ["calendar", "news"]
    if len(pair) != 2:
        return {}

    segs = []
    all_facts = []
    all_sources = []
    for rn in pair:
        rr = rule_by_name.get(rn)
        if rr is None:
            continue
        try:
            if rn == "calendar":
                cal_q = _calendar_compound_query(q)
                raw = route_request_fn(cal_q, str(getattr(ctx, "language", "") or ""), False)
            else:
                raw = rr.handle(ctx)
            wrapped = wrap_fn(raw, rn, mode, {"compound": True})
            ft = str((wrapped.get("final_text") if isinstance(wrapped, dict) else "") or "").strip()
            if ft:
                segs.append(ft)
            facts = (wrapped.get("facts") if isinstance(wrapped, dict) and isinstance(wrapped.get("facts"), list) else [])
            sources = (wrapped.get("sources") if isinstance(wrapped, dict) and isinstance(wrapped.get("sources"), list) else [])
            for x in facts:
                if len(all_facts) >= 6:
                    break
                xv = str(x or "").strip()
                if xv and (xv not in all_facts):
                    all_facts.append(xv)
            for s in sources:
                if len(all_sources) >= 6:
                    break
                if not isinstance(s, dict):
                    continue
                all_sources.append(s)
        except Exception:
            continue

    if len(segs) == 0:
        return {}
    final = " ".join(segs)
    if not str(final or "").strip():
        return {}
    if bool(getattr(ctx, "debug", False)) and callable(debug_log):
        debug_log("compound_route=" + str(pair))
    return skill_result_fn(
        final,
        all_facts[:6],
        all_sources[:6],
        [],
        {"skill": "answer_question", "mode": mode, "route": "compound", "compound_routes": pair},
    )


def looks_like_local_info_query(text_norm: str) -> bool:
    t = str(text_norm or "").lower()
    keys = [
        "附近", "营业时间", "openinghours", "开放时间", "几点关门",
        "停车", "票价", "门票", "路线", "机票", "怎么选",
        "costco", "bunnings", "airportparking", "房价走势",
    ]
    for k in keys:
        if k in t:
            return True
    return False


def looks_like_parking_fee_query(text_raw: str) -> bool:
    t = str(text_raw or "").strip()
    tl = t.lower()
    keys = ["停车", "停车费", "parking", "car park", "carpark"]
    return any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())


def looks_like_open_advice_general_query(text_raw: str) -> bool:
    t = str(text_raw or "").strip()
    tl = t.lower()
    keys = [
        "学习计划", "study plan", "提高效率", "专注", "拖延",
        "晚间简报", "晨间简报", "morning brief", "evening brief",
        "今天需要注意什么", "周末去哪玩", "晚饭吃什么", "今晚吃什么",
        "讲个笑话", "笑话", "joke",
    ]
    return any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())


def looks_like_property_info_query(text_raw: str) -> bool:
    t = str(text_raw or "").strip()
    tl = t.lower()
    keys = ["房价走势", "房价", "利率", "电价变化", "租房市场", "租金", "property", "rent", "interest rate", "electricity price"]
    return any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())


def looks_like_home_health_check_query(text_raw: str) -> bool:
    t = str(text_raw or "").strip()
    tl = t.lower()
    keys = ["家里设备有异常吗", "设备异常", "有啥坏了", "有什么提醒", "home device issue", "device abnormal", "alerts"]
    return any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())


def has_weather_intent(text: str) -> bool:
    t = str(text or "").strip()
    tl = t.lower()
    keys = ["天气", "温度", "气温", "下雨", "降雨", "weather", "rain", "forecast"]
    return (any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii()))


def has_calendar_intent(text: str) -> bool:
    t = str(text or "").strip()
    tl = t.lower()
    keys = ["日程", "日历", "日曆", "安排", "行程", "calendar", "schedule", "提醒"]
    return (any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii()))


def has_news_intent(text: str) -> bool:
    t = str(text or "").strip()
    tl = t.lower()
    keys = ["新闻", "热点", "news", "headline", "headlines"]
    return (any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii()))


def looks_like_home_device_state_query(text_raw: str) -> bool:
    t = str(text_raw or "").strip()
    tl = t.lower()
    has_entity = bool(re.search(r"\b[a-z_]+\.[a-z0-9_]+\b", tl))
    if has_entity:
        return False
    device_terms = ["洗衣机", "烘干机", "洗碗机", "空调", "washer", "dryer", "dishwasher", "ac", "aircon"]
    state_terms = ["状态", "开着吗", "关着吗", "运行", "在运行", "是否", "status", "running", "on", "off"]
    hit_d = any(k in t for k in device_terms if not k.isascii()) or any(k in tl for k in device_terms if k.isascii())
    hit_s = any(k in t for k in state_terms if not k.isascii()) or any(k in tl for k in state_terms if k.isascii())
    return bool(hit_d and hit_s)


def load_answer_route_whitelist(env_value: str = "") -> Set[str]:
    raw = str(env_value or "").strip()
    if not raw:
        return set(DEFAULT_ANSWER_ROUTE_WHITELIST)
    out = set()
    for part in raw.split(","):
        x = str(part or "").strip()
        if x:
            out.add(x)
    if len(out) == 0:
        return set(DEFAULT_ANSWER_ROUTE_WHITELIST)
    return out


def enforce_answer_route_whitelist(
    picked: Dict,
    rules: List,
    allowed_routes: Set[str],
    debug: bool = False,
    debug_log: Optional[Callable[[str], None]] = None,
) -> Dict:
    if not isinstance(picked, dict):
        return picked
    if str(picked.get("special") or "") == "clarify":
        return picked

    chosen = picked.get("chosen") or {}
    chosen_name = str(chosen.get("name") or "")
    if not chosen_name:
        return picked
    if chosen_name in allowed_routes:
        return picked

    rule_by_name = {}
    for r in rules or []:
        nm = str(getattr(r, "name", "") or "")
        if nm:
            rule_by_name[nm] = r

    candidates = picked.get("candidates") or []
    for c in candidates:
        nm = str((c or {}).get("name") or "")
        sc = float((c or {}).get("score") or 0.0)
        if (nm in allowed_routes) and (sc > 0.0) and (nm in rule_by_name):
            out = dict(picked)
            out["chosen"] = {"name": nm, "rule": rule_by_name[nm], "score": sc}
            out["whitelist_blocked"] = chosen_name
            out["chosen_by_whitelist"] = nm
            if debug and callable(debug_log):
                debug_log("answer_route_whitelist blocked={0} switched_to={1}".format(chosen_name, nm))
            return out

    fallback_name = "fallback_local_first"
    if fallback_name in allowed_routes and fallback_name in rule_by_name:
        out = dict(picked)
        out["chosen"] = {"name": fallback_name, "rule": rule_by_name[fallback_name], "score": 0.0}
        out["whitelist_blocked"] = chosen_name
        out["chosen_by_whitelist"] = fallback_name
        if debug and callable(debug_log):
            debug_log("answer_route_whitelist blocked={0} fallback={1}".format(chosen_name, fallback_name))
        return out

    return picked
