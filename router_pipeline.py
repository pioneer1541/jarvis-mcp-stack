from typing import Callable, Dict, Any


def control_handoff_response() -> Dict[str, Any]:
    return {
        "ok": True,
        "route_type": "open_domain",
        "final": "这是设备控制请求，请通过 Home Assistant 设备控制通道执行（如 Assist 控制意图）。",
    }


def should_handoff_control(
    user_text: str,
    is_home_control_like_intent: Callable[[str], bool],
    is_music_control_query: Callable[[str], bool],
) -> bool:
    return bool(is_home_control_like_intent(user_text) and (not is_music_control_query(user_text)))


def handle_default_fallback(
    user_text: str,
    prefer_lang: str,
    route_return_data: bool,
    *,
    is_obvious_smalltalk: Callable[[str], bool],
    smalltalk_reply: Callable[[str, str], str],
    is_poi_intent: Callable[[str], bool],
    poi_answer: Callable[[str, str], str],
    web_search_answer: Callable[[str, str, int], tuple],
    news_extract_limit: Callable[[str, int], int],
    has_strong_lookup_intent: Callable[[str], bool],
    is_life_advice_intent: Callable[[str], bool],
    life_advice_fallback: Callable[[str, str], str],
) -> Dict[str, Any]:
    if is_obvious_smalltalk(user_text):
        return {"ok": True, "route_type": "open_domain", "final": smalltalk_reply(user_text, prefer_lang)}

    if is_poi_intent(user_text):
        poi_final = poi_answer(user_text, prefer_lang)
        if str(poi_final or "").strip():
            ret = {"ok": True, "route_type": "semi_structured_poi", "final": str(poi_final)}
            if route_return_data:
                ret["data"] = {"source": "google_places_new"}
            return ret
        web_final, web_data = web_search_answer(user_text, prefer_lang, limit=news_extract_limit(user_text, 3))
        if str(web_final or "").strip():
            ret = {"ok": True, "route_type": "semi_structured_web", "final": str(web_final)}
            if route_return_data:
                ret["data"] = web_data
            return ret
        final = "我先没定位到合适结果。你可以补充更具体地点（例如区名、商场名或街道名），我再帮你查。"
        ret = {"ok": True, "route_type": "semi_structured_web", "final": final}
        if route_return_data:
            ret["data"] = web_data if "web_data" in locals() else {}
        return ret

    web_final, web_data = web_search_answer(user_text, prefer_lang, limit=news_extract_limit(user_text, 3))
    if str(web_final or "").strip():
        ret = {"ok": True, "route_type": "semi_structured_web", "final": str(web_final)}
        if route_return_data:
            ret["data"] = web_data
        return ret

    if has_strong_lookup_intent(user_text):
        if is_life_advice_intent(user_text):
            final = life_advice_fallback(user_text, prefer_lang)
            ret = {"ok": True, "route_type": "open_domain", "final": final}
            if route_return_data:
                ret["data"] = web_data if "web_data" in locals() else {}
            return ret
        final = "我先没拿到可靠来源。你可以补充关键词（品牌/地点/型号/时间）后我再精确查一次。"
        ret = {"ok": True, "route_type": "semi_structured_web", "final": final}
        if route_return_data:
            ret["data"] = web_data if "web_data" in locals() else {}
        return ret

    ret = {"ok": True, "route_type": "open_domain", "final": smalltalk_reply(user_text, prefer_lang)}
    if route_return_data:
        ret["data"] = web_data if "web_data" in locals() else {}
    return ret
