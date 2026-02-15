
import re


def build_news_facts_payload(core_result: dict) -> dict:
    facts = core_result.get("facts") if isinstance(core_result, dict) else []
    if not isinstance(facts, list):
        facts = []
    out = []
    for it in facts:
        s = str(it or "").strip()
        if s:
            out.append(s)
    return {"facts": out}


def skill_news_brief_core(topic: str, limit: int, h) -> dict:
    t = str(topic or "本地").strip()
    try:
        lim = int(limit)
    except Exception:
        lim = 5
    if lim < 1:
        lim = 1
    if lim > 10:
        lim = 10

    cat = h["skill_news_category_from_topic"](t)
    rr = {}
    sr = {}
    cache = {}
    items = []
    cache_hit = False
    fallback_used = False
    if cat == "hot":
        cache = h["news_cache_query"]("", lim, do_refresh=False)
        items = (cache.get("items") if isinstance(cache, dict) else []) or []
        cache_hit = len(items) >= 1
        if len(items) < lim:
            rr = h["news_hot"](limit=lim, time_range="24h", prefer_lang="zh", user_text=t)
            ri = rr.get("items") if isinstance(rr, dict) else []
            if isinstance(ri, list) and ri:
                if len(items) > 0:
                    merged = []
                    merged.extend(items)
                    merged.extend(ri)
                    items = h["news_dedupe_items_for_voice"](merged)
                    if len(items) > lim:
                        items = items[:lim]
                else:
                    items = ri
                fallback_used = True
            else:
                fallback_used = True
    else:
        cache = h["news_cache_query"](t, lim, do_refresh=False)
        items = (cache.get("items") if isinstance(cache, dict) else []) or []
        cache_hit = len(items) >= 1
        if not cache_hit:
            sr = h["skill_miniflux_search"](t, lim, 14)
            items = (sr.get("items") if isinstance(sr, dict) else []) or []
            if len(items) < 1:
                fallback_used = True
                if h["skill_debug_enabled"]():
                    h["skill_debug_log"]("news_search_fallback=1")
                rr = h["news_hot"](limit=lim, time_range="24h", prefer_lang="zh", user_text=t)
                ri = rr.get("items") if isinstance(rr, dict) else []
                if isinstance(ri, list) and ri:
                    items = ri
                if len(items) < 1:
                    web_fallback = h["skill_web_lookup"]((t if t else "news") + " news", "zh", lim)
                    wf = web_fallback.get("facts") if isinstance(web_fallback, dict) else []
                    ws = web_fallback.get("sources") if isinstance(web_fallback, dict) else []
                    if isinstance(wf, list) and wf:
                        for title in wf[:lim]:
                            tt = str(title or "").strip()
                            if not tt:
                                continue
                            items.append({"title": tt, "title_voice": tt, "url": "", "source": "web", "published_at": "", "snippet": ""})
                    if isinstance(ws, list) and ws:
                        rr = {"items": items, "sources": ws}
            else:
                if h["skill_debug_enabled"]():
                    h["skill_debug_log"]("news_search_fallback=0")
    if (cat != "hot") and cache_hit and h["skill_debug_enabled"]():
        h["skill_debug_log"]("news_cache_hit=1")

    items = h["news_dedupe_items_for_voice"](items)
    if len(items) > lim:
        items = items[:lim]

    facts = []
    sources = []
    for it in items[:lim]:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title_voice") or it.get("title") or "").strip()
        if not title:
            continue
        sn = str(it.get("snippet") or "").strip()
        if len(sn) > 120:
            sn = sn[:120].rstrip() + "..."
        if sn:
            facts.append(title + "｜" + sn)
        else:
            facts.append(title)
        src = str(it.get("source") or h["news_source_from_url"](it.get("url")) or "").strip()
        day = str(it.get("published_at") or "").strip()
        sources.append(h["skill_source_item"](src, title, day, ""))

    final_text = h["skill_news_summary"](items, t)
    next_actions = []
    topic_kind = h["skill_news_topic_kind"](t)
    topic_hit = h["skill_news_topic_hit_count"](items, topic_kind)
    if h["skill_text_is_weak_or_empty"](final_text):
        final_text = str((rr.get("final_voice") if isinstance(rr, dict) else "") or (rr.get("final") if isinstance(rr, dict) else "") or "").strip()
    if h["skill_text_is_weak_or_empty"](final_text):
        near = []
        for x in facts[:3]:
            xx = str(x or "").strip()
            if xx:
                near.append(xx)
        if near:
            final_text = "我先给你最接近主题的 {0} 条：{1}。".format(len(near), "；".join(near))
        else:
            final_text = "我先给你最接近主题的新闻线索，但当前结果较少。"
    try:
        final_text = re.sub(r"^我找到\s*\d+\s*条和「[^」]*」相关的新闻，先读\s*\d+\s*条。\s*重点包括：\s*", "", str(final_text or "")).strip()
    except Exception:
        final_text = str(final_text or "").strip()
    brief_snips = []
    for it in items[:3]:
        if not isinstance(it, dict):
            continue
        sn = str(it.get("snippet") or "").strip()
        if not sn:
            continue
        if len(sn) > 80:
            sn = sn[:80].rstrip() + "..."
        brief_snips.append(sn)
    if brief_snips:
        final_text = (final_text + "。概述：" + "；".join(brief_snips[:2])).strip("。") + "。"
    if h["skill_text_is_weak_or_empty"](final_text):
        final_text = "我这次没有抓到可用新闻。"
    if h["skill_text_is_weak_or_empty"](final_text):
        final_text = "我先给你最接近主题的新闻线索。"
    if (len(items) == 0) and h["skill_debug_enabled"]():
        h["skill_debug_log"]("news_empty=1")

    meta = {
        "skill": "news_brief",
        "topic": t,
        "category": cat,
        "count": len(facts),
        "search_query": (sr.get("query") if isinstance(sr, dict) else None),
        "search_query_raw": (sr.get("query_raw") if isinstance(sr, dict) else None),
        "published_after": (sr.get("published_after") if isinstance(sr, dict) else None),
        "fallback_used": bool(fallback_used),
        "cache_hit": bool(cache_hit),
        "topic_kind": topic_kind,
        "topic_hit_count": int(topic_hit),
    }
    return h["skill_result"](final_text, facts=facts[:10], sources=sources[:10], next_actions=next_actions, meta=meta)


def route_news_request(user_text: str, prefer_lang: str, route_return_data: bool, h) -> dict:
    cat = h["news_category_from_text"](user_text)
    tr = h["news_time_range_from_text"](user_text)
    if cat == "hot":
        rrn = h["news_hot"](limit=10, time_range=tr, prefer_lang=prefer_lang, user_text=user_text)
    else:
        rrn = h["news_digest"](
            category=cat,
            limit=h["news_extract_limit"](user_text, 3),
            time_range=tr,
            prefer_lang=prefer_lang,
            user_text=user_text,
        )
    if rrn.get("ok") and str(rrn.get("final") or "").strip():
        final = rrn.get("final_voice") or rrn.get("final") or ""
        ret = {"ok": True, "route_type": "semi_structured_news", "final": final}
        if route_return_data:
            ret["data"] = rrn
        return ret
    ret = {"ok": True, "route_type": "semi_structured_news", "final": "新闻检索失败或暂无结果。"}
    if route_return_data:
        ret["data"] = rrn
    return ret
