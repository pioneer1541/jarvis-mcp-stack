# PATCH_CN_FINANCE_TO_CN_ECONOMY_V1
# NEWS_SUMMARY_V2
# ---- News voice + optional EN->ZH translation (Ollama) ----
_NEWS_TR_CACHE = {}  # key -> {"ts": int, "title": str, "snippet": str}
def _news__dedupe_items_for_voice(items: list) -> list:
    """
    Dedupe near-duplicate news items for voice.
    - Prefer non-video items over video items when titles are the same after normalization.
    - Normalize: remove punctuation/quotes, strip 'video/视频', collapse spaces.
    """
    try:
        if not isinstance(items, list) or len(items) == 0:
            return items

        def _is_video(x: dict) -> bool:
            try:
                t = str(x.get("title_voice") or x.get("title") or "").lower()
                u = str(x.get("url") or "").lower()
                if "video" in t or "视频" in (x.get("title_voice") or ""):
                    return True
                if "/video/" in u:
                    return True
            except Exception:
                pass
            return False

        def _norm(s: str) -> str:
            s = (s or "").strip().lower()
            # drop common video tokens
            s = s.replace("— video", " ").replace("– video", " ").replace("- video", " ")
            s = s.replace("video", " ").replace("视频", " ")
            # remove quotes/brackets and punctuation
            s = re.sub(r"[\u2018\u2019\u201c\u201d\"'“”‘’\(\)\[\]\{\}]", " ", s)
            s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s)
            s = re.sub(r"\s+", " ", s).strip()
            return s

        seen = {}
        out = []
        for x in items:
            if not isinstance(x, dict):
                continue
            title = str(x.get("title_voice") or x.get("title") or "").strip()
            if not title:
                continue
            k = _norm(title)
            if not k:
                out.append(x)
                continue

            if k not in seen:
                seen[k] = len(out)
                out.append(x)
                continue

            # already have one: prefer non-video
            j = seen[k]
            try:
                old = out[j]
                if _is_video(old) and (not _is_video(x)):
                    out[j] = x
            except Exception:
                pass

        return out
    except Exception:
        return items

def _news__tr__cache_get(key: str, ttl_sec: int):
    try:
        import time
        now = int(time.time())
        it = _NEWS_TR_CACHE.get(key)
        if not it:
            return None
        ts = int(it.get("ts") or 0)
        if (now - ts) > int(ttl_sec):
            return None
        return it
    except Exception:
        return None

def _news__tr__cache_put(key: str, title_zh: str, snippet_zh: str):
    try:
        import time
        _NEWS_TR_CACHE[key] = {
            "ts": int(time.time()),
            "title": (title_zh or "").strip(),
            "snippet": (snippet_zh or "").strip(),
        }
    except Exception:
        return

def _news__translate_batch_to_zh(pairs: list, model: str = "", base_url: str = "", timeout_sec: int = 12) -> list:
    """
    pairs: [{"title": "...", "snippet": "..."}]
    returns: [{"title": "...", "snippet": "..."}] (Chinese, same length as input; may contain empty strings on failure)

    v1.4: reduce cross-item contamination for small models
      - chunking (default 2 items per request)
      - temperature=0.0
      - contamination guard: if translated text contains brand keywords not present in source, drop snippet (keep title if safe)
    """
    out = []
    try:
        if not isinstance(pairs, list) or (len(pairs) == 0):
            return out

        import json
        import urllib.request

        bu = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip()
        if not bu:
            bu = "http://192.168.1.162:11434"
        mdl = (model or os.environ.get("NEWS_TRANSLATE_MODEL") or os.environ.get("OLLAMA_TRANSLATE_MODEL") or "qwen3:1.7b").strip()
        if not mdl:
            mdl = "qwen3:1.7b"

        try:
            bs = int(os.environ.get("NEWS_TRANSLATE_BATCH_SIZE") or "2")
        except Exception:
            bs = 2
        if bs < 1:
            bs = 1
        if bs > 4:
            bs = 4  # keep small to avoid mixing

        # simple brand/entity map for contamination guard (EN token -> CN keywords)
        brand_map = {
            "samsung": ["三星"],
            "google": ["谷歌", "Google"],
            "apple": ["苹果", "Apple"],
            "poco": ["Poco"],
            "infinix": ["Infinix"],
            "anbernic": ["Anbernic"],
            "nintendo": ["任天堂", "Nintendo"],
            "wii": ["Wii"],
            "verge": ["The Verge", "Verge"],
            "engadget": ["Engadget"],
            "gsmarena": ["GSMArena"],
            "switch": ["Switch"],
            "iran": ["伊朗"],
            "israel": ["以色列"],
            "russia": ["俄罗斯"],
            "ukraine": ["乌克兰"],
            "france": ["法国"],
            "texas": ["德州", "得克萨斯"],
            "minnesota": ["明尼苏达"],
        }

        def _call_ollama(chunk_pairs: list) -> list:
            # Build prompt
            sys_msg = (
                "你是中文新闻播报翻译助手。你必须逐条逐句翻译我给你的 TITLE 和 SNIP 字段。"
                "硬性规则："
                "1) TITLE 的中文只能来自 TITLE；SNIP 的中文只能来自 SNIP。不得把 TITLE 的信息补到 SNIP，也不得把 SNIP 的信息补到 TITLE。"
                "2) 只翻译，不得添加、推测、夸大、总结、改写事实；不得引入原文没有的时间、地点、数字、因果、结论。"
                "3) 若 SNIP 出现截断迹象（例如包含 '...'、'…'、'po...' 等），表示内容不完整：必须保持不完整，只翻译已给出的片段，禁止补全/扩写/发挥。"
                "4) 各条目彼此独立，禁止把其他条目的信息带入当前条目。"
                "5) 每条输出一行，严格保持条目数量一致。输出格式必须为："
                "N) <TITLE的中文翻译> ||| <SNIP的中文翻译> 。SNIP 可为空但分隔符必须保留。"
                "6) 除了上述格式，不得输出任何多余内容。"
            )

            lines = []
            i = 1
            for p in chunk_pairs:
                if not isinstance(p, dict):
                    p = {}
                t = str(p.get("title") or "").strip()
                s = str(p.get("snippet") or "").strip()
                if len(t) > 220:
                    t = t[:220].rstrip()
                if len(s) > 300:
                    s = s[:300].rstrip()
                lines.append("{0})".format(i))
                lines.append("TITLE: {0}".format(t))
                lines.append("SNIP: {0}".format(s))
                lines.append("")
                i += 1
            user_msg = "请翻译以下条目：\n" + "\n".join(lines)

            payload = {
                "model": mdl,
                "stream": False,
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                "options": {
                    "temperature": 0.0
                },
            }

            url = bu.rstrip("/") + "/api/chat"
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
                    raw = resp.read().decode("utf-8", "ignore")
            except Exception:
                return [{"title": "", "snippet": ""} for _ in chunk_pairs]

            try:
                obj = json.loads(raw)
            except Exception:
                obj = {}

            content = ""
            try:
                content = str(((obj.get("message") or {}).get("content")) or "").strip()
            except Exception:
                content = ""

            parsed = []
            if content:
                for ln in content.splitlines():
                    x = (ln or "").strip()
                    if x:
                        parsed.append(x)

            got = {}
            for x in parsed:
                m = None
                try:
                    import re
                    m = re.match(r"^\s*(\d{1,2})\s*[)\）]\s*(.*)$", x)
                except Exception:
                    m = None
                if not m:
                    continue
                try:
                    n = int(m.group(1))
                except Exception:
                    continue
                rest = (m.group(2) or "").strip()
                title_zh = rest
                snip_zh = ""
                if "|||" in rest:
                    parts = rest.split("|||", 1)
                    title_zh = (parts[0] or "").strip()
                    snip_zh = (parts[1] or "").strip()
                got[n] = {"title": title_zh, "snippet": snip_zh}

            res = []
            for idx in range(1, len(chunk_pairs) + 1):
                it = got.get(idx) or {"title": "", "snippet": ""}
                res.append({"title": (it.get("title") or "").strip(), "snippet": (it.get("snippet") or "").strip()})
            return res

        def _is_contaminated(src_title: str, src_snip: str, zh_title: str, zh_snip: str) -> bool:
            src = (str(src_title or "") + " " + str(src_snip or "")).lower()
            zh = (str(zh_title or "") + " " + str(zh_snip or ""))
            allowed_cn = set()
            for en, cn_list in brand_map.items():
                if en in src:
                    for w in cn_list:
                        allowed_cn.add(w)

            # if any CN keyword appears but its EN token not in source => suspicious
            for en, cn_list in brand_map.items():
                if en in src:
                    continue
                for w in cn_list:
                    if w and (w in zh):
                        return True
            return False

        # chunk loop
        n = len(pairs)
        i = 0
        while i < n:
            chunk = pairs[i:i + bs]
            tr = _call_ollama(chunk)

            # apply guard per item
            for p, rr in zip(chunk, tr):
                st = str((p or {}).get("title") or "")
                ss = str((p or {}).get("snippet") or "")
                zt = str((rr or {}).get("title") or "").strip()
                zs = str((rr or {}).get("snippet") or "").strip()

                if _is_contaminated(st, ss, zt, zs):
                    # keep title if it doesn't look contaminated alone; drop snippet
                    if _is_contaminated(st, ss, zt, ""):
                        zt = ""
                    zs = ""
                out.append({"title": zt, "snippet": zs})

            i += bs

        # ensure length match
        if len(out) < n:
            for _ in range(n - len(out)):
                out.append({"title": "", "snippet": ""})
        if len(out) > n:
            out = out[:n]

        return out
    except Exception:
        for _ in (pairs or []):
            out.append({"title": "", "snippet": ""})
        return out

def _news__voice_clip_snippet(s: str, max_len: int = 200) -> str:
    """Clip snippet for TTS.
    Allow ellipsis endings (… or ...) rather than rejecting them.
    """
    t = str(s or "").strip()
    if not t:
        return ""
    # Normalize whitespace
    t = " ".join(t.split())
    if max_len is None:
        return t
    try:
        m = int(max_len)
    except Exception:
        m = 200
    if m < 60:
        m = 60
    if len(t) <= m:
        return t
    return t[:m].rstrip() + "…"

def _news__format_voice_miniflux(items: list, max_items: int = 5) -> str:
    """Format news for voice output: title + summary (2 lines per item)."""
    its = items if isinstance(items, list) else []
    try:
        n = int(max_items)
    except Exception:
        n = 5
    if n <= 0:
        n = 5
    out_lines = []
    # per-item summary length for voice (TTS)
    try:
        sn_vo = int(os.environ.get("NEWS_VOICE_SNIP_LEN") or "200")
    except Exception:
        sn_vo = 200
    if sn_vo < 80:
        sn_vo = 80

    k = 0
    for it in its:
        if not isinstance(it, dict):
            continue
        if k >= n:
            break
        k += 1
        title = str(it.get("title_voice") or it.get("title") or "").strip()
        if not title:
            title = "(no title)"
        # choose best available summary
        sn = str(it.get("snippet") or "").strip()
        if not sn:
            sn = str(it.get("content_plain") or it.get("content") or "").strip()
        sn = _news__voice_clip_snippet(sn, sn_vo) if sn else ""
        out_lines.append(str(k) + ") " + title)
        if sn:
            out_lines.append("   " + sn)

    return "\n".join(out_lines).strip()

def _route__maybe_compact_return(ret: dict) -> dict:
    """
    If ROUTE_RETURN_DATA=0, return only {ok, route_type, final}.
    Default is returning full payload.
    """
    try:
        v = str(os.environ.get("ROUTE_RETURN_DATA") or "1").strip().lower()
        if v in ["0", "false", "no", "off"]:
            return {
                "ok": bool(ret.get("ok")),
                "route_type": ret.get("route_type"),
                "final": ret.get("final"),
            }
    except Exception:
        pass
    return ret

import os
import base64
import logging
import sys
import time
import socket
import uuid
from email.utils import parsedate_to_datetime
from contextvars import ContextVar

def _music_apply_aliases(user_text: str, ent: str) -> str:
    """Apply HA_MEDIA_PLAYER_ALIASES to override target entity.
    Format: 卧室:media_player.xxx,主卧:media_player.yyy,客厅:media_player.zzz
    """
    t = (user_text or "").strip()
    tl = t.lower()
    aliases_env = (os.environ.get('HA_MEDIA_PLAYER_ALIASES') or '').strip()
    if not aliases_env:
        return ent
    aliases_map = {}
    for p in [x.strip() for x in aliases_env.split(',') if x.strip()]:
        if ':' not in p:
            continue
        k, v = p.split(':', 1)
        k = (k or '').strip()
        v = (v or '').strip()
        if k and v:
            aliases_map[k] = v
    for k, v in aliases_map.items():
        if (k in t) or (k.lower() in tl):
            return v
    return ent

import re
import html
import unicodedata
import json
import hashlib
import sqlite3
from datetime import datetime, timedelta, date
from datetime import date as dt_date
from urllib.parse import urlparse

from typing import Any, Dict, List, Optional, Tuple


from zoneinfo import ZoneInfo
import requests
from starlette.routing import Mount
import router_helpers as rh
import router_pipeline as rp
from news import (
    build_news_facts_payload,
    skill_news_brief_core as _news_skill_news_brief_core,
    route_news_request as _news_route_request_core,
)
from calendar import (
    is_calendar_create_intent,
    calendar_capability_hint_text as _calendar_capability_hint_text_core,
    calendar_event_id_candidates as _calendar_event_id_candidates_core,
    calendar_parse_update_target_window as _calendar_parse_update_target_window_core,
    calendar_service_call_variants as _calendar_service_call_variants_core,
    calendar_ha_event_delete as _calendar_ha_event_delete_core,
    calendar_ha_event_update as _calendar_ha_event_update_core,
    route_calendar_request as _calendar_route_request_core,
)
from music import (
    is_music_control_query,
    music_parse_volume,
    music_volume_step_default,
    music_parse_volume_delta,
    music_default_player,
    music_load_aliases,
    music_extract_target_entity,
    music_control_core as _music_control_core,
    route_music_request as _music_route_request_core,
)
from answer import (
    load_answer_route_whitelist,
    enforce_answer_route_whitelist,
    looks_like_finance_price_query,
    finance_query_type,
    is_aud_usd_query,
    finance_guidance_by_type,
    finance_label_and_unit,
    finance_confidence_level,
    finance_normalize_query,
    finance_value_range,
    finance_neighbor_keywords,
    finance_extract_evidence,
    finance_extract_evidence_ai,
    clarify_route_to_utterance,
    score_and_pick_rule,
    build_clarify_plan,
    match_clarify_followup,
    wrap_any_result,
    compose_compound_answer,
    RouterContext,
    RouteRule,
    looks_like_local_info_query,
    looks_like_parking_fee_query,
    looks_like_open_advice_general_query,
    looks_like_property_info_query,
    looks_like_home_health_check_query,
    sanitize_route_candidates,
    skill_answer_question_core,
    route_request_core as _answer_route_request_core,
    route_weather_request as _answer_route_weather_core,
    route_holiday_request as _answer_route_holiday_core,
)
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None
try:
    from google.oauth2.credentials import Credentials as GoogleCredentials
    from google.auth.transport.requests import Request as GoogleRequest
    from googleapiclient.discovery import build as google_build
except Exception:
    GoogleCredentials = None
    GoogleRequest = None
    google_build = None

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings


def _ug_clean_unicode(text: str) -> str:
    if not text:
        return ""
    # Normalize
    text = unicodedata.normalize("NFKC", text)
    # Drop "format" chars (zero-width etc.)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    # Replace weird spaces
    for cp in [0x00A0, 0x202F, 0x2007, 0x2009, 0x200A]:
        text = text.replace(chr(cp), " ")
    # Remove BOM
    text = text.replace(chr(0xFEFF), "")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _news__strip_title_tail(title: str) -> str:
    """
    Remove trailing tails like:
    - " - video" / " – video" / " — video"
    - "（视频）" / "【视频】" / "——视频"
    Keep the rest unchanged.
    """
    t = (title or "").strip()
    if not t:
        return ""
    try:
        # Normalize whitespace a bit (keep punctuation)
        t = re.sub(r"\s+", " ", t).strip()
    except Exception:
        t = (title or "").strip()

    # English tail: - video / – video / — video / (video)
    try:
        t = re.sub(r"\s*[\-\u2013\u2014\u2212]\s*video\s*$", "", t, flags=re.IGNORECASE).strip()
        t = re.sub(r"\s*\(\s*video\s*\)\s*$", "", t, flags=re.IGNORECASE).strip()
    except Exception:
        pass

    # Chinese tail: ——视频 / -视频 / （视频）/【视频】
    try:
        t = re.sub(r"\s*[\-\u2013\u2014\u2212]\s*视频\s*$", "", t).strip()
        t = re.sub(r"\s*（\s*视频\s*）\s*$", "", t).strip()
        t = re.sub(r"\s*【\s*视频\s*】\s*$", "", t).strip()
        t = re.sub(r"\s*——\s*视频\s*$", "", t).strip()
    except Exception:
        pass

    try:
        t = re.sub(r"\s+", " ", t).strip()
    except Exception:
        t = (t or "").strip()
    return t


def _ug_extract_readable_text(html_text: str) -> str:
    """
    Lightweight extractor: title + meta description + main/article text, then strip tags.
    Finally apply Unicode cleanup so the output is readable for voice/LLM.
    """
    try:
        t = html_text or ""

        # title
        title = ""
        m1 = re.search(r"(?is)<title[^>]*>(.*?)</title>", t)
        if m1:
            title = html.unescape(m1.group(1)).strip()

        # meta description
        desc = ""
        m2 = re.search(
            r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            t,
        )
        if m2:
            desc = html.unescape(m2.group(1)).strip()

        # prefer main/article
        body_html = ""
        m3 = re.search(r"(?is)<main[^>]*>(.*?)</main>", t)
        if m3:
            body_html = m3.group(1)
        else:
            m4 = re.search(r"(?is)<article[^>]*>(.*?)</article>", t)
            if m4:
                body_html = m4.group(1)
            else:
                body_html = t

        # drop script/style/noscript
        body_html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body_html)

        # strip tags
        body_text = re.sub(r"(?is)<[^>]+>", " ", body_html)

        parts: List[str] = []
        if title:
            parts.append(title)
        if desc and (desc not in title):
            parts.append(desc)
        if body_text:
            parts.append(body_text)

        out = "\n".join(parts)
        out = html.unescape(out)
        out = re.sub(r"[\r\t]+", " ", out)
        out = re.sub(r"[ ]{2,}", " ", out)
        out = re.sub(r"\n[ ]+", "\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()

        out = _ug_clean_unicode(out)
        return out
    except Exception:
        return _ug_clean_unicode((html_text or "").strip())


def _ug_open_url_fetch(url: str, max_chars: int = 4000, timeout_sec: int = 10, accept_language: str = "") -> dict:
    """
    Fetch URL (HTML) and return extracted readable text excerpt.
    Keep it robust: only requests, no heavy deps.
    """
    u = (url or "").strip()
    if not u:
        return {"ok": False, "error": "empty_url"}

    if not (u.startswith("http://") or u.startswith("https://")):
        return {"ok": False, "error": "invalid_scheme", "hint": "Only http/https is allowed."}

    # Clamp max_chars
    try:
        mc = int(max_chars)
    except Exception:
        mc = 4000
    if mc < 200:
        mc = 200
    if mc > 12000:
        mc = 12000

    headers = {
        "User-Agent": "mcp-tools/1.0 (+homeassistant)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    al = str(accept_language or "").strip()
    if al:
        headers["Accept-Language"] = al

    try:
        r = requests.get(u, headers=headers, timeout=float(timeout_sec), stream=True, allow_redirects=True)
        status_code = int(getattr(r, "status_code", 0) or 0)
        ct = (r.headers.get("content-type") or "").lower()

        # Limit download size
        max_bytes = 1500000  # 1.5MB
        buf = b""
        for chunk in r.iter_content(chunk_size=32768):
            if not chunk:
                continue
            buf += chunk
            if len(buf) > max_bytes:
                break

        enc = r.encoding or "utf-8"
        try:
            page = buf.decode(enc, errors="ignore")
        except Exception:
            page = buf.decode("utf-8", errors="ignore")

        excerpt = _ug_extract_readable_text(page)
        excerpt = excerpt[:mc]

        title = ""
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page or "")
        if m:
            title = _ug_clean_unicode(html.unescape(m.group(1)))

        return {
            "ok": True,
            "url": u,
            "final_url": str(getattr(r, "url", "") or ""),
            "status_code": status_code,
            "content_type": ct,
            "title": title,
            "excerpt": excerpt,
        }
    except Exception as e:
        return {"ok": False, "url": u, "error": "fetch_failed", "message": str(e)}


# ---- Transport security (keep what you already validated) ----
_allowed_hosts = [
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "192.168.1.162",
    "192.168.1.162:*",
    "192.168.1.162:19090",
    "homeassistant",
    "homeassistant:*",
    "homeassistant.local",
    "homeassistant.local:*",
]

_allowed_origins = [
    "http://localhost",
    "http://localhost:*",
    "http://127.0.0.1",
    "http://127.0.0.1:*",
    "http://192.168.1.162",
    "http://192.168.1.162:*",
]

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_allowed_hosts,
    allowed_origins=_allowed_origins,
)

mcp = FastMCP("mcp-hello", transport_security=transport_security)
# MCP_EXPOSE_ONLY_ROUTE_REQUEST_V1: Only expose route_request to Home Assistant to prevent accidental tool selection.
# Other functions remain callable internally by route_request.

_SKILL_TOOL_NAMES = [
    "skill.answer_question",
    "skill.knowledge_lookup",
    "skill.memory_upsert",
    "skill.memory_search",
    "skill.news_brief",
    "skill.finance_admin",
    "skill.holiday_query",
    "skill.music_control",
    "skill.capabilities",
]

_SKILL_REQ_ID = ContextVar("SKILL_REQ_ID", default="")
_SKILL_REQ_DEPTH = ContextVar("SKILL_REQ_DEPTH", default=0)


def _skill_debug_enabled() -> bool:
    try:
        v = str(os.environ.get("SKILL_DEBUG") or "").strip().lower()
        return v in ("1", "true", "yes", "y", "on")
    except Exception:
        return False


def _skill_debug_log(msg: str):
    if not _skill_debug_enabled():
        return
    try:
        print("[skill] " + str(msg or ""), file=sys.stderr)
    except Exception:
        pass


def _skill_json_log_enabled() -> bool:
    try:
        v = str(os.environ.get("SKILL_JSON_LOG") or "1").strip().lower()
        return v not in ("0", "false", "no", "off")
    except Exception:
        return True


def _skill_request_id_new() -> str:
    try:
        return "req-" + str(uuid.uuid4())
    except Exception:
        return "req-" + str(int(time.time() * 1000))


def _skill_request_id_get() -> str:
    try:
        rid = str(_SKILL_REQ_ID.get() or "").strip()
        return rid
    except Exception:
        return ""


def _skill_request_id_set(rid: str):
    try:
        _SKILL_REQ_ID.set(str(rid or "").strip())
    except Exception:
        pass


def _skill_log_json(event: str, request_id: str = "", tool: str = "", data: Optional[dict] = None):
    if not _skill_json_log_enabled():
        return
    rid = str(request_id or _skill_request_id_get() or "").strip()
    payload = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "event": str(event or "").strip(),
    }
    if rid:
        payload["request_id"] = rid
    if str(tool or "").strip():
        payload["tool"] = str(tool or "").strip()
    if isinstance(data, dict):
        for k, v in data.items():
            payload[str(k)] = v
    try:
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    except Exception:
        try:
            print(str(payload), file=sys.stderr)
        except Exception:
            pass


def _skill_call_begin(tool_name: str, args: Optional[dict] = None) -> Tuple[str, float]:
    try:
        depth = int(_SKILL_REQ_DEPTH.get() or 0)
    except Exception:
        depth = 0
    rid = _skill_request_id_get()
    if (depth <= 0) or (not rid):
        rid = _skill_request_id_new()
        _skill_request_id_set(rid)
    try:
        _SKILL_REQ_DEPTH.set(depth + 1)
    except Exception:
        pass
    started = time.time()
    _skill_log_json("tool_call_start", request_id=rid, tool=tool_name, data=(args if isinstance(args, dict) else {}))
    return rid, started


def _skill_call_end(tool_name: str, request_id: str, started_ts: float, ok: bool = True, data: Optional[dict] = None):
    dur_ms = int(max(0.0, (time.time() - float(started_ts)) * 1000.0))
    payload = {"ok": bool(ok), "duration_ms": dur_ms}
    if isinstance(data, dict):
        for k, v in data.items():
            payload[str(k)] = v
    _skill_log_json("tool_call_end", request_id=request_id, tool=tool_name, data=payload)
    try:
        depth = int(_SKILL_REQ_DEPTH.get() or 0) - 1
    except Exception:
        depth = 0
    if depth <= 0:
        try:
            _SKILL_REQ_DEPTH.set(0)
            _SKILL_REQ_ID.set("")
        except Exception:
            pass
    else:
        try:
            _SKILL_REQ_DEPTH.set(depth)
        except Exception:
            pass


def _skill_source_item(source: str, title: str, published_at: str = "", url: str = "") -> dict:
    return {
        "source": str(source or "").strip(),
        "title": str(title or "").strip(),
        "published_at": str(published_at or "").strip(),
        "url": str(url or "").strip(),
    }


def _skill_next_action_item(action_type: str, text: str, payload: Optional[dict] = None) -> dict:
    out = {
        "type": str(action_type or "").strip(),
        "text": str(text or "").strip(),
    }
    if isinstance(payload, dict) and payload:
        out["payload"] = payload
    return out


def _skill_result(final_text, facts=None, sources=None, next_actions=None, meta=None) -> dict:
    ft = str(final_text or "").strip()
    if not ft:
        ft = "我暂时没拿到可靠结果。"
    assert isinstance(ft, str) and bool(ft.strip())

    facts_out = []
    if isinstance(facts, list):
        for it in facts:
            s = str(it or "").strip()
            if s:
                facts_out.append(s)

    if len(facts_out) == 0:
        facts_out = [ft]

    out = {
        "final_text": ft,
        "facts": facts_out,
    }
    if isinstance(next_actions, list):
        na = []
        for it in next_actions:
            if isinstance(it, dict):
                na.append(it)
        if len(na) > 0:
            out["next_actions"] = na
    if isinstance(meta, dict) and len(meta) > 0:
        out["meta"] = meta
    return out


# @mcp.tool(description="(Test tool) Say hello. Use this when the user asks to test MCP tools or connectivity.")
def hello(name: str = "world") -> dict:
    return {"ok": True, "text": "Hello, " + str(name) + "!"}


# @mcp.tool(description="(Test tool) Simple ping for connectivity checks.")
def ping() -> dict:
    return {"ok": True, "pong": True}


# ---- HA REST API helpers (optional; used for Structured / Live tools) ----
# Configure via env:
#   HA_BASE_URL (default http://homeassistant:8123)
#   HA_TOKEN (required)
#
# Note: These tools are meant to provide *structured* data. They do NOT browse the public internet.

def _ha_base_url() -> str:
    u = str(os.getenv("HA_BASE_URL", "") or "").strip()
    if not u:
        u = "http://homeassistant:8123"
    return u.rstrip("/")


def _ha_headers() -> Dict[str, str]:
    tok = str(os.getenv("HA_TOKEN", "") or "").strip()
    if not tok:
        return {}
    return {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}


def _ha_request(method: str, path: str, json_body: Any = None, timeout_sec: int = 10) -> dict:
    base = _ha_base_url()
    url = base + path
    headers = _ha_headers()
    if not headers:
        return {"ok": False, "error": "ha_token_missing", "hint": "Set HA_TOKEN env var for HA REST API access."}

    try:
        if method.upper() == "GET":
            r = requests.get(url, headers=headers, timeout=float(timeout_sec))
        else:
            r = requests.request(method.upper(), url, headers=headers, json=json_body, timeout=float(timeout_sec))
        status = int(getattr(r, "status_code", 0) or 0)
        try:
            data = r.json()
        except Exception:
            data = (r.text or "")
        if status >= 200 and status < 300:
            return {"ok": True, "status_code": status, "data": data}
        return {"ok": False, "status_code": status, "data": data, "error": "ha_http_error"}
    except Exception as e:
        return {"ok": False, "error": "ha_request_failed", "message": str(e), "url": url}


# @mcp.tool(description="(Structured) Get Home Assistant state for a specific entity_id via HA REST API.")
def ha_get_state(entity_id: str, timeout_sec: int = 10) -> dict:
    eid = str(entity_id or "").strip()
    if not eid:
        return {"ok": False, "error": "empty_entity_id"}
    return _ha_request("GET", "/api/states/" + eid, timeout_sec=int(timeout_sec))


# @mcp.tool(description="(Structured) Call a Home Assistant service via HA REST API.")
def ha_call_service(domain: str, service: str, service_data: Optional[dict] = None, return_response: bool = False, timeout_sec: int = 10) -> dict:
    d = str(domain or "").strip()
    s = str(service or "").strip()
    if (not d) or (not s):
        return {"ok": False, "error": "empty_domain_or_service"}
    body = service_data if isinstance(service_data, dict) else {}
    path = "/api/services/" + d + "/" + s
    if bool(return_response):
        path = path + "?return_response"
    return _ha_request("POST", path, json_body=body, timeout_sec=int(timeout_sec))

# @mcp.tool(description="(Structured) Get forecast for a HA weather entity using weather.get_forecasts service.")
def ha_weather_forecast(entity_id: str, forecast_type: str = "daily", timeout_sec: int = 12) -> dict:
    eid = str(entity_id or "").strip()
    ftype = str(forecast_type or "daily").strip().lower()
    if not eid:
        return {"ok": False, "error": "empty_entity_id"}
    if ftype not in ("daily", "hourly", "twice_daily"):
        ftype = "daily"

    body = {"entity_id": eid, "type": ftype}
    r = ha_call_service("weather", "get_forecasts", service_data=body, return_response=True, timeout_sec=int(timeout_sec))
    if not r.get("ok"):
        return r

    data = r.get("data") or {}
    sr = data.get("service_response") or {}
    ent = sr.get(eid) or {}
    fc = ent.get("forecast") or []
    if not isinstance(fc, list):
        fc = []

    return {
        "ok": True,
        "status_code": r.get("status_code"),
        "entity_id": eid,
        "forecast_type": ftype,
        "count": len(fc),
        "forecast": fc,
    }

# @mcp.tool(description="(Structured) List available HA calendars (entity_id + name).")
def ha_list_calendars(timeout_sec: int = 12) -> dict:
    return _ha_request("GET", "/api/calendars", timeout_sec=int(timeout_sec))


# @mcp.tool(description="(Structured) List events for a HA calendar entity. Dates are ISO 8601, e.g. 2026-01-22T00:00:00+11:00")
def ha_calendar_events(entity_id: str, start: str, end: str, timeout_sec: int = 12) -> dict:
    eid = str(entity_id or "").strip()
    if not eid:
        return {"ok": False, "error": "empty_entity_id"}
    s = str(start or "").strip()
    e = str(end or "").strip()
    if (not s) or (not e):
        return {"ok": False, "error": "empty_start_or_end", "hint": "Provide start/end ISO strings."}
    path = "/api/calendars/" + eid + "?start=" + requests.utils.quote(s) + "&end=" + requests.utils.quote(e)
    return _ha_request("GET", path, timeout_sec=int(timeout_sec))


# ---- Public holidays (offline / deterministic) ----
# @mcp.tool(description="(Structured) Public holidays for Victoria, Australia. Uses python 'holidays' if available; otherwise returns an error.")
def holiday_vic(year: int, timeout_sec: int = 3) -> dict:
    y = year
    try:
        y = int(year)
    except Exception:
        y = int(datetime.now().year)
    try:
        import holidays  # type: ignore
    except Exception:
        return {
            "ok": False,
            "error": "holidays_lib_missing",
            "hint": "Install python package 'holidays' in this container to enable holiday_vic().",
        }

    try:
        # 'Australia' supports subdiv; VIC is Victoria.
        try:
            h = holidays.Australia(years=[y], subdiv="VIC")  # type: ignore
        except Exception:
            h = holidays.country_holidays("AU", years=[y], subdiv="VIC")  # type: ignore

        items = []
        for d, name in sorted(h.items()):
            items.append({"date": str(d), "name": str(name)})
        return {"ok": True, "year": y, "region": "AU-VIC", "holidays": items}
    except Exception as e:
        return {"ok": False, "error": "holiday_compute_failed", "message": str(e)}




# --- RANGE_PARSE_HELPERS_V1 BEGIN ---
def _parse_ymd(s: str):
    ss = (s or "").strip()
    if len(ss) != 10:
        return None
    try:
        y = int(ss[0:4]); m = int(ss[5:7]); d = int(ss[8:10])
        return dt_date(y, m, d)
    except Exception:
        return None


def _cn_date_to_ymd(text: str, now_d):
    """
    Parse Chinese '1月26日' / '1月26号' into dt_date(year, month, day)
    If year missing, use now_d.year.
    """
    t = (text or "").strip()
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*(日|号)", t)
    if not m:
        return None
    try:
        mm = int(m.group(1)); dd = int(m.group(2))
        yy = int(getattr(now_d, "year", 1970) or 1970)
        return dt_date(yy, mm, dd)
    except Exception:
        return None


def _range_from_text(text: str, now_d):
    """
    Returns dict:
      mode: 'single' | 'range'
      label: '今天'/'明天'/'后天'/'' (optional)
      offset: int (for relative single)
      target_date: dt_date (for explicit single)
      start_date: dt_date (for range)
      end_date: dt_date (optional)
      days: int (for '未来N天' / '接下来N天')
    """
    t = (text or "").strip()
    out = {"mode": "single", "offset": 0, "label": ""}

    if re.search(r"(今天|今日)", t):
        out["label"] = "今天"
        out["offset"] = 0
    elif re.search(r"(明天|明日)", t):
        out["label"] = "明天"
        out["offset"] = 1
    elif re.search(r"(后天)", t):
        out["label"] = "后天"
        out["offset"] = 2

    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", t)
    if m:
        out["mode"] = "range"
        try:
            out["days"] = int(m.group(2))
        except Exception:
            out["days"] = 3
        out["start_date"] = now_d
        out["label"] = ""
        return out

    m2 = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if m2:
        d = _parse_ymd(m2.group(1))
        if d is not None:
            out["target_date"] = d
            out["label"] = m2.group(1)
            out["offset"] = 0

    if "target_date" not in out:
        d2 = _cn_date_to_ymd(t, now_d)
        if d2 is not None:
            out["target_date"] = d2
            out["label"] = str(int(d2.month)) + "月" + str(int(d2.day)) + "日"
            out["offset"] = 0

    m3 = re.search(r"(\d{4}-\d{2}-\d{2})\s*(到|至|~|-)\s*(\d{4}-\d{2}-\d{2})", t)
    if m3:
        d1 = _parse_ymd(m3.group(1))
        d2 = _parse_ymd(m3.group(3))
        if (d1 is not None) and (d2 is not None):
            if d2 < d1:
                d1, d2 = d2, d1
            out = {"mode": "range", "start_date": d1, "end_date": d2, "label": m3.group(1) + "到" + m3.group(3)}
            return out

    return out
# --- RANGE_PARSE_HELPERS_V1 END ---

def _holiday_next_from_list(items: list, today_ymd: str) -> dict:
    """Return the next holiday on/after today_ymd."""
    try:
        y = int(today_ymd[0:4]); mo = int(today_ymd[5:7]); da = int(today_ymd[8:10])
        today = dt_date(y, mo, da)
    except Exception:
        return {"ok": False}

    best = None
    best_d = None
    for x in items or []:
        if not isinstance(x, dict):
            continue
        ds = str(x.get("date") or "").strip()
        nm = str(x.get("name") or "").strip()
        if len(ds) != 10:
            continue
        try:
            yy = int(ds[0:4]); mm = int(ds[5:7]); dd = int(ds[8:10])
            d = dt_date(yy, mm, dd)
        except Exception:
            continue
        if d < today:
            continue
        if (best_d is None) or (d < best_d):
            best_d = d
            best = {"date": ds, "name": nm}

    if not best or (best_d is None):
        return {"ok": False}

    try:
        days = (best_d - today).days
    except Exception:
        days = None

    out = {"ok": True, "date": best.get("date"), "name": best.get("name")}
    if isinstance(days, int):
        out["days"] = days
    return out

def _holiday_prev_from_list(items: list, today_ymd: str) -> dict:
    """Return the most recent holiday on/before today_ymd."""
    try:
        y = int(today_ymd[0:4]); mo = int(today_ymd[5:7]); da = int(today_ymd[8:10])
        today = dt_date(y, mo, da)
    except Exception:
        return {"ok": False}

    best = None
    best_d = None
    for x in items or []:
        if not isinstance(x, dict):
            continue
        ds = str(x.get("date") or "").strip()
        nm = str(x.get("name") or "").strip()
        if len(ds) != 10:
            continue
        try:
            yy = int(ds[0:4]); mm = int(ds[5:7]); dd = int(ds[8:10])
            d = dt_date(yy, mm, dd)
        except Exception:
            continue
        if d > today:
            continue
        if (best_d is None) or (d > best_d):
            best_d = d
            best = {"date": ds, "name": nm}

    if not best or (best_d is None):
        return {"ok": False}

    try:
        days_ago = (today - best_d).days
    except Exception:
        days_ago = None

    out = {"ok": True, "date": best.get("date"), "name": best.get("name")}
    if isinstance(days_ago, int):
        out["days_ago"] = days_ago
    return out

def _brave__map_time_range_to_freshness(time_range: Optional[str]) -> Optional[str]:
    """
    Brave Search API "freshness" param:
      pd / pw / pm / py
      or explicit range: YYYY-MM-DDtoYYYY-MM-DD
    We accept a few legacy values (day/week/month/year) for compatibility.
    """
    t = (time_range or "").strip()
    if not t:
        return None
    tl = t.lower().strip()
    if tl in ["pd", "pw", "pm", "py"]:
        return tl
    if tl in ["day", "today", "24h", "d"]:
        return "pd"
    if tl in ["week", "7d", "w"]:
        return "pw"
    if tl in ["month", "30d", "31d", "m"]:
        return "pm"
    if tl in ["year", "y"]:
        return "py"
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*to\s*(\d{4}-\d{2}-\d{2})", t, flags=re.IGNORECASE)
    if m:
        return m.group(1) + "to" + m.group(2)
    m2 = re.match(r"^\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2}$", tl)
    if m2:
        return t.replace(" ", "")
    return None


def _brave__lang_params(language: str) -> Tuple[str, str]:
    """
    Map language hints to Brave params:
      search_lang: 2-letter (e.g., "en", "zh")
      ui_lang: locale (e.g., "en-US", "zh-CN")
    """
    lang = (language or "").strip()
    ll = lang.lower()
    if ll.startswith("zh"):
        return ("zh", "zh-CN")
    if ll.startswith("en"):
        return ("en", "en-US")
    m = re.match(r"^([a-z]{2})(?:-([a-z]{2}))?$", ll)
    if m:
        sl = m.group(1)
        if m.group(2):
            return (sl, sl + "-" + m.group(2).upper())
        return (sl, sl + "-" + sl.upper())
    return ("en", "en-US")


def _searxng_search(
    base_url: str,
    query: str,
    categories: str,
    language: str,
    count: int,
    time_range: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Brave Search API backend (replaces local SearXNG).
    Compatibility: returns a SearXNG-like JSON shape: {"results":[{title,url,content,engine,score},...]}.

    Env:
      - BRAVE_SEARCH_TOKEN (required)
      - BRAVE_SEARCH_URL (default: https://api.search.brave.com/res/v1/web/search)
      - BRAVE_SEARCH_TIMEOUT (default: 8)
      - BRAVE_SEARCH_COUNTRY (default: AU)
      - BRAVE_SAFESEARCH (default: moderate)
      - BRAVE_EXTRA_SNIPPETS (default: true)
    """
    api_url = (os.getenv("BRAVE_SEARCH_URL") or "").strip()
    if not api_url:
        api_url = (base_url or "").strip()
    if not api_url:
        api_url = "https://api.search.brave.com/res/v1/web/search"

    token = (os.getenv("BRAVE_SEARCH_TOKEN") or os.getenv("BRAVE_API_KEY") or "").strip()
    if not token:
        raise RuntimeError("BRAVE_SEARCH_TOKEN not set")

    timeout_s = float(os.getenv("BRAVE_SEARCH_TIMEOUT", "8"))
    country = (os.getenv("BRAVE_SEARCH_COUNTRY") or "AU").strip() or "AU"
    safesearch = (os.getenv("BRAVE_SAFESEARCH") or "moderate").strip() or "moderate"
    extra_snippets = str(os.getenv("BRAVE_EXTRA_SNIPPETS", "true")).strip().lower() in ["1", "true", "yes", "y", "on"]

    search_lang, ui_lang = _brave__lang_params(language)
    freshness = _brave__map_time_range_to_freshness(time_range)

    params = {
        "q": query,
        "count": int(count),
        "offset": 0,
        "country": country,
        "search_lang": search_lang,
        "ui_lang": ui_lang,
        "safesearch": safesearch,
    }
    if freshness:
        params["freshness"] = freshness
    if extra_snippets:
        params["extra_snippets"] = "true"

    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "Accept-Encoding": "gzip",
        "Cache-Control": "no-cache",
        "X-Subscription-Token": token,
        "Accept-Language": ui_lang,
    }

    # brave QPS throttle (avoid 429 when multiple searches happen quickly)
    try:
        import time as _time
        import threading as _threading
        if not hasattr(_searxng_search, "_brave_lock"):
            _searxng_search._brave_lock = _threading.Lock()
            _searxng_search._brave_last_ts = 0.0
        _min_interval = float(os.getenv("BRAVE_MIN_INTERVAL", "1.2"))
        if _min_interval < 0.2:
            _min_interval = 0.2
        def _throttle():
            with _searxng_search._brave_lock:
                now = _time.time()
                last = float(getattr(_searxng_search, "_brave_last_ts", 0.0))
                wait = _min_interval - (now - last)
                if wait > 0:
                    # keep it bounded to avoid very long blocking
                    if wait > 3.0:
                        wait = 3.0
                    _time.sleep(wait)
                _searxng_search._brave_last_ts = _time.time()
    except Exception:
        def _throttle():
            return

    def _do_get(p, h):
        _throttle()
        return requests.get(api_url, params=p, headers=h, timeout=timeout_s)

    resp = _do_get(params, headers)

    if resp.status_code == 429:
        ra = (resp.headers.get("Retry-After") or "").strip()
        wait_s = 1.2
        try:
            wait_s = float(ra)
        except Exception:
            pass
        if wait_s < 0.5:
            wait_s = 0.5
        max_wait_s = float(os.getenv("BRAVE_MAX_RETRY_AFTER", "6.0"))
        if max_wait_s < 1.0:
            max_wait_s = 1.0
        if max_wait_s > 10.0:
            max_wait_s = 10.0
        if wait_s > max_wait_s:
            wait_s = max_wait_s
        try:
            import time as _time
            _time.sleep(wait_s)
        except Exception:
            pass
        resp = _do_get(params, headers)

    if resp.status_code == 422:
        # fallback: most conservative lang/ui + drop extra_snippets
        p2 = dict(params)
        p2["search_lang"] = "en"
        p2["ui_lang"] = "en-US"
        if "extra_snippets" in p2:
            try:
                del p2["extra_snippets"]
            except Exception:
                pass
        h2 = dict(headers)
        h2["Accept-Language"] = "en-US"
        h2["Cache-Control"] = "no-cache"
        resp = _do_get(p2, h2)

    resp.raise_for_status()
    j = resp.json()

    web = j.get("web") if isinstance(j, dict) else None
    items = (web or {}).get("results") if isinstance(web, dict) else None
    if not isinstance(items, list):
        items = []

    out_results = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        url = str(it.get("url") or it.get("link") or "").strip()
        desc = str(it.get("description") or it.get("desc") or "").strip()
        extras = it.get("extra_snippets") or []
        extras2 = []
        if isinstance(extras, list):
            for x in extras:
                sx = str(x or "").strip()
                if sx:
                    extras2.append(sx)

        content = desc
        if extras2:
            for x in extras2[:2]:
                if x and (x not in content):
                    content = (content + " " + x).strip() if content else x

        if not title and not url and not content:
            continue

        out_results.append(
            {
                "title": title,
                "url": url,
                "content": content,
                "engine": "brave",
                "score": it.get("score"),
            }
        )

    return {
        "results": out_results,
        "query": (j.get("query") if isinstance(j, dict) else None),
        "backend": "brave",
    }


def _web__is_brave_quota_error(err_text: str) -> bool:
    t = str(err_text or "").strip().lower()
    if not t:
        return False
    keys = [
        "429",
        "rate limit",
        "too many requests",
        "quota",
        "exceeded",
        "brave_not_configured",
        "brave_search_token not set",
    ]
    for k in keys:
        if k in t:
            return True
    return False


def _searxng_http_search(
    base_url: str,
    query: str,
    categories: str,
    language: str,
    count: int,
    time_range: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Real SearXNG backend.
    Returns a compatible shape: {"results":[...], "backend":"searxng"}.
    """
    su = str(base_url or "").strip().rstrip("/")
    if not su:
        raise RuntimeError("SEARXNG_URL not configured")
    endpoint = su + "/search"
    try:
        timeout_s = float(os.getenv("SEARXNG_TIMEOUT") or "8")
    except Exception:
        timeout_s = 8.0
    if timeout_s < 2.0:
        timeout_s = 2.0
    if timeout_s > 20.0:
        timeout_s = 20.0

    params = {
        "q": str(query or "").strip(),
        "format": "json",
        "language": str(language or "en").strip(),
        "categories": str(categories or "general").strip(),
    }
    try:
        cc = int(count)
    except Exception:
        cc = 5
    if cc < 1:
        cc = 1
    if cc > 20:
        cc = 20
    params["count"] = cc

    tr = str(time_range or "").strip().lower()
    if tr:
        params["time_range"] = tr

    r = requests.get(endpoint, params=params, timeout=timeout_s)
    r.raise_for_status()
    j = r.json() if hasattr(r, "json") else {}
    items = j.get("results") if isinstance(j, dict) else None
    if not isinstance(items, list):
        items = []

    out_results = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out_results.append(
            {
                "title": str(it.get("title") or "").strip(),
                "url": str(it.get("url") or "").strip(),
                "content": str(it.get("content") or it.get("snippet") or "").strip(),
                "engine": str(it.get("engine") or "searxng").strip(),
                "score": it.get("score"),
            }
        )
    return {"results": out_results, "backend": "searxng", "query": str(query or "").strip()}
def _mcp__normalize_relative_time(q):
    try:
        txt = str(q or "").strip()
    except Exception:
        return str(q or "").strip()

    # If query already contains an explicit year, do not rewrite.
    try:
        if re.search(r"\b20\d{2}\b", txt):
            return txt
    except Exception:
        return txt

    try:
        y = int(datetime.now().year)
    except Exception:
        y = 2026

    txt = txt.replace("本年", str(y))
    txt = txt.replace("今年", str(y))
    txt = txt.replace("明年", str(y + 1))
    txt = txt.replace("后年", str(y + 2))
    return txt

def _mcp__is_calendar_query(q):
    t = str(q or "")
    tl = t.lower()
    keys_zh = ["公共假期", "假期", "节假日", "日历", "日期表", "时间表"]
    for k in keys_zh:
        if k in t:
            return True
    if ("public holiday" in tl) or ("public holidays" in tl) or ("holiday calendar" in tl):
        return True
    return False

def _mcp__normalize_query(q):
    txt = str(q or "").strip()
    txt = _mcp__normalize_relative_time(txt)

    # Public holidays are state-level; "Victoria" is usually more reliable than "Melbourne".
    try:
        if _mcp__has_zh(txt) and _mcp__is_calendar_query(txt):
            if ("维多利亚" not in txt) and ("Victoria" not in txt):
                if "墨尔本" in txt:
                    txt = txt.replace("墨尔本", "维多利亚")
                else:
                    txt = txt + " 维多利亚"
    except Exception:
        pass

    return txt
# --- MCP_GENERAL_FIRST_TIME_NORM_V1 END ---

# Phase B: defaults that reduce runaway / off-topic results.
# - language='auto': Chinese -> zh-CN, else en
# - categories='auto': event/news-like -> news, else general
# - relevance self-check: if top results don't match query keywords, set relevance_low=True

def _mcp__has_zh(text):
    try:
        return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))
    except Exception:
        return False

def _mcp__auto_language(query, language):
    q = str(query or "").strip()
    lg = str(language or "").strip()
    if (not lg) or (lg.lower() == "auto"):
        return "zh-CN" if _mcp__has_zh(q) else "en"
    return lg


def _mcp__norm_accept_language(lang):
    # Normalize to a safe Accept-Language header value.
    lg = str(lang or "").strip()
    if not lg:
        return ""
    lg = lg.replace("_", "-")
    if lg.lower() == "zh":
        lg = "zh-CN"
    base = lg.split("-")[0].strip()
    if not base:
        return lg
    # Prefer requested locale, then base language, then English as fallback.
    if base.lower() == "zh":
        return lg + ",zh;q=0.9,en;q=0.2"
    if base.lower() == "en":
        return lg + ",en;q=0.9"
    return lg + "," + base + ";q=0.9,en;q=0.2"

def _mcp__looks_like_news_event(query):
    q = str(query or "").strip()
    if not q:
        return False
    # Heuristic keywords for Chinese news/event queries
    if _mcp__has_zh(q):
        keys = ["事件","新闻","怎么回事","为何","原因","通报","警方","官方","调查","最新","回应","通告","通报"]
        for k in keys:
            if k in q:
                return True
    else:
        ql = q.lower()
        keys = ["what happened","incident","breaking","news","statement","police","investigation","latest"]
        for k in keys:
            if k in ql:
                return True
    return False

def _mcp__auto_categories(query, categories):
    q = str(query or "").strip()
    cat = str(categories or "").strip()
    if (not cat) or (cat.lower() == "auto"):
        return "news" if _mcp__looks_like_news_event(q) else "general"
    return cat

def _mcp__mk_keywords(query):
    q = str(query or "").strip()
    if not q:
        return []
    kws = []
    # 1) Chinese fragments (existing behavior)
    if _mcp__has_zh(q):
        stop = set(["怎么","回事","什么","如何","怎么样","最新","情况","新闻","事件","问题"])
        qq = re.sub(r"[^\u4e00-\u9fff]", "", q)
        seen = set()
        for L in [4,3,2]:
            for i in range(0, max(0, len(qq) - L + 1)):
                sub = qq[i:i+L]
                if (not sub) or (sub in stop):
                    continue
                if sub in seen:
                    continue
                seen.add(sub)
                kws.append(sub)
                if len(kws) >= 8:
                    break
            if len(kws) >= 8:
                break

    # 2) ASCII tokens + adjacent bigrams (generic, no special-case)
    toks = re.findall(r"[A-Za-z0-9]{2,}", q)
    toks = [t.lower() for t in toks if t]
    for t in toks:
        if t not in kws:
            kws.append(t)
    if len(toks) >= 2:
        i = 0
        while i + 1 < len(toks):
            bg = toks[i] + " " + toks[i+1]
            if bg not in kws:
                kws.append(bg)
            i += 1

    return kws[:12]

def _mcp__is_relevant(title, snippet, kws):
    t = (str(title or "") + " " + str(snippet or "")).strip()
    if not t:
        return False
    tl = t.lower()

    # Generic weak/low-signal tokens (not domain-specific)
    weak = set(["home", "app", "login", "download", "官网", "入口", "windows", "电脑", "键盘"])

    kws2 = []
    for k in (kws or []):
        kk = str(k or "").strip()
        if kk:
            kws2.append(kk)
    if not kws2:
        return True

    hits = 0
    seen = set()
    for kk in kws2:
        if _mcp__has_zh(kk):
            if (kk in t) and (kk not in seen):
                seen.add(kk)
                hits += 1
        else:
            kl = kk.lower()
            # ignore standalone weak words (keep phrases like 'home assistant' because it has space)
            if (kl in weak) and (" " not in kl):
                continue
            if (kl in tl) and (kl not in seen):
                seen.add(kl)
                hits += 1

    # Generic rule: if we have 3+ keywords, require 2+ distinct hits
    if len(kws2) >= 3:
        return True if hits >= 2 else False
    return True if hits >= 1 else False

# --- MCP_PHASEB_DEFAULT_NORUNAWAY_V3 END ---

# @mcp.tool(description="Web search via local SearXNG. Returns short structured evidence. No cloud LLM is used.")
def web_search(
    query: str,
    k: int = 3,
    categories: str = "general",
    language: str = "zh-CN",
    time_range: str = "",
) -> dict:
    q = (query or "").strip()
    q = _mcp__normalize_query(q)
    if not q:
        return {"ok": False, "error": "empty_query"}

    # Phase B defaults
    lang_used = _mcp__auto_language(q, language)
    # force English for non-zh queries (avoid Brave 422 with zh params on latin query)
    try:
        if (not _mcp__has_zh(q)) and re.search(r"[A-Za-z]", q or ""):
            lang_used = "en"
    except Exception:
        pass
    # General-first: if categories is empty/auto, start with general and optionally fallback to news.
    cat_in = str(categories or "").strip()
    if (not cat_in) or (cat_in.lower() == "auto"):
        cat_used = "general"
        _mcp__cat_auto = True
    else:
        cat_used = _mcp__auto_categories(q, categories)
        _mcp__cat_auto = False
    # Legacy-default compatibility branch. Disabled by default to reduce hidden routing drift.
    legacy_defaults_on = str(os.environ.get("WEB_SEARCH_LEGACY_DEFAULTS") or "0").strip().lower() in ["1", "true", "yes", "on"]
    if legacy_defaults_on:
        # IMPORTANT: do NOT override categories when user explicitly provides it (e.g., 'general').
        try:
            if _mcp__has_zh(q):
                if str(language or "").strip().lower() in ("", "en"):
                    lang_used = "zh-CN"
                cat_in = str(categories or "").strip().lower()
                if cat_in in ("", "auto"):
                    cat_used = _mcp__auto_categories(q, "auto")
        except Exception:
            pass

    kws = _mcp__mk_keywords(q)
    relevance_low = None

    try:
        kk = int(k)
    except Exception:
        kk = 5
    if kk < 1:
        kk = 1
    if kk > 5:
        kk = 5

    brave_base_url = os.getenv("BRAVE_SEARCH_URL", "https://api.search.brave.com/res/v1/web/search").strip()
    searx_base_url = str(os.getenv("SEARXNG_URL") or "").strip()
    token = (os.getenv("BRAVE_SEARCH_TOKEN") or os.getenv("BRAVE_API_KEY") or "").strip()
    tr = time_range.strip() if time_range else None

    backend = "brave"
    fallback_reason = ""

    def _run_search_with_backend(backend_name: str, count_v: int):
        if backend_name == "searxng":
            return _searxng_http_search(
                base_url=searx_base_url,
                query=q,
                categories=str(cat_used or "general").strip(),
                language=str(lang_used or "en").strip(),
                count=count_v,
                time_range=tr,
            )
        return _searxng_search(
            base_url=brave_base_url,
            query=q,
            categories=str(cat_used or "general").strip(),
            language=str(lang_used or "en").strip(),
            count=count_v,
            time_range=tr,
        )

    if token:
        try:
            data = _run_search_with_backend("brave", kk)
        except Exception as e:
            em = str(e or "")
            if searx_base_url:
                backend = "searxng"
                if _web__is_brave_quota_error(em):
                    fallback_reason = "brave_quota_or_rate_limit"
                else:
                    fallback_reason = "brave_failed_fallback"
                try:
                    data = _run_search_with_backend("searxng", kk)
                except Exception as e2:
                    return {"ok": False, "error": "search_failed", "backend": "searxng", "message": str(e2)}
            else:
                return {"ok": False, "error": "brave_failed", "backend": "brave", "message": em}
    else:
        if not searx_base_url:
            return {
                "ok": False,
                "error": "search_not_configured",
                "backend": "none",
                "message": "BRAVE_SEARCH_TOKEN missing and SEARXNG_URL missing",
            }
        backend = "searxng"
        fallback_reason = "brave_token_missing"
        try:
            data = _run_search_with_backend("searxng", kk)
        except Exception as e:
            return {"ok": False, "error": "search_failed", "backend": "searxng", "message": str(e)}

    if not isinstance(data, dict):
        return {"ok": False, "error": "search_failed", "backend": backend, "message": "invalid search backend response"}

    results_in = data.get("results") or []
    results_out: List[Dict[str, Any]] = []
    for item in results_in[:kk]:
        results_out.append(
            {
                "title": (item.get("title") or "").strip(),
                "url": (item.get("url") or "").strip(),
                "snippet": _ug_clean_unicode((item.get("content") or "").strip()),
                "engine": (item.get("engine") or "").strip(),
                "score": item.get("score", None),
            }
        )

    # Phase B: relevance self-check (top 5)
    try:
        top5 = results_out[:5]
        rel_top5 = 0
        for it in top5:
            if _mcp__is_relevant(it.get("title"), it.get("snippet"), kws):
                rel_top5 += 1
        if _mcp__has_zh(q) and rel_top5 == 0:
            relevance_low = True
        else:
            relevance_low = False
    except Exception:
        relevance_low = None

    # Phase B: lightweight evidence block for the LLM (routing + grounded answering)
    evidence = {}
    try:
        top = results_out[: min(3, len(results_out))]
        prefer_zh = True if str(lang_used or "").strip().lower().startswith("zh") else False

        # MCP_WS_V6: score-based selection (generic)
        def _score(it):
            try:
                title = it.get("title")
                snippet = it.get("snippet")
                txt = (str(title or "") + " " + str(snippet or "")).lower()
                kws2 = [str(k or "").strip().lower() for k in (kws or []) if str(k or "").strip()]
                weak = set(["home", "app", "login", "download", "官网", "入口", "windows", "电脑", "键盘"])
                hit = 0
                phrase_hit = 0
                seen = set()
                for k in kws2:
                    if (k in weak) and (" " not in k):
                        continue
                    if (k in txt) and (k not in seen):
                        seen.add(k)
                        hit += 1
                    if (" " in k) and (k in txt):
                        phrase_hit += 1
                zh_bonus = 2 if (prefer_zh and _mcp__has_zh(txt)) else 0
                return (hit * 10) + (phrase_hit * 6) + zh_bonus
            except Exception:
                return 0

        best = None
        best_score = -1
        for it in results_out:
            if not _mcp__is_relevant(it.get("title"), it.get("snippet"), kws):
                continue
            sc = _score(it)
            if sc > best_score:
                best_score = sc
                best = it

        # Generic auto-expand: if k small and score low, fetch more results once and re-score
        try:
            if (best_score < 12) and (kk <= 3):
                kk2 = 8
                data2 = _run_search_with_backend(backend, int(kk2))
                r2 = data2.get("results") if isinstance(data2, dict) else None
                if isinstance(r2, list):
                    seen_url = set([str(it.get("url") or "") for it in results_out])
                    for it2 in r2:
                        title2 = str(it2.get("title") or "").strip()
                        url2 = str(it2.get("url") or "").strip()
                        sn2 = str(it2.get("content") or "").strip()
                        if (not title2) or (not url2):
                            continue
                        if url2 in seen_url:
                            continue
                        seen_url.add(url2)
                        results_out.append({"title": title2, "url": url2, "snippet": sn2})
                    # re-score
                    best = None
                    best_score = -1
                    for it in results_out:
                        if not _mcp__is_relevant(it.get("title"), it.get("snippet"), kws):
                            continue
                        sc = _score(it)
                        if sc > best_score:
                            best_score = sc
                            best = it
        except Exception:
            pass

        if best is None and top:
            best = top[0]

        best_url = (best or {}).get("url")
        best_title = (best or {}).get("title")
        best_snippet = (best or {}).get("snippet") or ""

        need_open = False
        qtxt = q or ""
        # queries that usually need full page (lists/dates/prices/versions/policies)
        need_keys = ["具体", "列表", "日期", "时间", "安排", "版本", "更新", "价格", "多少钱", "政策", "条款", "细则"]
        for k in need_keys:
            if k in qtxt:
                need_open = True
                break
        if len(best_snippet) < 120:
            need_open = True
        if relevance_low is True:
            need_open = True

        evidence = {
            "top": top,
            "best_url": best_url,
            "best_title": best_title,
            "best_snippet": best_snippet[:600],
            "suggested_answer": (best_snippet[:400] if best_snippet else None),
            "need_open_url_extract": need_open,
        }
    except Exception:
        evidence = {}
    return {
        "ok": True,
        "query": q,
        "k": kk,
        "categories": cat_used,
        "language": lang_used,
        "backend": backend,
        "fallback_reason": fallback_reason,
        "base_url": (searx_base_url if backend == "searxng" else brave_base_url),
        "relevance_low": relevance_low,
        "evidence": evidence,
        "best_url": (evidence.get("best_url") if isinstance(evidence, dict) else None),
        "best_title": (evidence.get("best_title") if isinstance(evidence, dict) else None),
        "best_snippet": (evidence.get("best_snippet") if isinstance(evidence, dict) else None),
        "answer_hint": (evidence.get("suggested_answer") if isinstance(evidence, dict) else None),
        "need_open_url_extract": (evidence.get("need_open_url_extract") if isinstance(evidence, dict) else None),
        "results": results_out,
    }

# @mcp.tool(description="Open a URL and return a short extracted excerpt (readable + unicode cleaned).")
def open_url_extract(url: str, max_chars: int = 4000, timeout_sec: int = 10, accept_language: str = "") -> dict:
    return _ug_open_url_fetch(url=url, max_chars=max_chars, timeout_sec=timeout_sec, accept_language=accept_language)


# @mcp.tool(description="Fetch a web page and return a short plain-text excerpt (simple version for HA MCP).")
def open_url(url: str, accept_language: str = "") -> dict:
    out = _ug_open_url_fetch(url=url, max_chars=1200, timeout_sec=10, accept_language=accept_language)
    if not out.get("ok"):
        return {"ok": False, "url": url, "error": out.get("error", ""), "message": out.get("message", "")}
    return {
        "ok": True,
        "url": out.get("url"),
        "final_url": out.get("final_url"),
        "status_code": out.get("status_code"),
        "title": out.get("title", ""),
        "excerpt": (out.get("excerpt") or "")[:1200],
    }




# ---- Router: route user requests by information shape (Structured / Retrieval / Open-domain) ----

def _extract_year(text: str, default_year: int) -> int:
    t = text or ""
    m = re.search(r"(19|20)\d{2}", t)
    if not m:
        return int(default_year)
    try:
        y = int(m.group(0))
        return y
    except Exception:
        return int(default_year)

def _route_type(user_text: str) -> str:
    t = (user_text or "").strip().lower()

    # Structured: holiday
    if ("public holiday" in t) or ("holiday" in t) or ("假日" in t) or ("假期" in t) or ("公众假期" in t) or ("公休" in t) or ("维州" in t and "假" in t):
        return "structured_holiday"

    # Structured: calendar (support 日程/安排/事件/会议)
    # Output wording uses "日程", but recognition keeps compatible keywords.
    if ("calendar" in t) or ("日程" in t) or ("行程" in t) or ("安排" in t) or ("事件" in t) or ("会议" in t):
        return "structured_calendar"
    if ("提醒" in t) and (("今天" in t) or ("明天" in t) or ("后天" in t) or ("下周" in t) or ("本周" in t) or ("星期" in t) or ("周" in t) or ("点" in t)):
        return "structured_calendar"
    # Structured: weather
    # Make it robust for Chinese phrasing variants like "今天的天气怎么样"
    if ("weather" in t) or ("forecast" in t) or ("天气" in t) or ("天氣" in t) or ("预报" in t) or ("氣象" in t) or ("气温" in t) or ("溫度" in t) or ("温度" in t) or ("下雨" in t) or ("降雨" in t) or ("雨" in t and "量" in t) or ("风" in t and ("速" in t or "大" in t)):
        return "structured_weather"

    return "open_domain"

def _summarise_daily_forecast(fc: list) -> str:
    if not isinstance(fc, list) or (len(fc) == 0):
        return "暂无可用的天气预报数据。"
    x = fc[0] if isinstance(fc[0], dict) else {}
    cond = str(x.get("condition") or "").strip()

    t_hi = x.get("temperature")
    t_lo = x.get("templow")
    rain = x.get("precipitation")
    wind = x.get("wind_speed")

    parts = []

    # condition (keep raw token, but in Chinese skeleton)
    if cond:
        parts.append("天气: " + cond)

    # temperature
    if (t_hi is not None) and (t_lo is not None):
        parts.append("最低：" + str(t_lo) + "°C，最高：" + str(t_hi) + "°C")
    elif t_hi is not None:
        parts.append("温度: " + str(t_hi) + "°C")

    # precipitation (human)
    if rain is not None:
        try:
            rv = float(rain)
            if rv <= 0.0:
                parts.append("预计无降雨")
            else:
                parts.append("预计降雨: " + str(rain))
        except Exception:
            parts.append("预计降雨: " + str(rain))

    # wind (human bands)
    if wind is not None:
        try:
            wv = float(wind)
            if wv < 10:
                parts.append("微风（约 " + str(wind) + "）")
            elif wv < 20:
                parts.append("有风（约 " + str(wind) + "）")
            else:
                parts.append("风较大（约 " + str(wind) + "）")
        except Exception:
            parts.append("风速: " + str(wind))

    if not parts:
        return "已获取天气预报。"
    return "，".join(parts) + "。"

# --- WEATHER_RANGE_V1 HELPERS BEGIN ---
# --- CN_RANGE_EXT_V1 HELPERS BEGIN ---
# CN_RANGE_EXT_V1_WEEKEND_PRIORITY
# CN_RANGE_EXT_V1_DOM_FIX
# Extended CN range parsing (week / weekend / month)
def _cn_wd_to_idx(s: str):
    t = str(s or "")
    t = t.replace("星期", "周")
    if "周天" in t:
        return 6
    if "周日" in t:
        return 6
    m = re.search(r"周([一二三四五六日天])", t)
    if not m:
        return None
    c = m.group(1)
    mp = {"一":0, "二":1, "三":2, "四":3, "五":4, "六":5, "日":6, "天":6}
    return mp.get(c)

def _week_start_monday(d):
    try:
        from datetime import timedelta
        wd = int(d.weekday())
        return d - timedelta(days=wd)
    except Exception:
        return d

def _month_first_day(y, m):
    from datetime import date as _date
    return _date(int(y), int(m), 1)

def _add_months_first_day(d, add_months):
    try:
        y = int(d.year)
        mo = int(d.month)
        mo2 = mo + int(add_months)
        while mo2 > 12:
            mo2 -= 12
            y += 1
        while mo2 < 1:
            mo2 += 12
            y -= 1
        return _month_first_day(y, mo2)
    except Exception:
        return None

def _end_of_month(d_first):
    try:
        from datetime import timedelta
        next_first = _add_months_first_day(d_first, 1)
        return next_first - timedelta(days=1)
    except Exception:
        return None

def _parse_cn_week_month_range(text: str, now_d):
    t = str(text or "").strip()
    if not t:
        return None
    try:
        from datetime import timedelta
    except Exception:
        timedelta = None

    t_norm = t.replace("这个星期", "这周").replace("这个周", "这周").replace("星期", "周")
    # CN_RANGE_EXT_V1_WEEKEND_PRIORITY: parse 周末 before whole-week rules
    if "周末" in t_norm:
        try:
            from datetime import timedelta
        except Exception:
            timedelta = None
        if timedelta is not None:
            ws = _week_start_monday(now_d)
            # 下周末 / 下星期周末
            if ("下周末" in t_norm) or ("下星期周末" in t_norm) or ((("下周" in t_norm) or ("下星期" in t_norm)) and ("周末" in t_norm)):
                ws2 = ws + timedelta(days=7)
                sat = ws2 + timedelta(days=5)
                sun = ws2 + timedelta(days=6)
                return {"mode":"range","start_date": sat, "end_date": sun, "label":"下周末"}
            # 这个周末 / 这周末 / 本周末 / 周末：取“当前或即将到来的周末”
            wd = int(now_d.weekday())
            if wd == 5:
                sat = now_d
                sun = now_d + timedelta(days=1)
            elif wd == 6:
                sat = now_d - timedelta(days=1)
                sun = now_d
            else:
                sat = now_d + timedelta(days=(5 - wd))
                sun = sat + timedelta(days=1)
            return {"mode":"range","start_date": sat, "end_date": sun, "label":"这个周末"}


    # CN_RANGE_EXT_V1_DOM_FIX: day-of-month parsing
    def _mk_date(y, m, d):
        try:
            from datetime import date as _date
            return _date(int(y), int(m), int(d))
        except Exception:
            return None

    # 下个月N号 / 下月N号
    m_dom_next = re.search(r"(?<!\d)(\d{1,2})(号|日)(?!\d)", t_norm)
    if m_dom_next and (("下个月" in t_norm) or ("下月" in t_norm)):
        dn = m_dom_next.group(1)
        d_first = _add_months_first_day(now_d, 1)
        if d_first is not None:
            d_target = _mk_date(d_first.year, d_first.month, int(dn))
            if d_target is not None:
                return {"mode":"single", "target_date": d_target, "label":"下个月" + str(dn) + "号"}

    # 本月N号 / 这个月N号
    if m_dom_next and (("这个月" in t_norm) or ("本月" in t_norm)):
        dn = m_dom_next.group(1)
        d_target = _mk_date(now_d.year, now_d.month, int(dn))
        if d_target is not None:
            return {"mode":"single", "target_date": d_target, "label":"本月" + str(dn) + "号"}

    # 仅 N号 / N日（无显式月份）：若 dn >= 今天几号 -> 本月；否则 -> 下个月
    if m_dom_next and ("月" not in t_norm) and ("周" not in t_norm):
        dn = int(m_dom_next.group(1))
        if dn >= int(now_d.day):
            d_target = _mk_date(now_d.year, now_d.month, dn)
            if d_target is not None:
                return {"mode":"single", "target_date": d_target, "label": str(dn) + "号"}
        else:
            d_first = _add_months_first_day(now_d, 1)
            if d_first is not None:
                d_target = _mk_date(d_first.year, d_first.month, dn)
                if d_target is not None:
                    return {"mode":"single", "target_date": d_target, "label": str(dn) + "号"}


    # Month: next month first day / this month first day
    if ("下个月" in t_norm) or ("下月" in t_norm):
        if ("第一天" in t_norm) or ("1号" in t_norm) or ("1日" in t_norm):
            d1 = _add_months_first_day(now_d, 1)
            if d1 is not None:
                return {"mode":"single","target_date": d1, "label":"下个月第一天"}
        if ("日程" in t_norm) or ("日历" in t_norm) or ("日曆" in t_norm) or ("安排" in t_norm) or ("行程" in t_norm) or ("calendar" in t_norm) or ("event" in t_norm):
            d_first = _add_months_first_day(now_d, 1)
            d_last = _end_of_month(d_first) if d_first is not None else None
            if (d_first is not None) and (d_last is not None):
                return {"mode":"range","start_date": d_first, "end_date": d_last, "label":"下个月"}

    if ("这个月" in t_norm) or ("本月" in t_norm):
        if ("第一天" in t_norm) or ("1号" in t_norm) or ("1日" in t_norm):
            d1 = _add_months_first_day(now_d, 0)
            if d1 is not None:
                return {"mode":"single","target_date": d1, "label":"本月第一天"}
        if ("日程" in t_norm) or ("日历" in t_norm) or ("日曆" in t_norm) or ("安排" in t_norm) or ("行程" in t_norm) or ("calendar" in t_norm) or ("event" in t_norm):
            d_first = _add_months_first_day(now_d, 0)
            d_last = _end_of_month(d_first) if d_first is not None else None
            if (d_first is not None) and (d_last is not None):
                return {"mode":"range","start_date": d_first, "end_date": d_last, "label":"本月"}

    # Weekday: 下周三 / 这周三 / 本周三 / 周三
    m = re.search(r"(下周|下星期|这周|本周|周)([一二三四五六日天])(?!气)", t_norm)
    if m:
        prefix = m.group(1)
        target_wd = _cn_wd_to_idx("周" + m.group(2))
        if (target_wd is not None) and (timedelta is not None):
            ws = _week_start_monday(now_d)
            if (prefix == "下周") or (prefix == "下星期"):
                ws = ws + timedelta(days=7)
            if prefix == "周":
                cand = ws + timedelta(days=int(target_wd))
                if cand < now_d:
                    ws = ws + timedelta(days=7)
            d_target = ws + timedelta(days=int(target_wd))
            return {"mode":"single","target_date": d_target, "label": prefix + m.group(2)}

    # Whole week: 下周 / 本周 / 这周
    if ("下周" in t_norm) or ("下星期" in t_norm) or ("这周" in t_norm) or ("本周" in t_norm):
        if timedelta is None:
            return None
        ws = _week_start_monday(now_d)
        if ("下周" in t_norm) or ("下星期" in t_norm):
            ws = ws + timedelta(days=7)
            label = "下周"
        else:
            label = "本周"
        we = ws + timedelta(days=6)
        return {"mode":"range","start_date": ws, "end_date": we, "label": label}

    # Weekend: 这个周末 / 周末 / 下周末
    if "周末" in t_norm:
        if timedelta is None:
            return None
        ws = _week_start_monday(now_d)
        if ("下周末" in t_norm) or ("下星期周末" in t_norm) or (("下周" in t_norm or "下星期" in t_norm) and ("周末" in t_norm)):
            ws2 = ws + timedelta(days=7)
            sat = ws2 + timedelta(days=5)
            sun = ws2 + timedelta(days=6)
            return {"mode":"range","start_date": sat, "end_date": sun, "label":"下周末"}
        wd = int(now_d.weekday())
        if wd == 5:
            sat = now_d
            sun = now_d + timedelta(days=1)
        elif wd == 6:
            sat = now_d - timedelta(days=1)
            sun = now_d
        else:
            sat = now_d + timedelta(days=(5 - wd))
            sun = sat + timedelta(days=1)
        return {"mode":"range","start_date": sat, "end_date": sun, "label":"这个周末"}

    return None

# --- CN_RANGE_EXT_V1 HELPERS END ---

def _local_date_from_iso(dt_str: str, tzinfo) -> date:
    try:
        if not dt_str:
            return None
        dtx = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
        if getattr(dtx, 'tzinfo', None) is None:
            try:
                dtx = dtx.replace(tzinfo=tzinfo)
            except Exception:
                pass
        try:
            dtx2 = dtx.astimezone(tzinfo)
        except Exception:
            dtx2 = dtx
        return date(dtx2.year, dtx2.month, dtx2.day)
    except Exception:
        return None

def _weather_range_from_text(text: str, now_local: object = None) -> dict:
    """
    Parse user text into a weather query:
      - single day: today/tomorrow/day after tomorrow/explicit date
      - range: next N days / explicit date range
    Return dict:
      {"mode":"single","offset":int,"label":str}
      {"mode":"single","target_date": datetime.date, "label":str}
      {"mode":"range","start_date": datetime.date, "days":int, "label":str}
    """
    out = {"mode": "single", "offset": 0, "label": ""}
    t = str(text or "").strip()

    # Normalize spaces
    t2 = re.sub(r"\s+", " ", t)


    # CN_RANGE_EXT_V1 APPLY WEATHER
    try:
        from datetime import datetime as _dt
        if (now_local is not None) and hasattr(now_local, "year"):
            from datetime import date as _date
            now_d = _date(int(getattr(now_local, "year")), int(getattr(now_local, "month")), int(getattr(now_local, "day")))
        else:
            now_d = _dt.now().date()
    except Exception:
        now_d = None

    if now_d is not None:
        ext = _parse_cn_week_month_range(t2, now_d)
        if isinstance(ext, dict):
            if ext.get("mode") == "range":
                sd = ext.get("start_date")
                ed = ext.get("end_date")
                if (sd is not None) and (ed is not None):
                    try:
                        days = (ed - sd).days + 1
                        if days < 1:
                            days = 1
                    except Exception:
                        days = 1
                    return {"mode":"range", "start_date": sd, "days": int(days), "label": str(ext.get("label") or "")}
            return ext

    # Date range: YYYY-MM-DD 到 YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(到|至|\-)\s*(\d{4}-\d{2}-\d{2})", t2)
    if m:
        try:
            from datetime import datetime as _dt
            from datetime import date as _date
            s1 = m.group(1)
            s2 = m.group(3)
            d1 = _dt.fromisoformat(s1).date()
            d2 = _dt.fromisoformat(s2).date()
            if d2 >= d1:
                days = (d2 - d1).days + 1
                if days < 1:
                    days = 1
                out = {"mode": "range", "start_date": d1, "days": int(days), "label": s1 + "到" + s2}
                return out
        except Exception:
            pass

    # Single explicit: YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t2)
    if m:
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(m.group(1)).date()
            out = {"mode": "single", "target_date": d, "label": m.group(1)}
            return out
        except Exception:
            pass

    # "1月26日" (assume current year)
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", t2)
    if m:
        try:
            mm = int(m.group(1))
            dd = int(m.group(2))
            from datetime import date as _date
            if now_local is not None and hasattr(now_local, "year"):
                yy = int(getattr(now_local, "year"))
            else:
                from datetime import datetime as _dt
                yy = int(_dt.now().year)
            d = _date(yy, mm, dd)
            out = {"mode": "single", "target_date": d, "label": str(mm) + "月" + str(dd) + "日"}
            return out
        except Exception:
            pass

    # Next N days: 接下来N天 / 未来N天 / 接下來N天 / 未來N天
    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", t2)
    if m:
        try:
            n = int(m.group(2))
        except Exception:
            n = 3
        if n < 1:
            n = 1
        out = {"mode": "range", "days": int(n), "label": m.group(1) + str(n) + "天"}
        return out

    # Relative days
    if ("大后天" in t2) or ("大後天" in t2):
        return {"mode": "single", "offset": 3, "label": "大后天"}
    if ("后天" in t2) or ("後天" in t2):
        return {"mode": "single", "offset": 2, "label": "后天"}
    if ("明天" in t2):
        return {"mode": "single", "offset": 1, "label": "明天"}
    if ("今天" in t2) or ("今日" in t2):
        return {"mode": "single", "offset": 0, "label": "今天"}

    return out

def _calendar_range_from_text(text: str, now_local: object = None) -> dict:
    """
    Parse user text into calendar query range.
    Return:
      {"mode":"single","offset":int,"label":str}
      {"mode":"single","target_date": date, "label":str}
      {"mode":"range","start_date": date, "days":int, "label":str}
      {"mode":"range","start_date": date, "end_date": date, "label":str}
    """
    out = {"mode": "single", "offset": 0, "label": ""}
    t = str(text or "").strip()
    t2 = re.sub(r"\s+", " ", t)


    # CN_RANGE_EXT_V1 APPLY CALENDAR
    try:
        from datetime import datetime as _dt
        if (now_local is not None) and hasattr(now_local, "year"):
            from datetime import date as _date
            now_d = _date(int(getattr(now_local, "year")), int(getattr(now_local, "month")), int(getattr(now_local, "day")))
        else:
            now_d = _dt.now().date()
    except Exception:
        now_d = None

    if now_d is not None:
        ext = _parse_cn_week_month_range(t2, now_d)
        if isinstance(ext, dict):
            return ext

    # YYYY-MM-DD 到 YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(到|至|\-)\s*(\d{4}-\d{2}-\d{2})", t2)
    if m:
        try:
            from datetime import datetime as _dt
            d1 = _dt.fromisoformat(m.group(1)).date()
            d2 = _dt.fromisoformat(m.group(3)).date()
            if d2 >= d1:
                return {"mode": "range", "start_date": d1, "end_date": d2, "label": m.group(1) + "到" + m.group(3)}
        except Exception:
            pass

    # YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t2)
    if m:
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(m.group(1)).date()
            return {"mode": "single", "target_date": d, "label": m.group(1)}
        except Exception:
            pass

    # 1月26日
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", t2)
    if m:
        try:
            mm = int(m.group(1))
            dd = int(m.group(2))
            from datetime import date as _date
            if now_local is not None and hasattr(now_local, "year"):
                yy = int(getattr(now_local, "year"))
            else:
                from datetime import datetime as _dt
                yy = int(_dt.now().year)
            d = _date(yy, mm, dd)
            return {"mode": "single", "target_date": d, "label": str(mm) + "月" + str(dd) + "日"}
        except Exception:
            pass

    # 接下来N天/未来N天
    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", t2)
    if m:
        try:
            n = int(m.group(2))
        except Exception:
            n = 3
        if n < 1:
            n = 1
        return {"mode": "range", "days": int(n), "label": m.group(1) + str(n) + "天"}

    if ("大后天" in t2) or ("大後天" in t2):
        return {"mode": "single", "offset": 3, "label": "大后天"}
    if ("后天" in t2) or ("後天" in t2):
        return {"mode": "single", "offset": 2, "label": "后天"}
    if ("明天" in t2):
        return {"mode": "single", "offset": 1, "label": "明天"}
    if ("今天" in t2) or ("今日" in t2):
        return {"mode": "single", "offset": 0, "label": "今天"}

    return out


def _cn_num_to_int(s: str) -> int:
    t = str(s or "").strip()
    if not t:
        return -1
    if t.isdigit():
        try:
            return int(t)
        except Exception:
            return -1
    mp = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if t == "十":
        return 10
    if "十" in t:
        p = t.split("十", 1)
        left = p[0]
        right = p[1]
        tens = 1 if not left else mp.get(left, -100)
        ones = 0 if not right else mp.get(right, -100)
        if tens < 0 or ones < 0:
            return -1
        return int(tens * 10 + ones)
    if len(t) == 1 and t in mp:
        return int(mp.get(t))
    return -1


def _calendar_is_create_intent(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    sl = s.lower()
    if ("提醒我" not in s) and ("请提醒我" not in s) and ("remind me" not in sl):
        return False
    query_words = ["有什么", "有哪些", "查看", "查询", "日程", "行程", "calendar", "event"]
    for q in query_words:
        if (q in s) or (q in sl):
            return False
    time_cues = [
        "今天", "明天", "后天", "大后天", "下周", "本周", "周", "星期", "礼拜", "上午", "下午", "晚上", "中午", "点", "am", "pm",
    ]
    for k in time_cues:
        if (k in s) or (k in sl):
            return True
    if re.search(r"\d{1,2}:\d{2}", sl):
        return True
    return False


def _calendar_build_create_event(text: str, now_local: object = None) -> dict:
    s = str(text or "").strip()
    if not s:
        return {"ok": False, "error": "empty_text"}
    now_dt = now_local if now_local is not None else _now_local()
    base_d = dt_date(int(now_dt.year), int(now_dt.month), int(now_dt.day))
    offset = 0
    label = "今天"
    if ("大后天" in s) or ("大後天" in s):
        offset = 3
        label = "大后天"
    elif ("后天" in s) or ("後天" in s):
        offset = 2
        label = "后天"
    elif "明天" in s:
        offset = 1
        label = "明天"
    elif ("今天" in s) or ("今日" in s):
        offset = 0
        label = "今天"

    try:
        d = base_d + timedelta(days=int(offset))
    except Exception:
        d = base_d

    hh = 9
    mm = 0
    m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", s)
    if m:
        try:
            hh = int(m.group(1))
            mm = int(m.group(2))
        except Exception:
            hh = 9
            mm = 0
    else:
        m2 = re.search(r"(\d{1,2})\s*点\s*(半|[0-5]?\d\s*分?)?", s)
        if m2:
            try:
                hh = int(m2.group(1))
            except Exception:
                hh = 9
            tail = str(m2.group(2) or "").strip()
            if "半" in tail:
                mm = 30
            else:
                m3 = re.search(r"([0-5]?\d)", tail)
                if m3:
                    try:
                        mm = int(m3.group(1))
                    except Exception:
                        mm = 0
        else:
            m4 = re.search(r"([零〇一二两三四五六七八九十]{1,3})\s*点\s*(半)?", s)
            if m4:
                h2 = _cn_num_to_int(m4.group(1))
                if h2 >= 0:
                    hh = h2
                if str(m4.group(2) or "").strip():
                    mm = 30

    if ("下午" in s) or ("晚上" in s):
        if hh < 12:
            hh = hh + 12
    if "中午" in s and hh < 11:
        hh = hh + 12
    if hh < 0 or hh > 23:
        hh = 9
    if mm < 0 or mm > 59:
        mm = 0

    summary = ""
    if "开会" in s:
        summary = "开会"
    else:
        t = s
        for k in ["请提醒我", "提醒我", "提醒一下我", "提醒一下"]:
            t = t.replace(k, "")
        t = re.sub(r"(今天|明天|后天|大后天|上午|下午|晚上|中午|本周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天])", " ", t)
        t = re.sub(r"(\d{1,2}\s*[:：]\s*\d{2})", " ", t)
        t = re.sub(r"(\d{1,2}\s*点\s*(半|[0-5]?\d\s*分?)?)", " ", t)
        t = re.sub(r"([零〇一二两三四五六七八九十]{1,3}\s*点\s*半?)", " ", t)
        t = re.sub(r"\s+", " ", t).strip(" ，。,:：;；")
        summary = t if t else "事项提醒"
    if len(summary) > 40:
        summary = summary[:40].strip()

    try:
        tz = ZoneInfo("Australia/Melbourne")
    except Exception:
        tz = None
    if tz is not None:
        st = datetime(d.year, d.month, d.day, hh, mm, 0, tzinfo=tz)
    else:
        st = datetime(d.year, d.month, d.day, hh, mm, 0)
    et = st + timedelta(minutes=30)
    return {
        "ok": True,
        "label": label,
        "summary": summary,
        "start_date_time": st.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date_time": et.strftime("%Y-%m-%d %H:%M:%S"),
    }

# --- MCP_ENTRYPOINT_AND_ROUTE_V1 ---

# Notes:
# - Fix "Restarting (0)" by providing a long-running entrypoint.
# - Provide MCP tools: route_request + tools_selfcheck.
# - No f-strings (project rule).

def _safe_int(x, d):
    try:
        return int(x)
    except Exception:
        return d

def _tzinfo():
    tzname = os.environ.get("TZ") or "Australia/Melbourne"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tzname)
    except Exception:
        return None

def _now_local():
    tz = _tzinfo()
    try:
        from datetime import datetime
        return datetime.now(tz) if tz else datetime.now()
    except Exception:
        from datetime import datetime
        return datetime.now()

def _dt_from_iso(s):
    try:
        from datetime import datetime
        t = str(s or "").strip()
        if not t:
            return None
        t = t.replace("Z", "+00:00")
        return datetime.fromisoformat(t)
    except Exception:
        return None

def _local_date_from_forecast_item(it, tzinfo):
    if not isinstance(it, dict):
        return None
    dt = _dt_from_iso(it.get("datetime"))
    if dt is None:
        return None
    try:
        if tzinfo is not None:
            return dt.astimezone(tzinfo).date()
        return dt.date()
    except Exception:
        try:
            return dt.date()
        except Exception:
            return None

def _weather_condition_localize(cond: str) -> str:
    c = str(cond or "").strip().lower()
    if not c:
        return ""
    norm = c.replace("_", " ").replace("-", " ")
    norm = re.sub(r"\s+", " ", norm).strip()
    mapping = [
        ("partly cloudy", "局部多云"),
        ("mostly cloudy", "大部多云"),
        ("clear night", "晴夜"),
        ("clear", "晴"),
        ("sunny", "晴"),
        ("cloudy", "多云"),
        ("overcast", "阴"),
        ("rainy", "雨"),
        ("rain", "雨"),
        ("showers", "阵雨"),
        ("shower", "阵雨"),
        ("thunderstorm", "雷雨"),
        ("storm", "风暴"),
        ("snowy", "雪"),
        ("snow", "雪"),
        ("fog", "雾"),
        ("windy", "有风"),
    ]
    for en, zh in mapping:
        if en in norm:
            return zh
    return cond

def _summarise_weather_item(it):
    if not isinstance(it, dict):
        return "无可用预报。"
    def _fmt_temp(v):
        if v is None:
            return "暂无"
        try:
            fv = float(v)
            if abs(fv - int(fv)) < 0.001:
                return str(int(fv))
            return str(round(fv, 1))
        except Exception:
            return str(v)
    def _fmt_temp_u(v):
        s = _fmt_temp(v)
        if s == "暂无":
            return s
        return s + "°C"
    def _fmt_mm(v):
        try:
            fv = float(v)
            if abs(fv - int(fv)) < 0.001:
                return str(int(fv))
            return str(round(fv, 1))
        except Exception:
            return str(v)
    cond = _weather_condition_localize(str(it.get("condition") or "").strip())
    tmax = it.get("temperature")
    tmin = it.get("templow")
    pr = it.get("precipitation")
    ws = it.get("wind_speed")

    parts = []
    if cond:
        parts.append(cond)
    if (tmax is not None) or (tmin is not None):
        parts.append("最低：" + _fmt_temp_u(tmin) + "，最高：" + _fmt_temp_u(tmax))
    if pr is not None:
        try:
            prf = float(pr)
        except Exception:
            prf = None
        if prf is not None:
            parts.append("预计" + ("无降雨" if prf == 0.0 else ("降雨 " + _fmt_mm(pr) + " mm")))
    if ws is not None:
        parts.append("有风（约 " + str(ws) + "）")

    if not parts:
        return "无可用预报。"
    return "，".join(parts) + "。"

def _pick_daily_forecast_by_local_date(fc_list, target_date, tzinfo):
    if not isinstance(fc_list, list):
        return None
    for it in fc_list:
        d = _local_date_from_forecast_item(it, tzinfo)
        if d is None:
            continue
        if d == target_date:
            return it
    return None

def _summarise_weather_range(fc_list, start_date, days, tzinfo):
    if not isinstance(fc_list, list):
        return "无可用预报。"
    def _fmt_temp(v):
        if v is None:
            return "暂无"
        try:
            fv = float(v)
            if abs(fv - int(fv)) < 0.001:
                return str(int(fv))
            return str(round(fv, 1))
        except Exception:
            return str(v)
    def _fmt_temp_u(v):
        s = _fmt_temp(v)
        if s == "暂无":
            return s
        return s + "°C"
    try:
        days_i = int(days)
    except Exception:
        days_i = 3
    if days_i < 1:
        days_i = 1
    # plugin typically only provides today + next 5 days
    if days_i > 6:
        days_i = 6

    out = []
    try:
        from datetime import timedelta
        for i in range(days_i):
            d = start_date + timedelta(days=i)
            it = _pick_daily_forecast_by_local_date(fc_list, d, tzinfo)
            if it is None:
                out.append(str(d) + ": 无预报")
            else:
                cond = _weather_condition_localize(str(it.get("condition") or "").strip())
                tmax = it.get("temperature")
                tmin = it.get("templow")
                cond_show = cond if cond else "天气"
                out.append(str(d) + ": " + cond_show + " 最低：" + _fmt_temp_u(tmin) + "，最高：" + _fmt_temp_u(tmax))
    except Exception:
        return "无可用预报。"
    return "；".join(out) + "。"

def _is_weather_query(t):
    s = str(t or "")
    keys = ["天气", "温度", "降雨", "下雨", "气温", "风", "预报", "天氣"]
    for k in keys:
        if k in s:
            return True
    return False

def _is_calendar_query(t):
    s = str(t or "")
    direct_keys = ["日程", "日历", "日曆", "安排", "行程", "event", "calendar"]
    for k in direct_keys:
        if k in s:
            return True
    sl = s.lower()
    has_event_word = ("会议" in s) or ("开会" in s) or ("meeting" in sl)
    has_mutation_word = ("删除" in s) or ("取消" in s) or ("修改" in s) or ("改到" in s) or ("改成" in s) or ("调整到" in s) or ("reschedule" in sl) or ("delete" in sl) or ("update" in sl)
    if has_event_word and has_mutation_word:
        return True
    reminder_keys = ["提醒", "待办", "待辦", "remind", "reminder"]
    has_reminder = False
    for k in reminder_keys:
        if (k in s) or (k in sl):
            has_reminder = True
            break
    if not has_reminder:
        return False
    # Treat reminder as calendar only when a time cue exists.
    time_cues = [
        "今天", "明天", "后天", "下周", "本周", "周一", "周二", "周三", "周四", "周五", "周六", "周日",
        "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日",
        "礼拜一", "礼拜二", "礼拜三", "礼拜四", "礼拜五", "礼拜六", "礼拜日",
        "号", "日", "月", "点", "am", "pm", "today", "tomorrow", "next week", "this week",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    ]
    for k in time_cues:
        if (k in s) or (k in sl):
            return True
    return False

def _is_holiday_query(t):
    s = str(t or "")
    keys = ["公众假期", "公眾假期", "法定假日", "假期", "假日", "holiday"]
    for k in keys:
        if k in s:
            return True
    return False

def _is_rag_intent(t):
    s = str(t or "").strip()
    if not s:
        return False
    tl = s.lower()

    # Keep RAG trigger strict enough to avoid stealing structured/search routes.
    blocked = [
        "搜索", "搜一下", "查一下", "查查", "查下", "news", "新闻",
        "天气", "weather", "日程", "日历", "calendar", "假期", "holiday",
    ]
    for k in blocked:
        if k in s or k in tl:
            return False

    keys_cn = [
        "资料库", "知识库", "家庭资料", "家庭知识",
        "家里资料", "家里说明书", "手册",
    ]
    for k in keys_cn:
        if k in s:
            return True

    keys_en = ["knowledge base", "home knowledge"]
    for k in keys_en:
        if k in tl:
            return True

    padded = " " + tl + " "
    if (" rag " in padded) or tl == "rag":
        return True
    if (" kb " in padded) or tl == "kb":
        return True
    return False

def _is_rag_disable_intent(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    tl = s.lower()
    has_rag_scope = False
    rag_words_cn = ["资料库", "家庭资料库", "rag"]
    for k in rag_words_cn:
        if k in s or k in tl:
            has_rag_scope = True
            break
    if not has_rag_scope:
        return False

    norm = tl
    for ch in ["，", "。", "；", "：", "（", "）", "(", ")", "[", "]", "{", "}", ",", ".", ";", ":", "!", "?", "、", "/", "\\", "|", "\"", "'"]:
        norm = norm.replace(ch, " ")
    tokens = [t for t in norm.split() if t]

    neg_tokens = {"no", "not", "dont", "don't", "disable", "stop"}
    has_en_neg = False
    for t in tokens:
        if t in neg_tokens:
            has_en_neg = True
            break

    has_cn_neg = False
    for k in ["不要", "不用", "别", "停止", "不使用", "不查"]:
        if k in s:
            has_cn_neg = True
            break
    return has_en_neg or has_cn_neg

def _rag_mode(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return "query"
    tl = s.lower()

    add_keys_cn = ["加入", "添加", "写入", "保存到", "导入", "导入到"]
    for k in add_keys_cn:
        if k in s:
            return "add"
    add_keys_en = ["ingest", "add", "save", "import"]
    for k in add_keys_en:
        if k in tl:
            return "add"

    update_keys_cn = ["更新", "修改", "替换"]
    for k in update_keys_cn:
        if k in s:
            return "update"
    update_keys_en = ["update", "edit"]
    for k in update_keys_en:
        if k in tl:
            return "update"

    return "query"

def _rag_extract_min_fields(text: str) -> dict:
    s = str(text or "").strip()
    tl = s.lower()
    mode = _rag_mode(s)

    subject = ""
    if "：" in s:
        subject = str(s.split("：", 1)[1] or "").strip()
    elif ":" in s:
        subject = str(s.split(":", 1)[1] or "").strip()
    if len(subject) > 120:
        subject = subject[:120].rstrip()

    path = ""
    sep_chars = ["\n", "\t", ",", "，", "。", ";", "；", "(", ")", "[", "]", "{", "}", "\"", "'"]
    work = s
    for ch in sep_chars:
        work = work.replace(ch, " ")
    tokens = work.split()
    for tok in tokens:
        tk = str(tok or "").strip()
        if not tk:
            continue
        tkl = tk.lower()
        if tkl.startswith("/mnt/") or tkl.startswith("/home/") or tkl.startswith("c:\\") or tkl.startswith("nas:"):
            path = tk
            break

    filetype = ""
    exts = ["pdf", "txt", "md", "docx", "xlsx", "json", "yaml", "yml"]
    for ext in exts:
        if (" " + ext + " ") in (" " + tl + " "):
            filetype = ext
            break
    if not filetype:
        for ext in exts:
            mark = "." + ext
            if mark in tl:
                filetype = ext
                break

    source_type = "unknown"
    if ("/mnt/nas" in tl) or ("nas" in tl) or ("共享" in s):
        source_type = "nas_folder"
    elif any(k in tl for k in ["notion", "obsidian", "onenote", "evernote"]) or "笔记" in s:
        source_type = "notes_app"
    elif ("http://" in tl) or ("https://" in tl):
        source_type = "url"
    elif ("/home/" in tl) or ("c:\\" in tl):
        source_type = "local_path"

    return {
        "mode": mode,
        "subject": subject,
        "path": path,
        "filetype": filetype,
        "source_type": source_type,
    }

def _rag_stub_answer(text: str, language: str = "", mode: str = "query") -> str:
    lang = str(language or "").strip().lower()
    txt = str(text or "")
    m = str(mode or "query").strip().lower()
    fields = _rag_extract_min_fields(txt)
    f_subject = str(fields.get("subject") or "").strip()
    f_path = str(fields.get("path") or "").strip()
    f_filetype = str(fields.get("filetype") or "").strip()
    f_source_type = str(fields.get("source_type") or "unknown").strip()
    if f_filetype:
        input_type_zh = "文件"
        input_type_en = "file"
    elif f_subject:
        input_type_zh = "文本"
        input_type_en = "text"
    else:
        input_type_zh = "未识别"
        input_type_en = "unknown"
    mode_label_zh = {"query": "查询", "add": "新增", "update": "更新"}.get(m, "查询")
    mode_label_en = {"query": "query", "add": "add", "update": "update"}.get(m, "query")
    recognized_zh = "已识别：模式=" + mode_label_zh + "；输入类型=" + input_type_zh + "；来源类型=" + (f_source_type or "unknown") + "；主题=" + (f_subject or "未提供") + "；路径=" + (f_path or "未提供") + "；文件类型=" + (f_filetype or "未识别") + "。"
    recognized_en = "Recognized: mode=" + mode_label_en + "; input_type=" + input_type_en + "; source_type=" + (f_source_type or "unknown") + "; subject=" + (f_subject or "not provided") + "; path=" + (f_path or "not provided") + "; filetype=" + (f_filetype or "unrecognized") + "."
    if m not in ("query", "add", "update"):
        m = "query"
    if re.search(r"[\u4e00-\u9fff]", txt):
        lang = "zh"

    if lang.startswith("en"):
        if m == "add":
            out = "Home knowledge base add-entry is stubbed, but data source and write policy are not configured yet.\n" + recognized_en + "\nPlease provide: source (path/app/link), write scope, update frequency, reply language."
        elif m == "update":
            out = "Home knowledge base update-entry is stubbed, but data source and write policy are not configured yet.\n" + recognized_en + "\nPlease provide: target document, write scope, update frequency, reply language."
        else:
            out = "Local home knowledge base (RAG) is stubbed but no data source is configured yet.\n" + recognized_en + "\nPlease provide: source (path/app/link), write scope, update frequency, reply language."
    else:
        if m == "add":
            out = "家庭资料库新增入口已预留，但当前未配置数据源与写入权限策略。\n" + recognized_zh + "\n请补充：来源（路径/应用/链接）、写入范围（全局/指定目录）、更新频率、回复语言。"
        elif m == "update":
            out = "家庭资料库更新入口已预留，但当前未配置数据源与写入权限策略。\n" + recognized_zh + "\n请补充：来源（路径/应用/链接）、写入范围（全局/指定目录）、更新频率、回复语言。"
        else:
            out = "本地家庭资料库（RAG）已预留入口，但当前未配置数据源。\n" + recognized_zh + "\n请补充：来源（路径/应用/链接）、写入范围（全局/指定目录）、更新频率、回复语言。"
    out = str(out or "").strip()
    example = _rag_schema_example(m, lang)
    if example:
        out = out + "\n" + example
    if out:
        return out
    return "RAG stub is ready but no data source is configured yet."


def _rag_schema_example(mode: str, language: str) -> str:
    m = str(mode or "query").strip().lower()
    lang = str(language or "").strip().lower()
    if lang.startswith("en"):
        if m == "add":
            return "Example: connect Obsidian=Vault:Home (md), manual updates; permission=append-only."
        if m == "update":
            return "Example: connect Obsidian=Vault:Home (md), manual updates; permission=overwrite."
        return "Example: connect NAS=/mnt/nas/manuals (pdf,md), daily 03:00 incremental updates; permission=read-only."
    if m == "add":
        return "示例：接入 Obsidian=Vault:Home（md），手动更新；可写入。"
    if m == "update":
        return "示例：接入 Obsidian=Vault:Home（md），手动更新；可覆盖。"
    return "示例：接入 NAS=/mnt/nas/manuals（pdf,md），每日 03:00 增量更新；只读。"


def _is_rag_config_intent(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    tl = s.lower()
    keywords = ["接入", "连接", "配置", "绑定", "setup", "connect", "configure"]
    has_kw = False
    for k in keywords:
        if (k in s) or (k in tl):
            has_kw = True
            break
    if not has_kw:
        return False
    return ("=" in s) or (":" in s)


def _rag_parse_config_draft(text: str) -> dict:
    s = str(text or "").strip()
    tl = s.lower()
    connector = "unknown"
    has_obsidian = ("obsidian" in tl) or ("vault:" in tl)
    has_nas = ("nas" in tl) or ("nfs" in tl)
    if has_obsidian:
        connector = "obsidian"
    elif has_nas:
        connector = "nas"
    elif "notion" in tl:
        connector = "notion"
    elif "http://" in tl or "https://" in tl:
        connector = "url"

    def _extract_value_by_markers(raw: str, markers: list) -> str:
        text_raw = str(raw or "")
        text_low = text_raw.lower()
        for mk in markers:
            idx = text_low.find(mk.lower())
            if idx < 0:
                continue
            val = text_raw[idx + len(mk):].strip()
            if not val:
                continue
            for delim in ["，", ";", "；", "。", ",", "\n", "\r", "\t"]:
                d = val.find(delim)
                if d >= 0:
                    val = val[:d].strip()
            if val:
                return val
        return ""

    target = ""
    path_hint = _extract_value_by_markers(s, ["路径=", "path=", "目录=", "dir="])
    if path_hint:
        target = path_hint
    elif "=" in s:
        target = str(s.split("=", 1)[1] or "").strip()
    elif ":" in s:
        target = str(s.split(":", 1)[1] or "").strip()
    target_base, target_extra = _strip_trailing_paren_block(target)
    if target_base:
        target = target_base

    if target:
        for delim in ["，", ";", "；", "。", "."]:
            idx = target.find(delim)
            if idx >= 0:
                target = target[:idx].strip()
                break
    if connector == "obsidian":
        if target.startswith("Vault:") or target.startswith("vault:"):
            target = "/mnt/nas/Obsidian/VaultHome"
        if not target:
            target = "/mnt/nas/Obsidian/VaultHome"

    filetypes = ""
    if ("(" in s and ")" in s) or ("（" in s and "）" in s):
        open_char = "（" if "（" in s else "("
        close_char = "）" if "）" in s else ")"
        start = s.index(open_char) + 1
        end = s.index(close_char, start)
        snippet = s[start:end].strip()
        tokens = [p.strip(" ,，") for p in snippet.replace("，", ",").split(",")]
        allowed = ["pdf", "md", "txt", "docx", "xlsx", "json", "yaml", "yml"]
        picked = [p for p in tokens if p and p.lower() in allowed]
        if picked:
            filetypes = ",".join(picked)
        else:
            filetypes = snippet
    if not filetypes and target_extra:
        tokens = [p.strip(" ,，") for p in target_extra.replace("，", ",").split(",")]
        allowed = ["pdf", "md", "txt", "docx", "xlsx", "json", "yaml", "yml"]
        filtered = [p for p in tokens if p and p.lower() in allowed]
        if filtered:
            filetypes = ",".join(filtered)
        else:
            filetypes = target_extra
    if not filetypes:
        exts = ["pdf", "md", "txt", "docx", "xlsx", "json", "yaml"]
        tokens = tl.split()
        found = []
        for tok in tokens:
            if tok.strip(",;") in exts:
                found.append(tok.strip(",;"))
        if found:
            filetypes = ",".join(found)

    schedule = ""
    if "每日" in s or "daily" in tl:
        schedule = "每日"
    elif "每周" in s or "weekly" in tl:
        schedule = "每周"
    elif "手动" in s or "manual" in tl:
        schedule = "手动"
    elif "03:00" in s:
        schedule = "03:00"

    permission = ""
    perms = ["只读", "可写", "仅追加", "可覆盖"]
    for p in perms:
        if p in s:
            permission = p
            break
    if not permission:
        enl = ["read-only", "write", "append-only", "overwrite"]
        for p in enl:
            if p in tl:
                permission = p
                break

    return {
        "connector": connector,
        "target": target,
        "filetypes": filetypes,
        "schedule": schedule,
        "permission": permission,
    }


def _strip_trailing_paren_block(s: str):
    if not s:
        return "", ""
    trimmed = s.strip()
    if trimmed.endswith(")") and "(" in trimmed:
        idx = trimmed.rfind("(")
        return trimmed[:idx].strip(), trimmed[idx + 1:-1].strip()
    if trimmed.endswith("）") and "（" in trimmed:
        idx = trimmed.rfind("（")
        return trimmed[:idx].strip(), trimmed[idx + 1:-1].strip()
    return trimmed, ""


def _rag_data_dir() -> str:
    try:
        base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = "."
    path = os.path.join(base, "data")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _rag_draft_path() -> str:
    return os.path.join(_rag_data_dir(), "rag_draft.json")


def _rag_sources_path() -> str:
    return os.path.join(_rag_data_dir(), "rag_sources.json")


def _rag_index_db_path() -> str:
    return os.path.join(_rag_data_dir(), "rag_index.sqlite3")


def _rag_db_init(conn):
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, name TEXT, ext TEXT, mtime REAL, size INTEGER)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_name ON files(name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime)")
    cur.execute("CREATE TABLE IF NOT EXISTS doc_text(path TEXT PRIMARY KEY, mtime REAL, text TEXT)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_doc_text_mtime ON doc_text(mtime)")
    conn.commit()


def _rag_db_upsert_file(conn, row: dict):
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO files(path, name, ext, mtime, size) VALUES(?,?,?,?,?)",
        (
            str(row.get("path") or ""),
            str(row.get("name") or ""),
            str(row.get("ext") or ""),
            float(row.get("mtime") or 0.0),
            int(row.get("size") or 0),
        ),
    )


def _rag_db_delete_path(conn, path: str):
    cur = conn.cursor()
    p = str(path or "")
    cur.execute("DELETE FROM files WHERE path=?", (p,))
    cur.execute("DELETE FROM doc_text WHERE path=?", (p,))


def _rag_db_upsert_doc_text(conn, path: str, mtime: float, text: str):
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO doc_text(path, mtime, text) VALUES(?,?,?)",
        (str(path or ""), float(mtime or 0.0), str(text or "")),
    )


def _rag_doc_text_get(conn, path: str):
    cur = conn.cursor()
    cur.execute("SELECT mtime, text FROM doc_text WHERE path=?", (str(path or ""),))
    row = cur.fetchone()
    if not row:
        return None, ""
    old_mtime = float(row[0] or 0.0)
    old_text = str(row[1] or "")
    return old_mtime, old_text


_RAG_TEXT_MAX_BYTES = 524288
_RAG_TEXT_MAX_PAGES = 20
_RAG_TEXT_MAX_CHARS = 200000
_RAG_CONTENT_TOPN = 3
_RAG_CONTENT_CANDIDATES = 200
_RAG_CONTENT_EXTRACT_EXTS = {"md", "txt", "pdf"}


def _rag_extract_plain_text(path: str, ext: str) -> str:
    ext_norm = str(ext or "").strip().lower().lstrip(".")
    try:
        if ext_norm in {"md", "txt"}:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(_RAG_TEXT_MAX_BYTES)
            return str(content or "")
        if ext_norm == "pdf":
            if PdfReader is None:
                return ""
            pieces = []
            total_len = 0
            reader = PdfReader(path)
            for i, page in enumerate(reader.pages):
                if i >= _RAG_TEXT_MAX_PAGES:
                    break
                try:
                    part = page.extract_text() or ""
                except Exception:
                    part = ""
                if not part:
                    continue
                remain = _RAG_TEXT_MAX_CHARS - total_len
                if remain <= 0:
                    break
                if len(part) > remain:
                    part = part[:remain]
                pieces.append(part)
                total_len += len(part)
                if total_len >= _RAG_TEXT_MAX_CHARS:
                    break
            return "\n".join(pieces)
    except Exception:
        return ""
    return ""


def _rag_ensure_doc_text_cache_meta(conn, path: str, ext: str, mtime: float):
    cached_mtime, cached_text = _rag_doc_text_get(conn, path)
    try:
        current_mtime = float(mtime or 0.0)
    except Exception:
        current_mtime = 0.0
    if cached_mtime is not None:
        if abs(float(cached_mtime) - current_mtime) < 0.000001:
            return str(cached_text or ""), "hit"
    text = _rag_extract_plain_text(path, ext)
    try:
        _rag_db_upsert_doc_text(conn, path, current_mtime, text)
    except Exception:
        return "", "error"
    if str(text or "").strip():
        return str(text or ""), "updated"
    return str(text or ""), "empty"


def _rag_ensure_doc_text_cache(conn, path: str, ext: str, mtime: float) -> str:
    text, _status = _rag_ensure_doc_text_cache_meta(conn, path, ext, mtime)
    return str(text or "")


def _rag_content_exts_from_sources() -> list:
    sources = _rag_load_json(_rag_sources_path(), {})
    allowed = []
    if isinstance(sources, dict):
        for src in sources.values():
            if not isinstance(src, dict):
                continue
            filetypes = str(src.get("filetypes") or "").strip().lower()
            if not filetypes:
                continue
            for item in filetypes.replace(";", ",").split(","):
                ext = str(item or "").strip().lower().lstrip(".")
                if ext in _RAG_CONTENT_EXTRACT_EXTS and ext not in allowed:
                    allowed.append(ext)
    if allowed:
        return allowed
    return ["pdf", "md", "txt"]


def _is_rag_content_query_intent(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    keys = ["搜内容", "内容搜索", "搜索内容", "在家庭资料库里搜内容"]
    for k in keys:
        if k in s:
            return True
    return False


def _rag_extract_prewarm_target(text: str) -> tuple[str, str]:
    s = str(text or "").strip()
    if not s:
        return "", ""
    folder, base_text = _rag_extract_folder_hint(s)
    t = str(base_text or s).strip()
    if "预热数据源" in t:
        t = t.split("预热数据源", 1)[1].strip()
    elif "预热" in t:
        t = t.split("预热", 1)[1].strip()
    t = t.replace("：", " ").replace(":", " ").strip(" ，。,.!?！？")
    parts = [p for p in t.split() if p]
    name = parts[0] if parts else ""
    return name, folder


def _is_rag_prewarm_intent(text: str):
    s = str(text or "").strip()
    if not s:
        return False, "", ""
    if ("预热数据源" not in s) and ("预热" not in s):
        return False, "", ""
    name, folder = _rag_extract_prewarm_target(s)
    return True, name, folder


def _rag_parse_limit_env(name: str, default_val: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default_val
    try:
        val = int(raw)
    except Exception:
        return default_val
    if val < 1:
        return default_val
    if val > 1000:
        return 1000
    return val


def _rag_source_allowed_exts(source: dict) -> list:
    filetypes = str((source or {}).get("filetypes") or "").strip().lower()
    allow_exts = []
    if filetypes:
        for item in filetypes.replace(";", ",").split(","):
            ext = str(item or "").strip().lower().lstrip(".")
            if ext in _RAG_CONTENT_EXTRACT_EXTS and ext not in allow_exts:
                allow_exts.append(ext)
    if allow_exts:
        return allow_exts
    return ["pdf", "md", "txt"]


def _rag_obsidian_base_path_from_sources() -> str:
    sources = _rag_load_json(_rag_sources_path(), {})
    if isinstance(sources, dict):
        info = sources.get("obsidian")
        if isinstance(info, dict):
            target = str(info.get("target") or "").strip()
            if target:
                return target
    return "/mnt/nas/Obsidian/VaultHome"


def _rag_obsidian_allowed_dirs(base_path: str):
    base = str(base_path or "").strip()
    if not base:
        base = "/mnt/nas/Obsidian/VaultHome"
    return [
        os.path.abspath(os.path.join(base, "Inbox")),
        os.path.abspath(os.path.join(base, "Notes")),
    ]


def _rag_is_path_under(path: str, base_dir: str) -> bool:
    try:
        p = os.path.abspath(str(path or ""))
        b = os.path.abspath(str(base_dir or ""))
        return (p == b) or p.startswith(b + os.sep)
    except Exception:
        return False


def _rag_obsidian_safe_filename_seed(s: str) -> str:
    t = str(s or "").strip().lower()
    t = re.sub(r"[\s\r\n\t]+", "_", t)
    t = re.sub(r"[^a-z0-9_]+", "_", t)
    t = re.sub(r"_+", "_", t).strip("_")
    if not t:
        t = "note"
    if len(t) > 32:
        t = t[:32].rstrip("_")
    return t or "note"


def _rag_obsidian_pick_target_dir(base_path: str, target_hint: str = "") -> str:
    dirs = _rag_obsidian_allowed_dirs(base_path)
    if target_hint:
        hint = str(target_hint or "").strip().lower()
        if "note" in hint:
            return dirs[1]
        if "inbox" in hint:
            return dirs[0]
    return dirs[0]


def _rag_obsidian_relpath(path: str, base_path: str) -> str:
    p = os.path.abspath(str(path or ""))
    b = os.path.abspath(str(base_path or ""))
    try:
        rel = os.path.relpath(p, b)
    except Exception:
        rel = os.path.basename(p)
    return rel.replace("\\", "/")


def _rag_obsidian_index_upsert_md(path: str):
    full = os.path.abspath(str(path or ""))
    if (not full) or (not os.path.exists(full)) or (not os.path.isfile(full)):
        return
    try:
        st = os.stat(full)
    except Exception:
        return
    text = ""
    try:
        with open(full, "r", encoding="utf-8", errors="ignore") as f:
            text = str(f.read(_RAG_TEXT_MAX_BYTES) or "")
    except Exception:
        text = ""
    try:
        conn = sqlite3.connect(_rag_index_db_path())
        _rag_db_init(conn)
        _rag_db_upsert_file(
            conn,
            {
                "path": full,
                "name": os.path.basename(full),
                "ext": "md",
                "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                "size": int(getattr(st, "st_size", 0) or 0),
            },
        )
        _rag_db_upsert_doc_text(conn, full, float(getattr(st, "st_mtime", 0.0) or 0.0), text)
        conn.commit()
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _rag_obsidian_index_delete(path: str):
    full = os.path.abspath(str(path or ""))
    if not full:
        return
    try:
        conn = sqlite3.connect(_rag_index_db_path())
        _rag_db_init(conn)
        _rag_db_delete_path(conn, full)
        conn.commit()
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _rag_obsidian_find_md_candidates(base_path: str, keyword: str):
    kw = str(keyword or "").strip().lower()
    if not kw:
        return []
    out = []
    for d in _rag_obsidian_allowed_dirs(base_path):
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if x not in [".git", "__pycache__"]]
            for fn in files:
                if not fn.lower().endswith(".md"):
                    continue
                if kw not in fn.lower():
                    continue
                out.append(os.path.join(root, fn))
                if len(out) >= 50:
                    return out
    return out


def _rag_obsidian_extract_add_text(text: str) -> str:
    s = str(text or "").strip()
    for mk in ["加入家庭知识库：", "加入家庭知识库:", "写入家庭知识库：", "写入家庭知识库:"]:
        if mk in s:
            return str(s.split(mk, 1)[1] or "").strip()
    if "：" in s:
        return str(s.split("：", 1)[1] or "").strip()
    if ":" in s:
        return str(s.split(":", 1)[1] or "").strip()
    return ""


def _rag_obsidian_add_intent(text: str) -> bool:
    s = str(text or "").strip()
    return ("家庭知识库" in s) and (("加入" in s) or ("写入" in s)) and (("：" in s) or (":" in s))


def _rag_obsidian_update_intent(text: str) -> bool:
    s = str(text or "").strip()
    return ("更新知识库里" in s) and (("：" in s) or (":" in s))


def _rag_obsidian_delete_intent(text: str) -> bool:
    s = str(text or "").strip()
    return "删除知识库条目" in s


def _rag_obsidian_build_add_draft(text: str, language: str):
    body = _rag_obsidian_extract_add_text(text)
    if not body:
        return {"final": "请在冒号后提供要写入的内容。"}
    base = _rag_obsidian_base_path_from_sources()
    target_dir = _rag_obsidian_pick_target_dir(base, "inbox")
    draft = {
        "draft_type": "obsidian_add",
        "connector": "obsidian",
        "target": base,
        "target_dir": target_dir,
        "content": body,
    }
    _rag_save_json_atomic(_rag_draft_path(), draft)
    return {"final": "已识别=新增；写入=Vault:Home/Inbox；草案已保存（未应用）。"}


def _rag_obsidian_parse_update_payload(text: str):
    s = str(text or "").strip()
    left = s
    right = ""
    if "：" in s:
        left, right = s.split("：", 1)
    elif ":" in s:
        left, right = s.split(":", 1)
    kw = ""
    if "更新知识库里" in left:
        kw = str(left.split("更新知识库里", 1)[1] or "").strip()
    return kw.strip(), str(right or "").strip()


def _rag_obsidian_build_update_draft(text: str, language: str):
    kw, payload = _rag_obsidian_parse_update_payload(text)
    if (not kw) or (not payload):
        return {"final": "请按“更新知识库里 <关键词>：<内容>”输入。"}
    base = _rag_obsidian_base_path_from_sources()
    cands = _rag_obsidian_find_md_candidates(base, kw)
    if not cands:
        return {"final": "没找到与“" + kw + "”匹配的条目。"}
    if len(cands) > 1:
        lines = ["匹配到多个条目，请明确目标："]
        for p in cands[:3]:
            lines.append("- " + _rag_obsidian_relpath(p, base))
        return {"final": "\n".join(lines)}
    full = os.path.abspath(cands[0])
    draft = {
        "draft_type": "obsidian_update",
        "connector": "obsidian",
        "target": base,
        "full_path": full,
        "keyword": kw,
        "update_text": payload,
    }
    _rag_save_json_atomic(_rag_draft_path(), draft)
    return {"final": "已识别=更新；目标=" + _rag_obsidian_relpath(full, base) + "；草案已保存（未应用）。"}


def _rag_obsidian_build_delete_draft(text: str, language: str):
    s = str(text or "").strip()
    kw = ""
    if "删除知识库条目" in s:
        kw = str(s.split("删除知识库条目", 1)[1] or "").strip()
    kw = kw.strip(" ，。,.!?！？")
    if not kw:
        return {"final": "请按“删除知识库条目 <关键词>”输入。"}
    base = _rag_obsidian_base_path_from_sources()
    cands = _rag_obsidian_find_md_candidates(base, kw)
    if not cands:
        return {"final": "没找到与“" + kw + "”匹配的条目。"}
    if len(cands) > 1:
        lines = ["匹配到多个条目，请明确目标："]
        for p in cands[:3]:
            lines.append("- " + _rag_obsidian_relpath(p, base))
        return {"final": "\n".join(lines)}
    full = os.path.abspath(cands[0])
    draft = {
        "draft_type": "obsidian_delete",
        "connector": "obsidian",
        "target": base,
        "full_path": full,
        "keyword": kw,
    }
    _rag_save_json_atomic(_rag_draft_path(), draft)
    return {"final": "已识别=删除；目标=" + _rag_obsidian_relpath(full, base) + "；草案已保存（未应用）。"}


def _rag_obsidian_apply_draft(draft: dict, language: str):
    base = str(draft.get("target") or _rag_obsidian_base_path_from_sources()).strip()
    if not base:
        base = "/mnt/nas/Obsidian/VaultHome"
    dtyp = str(draft.get("draft_type") or "").strip().lower()
    allowed_dirs = _rag_obsidian_allowed_dirs(base)
    if dtyp == "obsidian_add":
        target_dir = str(draft.get("target_dir") or "").strip()
        if not target_dir:
            target_dir = allowed_dirs[0]
        target_dir = os.path.abspath(target_dir)
        ok_dir = False
        for d in allowed_dirs:
            if _rag_is_path_under(target_dir, d):
                ok_dir = True
                break
        if not ok_dir:
            target_dir = allowed_dirs[0]
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            return {"final": "应用失败：无法创建目标目录。"}
        body = str(draft.get("content") or "").strip()
        if not body:
            return {"final": "应用失败：草案内容为空。"}
        first = str(body.splitlines()[0] if body.splitlines() else body).strip()
        if not first:
            first = body[:20].strip()
        if len(first) > 20:
            first = first[:20].rstrip()
        slug = _rag_obsidian_safe_filename_seed(first)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        filename = ts + "_" + slug + ".md"
        full = os.path.abspath(os.path.join(target_dir, filename))
        idx = 2
        while os.path.exists(full):
            filename = ts + "_" + slug + "_" + str(idx) + ".md"
            full = os.path.abspath(os.path.join(target_dir, filename))
            idx += 1
            if idx > 99:
                break
        content = "# " + (first or "笔记") + "\n\n" + body + "\n"
        try:
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            return {"final": "应用失败：写入文件失败。"}
        _rag_obsidian_index_upsert_md(full)
        return {"final": "已写入：" + _rag_obsidian_relpath(full, base)}
    if dtyp == "obsidian_update":
        full = os.path.abspath(str(draft.get("full_path") or "").strip())
        if not full:
            return {"final": "应用失败：缺少目标文件。"}
        allowed = False
        for d in allowed_dirs:
            if _rag_is_path_under(full, d):
                allowed = True
                break
        if (not allowed) or (".." in full):
            return {"final": "应用失败：目标不在允许目录。"}
        if not os.path.exists(full):
            return {"final": "应用失败：目标文件不存在。"}
        upd = str(draft.get("update_text") or "").strip()
        if not upd:
            return {"final": "应用失败：更新内容为空。"}
        stamp = datetime.now().strftime("%Y-%m-%d")
        block = "\n\n## " + stamp + "\n" + upd + "\n"
        try:
            with open(full, "a", encoding="utf-8") as f:
                f.write(block)
        except Exception:
            return {"final": "应用失败：更新写入失败。"}
        _rag_obsidian_index_upsert_md(full)
        return {"final": "已更新：" + _rag_obsidian_relpath(full, base)}
    if dtyp == "obsidian_delete":
        full = os.path.abspath(str(draft.get("full_path") or "").strip())
        if not full:
            return {"final": "应用失败：缺少目标文件。"}
        allowed = False
        for d in allowed_dirs:
            if _rag_is_path_under(full, d):
                allowed = True
                break
        if (not allowed) or (".." in full):
            return {"final": "应用失败：目标不在允许目录。"}
        if not os.path.exists(full):
            return {"final": "应用失败：目标文件不存在。"}
        try:
            os.remove(full)
        except Exception:
            return {"final": "应用失败：删除文件失败。"}
        _rag_obsidian_index_delete(full)
        return {"final": "已删除：" + _rag_obsidian_relpath(full, base)}
    return {"final": "暂不支持的草案类型。"}


def _rag_prewarm_source(name: str, language: str, folder: str = "") -> dict:
    lang = str(language or "").lower()
    sources = _rag_load_json(_rag_sources_path(), {})
    if not isinstance(sources, dict) or (not sources):
        msg = "暂无已保存的数据源。" if not lang.startswith("en") else "No saved sources yet."
        return {"final": msg}
    if not name:
        available = ", ".join(sorted(sources.keys()))
        msg = "请指定要预热的数据源名称。当前可用：" + (available or "无") + "。"
        if lang.startswith("en"):
            msg = "Specify the data source name to prewarm. Available: " + (available or "none")
        return {"final": msg}
    source = sources.get(name)
    if not source:
        available = ", ".join(sorted(sources.keys()))
        msg = "未找到数据源：" + name + "。当前可用：" + (available or "无") + "。"
        if lang.startswith("en"):
            msg = "Data source not found: " + name + ". Available: " + (available or "none")
        return {"final": msg}
    db_path = _rag_index_db_path()
    if not os.path.exists(db_path):
        return {"final": "索引尚未建立，请先同步数据源。"}

    folder = _map_folder_alias(folder)
    folder_like = ""
    if folder:
        folder_like = "%/" + folder.strip("/\\").lower() + "/%"
    allow_exts = _rag_source_allowed_exts(source)
    placeholders = ",".join(["?"] * len(allow_exts))
    sql = (
        "SELECT path, ext, mtime "
        "FROM files "
        "WHERE lower(ext) IN (" + placeholders + ")"
    )
    params = list(allow_exts)
    if folder_like:
        sql = sql + " AND lower(path) LIKE lower(?)"
        params.append(folder_like)
    limit_val = _rag_parse_limit_env("RAG_PREWARM_LIMIT", 200)
    sql = sql + " ORDER BY mtime DESC LIMIT ?"
    params.append(limit_val)

    processed = 0
    updated = 0
    hit = 0
    empty = 0
    error = 0
    started = datetime.now().timestamp()

    try:
        conn = sqlite3.connect(db_path)
        _rag_db_init(conn)
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        for row in rows:
            path = str(row[0] or "")
            ext = str(row[1] or "").strip().lower()
            mtime = float(row[2] or 0.0)
            _text, status = _rag_ensure_doc_text_cache_meta(conn, path, ext, mtime)
            processed += 1
            if status == "hit":
                hit += 1
            elif status == "updated":
                updated += 1
            elif status == "empty":
                updated += 1
                empty += 1
            else:
                error += 1
        conn.commit()
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return {"final": "预热失败：无法访问索引或文件内容。"}

    elapsed = round(max(0.0, datetime.now().timestamp() - started), 2)
    if folder:
        final = (
            name
            + " 预热完成（限定目录："
            + folder
            + "）：处理="
            + str(processed)
            + "；新增/更新="
            + str(updated)
            + "；命中缓存="
            + str(hit)
            + "；空内容="
            + str(empty)
            + "；失败="
            + str(error)
            + "；用时="
            + str(elapsed)
            + "s。"
        )
    else:
        final = (
            name
            + " 预热完成：处理="
            + str(processed)
            + "；新增/更新="
            + str(updated)
            + "；命中缓存="
            + str(hit)
            + "；空内容="
            + str(empty)
            + "；失败="
            + str(error)
            + "；用时="
            + str(elapsed)
            + "s。"
        )
    return {"final": final}


def _rag_extract_content_query(text: str) -> tuple[str, str]:
    s = str(text or "").strip()
    if not s:
        return "", ""
    folder, base_text = _rag_extract_folder_hint(s)
    t = base_text or s
    for k in [
        "在家庭资料库里搜内容",
        "家庭资料库里搜内容",
        "在资料库里搜内容",
        "资料库里搜内容",
        "在家庭资料库里搜索内容",
        "在资料库里搜索内容",
        "搜内容",
        "内容搜索",
        "搜索内容",
    ]:
        t = t.replace(k, " ")
    tl = t.lower()
    en_wrappers = [
        "search home knowledge for",
        "search home knowledge",
        "search knowledge base for",
        "search knowledge base",
        "search in home knowledge",
        "lookup home knowledge for",
        "lookup home knowledge",
    ]
    for k in en_wrappers:
        if k in tl:
            idx = tl.find(k)
            t = (t[:idx] + " " + t[idx + len(k):]).strip()
            tl = t.lower()
    t = t.replace("：", " ").replace(":", " ").strip(" ，。,.!?！？")
    kw = " ".join([p for p in t.split() if p]).strip()
    return kw, folder


def _rag_make_content_snippet(text: str, pos: int, key_len: int) -> str:
    body = str(text or "")
    if not body:
        return ""
    start = max(0, int(pos) - 60)
    end = min(len(body), int(pos) + int(key_len) + 60)
    if end <= start:
        return ""
    piece = body[start:end]
    piece = re.sub(r"\s+", " ", piece).strip()
    if len(piece) > 160:
        piece = piece[:160].rstrip()
    return piece


def _rag_rel_path_for_display(path: str) -> str:
    display = str(path or "")
    prefix = "/mnt/nas/"
    if display.startswith(prefix):
        display = display[len(prefix):]
    return display


def _rag_unique_keep_order(items: list) -> list:
    out = []
    seen = set()
    for it in items:
        key = str(it or "").strip()
        if not key:
            continue
        lk = key.lower()
        if lk in seen:
            continue
        seen.add(lk)
        out.append(key)
    return out


def _rag_parse_content_terms(query: str):
    raw = str(query or "").strip()
    if not raw:
        return {"must_terms": [], "any_terms": [], "phrases": []}
    phrases = []
    try:
        for m in re.finditer(r"\"([^\"]+)\"", raw):
            p = str((m.group(1) or "")).strip()
            if p:
                phrases.append(p)
    except Exception:
        phrases = []
    work = re.sub(r"\"[^\"]+\"", " ", raw)
    work = work.replace("|", " OR ").replace("或", " OR ")
    work = re.sub(r"[，。,.!?！？;；:：()\[\]{}<>《》]", " ", work)
    tokens = [t.strip() for t in work.split() if t.strip()]
    has_or = False
    for t in tokens:
        if t.lower() == "or":
            has_or = True
            break
    must_terms = []
    any_terms = []
    if has_or:
        for t in tokens:
            if t.lower() == "or":
                continue
            any_terms.append(t)
    else:
        must_terms = tokens
    must_terms = _rag_unique_keep_order(must_terms)
    any_terms = _rag_unique_keep_order(any_terms)
    phrases = _rag_unique_keep_order(phrases)
    return {"must_terms": must_terms, "any_terms": any_terms, "phrases": phrases}


def _rag_content_match(text_lower: str, terms: dict) -> bool:
    must_terms = terms.get("must_terms") or []
    any_terms = terms.get("any_terms") or []
    phrases = terms.get("phrases") or []
    for p in phrases:
        if str(p).lower() not in text_lower:
            return False
    for t in must_terms:
        if str(t).lower() not in text_lower:
            return False
    if any_terms:
        ok = False
        for t in any_terms:
            if str(t).lower() in text_lower:
                ok = True
                break
        if not ok:
            return False
    return True


def _rag_content_total_hits(text_lower: str, terms: dict) -> int:
    total = 0
    merged = []
    merged.extend(terms.get("phrases") or [])
    merged.extend(terms.get("must_terms") or [])
    merged.extend(terms.get("any_terms") or [])
    for t in _rag_unique_keep_order(merged):
        tl = str(t).lower()
        if not tl:
            continue
        try:
            total += int(text_lower.count(tl))
        except Exception:
            continue
    return total


def _rag_collect_snippets(text: str, text_lower: str, terms: dict, max_items: int = 2) -> list:
    hits = []
    merged = []
    merged.extend(terms.get("phrases") or [])
    merged.extend(terms.get("must_terms") or [])
    merged.extend(terms.get("any_terms") or [])
    for t in _rag_unique_keep_order(merged):
        tl = str(t).lower()
        if not tl:
            continue
        pos = text_lower.find(tl)
        if pos >= 0:
            hits.append((pos, len(tl)))
    hits.sort(key=lambda x: int(x[0]))
    selected = []
    for pos, size in hits:
        keep = True
        for old_pos, _old_size in selected:
            if abs(int(pos) - int(old_pos)) < 30:
                keep = False
                break
        if keep:
            selected.append((pos, size))
        if len(selected) >= int(max_items):
            break
    out = []
    for pos, size in selected:
        snip = _rag_make_content_snippet(text, pos, size)
        if snip:
            out.append(snip)
    return out


def _rag_search_content(keyword: str, language: str, folder: str = "") -> str:
    raw_query = str(keyword or "").strip()
    if not raw_query:
        return "请补充要搜索的内容关键词。"
    parsed_terms = _rag_parse_content_terms(raw_query)
    if (not parsed_terms.get("must_terms")) and (not parsed_terms.get("any_terms")) and (not parsed_terms.get("phrases")):
        return "请补充要搜索的内容关键词。"
    db_path = _rag_index_db_path()
    if not os.path.exists(db_path):
        return "索引尚未建立，请先同步数据源。"
    folder = _map_folder_alias(folder)
    folder_like = ""
    if folder:
        folder_like = "%/" + folder.strip("/\\").lower() + "/%"
    exts = _rag_content_exts_from_sources()
    placeholders = ",".join(["?"] * len(exts))
    sql = (
        "SELECT path, name, ext, mtime "
        "FROM files "
        "WHERE lower(ext) IN (" + placeholders + ")"
    )
    params = list(exts)
    if folder_like:
        sql = sql + " AND lower(path) LIKE lower(?)"
        params.append(folder_like)
    sql = sql + " ORDER BY mtime DESC LIMIT ?"
    params.append(int(_RAG_CONTENT_CANDIDATES))

    matches = []
    topn = _rag_parse_limit_env("RAG_SEARCH_TOPN", 3)
    if topn > 10:
        topn = 10
    try:
        conn = sqlite3.connect(db_path)
        _rag_db_init(conn)
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        candidates = []
        for row in rows:
            path = str(row[0] or "")
            name = str(row[1] or "")
            ext = str(row[2] or "").strip().lower()
            mtime = float(row[3] or 0.0)
            name_low = name.lower()
            terms_for_name = []
            terms_for_name.extend(parsed_terms.get("phrases") or [])
            terms_for_name.extend(parsed_terms.get("must_terms") or [])
            terms_for_name.extend(parsed_terms.get("any_terms") or [])
            pre_score = 0
            for t in _rag_unique_keep_order(terms_for_name):
                tl = str(t).lower()
                if tl and (tl in name_low):
                    pre_score += 50
            candidates.append({
                "path": path,
                "name": name,
                "ext": ext,
                "mtime": mtime,
                "pre_score": pre_score,
            })

        candidates.sort(key=lambda x: (int(x.get("pre_score") or 0), float(x.get("mtime") or 0.0)), reverse=True)
        top_candidates = candidates[:30]

        for item in top_candidates:
            path = str(item.get("path") or "")
            ext = str(item.get("ext") or "").strip().lower()
            mtime = float(item.get("mtime") or 0.0)
            pre_score = int(item.get("pre_score") or 0)
            text = _rag_ensure_doc_text_cache(conn, path, ext, mtime)
            text_low = text.lower() if text else ""
            if not text_low:
                continue
            if not _rag_content_match(text_low, parsed_terms):
                continue
            total_hits = _rag_content_total_hits(text_low, parsed_terms)
            score = pre_score + (min(total_hits, 50) * 2)
            snippets = _rag_collect_snippets(text, text_low, parsed_terms, 2)
            matches.append({"path": path, "mtime": mtime, "snippets": snippets, "score": score})
        conn.commit()
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return "资料库内容搜索失败，请稍后重试。"

    if not matches:
        if folder:
            return "资料库检索完成：当前目录「" + folder + "」里暂未检索到与「" + raw_query + "」匹配的内容。"
        return "资料库检索完成：暂未检索到与「" + raw_query + "」匹配的内容。"
    matches.sort(key=lambda x: (int(x.get("score") or 0), float(x.get("mtime") or 0.0)), reverse=True)
    if folder:
        title = "内容命中「" + raw_query + "」的文件（限定目录：" + folder + "）："
    else:
        title = "内容命中「" + raw_query + "」的文件："
    lines = [title]
    for item in matches[:topn]:
        path = str(item.get("path") or "")
        mtime = float(item.get("mtime") or 0.0)
        snippets = item.get("snippets") or []
        day = ""
        try:
            day = datetime.fromtimestamp(float(mtime or 0.0)).strftime("%Y-%m-%d")
        except Exception:
            day = ""
        line = "- " + _rag_rel_path_for_display(path)
        if day:
            line = line + " （" + day + "）"
        lines.append(line)
        for snip in snippets[:2]:
            sn = str(snip or "").strip()
            if sn:
                lines.append("  * " + sn)
    return "\n".join(lines)


def _rag_load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _rag_save_json_atomic(path: str, obj):
    dirpath = os.path.dirname(path)
    try:
        os.makedirs(dirpath, exist_ok=True)
    except Exception:
        pass
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _rag_list_intent(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return False
    for k in ["列出资料库数据源", "数据源列表", "知识库数据源", "查看数据源列表", "list data sources"]:
        if k in s:
            return True
    return False


def _rag_apply_intent(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return False
    for k in ["应用刚才的草案", "保存这个配置", "应用配置", "apply configuration", "apply draft", "save configuration"]:
        if k in s:
            return True
    return False


def _is_rag_sync_intent(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return False
    keys = ["同步", "刷新", "更新索引", "build index", "reindex"]
    for k in keys:
        if k in s:
            return True
    return False


def _is_rag_query_intent(text: str) -> bool:
    s = str(text or "").strip()
    tl = s.lower()
    if not s:
        return False
    has_scope = ("家庭资料库" in s) or ("资料库" in s) or ("知识库" in s)
    has_query = ("找" in s) or ("搜索" in s) or ("查找" in s) or ("在哪里" in s) or ("在哪儿" in s)
    if has_scope and has_query:
        return True
    if ("rag" in tl) and has_query:
        return True
    return False


FOLDER_ALIASES = {
    "warranties": ["warranty", "保修", "质保", "保固"],
    "manuals": ["manual", "手册", "说明书", "指南"],
    "receipts": ["receipt", "发票", "收据", "小票"],
    "contracts": ["contract", "合同"],
}


def _map_folder_alias(name: str) -> str:
    if not name:
        return name
    candidate = str(name or "").strip().strip("/\\").lower()
    if not candidate:
        return name
    while candidate and (candidate[-1] in " ，。,.!?！？;；:："):
        candidate = candidate[:-1].strip()
    if candidate.endswith("里") or candidate.endswith("中") or candidate.endswith("下"):
        candidate = candidate[:-1].strip()
    candidate = candidate.strip("/\\")
    if not candidate:
        return ""
    for canonical, aliases in FOLDER_ALIASES.items():
        if candidate == canonical:
            return canonical
        for alias in aliases:
            alias_norm = str(alias or "").strip().strip("/\\").lower()
            if candidate == alias_norm:
                return canonical
    # Optional fallback: allow Chinese alias containment while keeping English strict.
    for canonical, aliases in FOLDER_ALIASES.items():
        for alias in aliases:
            alias_norm = str(alias or "").strip().strip("/\\").lower()
            if (not alias_norm) or re.search(r"[a-z0-9]", alias_norm):
                continue
            if alias_norm in candidate:
                return canonical
    tokens = [tok for tok in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", candidate) if tok]
    if tokens:
        for canonical, aliases in FOLDER_ALIASES.items():
            if canonical in tokens:
                return canonical
            for alias in aliases:
                alias_norm = str(alias or "").strip().strip("/\\").lower()
                if alias_norm in tokens:
                    return canonical
    return name


def _rag_extract_folder_hint(text: str) -> tuple[str, str]:
    s = str(text or "").strip()
    if not s:
        return "", ""

    def _trim_tail_punct(v: str) -> str:
        out = str(v or "").strip()
        while out and (out[-1] in " ，。,.!?！？;；:："):
            out = out[:-1].strip()
        return out

    def _normalize_folder(v: str, pick_last: bool = False) -> str:
        folder = _trim_tail_punct(v).strip().strip("/\\").lower()
        if folder.endswith("里") or folder.endswith("中") or folder.endswith("下"):
            folder = folder[:-1].strip()
        if folder:
            parts = [p for p in folder.split() if p]
            if parts:
                if pick_last:
                    folder = parts[-1]
                else:
                    folder = parts[0]
            folder = folder.strip().strip("/\\").lower()
        return folder

    sl = s.lower()
    li = sl.rfind("里")
    if li != -1:
        tail = _trim_tail_punct(s[li + 1:])
        if not tail:
            zai = sl.rfind("在", 0, li)
            if zai != -1 and li > zai + 1:
                folder = _normalize_folder(s[zai + 1:li], True)
                if folder:
                    folder = _map_folder_alias(folder)
                    return folder, _trim_tail_punct(s[:zai])

    for mk in ["只在", "限定"]:
        idx = sl.rfind(mk)
        if idx != -1:
            part = _trim_tail_punct(s[idx + len(mk):].strip())
            if part:
                folder = _normalize_folder(part.split()[0])
                if folder:
                    base_text = _trim_tail_punct(s[:idx])
                    if not base_text:
                        base_text = s
                    folder = _map_folder_alias(folder)
                    return folder, base_text
    return "", s


def _rag_extract_query_keyword(text: str) -> tuple[str, str]:
    s = str(text or "").strip()
    if not s:
        return "", ""
    folder, base_text = _rag_extract_folder_hint(s)
    t = base_text or s
    for k in ["在家庭资料库里", "家庭资料库里", "在资料库里", "资料库里", "在知识库里", "知识库里"]:
        t = t.replace(k, " ")
    if "找" in t:
        t = t.split("找", 1)[1]
    for k in ["搜索", "查找", "在哪里", "在哪儿", "在哪"]:
        t = t.replace(k, " ")
    t = t.replace("：", " ").replace(":", " ").strip(" ，。,.!?！？")
    parts = [p for p in t.split() if p]
    kw = parts[0] if parts else ""
    return kw, folder


def _rag_search_index(keyword: str, language: str, folder: str = "") -> str:
    kw = str(keyword or "").strip()
    if not kw:
        return "请补充要查找的关键词。"
    db_path = _rag_index_db_path()
    if not os.path.exists(db_path):
        return "索引尚未建立，请先同步数据源。"
    try:
        conn = sqlite3.connect(db_path)
        _rag_db_init(conn)
        cur = conn.cursor()
        like_q = "%" + kw + "%"
        folder = _map_folder_alias(folder)
        if folder:
            folder_norm = folder.strip("/\\ ").lower()
            folder_like = "%/" + folder_norm + "/%"
            query = (
                "SELECT path, name, mtime "
                "FROM files "
                "WHERE (name LIKE ? OR path LIKE ?) AND lower(path) LIKE lower(?) "
                "ORDER BY "
                "  CASE "
                "    WHEN lower(name) LIKE lower(?) THEN 2 "
                "    WHEN lower(path) LIKE lower(?) THEN 1 "
                "    ELSE 0 "
                "  END DESC, "
                "  mtime DESC "
                "LIMIT 3"
            )
            params = [like_q, like_q, folder_like, like_q, like_q]
        else:
            query = (
                "SELECT path, name, mtime "
                "FROM files "
                "WHERE name LIKE ? OR path LIKE ? "
                "ORDER BY "
                "  CASE "
                "    WHEN lower(name) LIKE lower(?) THEN 2 "
                "    WHEN lower(path) LIKE lower(?) THEN 1 "
                "    ELSE 0 "
                "  END DESC, "
                "  mtime DESC "
                "LIMIT 3"
            )
            params = [like_q, like_q, like_q, like_q]
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return "查询索引失败，请稍后重试。"
    if not rows:
        if folder:
            return "没找到与「" + kw + "」相关的文件（限定目录：" + folder + "）。"
        return "没找到与「" + kw + "」相关的文件。"
    if folder:
        title = "找到与「" + kw + "」相关的文件（限定目录：" + folder + "）："
    else:
        title = "找到与「" + kw + "」相关的文件："
    lines = [title]
    for r in rows:
        path = str(r[0] or "")
        display = path
        prefix = "/mnt/nas/"
        if display.startswith(prefix):
            display = display[len(prefix):]
        mtime = ""
        try:
            ts = float(r[2] or 0.0)
            dt = datetime.fromtimestamp(ts)
            mtime = dt.strftime("%Y-%m-%d")
        except Exception:
            mtime = ""
        line = "- " + display
        if mtime:
            line = line + " （" + mtime + "）"
        lines.append(line)
    return "\n".join(lines)


def _rag_extract_name(text: str, keywords: list) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    tl = s.lower()
    for kw in keywords:
        if kw in tl:
            idx = tl.index(kw)
            after = s[idx + len(kw):].strip()
            if after:
                parts = after.split()
                if parts:
                    return parts[0]
    return ""


def _rag_show_name(text: str) -> str:
    return _rag_extract_name(text, ["查看资料库配置", "显示资料库配置", "查看数据源", "show data source", "show configuration"])


def _rag_delete_name(text: str) -> str:
    return _rag_extract_name(text, ["删除资料库数据源", "移除数据源", "删除数据源", "remove data source"])


def _rag_sources_list_text(language: str):
    lang = str(language or "").strip().lower()
    sources = _rag_load_json(_rag_sources_path(), {})
    if not isinstance(sources, dict) or (not sources):
        return {"final": ("暂无已保存的数据源。" if not lang.startswith("en") else "No saved sources yet.")}
    lines = []
    for name in sorted(sources.keys()):
        info = sources.get(name) or {}
        target = str(info.get("target") or "未指定")
        filetypes = str(info.get("filetypes") or "未指定")
        permission = str(info.get("permission") or "未指定")
        schedule = str(info.get("schedule") or "未指定")
        lines.append("- " + name + ": " + target + " (" + filetypes + ") 权限=" + permission + " 更新=" + schedule)
    final = "\n".join(lines)
    return {"final": final}


def _rag_show_text(name: str, language: str):
    lang = str(language or "").strip().lower()
    if not name:
        hint = "请加上要查看的名称，例如 “查看资料库配置 nas”。" if not lang.startswith("en") else "Provide the name to show, e.g. “show data source nas”."
        return {"final": hint}
    sources = _rag_load_json(_rag_sources_path(), {})
    if not isinstance(sources, dict) or (not sources):
        return {"final": ("暂无已保存的数据源。" if not lang.startswith("en") else "No saved sources yet.")}
    info = sources.get(name)
    if not info:
        available = ", ".join(sorted(sources.keys()))
        msg = ("当前可用：" + available + "。" if available else "暂无可用名称。")
        if lang.startswith("en"):
            msg = "Available names: " + (available or "none")
        return {"final": msg}
    target = str(info.get("target") or "未指定")
    filetypes = str(info.get("filetypes") or "未指定")
    permission = str(info.get("permission") or "未指定")
    schedule = str(info.get("schedule") or "未指定")
    final = name + ": " + target + " (" + filetypes + ") 权限=" + permission + " 更新=" + schedule
    return {"final": final}


def _rag_delete_text(name: str, language: str):
    lang = str(language or "").strip().lower()
    if not name:
        hint = "请说明要删除的数据源名称，例如 “删除资料库数据源 nas”。" if not lang.startswith("en") else "Provide the source name to delete, e.g. “delete data source nas”."
        return {"final": hint}
    sources = _rag_load_json(_rag_sources_path(), {})
    if not isinstance(sources, dict) or (not sources):
        return {"final": ("暂无已保存的数据源。" if not lang.startswith("en") else "No saved sources yet.")}
    if name not in sources:
        available = ", ".join(sorted(sources.keys()))
        msg = ("当前可用：" + available + "。" if available else "暂无可用名称。")
        if lang.startswith("en"):
            msg = "Available names: " + (available or "none")
        return {"final": msg}
    del sources[name]
    _rag_save_json_atomic(_rag_sources_path(), sources)
    confirm = ("已删除数据源：" + name + "。" if not lang.startswith("en") else "Deleted data source: " + name + ".")
    return {"final": confirm}


def _rag_run_nas(source: dict, name: str, language: str, text: str) -> str:
    if _is_rag_preview_intent(text):
        return _rag_preview_nas(source, name, language)
    if _is_rag_sync_intent(text):
        return _rag_sync_nas_index(source, name, language)
    details = _rag_run_source_detail(source)
    if str(language or "").lower().startswith("en"):
        return "Run request received for nas (" + details + "). Sync logic is not implemented yet."
    return "已收到执行请求：nas（" + details + "）。同步逻辑尚未实现。"


def _rag_run_obsidian(source: dict, name: str, language: str, text: str) -> str:
    details = _rag_run_source_detail(source)
    if str(language or "").lower().startswith("en"):
        return "Run request received for obsidian (" + details + "). Sync logic is not implemented yet."
    return "已收到执行请求：obsidian（" + details + "）。同步逻辑尚未实现。"


def _rag_run_unknown(source: dict, name: str, language: str, text: str) -> str:
    connector = str(source.get("connector") or "unknown")
    if str(language or "").lower().startswith("en"):
        return "Connector not implemented: " + connector + "."
    return "该连接器未实现：" + connector + "。"


def _rag_run_source_detail(source: dict) -> str:
    target = str(source.get("target") or "未指定")
    filetypes = str(source.get("filetypes") or "未指定")
    permission = str(source.get("permission") or "未指定")
    schedule = str(source.get("schedule") or "未指定")
    return target + "，" + filetypes + "，" + permission + "，" + schedule


_RAG_CONNECTORS = {
    "nas": _rag_run_nas,
    "obsidian": _rag_run_obsidian,
    "notion": _rag_run_unknown,
    "url": _rag_run_unknown,
    "unknown": _rag_run_unknown,
}


def _is_rag_preview_intent(text: str) -> bool:
    s = str(text or "").lower()
    if not s:
        return False
    keywords = ["预览", "检查", "会扫描什么", "scan preview", "dry run", "dry-run"]
    return any(k in s for k in keywords)


def _rag_preview_nas(source: dict, name: str, language: str) -> str:
    base = str(source.get("target") or "").strip()
    filetypes = str(source.get("filetypes") or "").strip()
    if not base:
        msg = "未配置目标路径，无法预览。" if not str(language or "").lower().startswith("en") else "Target path missing for preview."
        return msg
    allow_exts = [e.strip().lower() for e in filetypes.split(",") if e.strip()]
    excludes = {".git", "@eadir", "#recycle", "$recycle.bin", "node_modules", "__pycache__"}
    matches = []
    if not os.path.exists(base):
        return "nas 预览失败：目录不存在。" if not str(language or "").lower().startswith("en") else "NAS preview failed: directory missing."
    if not os.path.isdir(base):
        return "nas 预览失败：目标不是目录。" if not str(language or "").lower().startswith("en") else "NAS preview failed: target is not a directory."
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.lower() not in excludes]
            rel_root = os.path.relpath(root, base)
            if rel_root == ".":
                rel_root = ""
            for fn in files:
                if len(matches) >= 20:
                    break
                ext = os.path.splitext(fn)[1].lstrip(".").lower()
                if allow_exts and ext not in allow_exts:
                    continue
                path = fn if not rel_root else rel_root + os.sep + fn
                matches.append(path)
            if len(matches) >= 20:
                break
    except Exception:
        msg = "nas 预览失败：无权限访问该目录。" if not str(language or "").lower().startswith("en") else "NAS preview failed: permission denied."
        return msg
    detail = base + "，" + (filetypes or "未指定")
    summary = ("NAS 扫描预览：根目录=" + detail + "；排除=" + ",".join(sorted(excludes)) + "；命中=" + str(len(matches)) + "（前" + str(min(len(matches), 20)) + "）：")
    lines = [summary]
    for it in matches[:20]:
        lines.append("- " + it)
    if not matches:
        lines.append("（无匹配文件）")
    return "\n".join(lines)


def _rag_sync_nas_index(source: dict, name: str, language: str) -> str:
    base = str(source.get("target") or "").strip()
    if not base:
        return "nas 同步失败：未配置目标路径。"
    if not os.path.exists(base):
        return "nas 同步失败：目录不存在。"
    if not os.path.isdir(base):
        return "nas 同步失败：目标不是目录。"

    filetypes = str(source.get("filetypes") or "").strip()
    allow_exts = [x.strip().lower() for x in filetypes.split(",") if x.strip()]
    if not allow_exts:
        allow_exts = ["pdf", "md"]
    exclude_dirs = {".git", "@eadir", "#recycle", "$recycle.bin", "node_modules", "__pycache__"}

    db_path = _rag_index_db_path()
    max_files = 5000
    touched = 0
    started = datetime.now().timestamp()
    hit_limit = False
    try:
        conn = sqlite3.connect(db_path)
        _rag_db_init(conn)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.lower() not in exclude_dirs]
            for fn in files:
                ext = os.path.splitext(fn)[1].lstrip(".").lower()
                if allow_exts and (ext not in allow_exts):
                    continue
                full_path = os.path.join(root, fn)
                try:
                    st = os.stat(full_path)
                except Exception:
                    continue
                row = {
                    "path": full_path,
                    "name": fn,
                    "ext": ext,
                    "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                    "size": int(getattr(st, "st_size", 0) or 0),
                }
                _rag_db_upsert_file(conn, row)
                touched += 1
                if touched >= max_files:
                    hit_limit = True
                    break
            if hit_limit:
                break
        conn.commit()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM files")
        total = int((cur.fetchone() or [0])[0] or 0)
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return "nas 同步失败：无权限访问该目录。"

    elapsed = round(max(0.0, datetime.now().timestamp() - started), 2)
    msg = "nas 索引完成：新增/更新=" + str(touched) + "；总计=" + str(total) + "；用时=" + str(elapsed) + "秒。"
    if hit_limit:
        msg = msg + " 已达到上限，建议分批/降低频率。"
    return msg


def _rag_run_source(name: str, language: str, text: str = "") -> dict:
    sources = _rag_load_json(_rag_sources_path(), {})
    if not isinstance(sources, dict) or (not sources):
        msg = "暂无已保存的数据源。" if not str(language or "").lower().startswith("en") else "No saved sources yet."
        return {"final": msg}
    if not name:
        available = ", ".join(sorted(sources.keys()))
        msg = ("当前可用：" + available + "。" if available else "暂无可用名称。")
        if str(language or "").lower().startswith("en"):
            msg = "Available names: " + (available or "none")
        return {"final": msg}
    source = sources.get(name)
    if not source:
        available = ", ".join(sorted(sources.keys()))
        msg = ("未找到数据源：" + name + "。当前可用：" + (available or "无") + "。")
        if str(language or "").lower().startswith("en"):
            msg = "Data source not found: " + name + ". Available: " + (available or "none")
        return {"final": msg}
    connector = str(source.get("connector") or "unknown")
    handler = _RAG_CONNECTORS.get(connector, _rag_run_unknown)
    text_out = handler(source, name, language, text or "")
    return {"final": text_out}


def _is_rag_run_intent(text: str):
    s = str(text or "").strip().lower()
    if not s:
        return False, ""
    keywords = ["运行", "执行", "同步", "刷新", "更新数据源", "run", "sync", "refresh", "预览", "检查", "scan preview", "dry run"]
    if not any(k in s for k in keywords):
        return False, ""
    sources = _rag_load_json(_rag_sources_path(), {})
    name = ""
    if isinstance(sources, dict):
        for nm in sources.keys():
            if nm.lower() in s:
                return True, nm
    parts = s.replace("：", " ").replace(":", " ").split()
    if parts:
        name = parts[-1]
    return True, name


def _rag_apply_draft(language: str):
    draft = _rag_load_json(_rag_draft_path(), {})
    if not isinstance(draft, dict) or (not draft):
        msg = "暂无可应用的草案。" if not str(language or "").lower().startswith("en") else "No draft to apply."
        return {"final": msg}
    draft_type = str(draft.get("draft_type") or "").strip().lower()
    if draft_type.startswith("obsidian_"):
        return _rag_obsidian_apply_draft(draft, language)
    name = str(draft.get("connector") or "unknown").strip()
    if name == "obsidian":
        name = "obsidian"
    if not name:
        name = "default"
    sources = _rag_load_json(_rag_sources_path(), {})
    if not isinstance(sources, dict):
        sources = {}
    target_clean, extra = _strip_trailing_paren_block(str(draft.get("target") or ""))
    if target_clean:
        draft["target"] = target_clean
    if name == "obsidian":
        t = str(draft.get("target") or "").strip()
        if (not t) or t.lower().startswith("vault:"):
            draft["target"] = "/mnt/nas/Obsidian/VaultHome"
        draft["connector"] = "obsidian"
    if extra:
        filetypes = str(draft.get("filetypes") or "").strip()
        if not filetypes:
            draft["filetypes"] = extra
    if name == "obsidian":
        if not str(draft.get("filetypes") or "").strip():
            draft["filetypes"] = "md"
        if not str(draft.get("schedule") or "").strip():
            draft["schedule"] = "手动"
        if not str(draft.get("permission") or "").strip():
            draft["permission"] = "可写"
    sources[name] = draft
    _rag_save_json_atomic(_rag_sources_path(), sources)
    return {"final": _rag_sources_confirm_text(name, draft, language), "route_type": "rag_config_apply"}


def _rag_handle_management(text: str, language: str):
    lang = language or ""
    if _rag_list_intent(text):
        result = _rag_sources_list_text(lang)
        return {"ok": True, "route_type": "rag_config_list", "final": result.get("final")}
    name = _rag_show_name(text)
    if name:
        result = _rag_show_text(name, lang)
        return {"ok": True, "route_type": "rag_config_show", "final": result.get("final")}
    name = _rag_delete_name(text)
    if name:
        result = _rag_delete_text(name, lang)
        return {"ok": True, "route_type": "rag_config_delete", "final": result.get("final")}
    if _rag_obsidian_add_intent(text):
        result = _rag_obsidian_build_add_draft(text, lang)
        return {"ok": True, "route_type": "rag_obsidian_add_draft", "final": result.get("final")}
    if _rag_obsidian_update_intent(text):
        result = _rag_obsidian_build_update_draft(text, lang)
        return {"ok": True, "route_type": "rag_obsidian_update_draft", "final": result.get("final")}
    if _rag_obsidian_delete_intent(text):
        result = _rag_obsidian_build_delete_draft(text, lang)
        return {"ok": True, "route_type": "rag_obsidian_delete_draft", "final": result.get("final")}
    if _rag_apply_intent(text):
        result = _rag_apply_draft(lang)
        return {"ok": True, "route_type": result.get("route_type") or "rag_config_apply", "final": result.get("final")}
    prewarm_flag, prewarm_name, prewarm_folder = _is_rag_prewarm_intent(text)
    if prewarm_flag:
        result = _rag_prewarm_source(prewarm_name, lang, prewarm_folder)
        return {"ok": True, "route_type": "rag_prewarm", "final": result.get("final")}
    if _is_rag_content_query_intent(text):
        kw, folder = _rag_extract_content_query(text)
        final = _rag_search_content(kw, lang, folder)
        return {"ok": True, "route_type": "rag_content_query", "final": final}
    if _is_rag_query_intent(text):
        kw, folder = _rag_extract_query_keyword(text)
        if "debug folder" in str(text or "").lower():
            folder_like = ""
            if folder:
                folder_like = "%/" + folder.strip("/").strip() + "/%"
            return {"ok": True, "route_type": "rag_index_query", "final": "folder_hint=" + (folder or "") + " folder_like=" + folder_like}
        final = _rag_search_index(kw, lang, folder)
        return {"ok": True, "route_type": "rag_index_query", "final": final}
    run_flag, run_name = _is_rag_run_intent(text)
    if run_flag:
        result = _rag_run_source(run_name, lang, text)
        return {"ok": True, "route_type": "rag_config_run", "final": result.get("final")}
    return None




def _rag_config_draft_text(draft: dict, language: str) -> str:
    lang = str(language or "").strip().lower()
    connector = str(draft.get("connector") or "unknown")
    target = str(draft.get("target") or "未识别")
    filetypes = str(draft.get("filetypes") or "未识别")
    schedule = str(draft.get("schedule") or "未识别")
    permission = str(draft.get("permission") or "未指定")
    def _next_steps(missings: list, lang_prefix: str) -> str:
        if not missings:
            return "" if lang_prefix == "zh" else " No further confirmations needed."
        snippet = "；".join(missings[:2])
        if lang_prefix == "zh":
            return " 下一步：" + snippet + "。"
        return " Next steps: " + ", ".join(missings[:2]) + "."

    if lang.startswith("en"):
        fields = "; ".join([
            "connect=" + connector,
            "target=" + target,
            "filetypes=" + filetypes,
            "schedule=" + schedule,
            "permission=" + permission,
        ]) + "."
        missing = []
        if not connector or connector == "unknown":
            missing.append("confirm the source path")
        if not target or target == "未识别":
            missing.append("specify the target identifier")
        if not filetypes or filetypes == "未识别":
            missing.append("list the filetypes")
        if not schedule or schedule == "未识别":
            missing.append("define the update cadence")
        if not permission or permission == "未指定":
            missing.append("describe the write policy")
        return "Draft config received (not applied): " + fields + _next_steps(missing, "en")
    missing = []
    if not connector or connector == "unknown":
        missing.append("1) 确认数据源路径")
    if not target or target == "未识别":
        missing.append("2) 定位目标标识")
    if not filetypes or filetypes == "未识别":
        missing.append("3) 明确文件类型")
    if not schedule or schedule == "未识别":
        missing.append("4) 说明更新节奏")
    if not permission or permission == "未指定":
        missing.append("5) 说明写入策略")
    return "".join([
        "已收到配置草案（未应用）：",
        "连接=" + connector + "；",
        "目标=" + target + "；",
        "文件类型=" + filetypes + "；",
        "更新=" + schedule + "；",
        "权限=" + permission + "。",
        _next_steps(missing, "zh")
    ])


def _rag_sources_confirm_text(name: str, draft: dict, language: str) -> str:
    lang = str(language or "").strip().lower()
    target = str(draft.get("target") or "未指定")
    filetypes = str(draft.get("filetypes") or "未指定")
    permission = str(draft.get("permission") or "未指定")
    schedule = str(draft.get("schedule") or "未指定")
    if lang.startswith("en"):
        return "Saved data source: " + name + " (" + target + ", " + filetypes + ", " + permission + ", " + schedule + ")."
    return "已保存数据源：" + name + "（" + target + "，" + filetypes + "，" + permission + "，" + schedule + "）。"

def _selftest_rag_stub_case() -> dict:
    q = "查询家庭资料库"
    hit = _is_rag_intent(q)
    ans = _rag_stub_answer(q, "zh-CN", mode=_rag_mode(q))
    ok = bool(hit and isinstance(ans, str) and ans.strip())
    return {"ok": ok, "query": q, "hit": bool(hit), "answer": str(ans or "")}

def _looks_like_entity_id(t):
    s = str(t or "").strip()
    if " " in s or "　" in s:
        return False
    if re.match(r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$", s):
        return True
    return False

def _iso_day_start_end(d, tzinfo):
    from datetime import datetime, timedelta
    try:
        if tzinfo:
            start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tzinfo)
        else:
            start = datetime(d.year, d.month, d.day, 0, 0, 0)
        end = start + timedelta(days=1)
        return start.isoformat(), end.isoformat()
    except Exception:
        start = datetime(d.year, d.month, d.day, 0, 0, 0)
        end = start + timedelta(days=1)
        return start.isoformat(), end.isoformat()

def _summarise_calendar_events(events):
    if (not isinstance(events, list)) or (len(events) == 0):
        return "没有日程。"
    parts = []
    lim = 6
    for it in events[:lim]:
        if not isinstance(it, dict):
            continue
        summ = str(it.get("summary") or "").strip()
        st = it.get("start") or {}
        if isinstance(st, dict) and st.get("date"):
            ds = str(st.get("date") or "").strip()
            if ds:
                parts.append(ds + " 全天 " + summ)
            else:
                parts.append("全天 " + summ)
        else:
            dt = None
            if isinstance(st, dict):
                dt = st.get("dateTime") or st.get("datetime")
            if dt:
                dts = str(dt)
                # Best-effort format: YYYY-MM-DD HH:MM
                if len(dts) >= 16 and "T" in dts:
                    d = dts[:10]
                    tm = dts[11:16]
                    parts.append(d + " " + tm + " " + summ)
                else:
                    parts.append(dts + " " + summ)
            else:
                parts.append(summ)
    if len(events) > lim:
        parts.append("等共 " + str(len(events)) + " 条")
    return "；".join([p for p in parts if p]) + "。"


def _calendar_extra_entity_for_merge() -> str:
    return "calendar.vs888home_gmail_com"


def _calendar_entities_for_query(default_entity: str) -> list:
    out = []
    d = str(default_entity or "").strip()
    if d:
        out.append(d)
    extra = _calendar_extra_entity_for_merge()
    if extra and (extra not in out):
        st = ha_get_state(extra, timeout_sec=8)
        if st.get("ok"):
            out.append(extra)
    return out


def _calendar_event_dedupe_key(it: dict) -> str:
    if not isinstance(it, dict):
        return ""
    st = it.get("start") or {}
    en = it.get("end") or {}
    s1 = str((st or {}).get("dateTime") or (st or {}).get("datetime") or (st or {}).get("date") or "").strip()
    e1 = str((en or {}).get("dateTime") or (en or {}).get("datetime") or (en or {}).get("date") or "").strip()
    summary = str(it.get("summary") or "").strip()
    location = str(it.get("location") or "").strip()
    return s1 + "|" + e1 + "|" + summary + "|" + location


def _calendar_event_sort_key(it: dict) -> str:
    if not isinstance(it, dict):
        return "9999-99-99T99:99:99"
    st = it.get("start") or {}
    dt = str((st or {}).get("dateTime") or (st or {}).get("datetime") or "").strip()
    if dt:
        return dt
    d = str((st or {}).get("date") or "").strip()
    if d:
        return d + "T00:00:00"
    return "9999-99-99T99:99:99"


def _calendar_fetch_merged_events(entities: list, start_iso: str, end_iso: str) -> tuple:
    merged = []
    errors = []
    seen = set()
    for eid in entities or []:
        rr = ha_calendar_events(str(eid or ""), start_iso, end_iso)
        if not rr.get("ok"):
            errors.append(rr)
            continue
        ev = rr.get("data") if isinstance(rr.get("data"), list) else []
        for it in ev:
            if not isinstance(it, dict):
                continue
            try:
                if "__entity_id" not in it:
                    it["__entity_id"] = str(eid or "")
            except Exception:
                pass
            key = _calendar_event_dedupe_key(it)
            if key and (key in seen):
                continue
            if key:
                seen.add(key)
            merged.append(it)
    merged.sort(key=_calendar_event_sort_key)
    return merged, errors


def _calendar_is_delete_intent(text: str) -> bool:
    s = str(text or "").strip()
    sl = s.lower()
    if (("删除" in s) or ("删掉" in s) or ("取消" in s) or ("移除" in s) or ("去掉" in s)) and (("日程" in s) or ("提醒" in s) or ("会议" in s) or ("开会" in s)):
        return True
    keys_cn = ["删除日程", "删掉日程", "取消日程", "删除提醒", "取消提醒", "移除日程", "去掉日程"]
    keys_en = ["delete event", "remove event", "cancel event", "delete reminder", "remove reminder"]
    return any(k in s for k in keys_cn) or any(k in sl for k in keys_en)


def _calendar_is_update_intent(text: str) -> bool:
    s = str(text or "").strip()
    sl = s.lower()
    if (("改到" in s) or ("改成" in s) or ("改为" in s) or ("修改" in s) or ("调整到" in s) or ("延期到" in s) or ("提前到" in s)) and (("日程" in s) or ("提醒" in s) or ("会议" in s) or ("开会" in s)):
        return True
    keys_cn = ["修改日程", "修改提醒", "改到", "改成", "调整到", "延期到", "提前到", "改时间", "改为"]
    keys_en = ["update event", "edit event", "reschedule", "move event", "change to"]
    return any(k in s for k in keys_cn) or any(k in sl for k in keys_en)


def _calendar_extract_target_summary(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return ""
    x = t
    for k in ["请", "帮我", "把", "将", "这个", "这条", "该", "我的"]:
        x = x.replace(k, " ")
    for k in [
        "删除日程", "删掉日程", "取消日程", "删除提醒", "取消提醒", "移除日程",
        "修改日程", "修改提醒", "改到", "改成", "调整到", "延期到", "提前到", "改时间", "改为",
    ]:
        x = x.replace(k, " ")
    x = re.sub(r"(今天|明天|后天|大后天|本周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天])", " ", x)
    x = re.sub(r"(上午|下午|晚上|中午|am|pm)", " ", x, flags=re.I)
    x = re.sub(r"(\d{1,2}\s*[:：]\s*\d{1,2})", " ", x)
    x = re.sub(r"(\d{1,2}\s*点\s*(半|[0-5]?\d\s*分?)?)", " ", x)
    x = re.sub(r"\s+", " ", x).strip(" ，。,:：;；")
    if len(x) > 40:
        x = x[:40].strip()
    return x


def _calendar_event_summary(it: dict) -> str:
    if not isinstance(it, dict):
        return ""
    return str(it.get("summary") or "").strip()


def _calendar_event_start_dt(it: dict):
    if not isinstance(it, dict):
        return None
    st = it.get("start") or {}
    if not isinstance(st, dict):
        return None
    dt = st.get("dateTime") or st.get("datetime")
    if dt:
        return _dt_from_iso(dt)
    d = st.get("date")
    if d:
        try:
            ds = str(d).strip()
            if not ds:
                return None
            return datetime.fromisoformat(ds + "T00:00:00")
        except Exception:
            return None
    return None


def _calendar_pick_event_for_text(events: list, text: str, target_date: object = None):
    if not isinstance(events, list) or (len(events) == 0):
        return None
    key = _calendar_extract_target_summary(text)
    cand = []
    for it in events:
        if not isinstance(it, dict):
            continue
        dt = _calendar_event_start_dt(it)
        if isinstance(target_date, dt_date) and (dt is not None):
            try:
                if dt.date() != target_date:
                    continue
            except Exception:
                pass
        cand.append(it)
    if len(cand) == 0:
        cand = [it for it in events if isinstance(it, dict)]
    if key:
        kl = key.lower()
        for it in cand:
            sm = _calendar_event_summary(it)
            if (key in sm) or (kl in sm.lower()):
                return it
    if len(cand) == 1:
        return cand[0]
    if len(events) == 1:
        return events[0]
    return None

# --- NEWS HELPERS (active path uses skill.news_brief / _skill_news_brief_core) ---
# Semi-structured retrieval: News digest via local SearXNG + domain allow-list.
# Chinese-first with minimal English fallback. No hallucinated news.

NEWS_SOURCES = {
    "world": {
        "zh": [
            "thepaper.cn",
            "caixin.com",
            "ifeng.com",
            "bbc.com/zhongwen",
            "bbc.com/zh",
            "dw.com/zh",
            "dw.com/zh-hans",
        ],
        "en": [
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "theguardian.com",
            "aljazeera.com",
        ],
    },
    "cn_economy": {
        "zh": [
            "caixin.com",
            "yicai.com",
        ],
        "en": [
            "reuters.com",
        ],
    },
    "au_politics": {
        "zh": [
            "sbs.com.au/language/chinese",
            "abc.net.au/chinese",
        ],
        "en": [
            "abc.net.au",
            "sbs.com.au/news",
            "theguardian.com/au",
            "aph.gov.au",
            "aec.gov.au",
            "pm.gov.au",
            "homeaffairs.gov.au",
            "treasury.gov.au",
        ],
    },
    "mel_life": {
        "zh": [
            "sbs.com.au/language/chinese",
            "abc.net.au/chinese",
        ],
        "en": [
            "abc.net.au",
            "9news.com.au",
            "melbourne.vic.gov.au",
        ],
        "region_keywords": ["melbourne", "victoria", "vic", "ptv", "metro", "yarra", "docklands", "cbd"],
    },
    "tech_internet": {
        "zh": [
            "36kr.com",
            "huxiu.com",
        ],
        "en": [
            "theverge.com",
            "techcrunch.com",
            "wired.com",
            "arstechnica.com",
        ],
    },
    "tech_gadgets": {
        "zh": [
            "sspai.com",
            "ifanr.com",
        ],
        "en": [
            "theverge.com",
        ],
    },
    "gaming": {
        "zh": [
            "gcores.com",
        ],
        "en": [
            "ign.com",
            "pcgamer.com",
        ],
    },
}

NEWS_QUERY_ZH = {
    "world": "国际 要闻",
    "cn_economy": "中国 财经",
    "au_politics": "澳洲 联邦 政治 议会 工党 反对党",
    "mel_life": "墨尔本 维州 民生 交通 火警 警情",
    "tech_internet": "互联网 科技 AI 开源 监管",
    "tech_gadgets": "数码 新品 评测 上手",
    "gaming": "游戏 新闻 Steam 主机 更新",
}

NEWS_QUERY_EN = {
    "world": "world news breaking",
    "cn_economy": "China economy finance market",
    "au_politics": "Australian politics federal parliament Canberra",
    "mel_life": "Melbourne Victoria local news transport police",
    "tech_internet": "internet technology AI regulation",
    "tech_gadgets": "gadgets review launch hands-on",
    "gaming": "game news patch update release",
}

NEWS_STOPWORDS = [
    "给我", "来点", "今天", "最新", "要闻", "新闻", "快讯", "头条",
    "世界", "国际", "中国", "财经", "澳洲", "澳大利亚", "政治",
    "墨尔本", "维州", "本地", "民生", "互联网", "科技", "数码", "产品", "游戏", "电竞",
    "please", "today", "latest", "news", "world", "china", "finance", "australia", "politics", "melbourne", "tech", "gaming"
]

def _news__is_query(text: str) -> bool:
    t = str(text or "").strip()
    tl = t.lower()
    # Strong condition only: must contain explicit news intent words.
    keys = [
        "新闻", "要闻", "头条", "快讯", "热点", "今日新闻", "今日要闻", "世界新闻", "本地新闻", "国际新闻",
        "墨尔本新闻", "最新消息", "发生了什么",
        "news", "headline", "headlines", "breaking news", "latest news",
    ]
    for k in keys:
        if (k in t) or (k in tl):
            return True
    return False

def _news__category_from_text(text: str) -> str:
    t = str(text or "")
    tl = t.lower()

    # hot / trending
    tl_s = tl.strip()
    if (
        ("热门" in t)
        or ("热搜" in t)
        or ("头条" in t)
        or ("热点" in t)
        or ("trending" in tl)
        or ("hot news" in tl)
        or ("headlines" in tl)
        or ("top news" in tl)
        or (tl_s == "top")
    ):
        return "hot"


    if ("墨尔本" in t) or ("维州" in t) or ("melbourne" in tl) or ("victoria" in tl) or ("vic" in tl):
        return "mel_life"

    if ("澳洲" in t) or ("澳大利亚" in t) or ("australia" in tl) or ("australian" in tl):
        return "au_politics"

    if ("中国" in t) and (("财经" in t) or ("金融" in t) or ("股" in t) or ("人民币" in t)):
        return "cn_economy"
    if ("财经" in t) or ("金融" in t) or ("a股" in tl):
        return "cn_economy"

    if ("互联网" in t) or ("ai" in tl) or ("openai" in tl) or ("监管" in t) or ("科技" in t):
        return "tech_internet"
    if ("数码" in t) or ("手机" in t) or ("相机" in t) or ("耳机" in t) or ("笔记本" in t) or ("评测" in t) or ("新品" in t):
        return "tech_gadgets"
    if ("游戏" in t) or ("电竞" in t) or ("steam" in tl) or ("ps5" in tl) or ("xbox" in tl) or ("switch" in tl):
        return "gaming"

    if ("世界" in t) or ("国际" in t) or ("global" in tl) or ("world" in tl):
        return "world"

    return "world"

def _news__time_range_from_text(text: str) -> str:
    t = str(text or "")
    tl = t.lower()
    if ("本周" in t) or ("这一周" in t) or ("过去一周" in t) or ("week" in tl):
        return "week"
    if ("本月" in t) or ("过去一个月" in t) or ("month" in tl):
        return "month"
    return "day"

def _news__site_filter(domains):
    ds = []
    for d in domains or []:
        dd = str(d or "").strip()
        if dd:
            ds.append(dd)
    if not ds:
        return ""
    parts = []
    for d in ds[:10]:
        parts.append("site:" + d)
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"

def _news__canonical_url(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    x = u
    if x.startswith("http://"):
        x = x[len("http://"):]
    if x.startswith("https://"):
        x = x[len("https://"):]
    x = x.split("#")[0]
    x = x.split("?")[0]
    parts = x.split("/", 1)
    host = parts[0].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    path = ""
    if len(parts) == 2:
        path = "/" + parts[1]
    return host + path

def _news__source_from_url(url):
    u = str(url or "").strip()
    if not u:
        return ""
    x = u
    if x.startswith("http://"):
        x = x[len("http://"):]
    if x.startswith("https://"):
        x = x[len("https://"):]
    x = x.split("/")[0].strip()
    return x

def _news__summarise_item(snippet, fallback_title):
    s = str(snippet or "").strip()
    if len(s) >= 30:
        s = " ".join(s.split())
        return s[:160]
    t = str(fallback_title or "").strip()
    if t:
        return t[:80]
    return "（摘要缺失）"

def _news__clean_user_query(user_text: str) -> str:
    t = str(user_text or "").strip()
    if not t:
        return ""
    x = t
    for w in NEWS_STOPWORDS:
        x = x.replace(w, " ")
    x = " ".join(x.split()).strip()
    if len(x) < 3:
        return ""
    return x[:120]

def _news__must_keywords(category: str):
    if category == "au_politics":
        return ["australia", "australian", "canberra", "parliament", "election", "budget", "albanese", "labor", "coalition", "greens", "澳", "联邦", "议会", "工党", "反对党", "选举", "预算"]
    if category == "mel_life":
        return ["melbourne", "victoria", "vic", "ptv", "metro", "yarra", "cbd", "docklands", "墨尔本", "维州", "公交", "火警", "警方", "交通"]
    return []

def _news__match_must_keywords(category: str, title: str, summary: str) -> bool:
    must = _news__must_keywords(category)
    if not must:
        return True
    blob = (str(title or "") + " " + str(summary or "")).lower()
    for k in must:
        kk = str(k or "").lower()
        if kk and (kk in blob):
            return True
    return False

def _news__pick_results(results, allow_domains, category):
    out = []
    seen = set()
    host_count = {}

    allow = []
    for d in allow_domains or []:
        dd = str(d or "").strip()
        if dd:
            allow.append(dd)

    for it in results or []:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        sn = str(it.get("snippet") or "").strip()
        if (not url) or (not title):
            continue

        if allow:
            ok_domain = False
            for d in allow:
                if d and (d in url):
                    ok_domain = True
                    break
            if not ok_domain:
                continue

        canon = _news__canonical_url(url)
        if not canon:
            continue
        if canon in seen:
            continue

        host = canon.split("/", 1)[0]
        cnt = host_count.get(host, 0)
        if cnt >= 2:
            continue

        summ = _news__summarise_item(sn, title)
        if not _news__match_must_keywords(category, title, summ):
            continue

        seen.add(canon)
        host_count[host] = cnt + 1

        out.append({"title": title, "url": url, "snippet": sn})
        if len(out) >= 12:
            break

    return out
def _news__coerce_rules(x):
    """
    允许 rules_zh / rules_en 为:
      - list[dict]（推荐）
      - list[str]（会转换为 dict）
      - dict（会包成单元素 list）
      - str（尝试 json.loads；失败则当作 domain 字符串）
      - None（转为空 list）
    返回: list[dict]
    """
    if x is None:
        return []
    if isinstance(x, list):
        out = []
        for it in x:
            if isinstance(it, dict):
                out.append(it)
            elif isinstance(it, str):
                dom = it.strip()
                if dom:
                    out.append({"domain": dom})
        return out
    if isinstance(x, dict):
        return [x]
    if isinstance(x, str):
        t = x.strip()
        if not t:
            return []
        if (t.startswith("[") and t.endswith("]")) or (t.startswith("{") and t.endswith("}")):
            try:
                j = json.loads(t)
                return _news__coerce_rules(j)
            except Exception:
                pass
        return [{"domain": t}]
    return []



def _news__build_query(category, user_text, lang):
    c = str(category or "").strip()
    lg = str(lang or "").strip()
    uq = _news__clean_user_query(user_text)

    base = uq
    if not base:
        if lg == "en":
            base = str(NEWS_QUERY_EN.get(c) or "news")
        else:
            base = str(NEWS_QUERY_ZH.get(c) or "新闻")

    # hard-bias for local categories
    if c == "mel_life":
        if ("melbourne" not in base.lower()) and ("墨尔本" not in base):
            base = base + " Melbourne Victoria"
    if c == "au_politics":
        if ("australia" not in base.lower()) and ("澳" not in base):
            base = base + " Australia 澳洲 联邦"

    if len(base) > 160:
        base = base[:160]
    return base

# @mcp.tool(
#     name="news_digest",
#     description="(Tool) News digest via Miniflux (RSS). Reads entries from the last 24 hours (rolling 24h). Category-driven; default 5 items. Chinese-first with lightweight topic filtering and fallback."
# )


def _news__is_video_entry(title: str, url: str) -> bool:
    """Return True if this entry is a video-type news item."""
    try:
        t = (title or "").strip().lower()
        u = (url or "").strip().lower()
        if "/video/" in u:
            return True
        # common title suffix patterns
        if " - video" in t or " – video" in t or " — video" in t:
            return True
        if t.endswith("video") and len(t) <= 140:
            return True
        return False
    except Exception:
        return False
# PATCH_NEWS_HOT_V1
def news_hot(limit: int = 10,
             time_range: str = "24h",
             prefer_lang: str = "en",
             user_text: str = "",
             **kwargs) -> dict:
    """Miniflux 热门新闻（跨所有分类聚合，默认最近24小时，取前 N 条，标题+摘要）。
    说明：
    - 不做翻译（按 Miniflux 原始语言输出）
    - 只做去重 + 简要摘要截断
    """
    base_url = os.environ.get("MINIFLUX_BASE_URL") or "http://192.168.1.162:19091"
    token = os.environ.get("MINIFLUX_API_TOKEN") or ""
    if not token.strip():
        return {"ok": False, "error": "MINIFLUX_API_TOKEN is not set", "items": [], "final": "Miniflux API Token 未配置（MINIFLUX_API_TOKEN）。"}

    def _mf_req(path: str, params: dict = None) -> dict:
        url = base_url.rstrip("/") + path
        headers = {"X-Auth-Token": token}
        try:
            r = requests.get(url, headers=headers, params=(params or {}), timeout=8)
            if int(getattr(r, "status_code", 0) or 0) >= 400:
                return {"ok": False, "status": int(r.status_code), "text": (r.text or "")[:500]}
            return {"ok": True, "data": r.json()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _strip_html(s: str) -> str:
        if not s:
            return ""
        try:
            s2 = re.sub(r"<[^>]+>", " ", s)
            s2 = html.unescape(s2)
            s2 = re.sub(r"\s+", " ", s2).strip()
            return s2
        except Exception:
            return (s or "").strip()

    import time as _time
    after_ts = int(_time.time()) - 24 * 3600

    try:
        lim_int = int(limit)
    except Exception:
        lim_int = 10
    if lim_int < 1:
        lim_int = 1
    if lim_int > 10:
        lim_int = 10

    try:
        sn_lim = int(os.environ.get("NEWS_SNIPPET_CHARS") or "220")
    except Exception:
        sn_lim = 220
    if sn_lim < 80:
        sn_lim = 80
    if sn_lim > 600:
        sn_lim = 600

    fetch_lim = lim_int * 10
    if fetch_lim < 40:
        fetch_lim = 40
    if fetch_lim > 120:
        fetch_lim = 120

    # 优先尝试 /v1/entries（单次请求更快）；失败则回退到按分类聚合
    params = {"order": "published_at", "direction": "desc", "limit": fetch_lim, "after": after_ts}
    ent = _mf_req("/v1/entries", params=params)

    entries = []
    if ent.get("ok"):
        payload = ent.get("data") or {}
        entries = payload.get("entries") or []
    else:
        cats = _mf_req("/v1/categories")
        if cats.get("ok"):
            categories = cats.get("data") or []
            for c in categories:
                try:
                    cid = c.get("id")
                    if cid is None:
                        continue
                    e2 = _mf_req("/v1/categories/{0}/entries".format(cid), params={"order": "published_at", "direction": "desc", "limit": 10, "after": after_ts})
                    if not e2.get("ok"):
                        continue
                    payload2 = e2.get("data") or {}
                    es = payload2.get("entries") or []
                    if es:
                        entries.extend(es)
                except Exception:
                    continue

    if not entries:
        return {"ok": True, "items": [], "final": "暂无符合最近24小时的条目。"}

    # 组装 items（标题 + 摘要）
    items = []
    drop_video = (os.environ.get("NEWS_DROP_VIDEO") or "1").strip().lower()
    for e in entries:
        try:
            title = (e.get("title") or "").strip()
            url = (e.get("url") or "").strip() or (e.get("comments_url") or "").strip()
            if drop_video not in ("0", "false", "no", "off"):
                if _news__is_video_entry(title, url):
                    continue
            feed = e.get("feed") or {}
            src = (feed.get("title") or "").strip()
            content_plain = _strip_html((e.get("content") or "").strip())
            snippet = content_plain
            if len(snippet) > sn_lim:
                snippet = snippet[:sn_lim].rstrip() + "..."
            items.append({"title": title, "url": url, "source": src, "snippet": snippet, "content_plain": content_plain})
        except Exception:
            continue

    # 去重 + 截断到 N 条
    try:
        items = _news__dedupe_items_for_voice(items)
    except Exception:
        pass
    if len(items) > lim_int:
        items = items[:lim_int]

    # 拼 final（标题 + 摘要）
    lines = []
    i = 0
    for it in items:
        i += 1
        t = (it.get("title") or "").strip()
        sn = (it.get("snippet") or "").strip()
        if sn:
            lines.append("{0}) {1}\n   {2}".format(i, t, sn))
        else:
            lines.append("{0}) {1}".format(i, t))

    final = "\n".join(lines).strip()
    return {"ok": True, "items": items, "final": final, "final_voice": final}


def news_digest(category: str = "world",
               limit: int = 5,
               time_range: str = "24h",
               prefer_lang: str = "zh",
               user_text: str = "",
               **kwargs) -> dict:
    """
    Miniflux-backed news digest.

    Hard rules:
    - Source of truth: Miniflux (RSS aggregator)
    - Window: last 24 hours (rolling 24h), regardless of time_range input
    - Output: default 5 items, Chinese-first; if not enough, fallback to English
    - Lightweight topic filter to reduce category pollution:
        * blacklist keywords -> drop
        * whitelist keywords (when available) -> keep if hit, otherwise filtered
        * if filtered results not enough -> relax whitelist, then cross-language fill
    """

    base_url = os.environ.get("MINIFLUX_BASE_URL") or "http://192.168.1.162:19091"
    token = os.environ.get("MINIFLUX_API_TOKEN") or ""
    if not token.strip():
        return {
            "ok": False,
            "error": "MINIFLUX_API_TOKEN is not set",
            "category": category,
            "time_range": "24h",
            "limit": limit,
            "items": [],
            "final": "Miniflux API Token 未配置（MINIFLUX_API_TOKEN）。"
        }

    # NEWS_FORCE_CHAT_TRANSLATE_V4
    def _translate_titles_chat(titles: list) -> list:
        # NEWS_TIMEOUT_BUDGET_V1
        """Robust batch title translation with a hard time budget.
        - Prefer one batch /api/chat.
        - If output parsing is odd, try to split numbered blob.
        - Do NOT do per-title fallback by default (too slow for HA tool timeout).
        Budget is controlled by NEWS_TRANSLATE_BUDGET_SEC (default 8s).
        """
        if not titles:
            return []
        t0 = time.time()
        budget = float(os.environ.get("NEWS_TRANSLATE_BUDGET_SEC") or "8")
        base = str(os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip().rstrip("/")
        model = str(os.environ.get("NEWS_TRANSLATE_MODEL") or os.environ.get("OLLAMA_TRANSLATE_MODEL") or "qwen3:1.7b").strip() or "qwen3:1.7b"
        want_n = len(titles)

        def _strip_num_prefix(s: str) -> str:
            return re.sub(r"^\s*\d+\s*[\.|\)|、]\s*", "", str(s or "").strip()).strip()

        def _split_numbered_blob(s: str) -> list:
            t = str(s or "").strip()
            if not t:
                return []
            pat = re.compile(r"(?:^|\s)(\d{1,2})\s*[\.|\)|、]\s+")
            ms = list(pat.finditer(t))
            if not ms:
                return []
            parts = []
            for idx, m in enumerate(ms):
                c0 = m.start(0)
                c1 = ms[idx+1].start(0) if (idx+1)<len(ms) else len(t)
                seg = t[c0:c1].strip()
                seg = _strip_num_prefix(seg)
                if seg:
                    parts.append(seg)
            return parts

        # build batch prompt
        in_lines = []
        k = 1
        for tt in titles:
            s = str(tt or "").strip() or "(empty)"
            if len(s) > 180:
                s = s[:180].rstrip() + "…"
            in_lines.append(str(k) + ". " + s)
            k += 1

        user_prompt = (
            "把下面每一行英文标题翻译成中文。\n"
            "要求：只输出对应的中文标题列表，每行一个。\n"
            "如果无法逐行输出，可以用 1) 2) 3) 的形式，但必须一一对应。\n\n"
            + "\n".join(in_lines)
        )

        # dynamic timeout: never exceed budget
        remain = max(1.0, budget - (time.time() - t0))
        timeout_sec = min(12.0, remain)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是翻译器。只输出中文标题列表。"},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }

        txt = ""
        try:
            r = requests.post(base + "/api/chat", json=payload, timeout=timeout_sec)
            if int(getattr(r, "status_code", 0) or 0) < 400:
                j = r.json() if hasattr(r, "json") else {}
                msg = j.get("message") if isinstance(j, dict) else None
                if isinstance(msg, dict):
                    txt = str(msg.get("content") or "").strip()
        except Exception:
            txt = ""

        cleaned = []
        if txt:
            out = [x.strip() for x in txt.splitlines() if x.strip()]
            for x in out:
                x2 = _strip_num_prefix(x)
                if x2:
                    cleaned.append(x2)
            if len(cleaned) < want_n:
                blob = _split_numbered_blob(txt)
                if blob and (len(blob) > len(cleaned)):
                    cleaned = blob

        # ensure length; if不足，直接回退原文（避免逐条翻译导致 HA 超时）
        out_list = []
        for i in range(want_n):
            v = str(cleaned[i] if i < len(cleaned) else "").strip()
            if not v:
                v = str(titles[i] or "").strip()
            out_list.append(v)
        return out_list

    def _mf_req(path: str, params: dict = None) -> dict:
        url = base_url.rstrip("/") + path
        headers = {"X-Auth-Token": token}
        try:
            r = requests.get(url, headers=headers, params=(params or {}), timeout=12)
            if int(getattr(r, "status_code", 0) or 0) >= 400:
                return {"ok": False, "status": int(r.status_code), "text": (r.text or "")[:500]}
            return {"ok": True, "data": r.json()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _strip_html(s: str) -> str:
        if not s:
            return ""
        try:
            s2 = re.sub(r"<[^>]+>", " ", s)
            s2 = html.unescape(s2)
            s2 = re.sub(r"\s+", " ", s2).strip()
            return s2
        except Exception:
            return (s or "").strip()

    def _to_local_time(iso_str: str) -> str:
        if not iso_str:
            return ""
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            tzname = os.environ.get("TZ") or "Australia/Melbourne"
            dt2 = dt.astimezone(ZoneInfo(tzname))
            return dt2.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return iso_str

    def _has_cjk(s: str) -> bool:
        if not s:
            return False
        try:
            han = 0
            total = 0
            for ch in s:
                oc = ord(ch)
                if ch.isspace():
                    continue
                total += 1
                if (0x4E00 <= oc <= 0x9FFF) or (0x3400 <= oc <= 0x4DBF) or (0x20000 <= oc <= 0x2A6DF):
                    han += 1
            if total <= 0:
                return False
            if han >= 8:
                return True
            return (float(han) / float(total)) >= 0.12
        except Exception:
            return False


    # normalize prefer_lang
    pl = str(prefer_lang or "").strip().lower()
    if pl.startswith("zh"):
        prefer_lang = "zh"
    elif pl.startswith("en"):
        prefer_lang = "en"
    else:
        prefer_lang = "zh" if _has_cjk(user_text) else "en"

    def _ollama_translate_batch(titles: list) -> list:
        # Best-effort batch translation (titles only).
        # Try /api/generate first; fallback to /api/chat if generate returns empty.
        if not titles:
            return []

        # base url candidates (env first)
        base_candidates = []
        try:
            env_b = str(os.environ.get("OLLAMA_BASE_URL") or "").strip()
        except Exception:
            env_b = ""
        if env_b:
            base_candidates.append(env_b)
        base_candidates.append("http://192.168.1.162:11434")
        base_candidates.append("http://ollama:11434")
        base_candidates.append("http://127.0.0.1:11434")

        model = str(os.environ.get("NEWS_TRANSLATE_MODEL") or os.environ.get("OLLAMA_TRANSLATE_MODEL") or "qwen3:1.7b").strip() or "qwen3:1.7b"

        # numbered lines in, lines out
        in_lines = []
        i = 1
        for t in titles:
            s = str(t or "").strip()
            if not s:
                s = "(empty)"
            if len(s) > 180:
                s = s[:180].rstrip() + "…"
            in_lines.append(str(i) + ". " + s)
            i += 1

        user_prompt = (
            "把下面每一行英文标题翻译成中文。\n"
            "要求：只输出对应的中文标题列表，每行一个，不要加解释，不要加序号，不要加任何多余文字。\n"
            "保留专有名词/型号/人名的原文或常见译名。\n\n"
            + "\n".join(in_lines)
        )

        def _clean_lines(txt: str) -> list:
            out = [x.strip() for x in str(txt or "").splitlines() if x.strip()]
            cleaned = []
            for x in out:
                x2 = re.sub(r"^\s*\d+\s*[\.|\)|、]\s*", "", x).strip()
                if x2:
                    cleaned.append(x2)
            return cleaned

        # try bases
        for base in base_candidates:
            try:
                b = str(base or "").strip().rstrip("/")
                if not b:
                    continue

                # 1) /api/generate
                gen_payload = {
                    "model": model,
                    "prompt": user_prompt,
                    "stream": False,
                    "keep_alive": -1,
                    "options": {"temperature": 0.0, "num_ctx": 2048, "num_predict": 256},
                }
                r = requests.post(b + "/api/generate", json=gen_payload, timeout=30)
                sc = int(getattr(r, "status_code", 0) or 0)
                if sc < 400:
                    j = r.json() if hasattr(r, "json") else {}
                    if isinstance(j, dict) and j.get("error"):
                        pass
                    else:
                        txt = str((j.get("response") or "")).strip()
                        cleaned = _clean_lines(txt)
                        if cleaned:
                            return cleaned

                # 2) fallback /api/chat
                chat_payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "你是一个翻译器。只做中英文标题翻译。"},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "keep_alive": -1,
                    "options": {"temperature": 0.0, "num_ctx": 2048},
                }
                r2 = requests.post(b + "/api/chat", json=chat_payload, timeout=45)
                sc2 = int(getattr(r2, "status_code", 0) or 0)
                if sc2 >= 400:
                    continue
                j2 = r2.json() if hasattr(r2, "json") else {}
                if isinstance(j2, dict) and j2.get("error"):
                    continue
                msg = j2.get("message") if isinstance(j2, dict) else None
                content = ""
                if isinstance(msg, dict):
                    content = str((msg.get("content") or "")).strip()
                cleaned2 = _clean_lines(content)
                if cleaned2:
                    return cleaned2

            except Exception:
                continue

        return []

    def _kw_hit(text_s: str, kws: list) -> bool:
        if not text_s:
            return False
        t0 = (text_s or "").lower()
        for k in (kws or []):
            kk = (k or "").strip().lower()
            if not kk:
                continue
            if kk in t0:
                return True
        return False

    def _norm_title(s: str) -> str:
        s2 = _ug_clean_unicode(s or "")
        s2 = s2.lower()
        s2 = re.sub(r"\s+", " ", s2).strip()
        return s2

    cats = _mf_req("/v1/categories")
    if not cats.get("ok"):
        return {"ok": False, "error": "failed to fetch miniflux categories", "detail": cats, "category": category, "time_range": "24h", "limit": limit, "items": [], "final": "Miniflux categories 拉取失败。"}

    categories = cats.get("data") or []
    key = (category or "").strip()

    aliases_map = {
        "world": ["world（世界新闻）", "世界新闻", "国际"],
        "cn_economy": ["cn_finance（中国财经）", "中国财经", "财经", "中国经济"],
        "au_politics": [
        "australia",
        "australian",
        "canberra",
        "parliament house",
        "commonwealth",
        "federal",
        "government",
        "opposition",
        "prime minister",
        "pm",
        "minister",
        "mp",
        "senator",
        "treasurer",
        "albanese",
        "dutton",
        "labor",
        "liberal",
        "greens",
        "coalition",
        "new south wales",
        "victoria",
        "queensland",
        "western australia",
        "south australia",
        "tasmania",
        "northern territory",
        "australian capital territory",
        "australian parliament",
        "澳",
        "澳洲",
        "澳大利亚",
        "联邦",
        "堪培拉",
        "议会",
        "政府",
        "反对党",
        "总理",
        "部长",
        "议员",
        "工党",
        "自由党",
        "绿党",
],
        "mel_life": ["mel_life（墨尔本民生）", "墨尔本民生", "维州民生", "Victoria"],
        "tech_internet": ["tech_internet（互联网科技）", "互联网科技", "科技", "Tech"],
        "tech_gadgets": ["tech_gadgets（数码产品）", "数码产品", "评测", "Gadgets"],
        "gaming": ["gaming（电子游戏）", "电子游戏", "游戏", "Gaming"],
    }

    def _match_cat_id(k: str):
        if not k:
            return None
        for c in categories:
            try:
                title = (c.get("title") or "").strip()
                if title == k:
                    return int(c.get("id"))
            except Exception:
                continue
        for c in categories:
            try:
                title = (c.get("title") or "").strip()
                if title.startswith(k) or (k in title):
                    return int(c.get("id"))
            except Exception:
                continue
        for al in (aliases_map.get(k) or []):
            for c in categories:
                try:
                    title = (c.get("title") or "").strip()
                    if (al in title) or title == al:
                        return int(c.get("id"))
                except Exception:
                    continue
        return None

    cat_id = _match_cat_id(key)
    if cat_id is None:
        return {"ok": True, "category": key, "time_range": "24h", "limit": limit, "items": [], "final": "Miniflux 中找不到对应分类：{0}".format(key), "query_used": "miniflux categories title match"}

    STRICT_WHITELIST_CATS = set(["au_politics"])
    FILTERS = {
        "world": {"whitelist": [], "blacklist": ["ufc", "mma", "boxing odds", "celebrity gossip", "porn", "onlyfans"]},
        "cn_economy": {"whitelist": ["财经", "经济", "金融", "股", "a股", "港股", "美股", "债", "基金", "利率", "通胀", "人民币", "央行", "证监", "bank", "stocks", "market", "bond", "yields", "cpi", "gdp"],
                      "blacklist": ["ufc", "mma", "赛后", "足球", "篮球", "综艺", "八卦", "明星", "电影", "电视剧"]},
        "au_politics": {"whitelist": ["parliament", "senate", "house", "election", "labor", "coalition", "liberal", "greens", "albanese", "dutton", "budget", "treasury", "immigration", "visa", "minister", "cabinet", "议会", "选举", "工党", "自由党", "绿党", "预算", "内阁", "移民", "签证"],
                        "blacklist": ["ufc", "mma", "sport", "match preview", "odds", "celebrity"]},
        "mel_life": {"whitelist": ["melbourne", "victoria", "vic", "cbd", "ptv", "metro", "tram", "train", "bus", "police", "fire", "ambulance", "road", "freeway", "yarra", "docklands", "st kilda", "墨尔本", "维州", "本地", "民生", "交通", "电车", "火车", "警方", "火警", "道路"],
                     "blacklist": ["ufc", "mma", "celebrity", "gossip", "crypto shill"]},
        "tech_internet": {"whitelist": ["ai", "openai", "google", "microsoft", "meta", "apple", "amazon", "tiktok", "x.com", "twitter", "github", "open source", "linux", "android", "ios", "cloud", "security", "privacy", "regulation", "chip", "semiconductor", "人工智能", "开源", "网络安全", "隐私", "监管", "芯片", "半导体"],
                         "blacklist": ["ufc", "mma", "crime", "murder", "celebrity", "gossip", "lottery", "horoscope"]},
        "tech_gadgets": {"whitelist": ["review", "hands-on", "launch", "iphone", "ipad", "mac", "samsung", "pixel", "camera", "laptop", "headphones", "oled", "cpu", "gpu", "benchmark", "评测", "上手", "新品", "发布", "开箱", "相机", "手机", "耳机", "笔记本"],
                        "blacklist": ["ufc", "mma", "crime", "celebrity", "gossip"]},
        "gaming": {"whitelist": ["game", "gaming", "steam", "playstation", "ps5", "xbox", "nintendo", "switch", "patch", "update", "dlc", "release", "trailer", "esports", "游戏", "主机", "更新", "补丁", "发售", "预告"],
                   "blacklist": ["ufc", "mma", "boxing", "wwe", "football", "basketball", "cricket", "horse racing"]},
    }

    import time as _time
    after_ts = int(_time.time()) - 24 * 3600

    try:
        lim_int = int(limit)
    except Exception:
        lim_int = 5
    if lim_int < 1:
        lim_int = 1
    if lim_int > 10:
        lim_int = 10

    fetch_lim = lim_int * 6
    if fetch_lim < 20:
        fetch_lim = 20
    if fetch_lim > 80:
        fetch_lim = 80

    params = {"order": "published_at", "direction": "desc", "limit": fetch_lim, "after": after_ts}
    ent = _mf_req("/v1/categories/{0}/entries".format(cat_id), params=params)
    if not ent.get("ok"):
        return {"ok": False, "error": "failed to fetch entries", "detail": ent, "category": key, "time_range": "24h", "limit": lim_int, "items": [], "final": "Miniflux entries 拉取失败。"}

    payload = ent.get("data") or {}
    entries = payload.get("entries") or []
    if not entries:
        return {"ok": True, "category": key, "time_range": "24h", "limit": lim_int, "items": [], "final": "暂无符合最近24小时的条目。", "query_used": "miniflux category_id={0} after={1}".format(cat_id, after_ts)}

    all_items = []
    for e in entries:
        try:
            title = (e.get("title") or "").strip()
            url = (e.get("url") or "").strip() or (e.get("comments_url") or "").strip()
            drop_video = (os.environ.get("NEWS_DROP_VIDEO") or "1").strip().lower()
            if drop_video not in ("0", "false", "no", "off"):
                if _news__is_video_entry(title, url):
                    continue
            published_at_raw = (e.get("published_at") or "").strip()
            published_at = _to_local_time(published_at_raw)
            feed = e.get("feed") or {}
            src = (feed.get("title") or "").strip()
            content_plain = _strip_html((e.get("content") or "").strip())
            snippet = content_plain
            if len(snippet) > 180:
                snippet = snippet[:180].rstrip() + "..."
            is_zh = _has_cjk((title or "") + " " + (content_plain or ""))
            all_items.append({
                "title": title,
                "url": url,
                "published_at": published_at,
                "published_at_raw": published_at_raw,
                "source": src,
                "snippet": snippet,
                "is_zh": is_zh,
                "content_plain": content_plain,
            })
        except Exception:
            continue

    cfg = FILTERS.get(key) or {"whitelist": [], "blacklist": []}
    wl = cfg.get("whitelist") or []
    bl = cfg.get("blacklist") or []
    dropped_blacklist = 0
    dropped_whitelist = 0
    dropped_anchor = 0
    dropped_intlban = 0
    relax_used = 0
    STRICT_WL_CATS = set(["au_politics"])
    require_wl = True if (key in STRICT_WL_CATS) else False

    def _passes_blacklist(it: dict) -> bool:
        txt = "{0} {1} {2}".format(it.get("title") or "", it.get("snippet") or "", it.get("source") or "")
        return (not _kw_hit(txt, bl))

    def _passes_whitelist(it: dict) -> bool:
        if not wl:
            return True
        txt = "{0} {1}".format(it.get("title") or "", it.get("snippet") or "")
        return _kw_hit(txt, wl)

    MUST_ANCHOR = {

        "au_politics": [

            "australia", "australian", "canberra", "parliament house", "commonwealth",

            "aec", "aph.gov.au", "pm.gov.au",

            "act", "nsw", "vic", "qld", "wa", "sa", "tas", "nt",

            "albanese", "dutton", "labor", "liberal", "greens", "coalition",

            "澳", "澳洲", "澳大利亚", "联邦", "堪培拉", "议会", "工党", "自由党", "绿党",

        ],

        "mel_life": [

            "melbourne", "victoria", "vic", "cbd", "ptv", "metro", "tram", "train", "bus",

            "yarra", "docklands", "st kilda",

            "墨尔本", "维州", "本地", "民生", "交通", "电车", "火车",

        ],

    }


    TOPIC_KWS = {

        "au_politics": [
        "parliament",
        "senate",
        "house",
        "cabinet",
        "minister",
        "shadow minister",
        "opposition",
        "election",
        "vote",
        "ballot",
        "campaign",
        "budget",
        "treasury",
        "tax",
        "spending",
        "funding",
        "policy",
        "bill",
        "law",
        "laws",
        "legislation",
        "reform",
        "inquiry",
        "royal commission",
        "immigration",
        "visa",
        "citizenship",
        "asylum",
        "home affairs",
        "national security",
        "defence",
        "foreign minister",
        "议会",
        "参议院",
        "众议院",
        "内阁",
        "部长",
        "影子部长",
        "反对党",
        "选举",
        "投票",
        "竞选",
        "预算",
        "财政",
        "税",
        "拨款",
        "政策",
        "法案",
        "法律",
        "立法",
        "改革",
        "调查",
        "移民",
        "签证",
        "国籍",
        "内政",
        "国防",
        "外交",
],

    }


    def _passes_anchor_topic(it: dict, strict: bool) -> bool:
        anchors0 = MUST_ANCHOR.get(key) or []
        topics0 = TOPIC_KWS.get(key) or []
        if (not anchors0) and (not topics0):
            return True

        title0 = it.get("title") or ""
        sn0 = it.get("snippet") or ""
        src0 = it.get("source") or ""
        txt_ts = "{0} {1}".format(title0, sn0)
        txt_all = "{0} {1} {2}".format(title0, sn0, src0)

        if key == "au_politics":
            # 只用 title/snippet 做判断，避免 source(Just In) 等导致误命中
            anchors = []
            for a in (anchors0 or []):
                aa = (a or "").strip()
                if not aa:
                    continue
                # 中文锚点保留；英文锚点要求长度>=4，避免 act/vic/wa 这类子串误命中
                try:
                    is_cjk = _has_cjk(aa)
                except Exception:
                    is_cjk = False
                if is_cjk:
                    anchors.append(aa)
                    continue
                if len(aa) >= 4:
                    anchors.append(aa)

            topics = topics0
            intl_ban = ["bangladesh", "pakistan", "dhaka", "sheikh hasina", "孟加拉", "巴基斯坦", "达卡", "哈西娜", "谢赫"]
            if _kw_hit(txt_ts, intl_ban):
                return False

            # au_politics：必须同时满足 AU anchor + politics topic
            if anchors and (not _kw_hit(txt_ts, anchors)):
                return False
            if topics and (not _kw_hit(txt_ts, topics)):
                return False
            return True

        # 其它分类：允许 source 参与 anchor 判断（保持原行为）
        if anchors0 and (not _kw_hit(txt_all, anchors0)):
            return False
        return True
    def _pick(items_in: list, require_wl: bool, need: int, picked: list, seen_titles: set):
        nonlocal dropped_blacklist, dropped_whitelist, dropped_anchor, dropped_intlban, relax_used
        # Strict categories: never relax whitelist (keep category clean even if fewer items)
        try:
            if key in STRICT_WHITELIST_CATS:
                require_wl = True
        except Exception:
            pass
        if need <= 0:
            return
        for it in (items_in or []):
            if need <= 0:
                break
            if not isinstance(it, dict):
                continue
            if not _passes_blacklist(it):
                dropped_blacklist += 1
                continue
            if require_wl and (not _passes_whitelist(it)):
                dropped_whitelist += 1
                continue
            if not _passes_anchor_topic(it, require_wl):
                continue
            nt = _norm_title(it.get("title") or "")
            if nt and nt in seen_titles:
                continue
            seen_titles.add(nt)
            picked.append(it)
            need -= 1

    prefer = (prefer_lang or "zh").strip().lower()
    if prefer not in ["zh", "en"]:
        prefer = "zh"

    zh_items = [x for x in all_items if bool(x.get("is_zh"))]
    en_items = [x for x in all_items if not bool(x.get("is_zh"))]

    picked = []
    seen = set()

    if prefer == "zh":
        _pick(zh_items, True, lim_int - len(picked), picked, seen)
        _pick(en_items, True, lim_int - len(picked), picked, seen)
    else:
        _pick(en_items, True, lim_int - len(picked), picked, seen)
        _pick(zh_items, True, lim_int - len(picked), picked, seen)

    if len(picked) < lim_int:
        if prefer == "zh":
            _pick(zh_items, False, lim_int - len(picked), picked, seen)
            _pick(en_items, False, lim_int - len(picked), picked, seen)
        else:
            _pick(en_items, False, lim_int - len(picked), picked, seen)
            _pick(zh_items, False, lim_int - len(picked), picked, seen)

    if len(picked) < lim_int:
        for it in all_items:
            if len(picked) >= lim_int:
                break
            nt = _norm_title(it.get("title") or "")
            if nt and nt in seen:
                continue
            seen.add(nt)
            picked.append(it)

    out_items = picked[:lim_int]

    # Build voice title field (translate EN titles when prefer_lang=zh)
    try:
        want_zh = (str(prefer_lang or "").strip().lower() == "zh")
    except Exception:
        want_zh = True
    # NEWS_DISABLE_TRANSLATE_V1
    # If set, skip EN->ZH translation and output English titles directly (faster + avoid HA tool timeout)
    try:
        _dis = str(os.environ.get("NEWS_TRANSLATE_DISABLE") or "").strip().lower()
        if _dis in ["1", "true", "yes", "on"]:
            want_zh = False
    except Exception:
        pass

    if want_zh:
        need = []
        need_idx = []
        for ii, it in enumerate(out_items):
            try:
                tt = str(it.get("title") or "").strip()
            except Exception:
                tt = ""
            if not tt:
                continue
            if _has_cjk(tt):
                it["title_voice"] = _news__strip_title_tail(tt)

            else:
                need.append(tt)
                need_idx.append(ii)
        if need:
            tr = _ollama_translate_batch(need)
            if tr and (len(tr) >= len(need_idx)):
                for k, ii in enumerate(need_idx):
                    out_items[ii]["title_voice"] = str(tr[k] or "").strip() or str(out_items[ii].get("title") or "").strip()
            else:
                # fallback: keep English if translation failed
                for ii in need_idx:
                    out_items[ii]["title_voice"] = str(out_items[ii].get("title") or "").strip()
    else:
        for it in out_items:
            try:
                it["title_voice"] = _news__strip_title_tail(str(it.get("title") or "").strip())

            except Exception:
                pass


    lines = []
    # NEWS_TRANSLATE_TITLES_V3
    # If prefer_lang=zh and selected items are English, translate titles and write into title_voice.
    try:
        if prefer_lang == "zh" and isinstance(out_items, list) and out_items:
            need = []
            need_idx = []
            for _idx, _it in enumerate(out_items):
                _t0 = str((_it.get("title_voice") or _it.get("title") or "")).strip()
                if _t0 and (not _has_cjk(_t0)):
                    need.append(_t0)
                    need_idx.append(_idx)
            if need:
                zh_list = _ollama_translate_batch(need)
                if isinstance(zh_list, list) and zh_list:
                    _n = min(len(zh_list), len(need_idx))
                    for j in range(_n):
                        _zt = str(zh_list[j] or "").strip()
                        if _zt and _has_cjk(_zt):
                            out_items[need_idx[j]]["title_voice"] = _zt
    except Exception:
        pass

    # NEWS_APPLY_TITLE_VOICE_CHAT_V4
    try:
        if prefer_lang == "zh" and isinstance(out_items, list) and out_items:
            need = []
            need_idx = []
            for _idx, _it in enumerate(out_items):
                _t0 = str((_it.get("title_voice") or _it.get("title") or "")).strip()
                if _t0 and (not _has_cjk(_t0)):
                    need.append(_t0)
                    need_idx.append(_idx)
            if need:
                zh_list = _translate_titles_chat(need)
                if isinstance(zh_list, list) and zh_list:
                    n = min(len(zh_list), len(need_idx))
                    for j in range(n):
                        zt = str(zh_list[j] or "").strip()
                        if zt and _has_cjk(zt):
                            out_items[need_idx[j]]["title_voice"] = zt
    except Exception:
        pass

    for i, it in enumerate(out_items, 1):
        t = it.get("title_voice") or it.get("title") or ""
        u = it.get("url") or ""
        src = it.get("source") or ""
        pa = it.get("published_at") or ""
        sn = it.get("snippet") or ""
        lines.append("{0}) {1}".format(i, t))
        meta = []
        if src:
            meta.append(src)
        if pa:
            meta.append(pa)
        if meta:
            lines.append("   [{0}]".format(" | ".join(meta)))
        if sn:
            lines.append("   {0}".format(sn))
        if u:
            lines.append("   {0}".format(u))

    ret = {
        "ok": True,
        "category": key,
        "time_range": "24h",
        "limit": lim_int,
        "items": out_items,
        "final": "\n".join(lines).strip(),
        "query_used": "miniflux category_id={0} after={1} fetch_limit={2}".format(cat_id, after_ts, fetch_lim),
        "stats": {"fetched": len(all_items), "zh_fetched": len(zh_items), "en_fetched": len(en_items), "returned": len(out_items)},
        "stats_detail": {"dropped_blacklist": dropped_blacklist, "dropped_whitelist": dropped_whitelist, "dropped_anchor": dropped_anchor, "dropped_intlban": dropped_intlban, "relax_used": relax_used},
    }


    if ("final_voice" not in ret) or (not str(ret.get("final_voice") or "").strip()):
        # NEWS_FORCE_ENGLISH_V1
        try:
            _dis = str(os.environ.get("NEWS_TRANSLATE_DISABLE") or "").strip().lower()
            if _dis in ["1", "true", "yes", "on"]:
                _its = ret.get("items") or []
                if isinstance(_its, list):
                    for _it in _its:
                        if isinstance(_it, dict):
                            _t = str(_it.get("title") or "").strip()
                            if _t:
                                _it["title_voice"] = _t
        except Exception:
            pass

        # NEWS_DISABLE_TRANSLATE_LOCK_V1
        # Translation is DISABLED by default. Only enable if NEWS_TRANSLATE_DISABLE is explicitly set to 0/false/off.
        try:
            _raw = os.environ.get("NEWS_TRANSLATE_DISABLE")
            if _raw is None:
                _dis = "1"  # default disabled
            else:
                _dis = str(_raw).strip().lower()
            _enabled = (_dis in ["0", "false", "no", "off"])
            if not _enabled:
                _its = ret.get("items") or []
                if isinstance(_its, list):
                    for _it in _its:
                        if isinstance(_it, dict):
                            _t = str(_it.get("title") or "").strip()
                            if _t:
                                _it["title_voice"] = _t
        except Exception:
            pass

        ret["final_voice"] = _news__format_voice_miniflux(ret.get("items") or [], ret.get("limit") or 5)

        # NEWS_SYNC_TITLE_VOICE_FROM_FINAL_VOICE
        try:
            _fv = str(ret.get("final_voice") or "").strip()
            _its = ret.get("items")
            if _fv and isinstance(_its, list) and _its:
                _tlist = []
                for _ln in [x.strip() for x in _fv.splitlines() if str(x or "").strip()]:
                    _m = re.match(r"^\s*\d+\)\s*(.+?)\s*$", _ln)
                    if _m:
                        _t = str(_m.group(1) or "").strip()
                        if _t:
                            _tlist.append(_t)
                _n = min(len(_tlist), len(_its))
                for _i in range(_n):
                    try:
                        if isinstance(_its[_i], dict) and _tlist[_i]:
                            _its[_i]["title_voice"] = _tlist[_i]
                    except Exception:
                        pass
        except Exception:
            pass
    return ret

def _news__norm_host(host: str) -> str:
    h = (host or "").lower().split(":", 1)[0]
    for pfx in ("www.", "m.", "amp."):
        if h.startswith(pfx):
            h = h[len(pfx):]
    return h

def _news__extract_limit(text: str, default: int = 5) -> int:
    t = text or ""
    m = re.search(r"(\d{1,2})\s*(条|則|则|个|篇)", t)
    if not m:
        m = re.search(r"top\s*(\d{1,2})", t, flags=re.I)
    if not m:
        return default
    try:
        n = int(m.group(1))
    except Exception:
        return default
    if n < 1:
        return 1
    if n > 10:
        return 10
    return n

def _news_category_from_text(text: str) -> str:
    t = (text or "").lower()
    if ("墨尔本" in t) or ("melbourne" in t) or ("维州" in t) or ("victoria" in t) or ("本地" in t and "新闻" in t):
        return "mel_life"
    if ("澳洲" in t or "澳大利亚" in t or "australia" in t) and ("政治" in t or "议会" in t or "工党" in t or "自由党" in t):
        return "au_politics"
    if ("财经" in t) or ("股市" in t) or ("a股" in t) or ("经济" in t and "中国" in t):
        return "cn_economy"
    if ("数码" in t) or ("手机" in t) or ("相机" in t) or ("电脑" in t) or ("评测" in t) or ("新品" in t):
        return "tech_gadgets"
    if ("互联网" in t) or ("ai" in t) or ("人工智能" in t) or ("开源" in t) or ("科技" in t):
        return "tech_internet"
    if ("游戏" in t) or ("steam" in t) or ("ps5" in t) or ("xbox" in t) or ("switch" in t):
        return "gaming"
    if ("世界" in t) or ("国际" in t) or ("world" in t):
        return "world"
    if "新闻" in t or "要闻" in t:
        return "world"
    return "world"

def _llm_router_enabled() -> bool:
    v = str(os.environ.get("ROUTER_LLM_ENABLE") or "1").strip().lower()
    return v not in ["0", "false", "no", "off"]


def _llm_router_model() -> str:
    m = str(os.environ.get("ROUTER_LLM_MODEL") or "qwen3:4b-instruct").strip()
    if not m:
        return "qwen3:4b-instruct"
    return m


def _llm_router_timeout() -> float:
    raw = str(os.environ.get("ROUTER_LLM_TIMEOUT") or "5.0").strip()
    try:
        x = float(raw)
    except Exception:
        x = 5.0
    if x < 0.8:
        x = 0.8
    if x > 8.0:
        x = 8.0
    return x


def _llm_router_conf_threshold() -> float:
    raw = str(os.environ.get("ROUTER_LLM_CONF") or "0.75").strip()
    try:
        x = float(raw)
    except Exception:
        x = 0.75
    if x < 0.4:
        x = 0.4
    if x > 0.95:
        x = 0.95
    return x


def _llm_route_decide(text: str, prefer_lang: str):
    if not _llm_router_enabled():
        return None
    t = str(text or "").strip()
    if not t:
        return None
    # Keep latency bounded on very long prompts.
    if len(t) > 500:
        t = t[:500]
    base = str(os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip().rstrip("/")
    if not base:
        return None
    url = base + "/api/chat"
    labels = "weather,calendar,holiday,bills,news,music,poi,web,smalltalk"
    sys_prompt = (
        "You are a strict intent router for a smart home assistant. "
        "Choose exactly one label from: " + labels + ". "
        "Routing policy: "
        "weather=weather/umbrella/rain/temperature; "
        "calendar=schedule/events; "
        "holiday=public holidays; "
        "bills=bill processing/report/sync; "
        "news=explicit news requests; "
        "music=play/pause/volume/next; "
        "poi=opening hours/address/phone/parking place; "
        "web=how-to, product info, facts, recommendations, generic search; "
        "smalltalk=brief greetings/thanks/chitchat only. "
        "If uncertain between smalltalk and web, choose web. "
        "Return one line only in this exact format: "
        "label=<label>;confidence=<0.00-1.00>;reason=<short>. "
        "Do not output anything else."
    )
    user_prompt = "language={0}; text={1}".format(prefer_lang or "", t)
    payload = {
        "model": _llm_router_model(),
        "stream": False,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.0},
    }
    try:
        r = requests.post(url, json=payload, timeout=_llm_router_timeout())
    except Exception:
        return None
    code = int(getattr(r, "status_code", 0) or 0)
    if code < 200 or code >= 300:
        return None
    try:
        obj = r.json()
    except Exception:
        return None
    content = str(((obj.get("message") or {}).get("content")) or "").strip()
    if not content:
        return None
    m1 = re.search(r"label\s*=\s*([a-z_]+)", content, flags=re.I)
    m2 = re.search(r"confidence\s*=\s*([0-9]*\.?[0-9]+)", content, flags=re.I)
    m3 = re.search(r"reason\s*=\s*(.+)$", content, flags=re.I)
    if not m1:
        return None
    label = str(m1.group(1) or "").strip().lower()
    allow = {"weather", "calendar", "holiday", "bills", "news", "music", "poi", "web", "smalltalk"}
    if label not in allow:
        return None
    conf = 0.0
    if m2:
        try:
            conf = float(m2.group(1))
        except Exception:
            conf = 0.0
    if conf < 0.0:
        conf = 0.0
    if conf > 1.0:
        conf = 1.0
    reason = str(m3.group(1) if m3 else "").strip()
    return {"label": label, "confidence": conf, "reason": reason, "raw": content}



def _is_web_search_query(text: str) -> bool:
    """
    Heuristic: decide whether we should use web search (semi-structured retrieval).
    Conservative triggers:
      - explicit "搜索/查询/查一下/帮我查/帮我搜索" or "search/look up"
      - recency words ("最新/现在/今天/目前/本周/本月/版本/价格/多少") or explicit year 20xx (>=2024)
    """
    t = (text or "").strip()
    if not t:
        return False
    tl = t.lower()

    explicit = ["搜索", "查询", "检索", "查一下", "查查", "查一查", "帮我查", "帮我搜索"]
    for k in explicit:
        if k in t:
            return True

    for k in ["search", "lookup", "look up", "google", "bing", "brave"]:
        if k in tl:
            return True

    rec = ["最新", "现在", "目前", "今天", "昨日", "昨天", "本周", "这周", "本月", "这个月", "更新", "版本",
           "多少钱", "价格", "多少", "排名", "榜单", "gdp", "population", "斩杀线"]
    for k in rec:
        if k in t:
            return True
    for k in ["latest", "current", "today", "this week", "this month"]:
        if k in tl:
            return True

    m = re.search(r"(20\d{2})", t)
    if m:
        try:
            y = int(m.group(1))
            if y >= 2024:
                return True
        except Exception:
            pass

    return False


def _web__strip_search_prefix(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    prefixes = [
        r"^\s*(请\s*)?(帮我\s*)?(搜索|查询|检索|查一下|查查|查一查)\s*",
        r"^\s*(please\s*)?(search|look\s*up|lookup)\s*",
    ]
    for p in prefixes:
        try:
            t2 = re.sub(p, "", t, flags=re.IGNORECASE).strip()
            if t2 and (t2 != t):
                t = t2
                break
        except Exception:
            pass
    return t.strip().strip('，。,.!?！？"“”\'')


def _web__render_narrative(query: str, items: list, lang: str) -> str:
    # Deterministic, low-hallucination, voice-friendly renderer.
    # Only uses title/url/snippet from results; no extra facts.
    # Env:
    #   WEB_SEARCH_MAX_SOURCES (default 2, max 3)
    #   WEB_SEARCH_INCLUDE_URLS (default false)
    #   WEB_SEARCH_SNIPPET_MAX (default 180, max 320)

    q = (query or "").strip()

    try:
        max_sources = int(os.getenv("WEB_SEARCH_MAX_SOURCES", "2"))
    except Exception:
        max_sources = 2
    if max_sources < 1:
        max_sources = 1
    if max_sources > 3:
        max_sources = 3

    include_urls = str(os.getenv("WEB_SEARCH_INCLUDE_URLS", "false")).strip().lower() in ["1", "true", "yes", "y", "on"]

    try:
        snip_max = int(os.getenv("WEB_SEARCH_SNIPPET_MAX", "180"))
    except Exception:
        snip_max = 180
    if snip_max < 80:
        snip_max = 80
    if snip_max > 320:
        snip_max = 320

    def _clean(s: str) -> str:
        s = str(s or "")
        # unescape HTML entities
        try:
            import html as _html
            s = _html.unescape(s)
        except Exception:
            pass
        # strip HTML tags like <strong>
        s = re.sub(r"<[^>]+>", "", s)
        # normalize separators/bullets
        s = s.replace("·", " ")
        s = s.replace("…", "...")
        # collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _pick(it):
        if not isinstance(it, dict):
            return None
        title = _clean(it.get("title") or "")
        url = _clean(it.get("url") or "")
        sn = _clean(it.get("snippet") or it.get("content") or "")
        if not title and not url and not sn:
            return None
        if sn and len(sn) > snip_max:
            sn = sn[:snip_max].rstrip(" ,;:，。") + "..."
        return {"title": title, "url": url, "snippet": sn}

    picked = []
    for it in (items or []):
        p = _pick(it)
        if p:
            picked.append(p)
        if len(picked) >= max_sources:
            break

    is_zh = str(lang or "").lower().startswith("zh")
    if not picked:
        return "我没找到特别靠谱的结果，你可以把关键词说得更具体一点再试一次。" if is_zh else "I couldn't find reliable results. Try a more specific query."

    def _title_brief(t):
        t = (t or "").strip()
        if not t:
            return "网页" if is_zh else "a page"
        # keep it short for TTS
        if len(t) > 48:
            t = t[:48].rstrip(" -—|") + "..."
        return t

    out = []
    p1 = picked[0]
    t1 = _title_brief(p1.get("title") or "")
    s1 = (p1.get("snippet") or "").strip()
    if not s1:
        s1 = "这条结果没有给摘要。" if is_zh else "This result did not include a snippet."

    if is_zh:
        if q:
            out.append("关于「{0}」，资料里一般这样描述：{1}（{2}）。".format(q, s1, t1))
        else:
            out.append("资料里一般这样描述：{0}（{1}）。".format(s1, t1))
    else:
        if q:
            out.append("About “{0}”, sources generally describe it like this: {1} ({2}).".format(q, s1, t1))
        else:
            out.append("Sources describe it like this: {0} ({1}).".format(s1, t1))

    if len(picked) >= 2:
        p2 = picked[1]
        t2 = _title_brief(p2.get("title") or "")
        s2 = (p2.get("snippet") or "").strip()
        if not s2:
            s2 = "这条结果没有给摘要。" if is_zh else "This result did not include a snippet."
        if is_zh:
            out.append("再补充一个角度：{0}（{1}）。".format(s2, t2))
        else:
            out.append("Another angle: {0} ({1}).".format(s2, t2))

    if include_urls:
        urls = []
        for p in picked:
            u = (p.get("url") or "").strip()
            if u:
                urls.append(u)
        if urls:
            out.append(("链接：" if is_zh else "Links: ") + ("；".join(urls) if is_zh else " ; ".join(urls)))

    return " ".join([x for x in out if x]).strip()


def _skill_detect_lang(text: str, default_lang: str = "zh") -> str:
    t = str(text or "")
    if re.search(r"[\u4e00-\u9fff]", t):
        return "zh"
    if re.search(r"[A-Za-z]", t):
        return "en"
    return str(default_lang or "zh")


def _skill_text_is_weak_or_empty(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return True
    bad = ["没找到", "暂无", "失败", "请补充", "尚未建立", "未配置", "未知原因", "重试", "无结果", "未命中"]
    for k in bad:
        if k in t:
            return True
    if re.search(r"没在.*找到", t):
        return True
    if re.search(r"未找到", t):
        return True
    if re.search(r"没有找到", t):
        return True
    if len(t) < 12:
        return True
    return False


def _skill_extract_facts_from_text(text: str, limit: int = 5) -> list:
    out = []
    t = str(text or "")
    if not t:
        return out
    for ln in t.splitlines():
        s = str(ln or "").strip()
        if not s:
            continue
        s = re.sub(r"^\d+\)\s*", "", s)
        s = re.sub(r"^[-*]\s*", "", s)
        s = re.sub(r"^[\u2022]\s*", "", s)
        if (not s) or s.startswith("内容命中") or s.startswith("找到与") or s.startswith("我整理了"):
            continue
        if _skill_text_is_weak_or_empty(s):
            continue
        out.append(s)
        if len(out) >= int(limit):
            break
    return out


def _skill_extract_sources_from_rag_text(text: str) -> list:
    sources = []
    t = str(text or "")
    if not t:
        return sources
    for ln in t.splitlines():
        s = str(ln or "").strip()
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        title = body
        day = ""
        m = re.search(r"^(.*?)\s*[（(](\d{4}-\d{2}-\d{2})[）)]\s*$", body)
        if m:
            title = str(m.group(1) or "").strip()
            day = str(m.group(2) or "").strip()
        if title:
            sources.append(_skill_source_item("local_rag", title, day, ""))
        if len(sources) >= 5:
            break
    return sources


def _skill_translate_rag_query(text: str, target_lang: str = "en") -> str:
    q = str(text or "").strip()
    tgt = str(target_lang or "").strip().lower()
    if (not q) or (tgt not in ["en", "zh"]):
        return ""
    if (tgt == "en") and (not re.search(r"[\u4e00-\u9fff]", q)):
        return q
    if (tgt == "zh") and re.search(r"[\u4e00-\u9fff]", q):
        return q
    base = str(os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip().rstrip("/")
    # Use a text model by default (VL models may return empty `content` on some Ollama versions).
    model = str(os.environ.get("RAG_QUERY_TRANSLATE_MODEL") or "qwen3:8b").strip()
    if not model:
        model = "qwen3:8b"
    try:
        timeout_sec = float(os.environ.get("RAG_QUERY_TRANSLATE_TIMEOUT_SEC") or "10")
    except Exception:
        timeout_sec = 10.0
    if timeout_sec < 3.0:
        timeout_sec = 3.0
    if timeout_sec > 30.0:
        timeout_sec = 30.0
    if tgt == "en":
        prompt = (
            "Translate this home knowledge search query into concise English keywords.\n"
            "Rules:\n"
            "1) Output only one line.\n"
            "2) Keep brand/model/entity names.\n"
            "3) Use 2-10 keywords.\n"
            "4) No explanation.\n"
            "Query: " + q
        )
        system = "You output concise English keywords only."
    else:
        prompt = (
            "把这个家庭资料库检索词翻译成简洁中文关键词。\n"
            "规则：\n"
            "1) 只输出一行。\n"
            "2) 保留品牌/型号/实体名。\n"
            "3) 2-10 个关键词。\n"
            "4) 不解释。\n"
            "Query: " + q
        )
        system = "你只输出简洁中文关键词，不要解释。"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    try:
        r = requests.post(base + "/api/chat", json=payload, timeout=timeout_sec)
        if int(getattr(r, "status_code", 0) or 0) >= 400:
            return ""
        data = r.json() if hasattr(r, "json") else {}
        msg = data.get("message") if isinstance(data, dict) else {}
        out = str((msg or {}).get("content") or "").strip()
        if not out:
            # qwen3-vl may place output in thinking; harmless fallback for other models.
            out = str((msg or {}).get("thinking") or "").strip()
        out = re.sub(r"[\r\n\t]+", " ", out).strip()
        out = re.sub(r"\s+", " ", out).strip()
        if tgt == "en":
            out = re.sub(r"[^A-Za-z0-9\-\+\s]", " ", out)
            out = re.sub(r"\s+", " ", out).strip()
        else:
            out = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9\-\+\s]", " ", out)
            out = re.sub(r"\s+", " ", out).strip()
        if len(out) > 160:
            out = out[:160].strip()
        return out
    except Exception:
        return ""


def _skill_merge_rag_sources(sources_a: list, sources_b: list, limit: int = 8) -> list:
    out = []
    seen = set()
    for arr in [sources_a or [], sources_b or []]:
        for it in arr:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            source = str(it.get("source") or "").strip()
            day = str(it.get("published_at") or "").strip()
            key = (title + "|" + source + "|" + day).lower()
            if (not title) or (key in seen):
                continue
            seen.add(key)
            out.append(_skill_source_item(source, title, day, str(it.get("url") or "")))
            if len(out) >= int(limit):
                return out
    return out


def _skill_qdrant_url() -> str:
    v = str(os.environ.get("QDRANT_URL") or "http://127.0.0.1:6333").strip().rstrip("/")
    return v


def _skill_qdrant_collection() -> str:
    v = str(os.environ.get("QDRANT_COLLECTION") or "ha_memory_qwen3").strip()
    return v or "ha_memory_qwen3"


def _skill_embed_model() -> str:
    v = str(os.environ.get("EMBED_MODEL") or "qwen3-embedding:0.6b").strip()
    return v or "qwen3-embedding:0.6b"


def _skill_ollama_base_url() -> str:
    v = str(os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").strip().rstrip("/")
    return v


def _skill_qdrant_vector_size() -> int:
    raw = str(os.environ.get("QDRANT_VECTOR_SIZE") or "1024").strip()
    try:
        n = int(raw)
    except Exception:
        n = 1024
    if n < 8:
        n = 1024
    return n


def _skill_embed_text(text: str) -> list:
    q = str(text or "").strip()
    if not q:
        return []
    payload = {"model": _skill_embed_model(), "input": q}
    try:
        timeout_sec = float(os.environ.get("EMBED_TIMEOUT_SEC") or "20")
    except Exception:
        timeout_sec = 20.0
    if timeout_sec < 3:
        timeout_sec = 3.0
    if timeout_sec > 60:
        timeout_sec = 60.0
    try:
        r = requests.post(_skill_ollama_base_url() + "/api/embed", json=payload, timeout=timeout_sec)
        if int(getattr(r, "status_code", 0) or 0) >= 400:
            return []
        obj = r.json() if hasattr(r, "json") else {}
        embs = obj.get("embeddings") if isinstance(obj, dict) else None
        if not isinstance(embs, list) or len(embs) <= 0:
            return []
        vec = embs[0] if isinstance(embs[0], list) else []
        if not isinstance(vec, list):
            return []
        out = []
        for x in vec:
            try:
                out.append(float(x))
            except Exception:
                out.append(0.0)
        if len(out) != _skill_qdrant_vector_size():
            return []
        return out
    except Exception:
        return []


def _skill_scope_to_tags(scope: str) -> list:
    s = str(scope or "").strip().lower()
    if not s:
        return []
    if s in ["资料库", "知识库", "rag", "kb"]:
        return []
    parts = [p.strip() for p in re.split(r"[,\n;|]+", s) if str(p or "").strip()]
    tags = []
    for p in parts:
        if p in ["processed_md", "processed-md", "processed", "pdf_md", "pdf-md"]:
            tags.append("scope:processed_md")
            continue
        if p in ["anytype", "note", "notes"]:
            tags.append("source:anytype")
            continue
        if p in ["export", "anytype_export", "file", "files"]:
            tags.append("source:export")
            continue
        # Treat as a directory tag (first path segment is usually enough).
        seg = p.replace("\\", "/").strip("/").split("/", 1)[0].strip()
        if seg:
            tags.append("dir:" + seg)
    out = []
    seen = set()
    for t in tags:
        tt = str(t or "").strip()
        if (not tt) or (tt in seen):
            continue
        seen.add(tt)
        out.append(tt)
    return out


def _skill_qdrant_upsert_points(points: list) -> dict:
    if not isinstance(points, list) or len(points) <= 0:
        return {"ok": False, "error": "empty_points"}
    url = _skill_qdrant_url() + "/collections/" + _skill_qdrant_collection() + "/points?wait=true"
    try:
        timeout_sec = float(os.environ.get("QDRANT_TIMEOUT_SEC") or "15")
    except Exception:
        timeout_sec = 15.0
    if timeout_sec < 3:
        timeout_sec = 3.0
    if timeout_sec > 60:
        timeout_sec = 60.0
    try:
        r = requests.put(url, json={"points": points}, timeout=timeout_sec)
        if int(getattr(r, "status_code", 0) or 0) >= 400:
            return {"ok": False, "error": "http_" + str(int(getattr(r, "status_code", 0) or 0)), "body": str(getattr(r, "text", "") or "")[:800]}
        return {"ok": True, "data": (r.json() if hasattr(r, "json") else {})}
    except Exception as e:
        return {"ok": False, "error": "request_failed", "message": str(e)}


def _skill_qdrant_search(query: str, top_k: int = 5, score_threshold: float = 0.35, user_id: str = "", scope_tags: list = None) -> list:
    q = str(query or "").strip()
    if not q:
        return []
    vec = _skill_embed_text(q)
    if not vec:
        return []
    lim = int(top_k or 5)
    if lim < 1:
        lim = 1
    if lim > 20:
        lim = 20
    body = {
        "vector": vec,
        "limit": lim,
        "with_payload": True,
    }
    uid = str(user_id or "").strip()
    filt = {}
    if uid:
        filt["must"] = [{"key": "user_id", "match": {"value": uid}}]
    stags = scope_tags if isinstance(scope_tags, list) else []
    stags = [str(x or "").strip() for x in stags if str(x or "").strip()]
    if stags:
        # Require at least one tag match (OR across tags).
        conds = [{"key": "tags", "match": {"value": t}} for t in stags[:12]]
        filt["min_should"] = {"conditions": conds, "min_count": 1}
    if filt:
        body["filter"] = filt
    if float(score_threshold or 0.0) > 0:
        body["score_threshold"] = float(score_threshold)
    url = _skill_qdrant_url() + "/collections/" + _skill_qdrant_collection() + "/points/search"
    try:
        timeout_sec = float(os.environ.get("QDRANT_TIMEOUT_SEC") or "15")
    except Exception:
        timeout_sec = 15.0
    if timeout_sec < 3:
        timeout_sec = 3.0
    if timeout_sec > 60:
        timeout_sec = 60.0
    try:
        r = requests.post(url, json=body, timeout=timeout_sec)
        if int(getattr(r, "status_code", 0) or 0) >= 400:
            return []
        obj = r.json() if hasattr(r, "json") else {}
        out = obj.get("result") if isinstance(obj, dict) else []
        if not isinstance(out, list):
            return []
        # If scope filter produced no hits, retry unscoped to avoid user confusion.
        if (len(out) == 0) and stags:
            body2 = dict(body)
            try:
                if "filter" in body2:
                    f2 = body2.get("filter") if isinstance(body2.get("filter"), dict) else {}
                    if isinstance(f2, dict):
                        f2.pop("min_should", None)
                        if (not f2.get("must")) and (not f2.get("must_not")) and (not f2.get("should")):
                            body2.pop("filter", None)
                        else:
                            body2["filter"] = f2
                r2 = requests.post(url, json=body2, timeout=timeout_sec)
                if int(getattr(r2, "status_code", 0) or 0) < 400:
                    obj2 = r2.json() if hasattr(r2, "json") else {}
                    out2 = obj2.get("result") if isinstance(obj2, dict) else []
                    if isinstance(out2, list):
                        out = out2
            except Exception:
                pass
        rows = []
        for it in out:
            if not isinstance(it, dict):
                continue
            payload = it.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            rows.append(
                {
                    "id": it.get("id"),
                    "score": float(it.get("score") or 0.0),
                    "payload": payload,
                }
            )
        return rows
    except Exception:
        return []


def _skill_qdrant_merge_hits(hits_a: list, hits_b: list, limit: int = 10) -> list:
    """Merge two qdrant hit lists by point id, keeping the higher score."""
    lim = int(limit or 10)
    if lim < 1:
        lim = 1
    if lim > 50:
        lim = 50

    by_id = {}
    order: List[str] = []
    for arr in (hits_a or [], hits_b or []):
        for it in arr:
            if not isinstance(it, dict):
                continue
            pid = str(it.get("id") or "").strip()
            if not pid:
                continue
            score = float(it.get("score") or 0.0)
            prev = by_id.get(pid)
            if prev is None:
                by_id[pid] = dict(it)
                order.append(pid)
            else:
                try:
                    prev_score = float(prev.get("score") or 0.0)
                except Exception:
                    prev_score = 0.0
                if score > prev_score:
                    by_id[pid] = dict(it)

    merged = [by_id[pid] for pid in order if pid in by_id]
    merged.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return merged[:lim]


def _skill_qdrant_search_bilingual(query: str, top_k: int = 5, score_threshold: float = 0.35, user_id: str = "", scope_tags: list = None) -> Tuple[list, str, str, bool]:
    """Try CN query and its EN keyword rewrite, then merge hits."""
    q = str(query or "").strip()
    if not q:
        return ([], "", "", False)

    q_has_zh = bool(re.search(r"[\u4e00-\u9fff]", q))
    if not q_has_zh:
        hits = _skill_qdrant_search(q, top_k=top_k, score_threshold=score_threshold, user_id=user_id, scope_tags=scope_tags)
        for h in hits:
            if isinstance(h, dict):
                h["matched_query"] = q
        return (hits, q, "", False)

    # Fast path: run CN search first. If we already have hits, don't block on translation.
    hits_cn = _skill_qdrant_search(q, top_k=top_k, score_threshold=score_threshold, user_id=user_id, scope_tags=scope_tags)
    for h in hits_cn:
        if isinstance(h, dict):
            h["matched_query"] = q

    if hits_cn:
        # When score_threshold is 0, any hit is fine.
        try:
            top_score = float(hits_cn[0].get("score") or 0.0) if isinstance(hits_cn[0], dict) else 0.0
        except Exception:
            top_score = 0.0
        if (float(score_threshold or 0.0) <= 0.0) or (top_score >= float(score_threshold or 0.0)):
            return (hits_cn, q, "", False)

    q_en = _skill_translate_rag_query(q, "en")
    hits_en = []
    if q_en and (q_en.lower() != q.lower()):
        hits_en = _skill_qdrant_search(q_en, top_k=top_k, score_threshold=score_threshold, user_id=user_id, scope_tags=scope_tags)
        for h in hits_en:
            if isinstance(h, dict):
                h["matched_query"] = q_en

    merged = _skill_qdrant_merge_hits(hits_cn, hits_en, limit=max(int(top_k or 5), 5))
    bilingual = bool(q_en and hits_en)
    return (merged, q, q_en, bilingual)


def _skill_qdrant_hits_to_sources(hits: list, limit: int = 5) -> list:
    out = []
    seen = set()
    for it in (hits or []):
        if not isinstance(it, dict):
            continue
        payload = it.get("payload") if isinstance(it.get("payload"), dict) else {}
        title = str(payload.get("title") or payload.get("object_title") or payload.get("text") or "").strip()
        if len(title) > 72:
            title = title[:72].rstrip() + "..."
        day = str(payload.get("updated_at") or payload.get("created_at") or "").strip()
        url = str(payload.get("url") or payload.get("deep_link") or "").strip()
        source = str(payload.get("source") or "qdrant").strip()
        key = (title + "|" + day + "|" + source).lower()
        if (not title) or (key in seen):
            continue
        seen.add(key)
        out.append(_skill_source_item(source, title, day, url))
        if len(out) >= int(limit):
            break
    return out


def _skill_qdrant_hits_to_facts(hits: list, limit: int = 5) -> list:
    out = []
    for it in (hits or []):
        if not isinstance(it, dict):
            continue
        payload = it.get("payload") if isinstance(it.get("payload"), dict) else {}
        txt = str(payload.get("text") or "").strip()
        if not txt:
            continue
        if len(txt) > 180:
            txt = txt[:180].rstrip() + "..."
        score = float(it.get("score") or 0.0)
        out.append("[" + format(score, ".3f") + "] " + txt)
        if len(out) >= int(limit):
            break
    return out


def _skill_qdrant_hits_to_final(query: str, hits: list, language: str = "zh") -> str:
    q = str(query or "").strip()
    is_zh = str(language or "").lower().startswith("zh")
    lines = []
    if is_zh:
        lines.append("向量记忆检索命中 " + str(len(hits or [])) + " 条。")
    else:
        lines.append("Vector memory hit " + str(len(hits or [])) + " items.")
    if q:
        lines.append(("查询：" if is_zh else "Query: ") + q)
    idx = 0
    for it in (hits or []):
        if not isinstance(it, dict):
            continue
        payload = it.get("payload") if isinstance(it.get("payload"), dict) else {}
        txt = str(payload.get("text") or "").strip()
        if not txt:
            continue
        if len(txt) > 200:
            txt = txt[:200].rstrip() + "..."
        idx += 1
        lines.append(str(idx) + ". " + txt + " (score=" + format(float(it.get("score") or 0.0), ".3f") + ")")
        if idx >= 5:
            break
    return "\n".join([x for x in lines if x]).strip()


def _skill_rag_lookup_core(query: str, scope: str = "", language: str = "zh") -> dict:
    q = str(query or "").strip()
    folder = str(scope or "").strip()
    scope_tags = _skill_scope_to_tags(folder)
    if not q:
        return {"final_text": "请告诉我你想在资料库里搜什么。", "facts": [], "sources": [], "hit_count": 0}
    try:
        vec_top_k = int(os.environ.get("MEMORY_TOP_K") or "5")
    except Exception:
        vec_top_k = 5
    if vec_top_k < 1:
        vec_top_k = 1
    if vec_top_k > 20:
        vec_top_k = 20
    try:
        vec_threshold = float(os.environ.get("MEMORY_SCORE_THRESHOLD") or "0.35")
    except Exception:
        vec_threshold = 0.35
    if vec_threshold < 0.0:
        vec_threshold = 0.0
    if vec_threshold > 1.0:
        vec_threshold = 1.0

    bilingual_enable = str(os.environ.get("MEMORY_BILINGUAL_ENABLE") or "").strip().lower() in ("1", "true", "yes", "on")
    if bilingual_enable:
        qdrant_hits, q_cn, q_en, bilingual = _skill_qdrant_search_bilingual(q, top_k=vec_top_k, score_threshold=vec_threshold, scope_tags=scope_tags)
    else:
        qdrant_hits = _skill_qdrant_search(q, top_k=vec_top_k, score_threshold=vec_threshold, scope_tags=scope_tags)
        q_cn, q_en, bilingual = "", "", False
    if len(qdrant_hits) > 0:
        return {
            "final_text": _skill_qdrant_hits_to_final(q, qdrant_hits, language=language),
            "facts": _skill_qdrant_hits_to_facts(qdrant_hits, limit=6),
            "sources": _skill_qdrant_hits_to_sources(qdrant_hits, limit=8),
            "hit_count": int(len(qdrant_hits)),
            "query_cn": str(q_cn or ""),
            "query_en": str(q_en or ""),
            "bilingual": bool(bilingual),
            "vector_hit_count": int(len(qdrant_hits)),
            "scope_tags": scope_tags,
            "route": "qdrant_vector",
        }

    q_has_zh = bool(re.search(r"[\u4e00-\u9fff]", q))
    q_cn = q if q_has_zh else _skill_translate_rag_query(q, "zh")
    q_en = _skill_translate_rag_query(q, "en")
    if not q_cn:
        q_cn = q if q_has_zh else ""
    if not q_en:
        q_en = q if (not q_has_zh) else ""

    final_cn = ""
    final_en = ""
    sources_cn = []
    sources_en = []
    if q_cn:
        final_cn = _rag_search_content(q_cn, "zh", folder=folder)
        sources_cn = _skill_extract_sources_from_rag_text(final_cn)
    if q_en and (q_en.lower() != q_cn.lower()):
        final_en = _rag_search_content(q_en, "en", folder=folder)
        sources_en = _skill_extract_sources_from_rag_text(final_en)

    sources = _skill_merge_rag_sources(sources_cn, sources_en, limit=8)
    hit_count = len(sources)
    if final_cn and final_en:
        final = "中文检索结果：\n" + str(final_cn or "").strip() + "\n\nEnglish query results:\n" + str(final_en or "").strip()
    else:
        final = str(final_cn or final_en or "").strip()
    facts = _skill_extract_facts_from_text(final, 6)
    return {
        "final_text": str(final or "").strip(),
        "facts": facts,
        "sources": sources,
        "hit_count": int(hit_count),
        "query_cn": str(q_cn or ""),
        "query_en": str(q_en or ""),
        "bilingual": bool(final_cn and final_en),
        "vector_hit_count": 0,
        "route": "local_rag",
    }


def _skill_rag_methodology_intent(query: str) -> bool:
    q = str(query or "").strip()
    ql = q.lower()
    keys = ["怎么", "如何", "步骤", "怎么查", "怎么找", "条款", "warranty", "clause", "how to", "steps"]
    return any(k in q for k in keys if not k.isascii()) or any(k in ql for k in keys if k.isascii())


def _skill_is_rag_hint_query(query: str) -> bool:
    q = str(query or "").strip()
    ql = q.lower()
    keys = ["资料库", "家庭资料库", "说明书", "合同", "条款", "保修", "发票", "manual", "contract", "clause", "warranty", "invoice"]
    return any(k in q for k in keys if not k.isascii()) or any(k in ql for k in keys if k.isascii())


def _skill_rag_methodology_pack(query: str) -> dict:
    q = str(query or "").strip()
    ql = q.lower()
    is_contract = ("合同" in q) or ("条款" in q) or ("contract" in ql) or ("clause" in ql)
    if is_contract:
        final = "资料库暂时没有命中合同条款内容。你可以这样查：1) 先确认合同名称和版本；2) 在目录里搜付款/违约/终止等关键词；3) 记录条款编号与原文；4) 核对生效日期、金额和自动续约。"
        facts = [
            "1) 确认合同名称、签署日期、版本号",
            "2) 搜关键词：付款、违约、终止、责任限制",
            "3) 记录条款编号与原文位置",
            "4) 核对生效日期、金额、自动续约",
        ]
        actions = [
            _skill_next_action_item("ask_user", "在资料库里搜内容 <关键词>", {"suggested_utterance": "在资料库里搜内容 合同 付款 条款", "route_hint": "rag"}),
            _skill_next_action_item("ask_user", "列出资料库里可能的合同/说明书文件名", {"suggested_utterance": "列出资料库里可能的合同/说明书文件名", "route_hint": "rag"}),
        ]
        return {"final_text": final, "facts": facts, "next_actions": actions}
    final = "资料库暂时没有命中。你可以这样查：1) 先找发票/订单号/序列号；2) 确认品牌型号和购买日期；3) 去官网查 warranty/保修条款；4) 对照 ACL 或银行账单交叉验证。"
    facts = [
        "1) 找发票、订单号、序列号",
        "2) 确认品牌、型号、购买日期",
        "3) 官网查 warranty/保修政策",
        "4) 对照 ACL 与商家承诺",
        "5) 必要时补充银行账单或邮件回执",
    ]
    actions = [
        _skill_next_action_item("ask_user", "在资料库里搜内容 <关键词>", {"suggested_utterance": "在资料库里搜内容 品牌 warranty", "route_hint": "rag"}),
        _skill_next_action_item("ask_user", "列出资料库里可能的合同/说明书文件名", {"suggested_utterance": "列出资料库里可能的合同/说明书文件名", "route_hint": "rag"}),
    ]
    return {"final_text": final, "facts": facts, "next_actions": actions}


def _skill_web_lookup(query: str, prefer_lang: str = "zh", limit: int = 3) -> dict:
    final, data = _web_search_answer(query, prefer_lang, limit=limit)
    facts = []
    sources = []
    if isinstance(data, dict):
        rs = data.get("results")
        if isinstance(rs, list):
            for it in rs[:5]:
                if not isinstance(it, dict):
                    continue
                title = str(it.get("title") or "").strip()
                url = str(it.get("url") or "").strip()
                snip = str(it.get("snippet") or "").strip()
                if title:
                    facts.append(title)
                    sources.append(_skill_source_item(_news__source_from_url(url), title, "", url))
                    if snip:
                        facts.append(snip[:120])
                if len(facts) >= 5:
                    break
    if not facts:
        facts = _skill_extract_facts_from_text(final, 5)
    return {"final_text": str(final or "").strip(), "facts": facts[:5], "sources": sources[:5], "data": data}


def _skill_news_category_from_topic(topic: str) -> str:
    t = str(topic or "").strip()
    tl = t.lower()
    if tl in ["today", "today news", "todays news", "top", "headlines"] or (t in ["今天", "今日", "今天新闻", "今日新闻"]):
        return "hot"
    if not t:
        return "local"
    c = _news__category_from_text(t)
    if not c:
        return "local"
    return c


def _skill_news_summary(items: list, topic: str) -> str:
    n = len(items or [])
    if n <= 0:
        return "我先给你一个新闻导读方向：请告诉我更具体的话题词，例如“澳洲利率”“墨尔本交通”或“AI 模型发布”。"
    top_titles = []
    for it in items[:3]:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title_voice") or it.get("title") or "").strip()
        if title:
            top_titles.append(title)
    head = "我找到 " + str(n) + " 条和「" + str(topic or "本地") + "」相关的新闻，先读 3 条。"
    if not top_titles:
        return head + " 你可以让我按序号展开。"
    if len(top_titles) == 1:
        return head + " 重点是：" + top_titles[0] + "。如需细看我可以展开。"
    if len(top_titles) == 2:
        return head + " 重点包括：" + top_titles[0] + "；" + top_titles[1] + "。"
    return head + " 重点包括：" + top_titles[0] + "；" + top_titles[1] + "；" + top_titles[2] + "。"


def _skill_news_topic_kind(topic: str) -> str:
    t = str(topic or "").strip()
    tl = t.lower()
    if ("交通" in t) or ("电车" in t) or ("火车" in t) or ("道路" in t) or ("traffic" in tl) or ("road" in tl) or ("rail" in tl) or ("tram" in tl) or ("train" in tl):
        return "traffic"
    if ("科技热点" in t) or ("科技新闻" in t) or ("ai" in tl):
        return "tech"
    if ("财经热点" in t) or ("财经" in t) or ("economy" in tl) or ("markets" in tl):
        return "finance"
    if ("体育热点" in t) or ("体育" in t) or ("sports" in tl):
        return "sports"
    if ("本地热点" in t) or ("本地新闻" in t) or ("local" in tl) or ("melbourne" in tl):
        return "local"
    if ("世界热点" in t) or ("国际热点" in t) or ("国际新闻" in t) or ("world" in tl) or ("international" in tl):
        return "world"
    return "general"


def _skill_news_topic_hit_count(items: list, topic_kind: str) -> int:
    keys = []
    if str(topic_kind or "") == "traffic":
        keys = [
            "road", "freeway", "highway", "traffic", "crash", "congestion", "closure", "toll",
            "train", "rail", "metro", "v/line", "station", "line", "level crossing", "signal",
            "tram", "bus", "ptv", "public transport", "disruption", "replacement bus", "transport",
            "交通", "道路", "地铁", "电车", "公交", "火车", "铁路", "维州交通",
        ]
    if not keys:
        return len(items or [])
    hit = 0
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        txt = (str(it.get("title_voice") or it.get("title") or "") + " " + str(it.get("snippet") or "")).lower()
        txt_cn = str(it.get("title_voice") or it.get("title") or "") + " " + str(it.get("snippet") or "")
        ok = any(k in txt_cn for k in keys if not k.isascii()) or any(k in txt for k in keys if k.isascii())
        if ok:
            hit += 1
    return hit


def _skill_news_is_traffic_item(it: dict) -> bool:
    if not isinstance(it, dict):
        return False
    txt = (str(it.get("title_voice") or it.get("title") or "") + " " + str(it.get("snippet") or "")).lower()
    txt_cn = str(it.get("title_voice") or it.get("title") or "") + " " + str(it.get("snippet") or "")
    keys = [
        "road", "freeway", "highway", "traffic", "crash", "congestion", "closure", "toll",
        "train", "rail", "metro", "v/line", "station", "line", "level crossing", "signal",
        "tram", "bus", "ptv", "public transport", "disruption", "replacement bus", "transport",
        "交通", "道路", "地铁", "电车", "公交", "火车", "铁路", "维州交通",
    ]
    return any(k in txt_cn for k in keys if not k.isascii()) or any(k in txt for k in keys if k.isascii())


def _skill_news_translate_items_zh(items: list, max_items: int = 3, timeout_sec: int = 4) -> list:
    out = []
    if not isinstance(items, list) or len(items) == 0:
        return out
    try:
        ttl_sec = int(os.environ.get("NEWS_TRANSLATE_CACHE_TTL_SEC") or "21600")
    except Exception:
        ttl_sec = 21600
    if ttl_sec < 60:
        ttl_sec = 60
    try:
        timeout_sec = int(os.environ.get("NEWS_TRANSLATE_TIMEOUT_SEC") or str(timeout_sec))
    except Exception:
        timeout_sec = int(timeout_sec)
    if timeout_sec < 3:
        timeout_sec = 3
    if timeout_sec > 8:
        timeout_sec = 8
    model = str(os.environ.get("NEWS_RETURN_TRANSLATE_MODEL") or "qwen3-vl:2b").strip()
    if not model:
        model = "qwen3-vl:2b"

    def _has_zh(s: str) -> bool:
        try:
            return bool(re.search(r"[\u4e00-\u9fff]", str(s or "")))
        except Exception:
            return False

    try:
        max_items_i = int(max_items)
    except Exception:
        max_items_i = 3
    if max_items_i < 1:
        max_items_i = 1
    if max_items_i > 5:
        max_items_i = 5

    pairs = []
    pair_map = []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            out.append({})
            continue
        cp = dict(it)
        title_raw = str(cp.get("title_voice") or cp.get("title") or "").strip()
        snip_raw = str(cp.get("snippet") or "").strip()
        need_tr = (not _has_zh(title_raw)) or (snip_raw and (not _has_zh(snip_raw)))
        if not need_tr:
            out.append(cp)
            continue
        cache_key_src = str(cp.get("url") or "").strip()
        if not cache_key_src:
            cache_key_src = title_raw + "|" + snip_raw
        cache_key = "news_rt:" + hashlib.md5(cache_key_src.encode("utf-8", "ignore")).hexdigest()
        cache_hit = _news__tr__cache_get(cache_key, ttl_sec)
        if isinstance(cache_hit, dict):
            zh_t = str(cache_hit.get("title") or "").strip()
            zh_s = str(cache_hit.get("snippet") or "").strip()
            if zh_t:
                cp["title_voice"] = zh_t
            if zh_s:
                cp["snippet"] = zh_s
            out.append(cp)
            continue
        out.append(cp)
        if len(pairs) < max_items_i:
            pairs.append({"title": title_raw, "snippet": snip_raw})
            pair_map.append({"out_idx": idx, "cache_key": cache_key})

    if len(pairs) > 0:
        trs = _news__translate_batch_to_zh(pairs, model=model, timeout_sec=timeout_sec)
        if isinstance(trs, list):
            for j in range(min(len(trs), len(pair_map))):
                tr = trs[j] if isinstance(trs[j], dict) else {}
                map_it = pair_map[j]
                oi = int(map_it.get("out_idx") or 0)
                if oi < 0 or oi >= len(out):
                    continue
                cp = out[oi] if isinstance(out[oi], dict) else {}
                zh_t = str(tr.get("title") or "").strip()
                zh_s = str(tr.get("snippet") or "").strip()
                if zh_t:
                    cp["title_voice"] = zh_t
                if zh_s:
                    cp["snippet"] = zh_s
                out[oi] = cp
                _news__tr__cache_put(str(map_it.get("cache_key") or ""), zh_t, zh_s)

    for i, it in enumerate(items):
        if i >= len(out):
            if isinstance(it, dict):
                out.append(dict(it))
            else:
                out.append({})
    return out


def _skill_translate_lines_to_zh(lines: list, timeout_sec: int = 12) -> list:
    if not isinstance(lines, list) or len(lines) == 0:
        return []
    model = str(os.environ.get("NEWS_RETURN_TRANSLATE_MODEL") or "qwen3-vl:2b").strip()
    if not model:
        model = "qwen3-vl:2b"
    base = str(os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip().rstrip("/")
    if not base:
        base = "http://192.168.1.162:11434"

    payload_lines = []
    for i, s in enumerate(lines, 1):
        payload_lines.append(str(i) + ") " + str(s or "").strip())
    prompt = (
        "把以下每一行英文或中英混合新闻内容翻译成自然中文。\n"
        "规则：\n"
        "1) 一行输入对应一行输出，行号必须保留。\n"
        "2) 只翻译，不补充事实，不增加新信息。\n"
        "3) 保留数字、专有名词、缩写。\n"
        "4) 输出格式必须是：N) <中文结果>\n\n"
        "输入：\n" + "\n".join(payload_lines)
    )
    req = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "你是翻译助手，只输出中文翻译结果。"},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.0},
    }
    try:
        r = requests.post(base + "/api/chat", json=req, timeout=float(timeout_sec))
        if int(getattr(r, "status_code", 0) or 0) >= 400:
            return [str(x or "").strip() for x in lines]
        data = r.json() if hasattr(r, "json") else {}
        content = str(((data.get("message") or {}).get("content")) or "").strip()
        out_map = {}
        for ln in content.splitlines():
            m = re.match(r"^\s*(\d{1,2})\s*[)\）]\s*(.*)$", str(ln or "").strip())
            if not m:
                continue
            try:
                idx = int(m.group(1))
            except Exception:
                continue
            out_map[idx] = str(m.group(2) or "").strip()
        out = []
        for i, s in enumerate(lines, 1):
            tr = str(out_map.get(i) or "").strip()
            out.append(tr if tr else str(s or "").strip())
        return out
    except Exception:
        return [str(x or "").strip() for x in lines]


def _skill_news_query_from_topic(topic: str) -> str:
    t = str(topic or "").strip()
    if not t:
        return "news"
    if len(t) > 80:
        t = t[:80].strip()
    return t


def _skill_translate_news_query_to_en(topic: str) -> str:
    text = str(topic or "").strip()
    if not text:
        return ""
    if not re.search(r"[\u4e00-\u9fff]", text):
        return text
    # Online query translation is disabled by default to avoid request-path timeout.
    # Set NEWS_QUERY_TRANSLATE_ONLINE=1 to enable LLM translation here.
    en_online = str(os.environ.get("NEWS_QUERY_TRANSLATE_ONLINE") or "0").strip().lower()
    if en_online not in ["1", "true", "yes", "on"]:
        return ""
    # Generic topics do not benefit from online translation.
    t = str(text or "")
    if ("新闻" in t) or ("热点" in t) or ("热门" in t) or ("要闻" in t):
        return ""
    base = str(os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip().rstrip("/")
    model = str(os.environ.get("NEWS_QUERY_TRANSLATE_MODEL") or "qwen3-vl:2b").strip()
    if not model:
        model = "qwen3-vl:2b"
    prompt = (
        "Translate the Chinese news query into concise English search keywords.\n"
        "Rules:\n"
        "1) Output only one line.\n"
        "2) Keep location/entity names.\n"
        "3) Use 3-8 keywords, no explanation.\n"
        "4) No punctuation except spaces.\n"
        "Query: " + text
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You output concise English search keywords only."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    try:
        r = requests.post(base + "/api/chat", json=payload, timeout=2)
        if int(getattr(r, "status_code", 0) or 0) >= 400:
            return ""
        data = r.json() if hasattr(r, "json") else {}
        msg = data.get("message") if isinstance(data, dict) else {}
        out = str((msg or {}).get("content") or "").strip()
        out = re.sub(r"[\r\n\t]+", " ", out).strip()
        out = re.sub(r"\s+", " ", out).strip()
        out = re.sub(r"[^A-Za-z0-9\-\+\s]", " ", out)
        out = re.sub(r"\s+", " ", out).strip()
        if len(out) > 120:
            out = out[:120].strip()
        return out
    except Exception:
        return ""


def _news_cache_db_path() -> str:
    p = str(os.environ.get("NEWS_CACHE_DB") or "/data/news_cache.sqlite3").strip()
    if not p:
        p = "/data/news_cache.sqlite3"
    parent = os.path.dirname(p) or "."
    try:
        os.makedirs(parent, exist_ok=True)
    except Exception:
        pass
    return p


def _news_cache_conn():
    return sqlite3.connect(_news_cache_db_path())


def _news_cache_init():
    conn = _news_cache_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS news_cache_entries (
                url TEXT PRIMARY KEY,
                title TEXT,
                snippet TEXT,
                title_zh TEXT,
                snippet_zh TEXT,
                source TEXT,
                published_at TEXT,
                topic_tags TEXT,
                keywords_en TEXT,
                keywords_zh TEXT,
                updated_ts INTEGER
            )
            """
        )
        try:
            cur.execute("PRAGMA table_info(news_cache_entries)")
            cols = [str(r[1] or "").strip().lower() for r in (cur.fetchall() or []) if isinstance(r, (list, tuple)) and len(r) >= 2]
            if "title_zh" not in cols:
                cur.execute("ALTER TABLE news_cache_entries ADD COLUMN title_zh TEXT")
            if "snippet_zh" not in cols:
                cur.execute("ALTER TABLE news_cache_entries ADD COLUMN snippet_zh TEXT")
        except Exception:
            pass
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_cache_published ON news_cache_entries(published_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_cache_source ON news_cache_entries(source)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS news_cache_meta (
                k TEXT PRIMARY KEY,
                v TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _news_cache_get_meta(key: str, default_val: str = "") -> str:
    conn = _news_cache_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT v FROM news_cache_meta WHERE k=?", (str(key or ""),))
        row = cur.fetchone()
        if not row:
            return str(default_val or "")
        return str(row[0] or "")
    except Exception:
        return str(default_val or "")
    finally:
        conn.close()


def _news_cache_set_meta(key: str, value: str):
    conn = _news_cache_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO news_cache_meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (str(key or ""), str(value or "")),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _news_keywords_heuristic(title: str, snippet: str) -> dict:
    txt = (str(title or "") + " " + str(snippet or "")).strip()
    tl = txt.lower()
    kws_en = []
    kws_zh = []
    tags = []
    token_en = re.findall(r"[a-zA-Z][a-zA-Z0-9\-\+]{2,}", tl)
    for w in token_en:
        if w in ["today", "news", "latest", "update", "report"]:
            continue
        if w not in kws_en:
            kws_en.append(w)
        if len(kws_en) >= 10:
            break
    token_zh = re.findall(r"[\u4e00-\u9fff]{2,}", txt)
    for w in token_zh:
        if w not in kws_zh:
            kws_zh.append(w)
        if len(kws_zh) >= 10:
            break
    tag_map = {
        "tech": ["ai", "technology", "startup", "模型", "科技", "人工智能"],
        "finance": ["market", "stock", "economy", "rate", "crypto", "finance", "财经", "股", "汇率", "比特币"],
        "sports": ["sport", "football", "soccer", "basketball", "tennis", "体育", "足球", "篮球"],
        "traffic": ["traffic", "road", "rail", "train", "tram", "transport", "交通", "道路", "火车", "电车"],
        "local": ["melbourne", "victoria", "australia", "墨尔本", "维州", "澳洲", "本地"],
    }
    mix = tl + " " + txt
    for tg, ks in tag_map.items():
        if any(k in mix for k in ks):
            tags.append(tg)
    return {"topic_tags": tags[:4], "keywords_en": kws_en[:10], "keywords_zh": kws_zh[:10]}


_NEWS_TAG_WHITELIST = set(["local", "world", "tech", "finance", "sports", "traffic", "policy", "education", "energy"])
_NEWS_EN_STOPWORDS = set(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "from",
        "with",
        "about",
        "after",
        "before",
        "into",
        "over",
        "under",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "new",
        "today",
        "latest",
        "news",
        "update",
        "report",
        "live",
        "briefing",
    ]
)
_NEWS_ZH_STOPWORDS = set(["今天", "最新", "新闻", "报道", "消息", "快讯", "点击", "阅读", "详情", "记者", "视频", "更多"])


def _news_normalize_tag(tag: str) -> str:
    s = str(tag or "").strip().lower()
    if s in _NEWS_TAG_WHITELIST:
        return s
    alias = {
        "technology": "tech",
        "economy": "finance",
        "market": "finance",
        "politics": "policy",
        "political": "policy",
        "transport": "traffic",
        "transportation": "traffic",
        "education_news": "education",
        "energy_news": "energy",
    }
    return alias.get(s, "")


def _news_normalize_keyword_en(kw: str) -> str:
    s = str(kw or "").strip().lower()
    s = re.sub(r"[^a-z0-9\-\+ ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if (not s) or len(s) < 2 or len(s) > 48:
        return ""
    parts = []
    for p in s.split(" "):
        if (not p) or (p in _NEWS_EN_STOPWORDS):
            continue
        parts.append(p)
    if not parts:
        return ""
    if len(parts) > 4:
        parts = parts[:4]
    out = " ".join(parts).strip()
    if (not out) or (out in _NEWS_EN_STOPWORDS):
        return ""
    if re.fullmatch(r"[0-9\-\+ ]+", out):
        return ""
    return out


def _news_normalize_keyword_zh(kw: str) -> str:
    s = str(kw or "").strip()
    s = re.sub(r"[\r\n\t]", " ", s)
    s = re.sub(r"[，。！？；：、“”\"'（）()【】\[\]<>《》]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if (not s) or len(s) < 2 or len(s) > 24:
        return ""
    if s in _NEWS_ZH_STOPWORDS:
        return ""
    if re.fullmatch(r"[0-9\-\+\./ ]+", s):
        return ""
    return s


def _news_infer_tags_from_text(text: str) -> list:
    t = str(text or "").lower()
    tag_map = {
        "tech": ["ai", "chip", "model", "openai", "nvidia", "苹果", "科技", "人工智能", "芯片"],
        "finance": ["economy", "market", "stock", "rate", "rba", "汇率", "股价", "比特币", "黄金", "经济"],
        "sports": ["sports", "sport", "football", "nba", "f1", "tennis", "体育", "足球", "篮球"],
        "traffic": ["traffic", "road", "rail", "train", "tram", "transport", "交通", "铁路", "电车", "道路"],
        "local": ["melbourne", "victoria", "australia", "墨尔本", "维州", "澳洲", "doncaster"],
        "world": ["world", "international", "global", "国际", "全球", "世界"],
        "policy": ["policy", "government", "election", "parliament", "政策", "政府", "选举"],
        "education": ["school", "university", "education", "学生", "教育", "学校"],
        "energy": ["energy", "power", "oil", "gas", "electricity", "能源", "电力", "油价", "天然气"],
    }
    out = []
    for tg, keys in tag_map.items():
        if any(k in t for k in keys):
            out.append(tg)
    return out[:4]


def _news_finalize_keyword_schema(title: str, snippet: str, tags: list, kws_en: list, kws_zh: list) -> dict:
    tags_out = []
    for x in tags or []:
        t = _news_normalize_tag(str(x or ""))
        if t and (t not in tags_out):
            tags_out.append(t)
        if len(tags_out) >= 6:
            break

    en_out = []
    for x in kws_en or []:
        s = _news_normalize_keyword_en(x)
        if s and (s not in en_out):
            en_out.append(s)
        if len(en_out) >= 10:
            break

    zh_out = []
    for x in kws_zh or []:
        s = _news_normalize_keyword_zh(x)
        if s and (s not in zh_out):
            zh_out.append(s)
        if len(zh_out) >= 10:
            break

    #补齐：当模型输出过弱时，回退到文本抽词，保证最小可用关键词集合。
    if len(en_out) < 3:
        mix_en = (str(title or "") + " " + str(snippet or "")).lower()
        for m in re.findall(r"[a-zA-Z][a-zA-Z0-9\-\+]{2,}", mix_en):
            s = _news_normalize_keyword_en(m)
            if s and (s not in en_out):
                en_out.append(s)
            if len(en_out) >= 10:
                break
    if len(zh_out) < 2:
        mix_zh = str(title or "") + " " + str(snippet or "")
        for m in re.findall(r"[\u4e00-\u9fff]{2,}", mix_zh):
            s = _news_normalize_keyword_zh(m)
            if s and (s not in zh_out):
                zh_out.append(s)
            if len(zh_out) >= 10:
                break

    infer_tags = _news_infer_tags_from_text(
        (str(title or "") + " " + str(snippet or "") + " " + " ".join(en_out) + " " + " ".join(zh_out)).strip()
    )
    for t in infer_tags:
        if t and (t not in tags_out):
            tags_out.append(t)
        if len(tags_out) >= 6:
            break

    return {"topic_tags": tags_out[:6], "keywords_en": en_out[:10], "keywords_zh": zh_out[:10]}


def _news_keywords_extract_ai(title: str, snippet: str) -> dict:
    text = (str(title or "") + "\n" + str(snippet or "")).strip()
    if not text:
        return {"topic_tags": [], "keywords_en": [], "keywords_zh": []}
    base = str(os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip().rstrip("/")
    model = str(os.environ.get("NEWS_KEYWORD_MODEL") or "qwen3-vl:2b").strip()
    if not model:
        model = "qwen3-vl:2b"
    prompt = (
        "Extract topic tags and keywords from this news item.\n"
        "Return strict JSON object with keys: topic_tags, keywords_en, keywords_zh.\n"
        "topic_tags choose from [local,world,tech,finance,sports,traffic,policy,education,energy].\n"
        "Keyword extraction priority:\n"
        "1) High-frequency nouns and type/category nouns in this item.\n"
        "2) Brand/company/product names.\n"
        "3) Location names (country/city/region).\n"
        "4) Technology terms (AI/chip/model/platform/protocol/etc).\n"
        "5) Person names and organization names.\n"
        "Rules for keywords_en / keywords_zh:\n"
        "- Keep concise noun phrases, no full sentences.\n"
        "- Remove generic filler words (news, update, report, today, latest).\n"
        "- Prefer specific entities over generic words.\n"
        "- Keep original language forms where possible.\n"
        "- Each list max 10 unique items.\n"
        "Text:\n" + text
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    try:
        r = requests.post(base + "/api/chat", json=payload, timeout=10)
        if int(getattr(r, "status_code", 0) or 0) >= 400:
            return {"topic_tags": [], "keywords_en": [], "keywords_zh": []}
        data = r.json() if hasattr(r, "json") else {}
        msg = data.get("message") if isinstance(data, dict) else {}
        out = str((msg or {}).get("content") or "").strip()
        if not out:
            return {"topic_tags": [], "keywords_en": [], "keywords_zh": []}
        m = re.search(r"\{[\s\S]*\}", out)
        if m:
            out = str(m.group(0) or "").strip()
        obj = json.loads(out)
        tags = obj.get("topic_tags") if isinstance(obj.get("topic_tags"), list) else []
        en = obj.get("keywords_en") if isinstance(obj.get("keywords_en"), list) else []
        zh = obj.get("keywords_zh") if isinstance(obj.get("keywords_zh"), list) else []
        return _news_finalize_keyword_schema(title, snippet, tags, en, zh)
    except Exception:
        return {"topic_tags": [], "keywords_en": [], "keywords_zh": []}


def _news_cache_upsert_item(item: dict, use_ai: bool = True):
    if not isinstance(item, dict):
        return
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    snippet = str(item.get("snippet") or "").strip()
    title_zh = str(item.get("title_zh") or "").strip()
    snippet_zh = str(item.get("snippet_zh") or "").strip()
    source = str(item.get("source") or "").strip()
    published_at = str(item.get("published_at") or "").strip()
    if (not url) and (not title):
        return
    ai = {"topic_tags": [], "keywords_en": [], "keywords_zh": []}
    if use_ai:
        ai = _news_keywords_extract_ai(title, snippet)
    if (not ai.get("topic_tags")) and (not ai.get("keywords_en")) and (not ai.get("keywords_zh")):
        ai = _news_keywords_heuristic(title, snippet)
    ai = _news_finalize_keyword_schema(
        title,
        snippet,
        ai.get("topic_tags") if isinstance(ai.get("topic_tags"), list) else [],
        ai.get("keywords_en") if isinstance(ai.get("keywords_en"), list) else [],
        ai.get("keywords_zh") if isinstance(ai.get("keywords_zh"), list) else [],
    )
    conn = _news_cache_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO news_cache_entries(url, title, snippet, title_zh, snippet_zh, source, published_at, topic_tags, keywords_en, keywords_zh, updated_ts)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              title=excluded.title,
              snippet=excluded.snippet,
              title_zh=excluded.title_zh,
              snippet_zh=excluded.snippet_zh,
              source=excluded.source,
              published_at=excluded.published_at,
              topic_tags=excluded.topic_tags,
              keywords_en=excluded.keywords_en,
              keywords_zh=excluded.keywords_zh,
              updated_ts=excluded.updated_ts
            """,
            (
                url if url else ("title:" + hashlib.sha1(title.encode("utf-8")).hexdigest()),
                title,
                snippet,
                title_zh,
                snippet_zh,
                source,
                published_at,
                json.dumps(ai.get("topic_tags") or [], ensure_ascii=False),
                json.dumps(ai.get("keywords_en") or [], ensure_ascii=False),
                json.dumps(ai.get("keywords_zh") or [], ensure_ascii=False),
                int(time.time()),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _news_cache_refresh_if_due(force: bool = False):
    _news_cache_init()
    try:
        interval = int(os.environ.get("NEWS_CACHE_REFRESH_SEC") or "1800")
    except Exception:
        interval = 1800
    if interval < 60:
        interval = 60
    now_ts = int(time.time())
    last = 0
    try:
        last = int(_news_cache_get_meta("last_refresh_ts", "0") or "0")
    except Exception:
        last = 0
    if (not force) and ((now_ts - last) < interval):
        return
    try:
        fetch_limit = int(os.environ.get("NEWS_CACHE_FETCH_LIMIT") or "120")
    except Exception:
        fetch_limit = 120
    if fetch_limit < 20:
        fetch_limit = 20
    if fetch_limit > 300:
        fetch_limit = 300
    base_items = []
    r = _skill_miniflux_req(
        "/v1/entries",
        {
            "order": "published_at",
            "direction": "desc",
            "limit": fetch_limit,
        },
    )
    if r.get("ok"):
        data = r.get("data") or {}
        entries = data.get("entries") or []
        for e in entries:
            if not isinstance(e, dict):
                continue
            title = str(e.get("title") or "").strip()
            if not title:
                continue
            feed = e.get("feed") or {}
            source = str(feed.get("title") or "").strip()
            url = str(e.get("url") or "").strip() or str(e.get("comments_url") or "").strip()
            raw_pub = str(e.get("published_at") or "").strip()
            content = str(e.get("content") or "").strip()
            plain = re.sub(r"<[^>]+>", " ", content)
            plain = html.unescape(plain)
            plain = re.sub(r"\s+", " ", plain).strip()
            if len(plain) > 220:
                plain = plain[:220].rstrip() + "..."
            base_items.append(
                {
                    "title": title,
                    "url": url,
                    "source": source,
                    "published_at": raw_pub,
                    "snippet": plain,
                }
            )
    # Pre-translate title/snippet during cache refresh to avoid request-time LLM latency.
    def _has_zh_local(s: str) -> bool:
        try:
            return bool(re.search(r"[\u4e00-\u9fff]", str(s or "")))
        except Exception:
            return False
    try:
        tr_cap = int(os.environ.get("NEWS_CACHE_TRANSLATE_PER_REFRESH") or "40")
    except Exception:
        tr_cap = 40
    if tr_cap < 0:
        tr_cap = 0
    if tr_cap > 120:
        tr_cap = 120
    tr_pairs = []
    tr_idx = []
    for i, it in enumerate(base_items):
        if len(tr_pairs) >= tr_cap:
            break
        if not isinstance(it, dict):
            continue
        ttl = str(it.get("title") or "").strip()
        sn = str(it.get("snippet") or "").strip()
        if (not ttl) and (not sn):
            continue
        if _has_zh_local(ttl) and ((not sn) or _has_zh_local(sn)):
            it["title_zh"] = ttl
            if sn:
                it["snippet_zh"] = sn
            continue
        tr_pairs.append({"title": ttl, "snippet": sn})
        tr_idx.append(i)
    if len(tr_pairs) > 0:
        model = str(os.environ.get("NEWS_CACHE_TRANSLATE_MODEL") or "qwen3-vl:2b").strip()
        if not model:
            model = "qwen3-vl:2b"
        try:
            tr_timeout = int(os.environ.get("NEWS_CACHE_TRANSLATE_TIMEOUT_SEC") or "8")
        except Exception:
            tr_timeout = 8
        if tr_timeout < 3:
            tr_timeout = 3
        if tr_timeout > 20:
            tr_timeout = 20
        tr_ret = _news__translate_batch_to_zh(tr_pairs, model=model, timeout_sec=tr_timeout)
        if isinstance(tr_ret, list):
            for j in range(min(len(tr_ret), len(tr_idx))):
                item_idx = int(tr_idx[j])
                if item_idx < 0 or item_idx >= len(base_items):
                    continue
                tr = tr_ret[j] if isinstance(tr_ret[j], dict) else {}
                zh_t = str(tr.get("title") or "").strip()
                zh_s = str(tr.get("snippet") or "").strip()
                if zh_t:
                    base_items[item_idx]["title_zh"] = zh_t
                if zh_s:
                    base_items[item_idx]["snippet_zh"] = zh_s
    # limit AI extraction per refresh to keep latency bounded
    try:
        ai_cap = int(os.environ.get("NEWS_CACHE_AI_PER_REFRESH") or "24")
    except Exception:
        ai_cap = 24
    if ai_cap < 0:
        ai_cap = 0
    i = 0
    for it in base_items:
        use_ai = (i < ai_cap)
        _news_cache_upsert_item(it, use_ai=use_ai)
        i += 1
    _news_cache_set_meta("last_refresh_ts", str(now_ts))


def _news_query_anchor_profile(q_raw: str, q_en: str) -> dict:
    qmix = (str(q_raw or "") + " " + str(q_en or "")).lower()
    groups = [
        {"name": "gold", "anchors": ["gold", "xau", "xauusd", "黄金"]},
        {"name": "crypto", "anchors": ["bitcoin", "btc", "crypto", "比特币", "加密货币"]},
        {"name": "finance", "anchors": ["economy", "market", "rate", "rba", "stock", "财经", "经济", "利率", "汇率", "股价"]},
        {"name": "traffic", "anchors": ["traffic", "transport", "road", "rail", "train", "tram", "交通", "铁路", "道路", "电车"]},
        {"name": "crime", "anchors": ["crime", "police", "murder", "assault", "arrest", "court", "犯罪", "警察", "凶杀", "袭击"]},
        {"name": "tech", "anchors": ["ai", "openai", "nvidia", "apple", "tech", "technology", "科技", "人工智能", "芯片"]},
        {"name": "sports", "anchors": ["sports", "sport", "football", "nba", "f1", "tennis", "体育", "足球", "篮球"]},
        {"name": "property", "anchors": ["property", "housing", "rental", "rent", "real estate", "房产", "租房", "房价"]},
    ]
    matched = []
    anchors = []
    for g in groups:
        hit = False
        for a in g.get("anchors") or []:
            if str(a or "") and (str(a).lower() in qmix):
                hit = True
                if a not in anchors:
                    anchors.append(a)
        if hit:
            matched.append(str(g.get("name") or ""))
    return {"groups": matched, "anchors": anchors}


def _news_count_anchor_hits(anchor_list: list, texts: list) -> int:
    if not anchor_list:
        return 0
    mix = " ".join([str(x or "").lower() for x in (texts or [])]).strip()
    if not mix:
        return 0
    c = 0
    for a in anchor_list:
        s = str(a or "").lower().strip()
        if s and (s in mix):
            c += 1
    return c


def _news_cache_query(topic: str, limit: int = 5, do_refresh: bool = True) -> dict:
    _news_cache_init()
    if bool(do_refresh):
        _news_cache_refresh_if_due(False)
    q_raw = str(topic or "").strip()
    q_en = _skill_translate_news_query_to_en(q_raw)
    q_mix = (q_raw + " " + q_en).strip()
    anchor_profile = _news_query_anchor_profile(q_raw, q_en)
    anchor_groups = anchor_profile.get("groups") if isinstance(anchor_profile.get("groups"), list) else []
    anchor_list = anchor_profile.get("anchors") if isinstance(anchor_profile.get("anchors"), list) else []
    tokens_zh = re.findall(r"[\u4e00-\u9fff]{2,}", q_raw)
    tokens_en = re.findall(r"[a-zA-Z][a-zA-Z0-9\-\+]{2,}", q_en.lower())
    tset_zh = []
    tset_en = []
    for x in tokens_zh:
        s = _news_normalize_keyword_zh(x)
        if s and (s not in tset_zh):
            tset_zh.append(s)
    for x in tokens_en:
        s = _news_normalize_keyword_en(x)
        if s and (s not in tset_en):
            tset_en.append(s)
    conn = _news_cache_conn()
    rows = []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT url, title, snippet, title_zh, snippet_zh, source, published_at, topic_tags, keywords_en, keywords_zh FROM news_cache_entries ORDER BY published_at DESC LIMIT 400"
        )
        rows = cur.fetchall() or []
    except Exception:
        rows = []
    finally:
        conn.close()
    scored = []
    for row in rows:
        url = str(row[0] or "")
        title = str(row[1] or "")
        snippet = str(row[2] or "")
        title_zh = str(row[3] or "")
        snippet_zh = str(row[4] or "")
        source = str(row[5] or "")
        published_at = str(row[6] or "")
        try:
            tags = json.loads(str(row[7] or "[]"))
        except Exception:
            tags = []
        try:
            kws_en = json.loads(str(row[8] or "[]"))
        except Exception:
            kws_en = []
        try:
            kws_zh = json.loads(str(row[9] or "[]"))
        except Exception:
            kws_zh = []
        score = 0.0
        tl = (title + " " + snippet).lower()
        tc = title + " " + snippet
        for t in tset_en:
            if t in [str(x).lower() for x in tags]:
                score += 3.0
            if t in [str(x).lower() for x in kws_en]:
                score += 2.5
            if t in tl:
                score += 1.4
        for t in tset_zh:
            if t in [str(x) for x in kws_zh]:
                score += 2.5
            if t in tc:
                score += 1.4
        anchor_hits = _news_count_anchor_hits(
            anchor_list,
            [
                title,
                snippet,
                source,
                " ".join([str(x) for x in tags or []]),
                " ".join([str(x) for x in kws_en or []]),
                " ".join([str(x) for x in kws_zh or []]),
            ],
        )
        if anchor_hits > 0:
            score += float(anchor_hits) * 2.2
        elif len(anchor_groups) > 0:
            # For topic-constrained queries, down-rank rows with zero anchor hits.
            score -= 2.5
        if ("墨尔本" in q_raw) or ("维州" in q_raw) or ("澳洲" in q_raw):
            src_l = source.lower()
            if ("abc" in src_l) or ("9news" in src_l) or ("the age" in src_l) or ("smh" in src_l) or ("guardian" in src_l):
                score += 0.7
        if (len(tset_en) + len(tset_zh)) == 0:
            score += 0.2
        if score <= 0:
            continue
        scored.append(
            {
                "score": score,
                "anchor_hits": anchor_hits,
                "title": title,
                "title_voice": (title_zh if title_zh else title),
                "snippet": (snippet_zh if snippet_zh else snippet),
                "source": source,
                "url": url,
                "published_at": published_at,
            }
        )
    scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    out_items = scored[: max(1, int(limit))]
    if len(anchor_groups) > 0:
        anchored = [x for x in scored if int(x.get("anchor_hits") or 0) > 0]
        if len(anchored) >= 1:
            need_n = max(1, int(limit))
            out_items = anchored[:need_n]
            if len(out_items) < need_n:
                rest = [x for x in scored if x not in out_items]
                out_items = out_items + rest[: (need_n - len(out_items))]
    return {"ok": True, "items": out_items, "query_raw": q_raw, "query_en": q_en, "query_mix": q_mix}


def _skill_miniflux_req(path: str, params: dict = None) -> dict:
    base_url = str(os.environ.get("MINIFLUX_BASE_URL") or "http://192.168.1.162:19091").strip()
    token = str(os.environ.get("MINIFLUX_API_TOKEN") or os.environ.get("MINIFLUX_TOKEN") or "").strip()
    if not token:
        return {"ok": False, "error": "MINIFLUX_TOKEN_MISSING"}
    url = base_url.rstrip("/") + str(path or "")
    headers = {"X-Auth-Token": token}
    try:
        r = requests.get(url, headers=headers, params=(params or {}), timeout=6)
        code = int(getattr(r, "status_code", 0) or 0)
        if code >= 400:
            return {"ok": False, "status": code, "text": str(r.text or "")[:500]}
        return {"ok": True, "data": r.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _skill_miniflux_search(topic: str, limit: int = 5, days: int = 14) -> dict:
    q_raw = _skill_news_query_from_topic(topic)
    q_en = _skill_translate_news_query_to_en(q_raw)
    query_candidates = []
    if q_en:
        query_candidates.append(q_en)
    if q_raw:
        query_candidates.append(q_raw)
    if not query_candidates:
        query_candidates = ["news"]
    try:
        lim = int(limit)
    except Exception:
        lim = 5
    if lim < 1:
        lim = 1
    if lim > 10:
        lim = 10
    fetch_lim = lim * 6
    if fetch_lim < 20:
        fetch_lim = 20
    if fetch_lim > 120:
        fetch_lim = 120

    try:
        dd = int(days)
    except Exception:
        dd = 14
    if dd < 1:
        dd = 1
    if dd > 30:
        dd = 30

    tz_name = str(os.environ.get("TZ") or "Australia/Melbourne").strip()
    try:
        now_dt = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now_dt = datetime.now()
    published_after = (now_dt - timedelta(days=dd)).isoformat()

    if _skill_debug_enabled():
        _skill_debug_log("news_search_query_raw=" + q_raw)
        _skill_debug_log("news_search_query_en=" + q_en)
        _skill_debug_log("news_search_published_after=" + published_after)

    entries = []
    used_unread = True
    fallback_stage = "none"
    query_used = ""
    for qc in query_candidates:
        q = str(qc or "").strip()
        if not q:
            continue
        query_used = q
        params_unread = {
            "status": "unread",
            "search": q,
            "order": "published_at",
            "direction": "desc",
            "limit": fetch_lim,
            "published_after": published_after,
        }
        r1 = _skill_miniflux_req("/v1/entries", params_unread)
        used_unread = True
        fallback_stage = "unread+window"
        if r1.get("ok"):
            data = r1.get("data") or {}
            entries = data.get("entries") or []
        if len(entries) < 1:
            used_unread = False
            fallback_stage = "all+window"
            params_all = {
                "search": q,
                "order": "published_at",
                "direction": "desc",
                "limit": fetch_lim,
                "published_after": published_after,
            }
            r2 = _skill_miniflux_req("/v1/entries", params_all)
            if r2.get("ok"):
                data2 = r2.get("data") or {}
                entries2 = data2.get("entries") or []
                if isinstance(entries2, list) and entries2:
                    entries = entries2
        if len(entries) < 1:
            fallback_stage = "all+no_window"
            params_all2 = {
                "search": q,
                "order": "published_at",
                "direction": "desc",
                "limit": fetch_lim,
            }
            r3 = _skill_miniflux_req("/v1/entries", params_all2)
            if r3.get("ok"):
                data3 = r3.get("data") or {}
                entries3 = data3.get("entries") or []
                if isinstance(entries3, list) and entries3:
                    entries = entries3
        if len(entries) < 1:
            fallback_stage = "all+no_window+short_query"
            q2 = q
            if " " in q2:
                q2 = q2.split(" ", 1)[0].strip()
            if not q2:
                q2 = str(topic or "news").strip()
            params_all3 = {
                "search": q2,
                "order": "published_at",
                "direction": "desc",
                "limit": fetch_lim,
            }
            r4 = _skill_miniflux_req("/v1/entries", params_all3)
            if r4.get("ok"):
                data4 = r4.get("data") or {}
                entries4 = data4.get("entries") or []
                if isinstance(entries4, list) and entries4:
                    entries = entries4
        if len(entries) > 0:
            break

    if _skill_debug_enabled():
        _skill_debug_log("news_search_hit_count=" + str(len(entries)))
        _skill_debug_log("news_search_used_unread=" + str(used_unread))
        _skill_debug_log("news_search_stage=" + str(fallback_stage))

    def _strip_html_local(s: str) -> str:
        if not s:
            return ""
        try:
            s2 = re.sub(r"<[^>]+>", " ", str(s or ""))
            s2 = html.unescape(s2)
            s2 = re.sub(r"\s+", " ", s2).strip()
            return s2
        except Exception:
            return str(s or "").strip()

    def _to_local(iso_str: str) -> str:
        x = str(iso_str or "").strip()
        if not x:
            return ""
        try:
            dt = datetime.fromisoformat(x.replace("Z", "+00:00"))
            dt2 = dt.astimezone(ZoneInfo(tz_name))
            return dt2.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return x

    items = []
    seen = set()
    for e in (entries or []):
        if not isinstance(e, dict):
            continue
        title = str(e.get("title") or "").strip()
        if not title:
            continue
        feed = e.get("feed") or {}
        source = str(feed.get("title") or "").strip()
        url = str(e.get("url") or "").strip() or str(e.get("comments_url") or "").strip()
        raw_pub = str(e.get("published_at") or "").strip()
        pub = _to_local(raw_pub)
        content = _strip_html_local(e.get("content"))
        snippet = content
        if len(snippet) > 180:
            snippet = snippet[:180].rstrip() + "..."
        key = ""
        if url:
            key = "u:" + url
        else:
            key = "t:" + title.lower() + "|" + source.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "title": title,
                "title_voice": title,
                "url": url,
                "source": source,
                "published_at": pub,
                "snippet": snippet,
            }
        )
        if len(items) >= lim:
            break

    return {"ok": True, "query": query_used, "query_raw": q_raw, "query_en": q_en, "published_after": published_after, "items": items}


def _skill_news_brief_core(topic: str = "本地", limit: int = 10) -> dict:
    return _news_skill_news_brief_core(
        topic,
        limit,
        {
            "skill_news_category_from_topic": _skill_news_category_from_topic,
            "news_extract_limit": _news__extract_limit,
            "news_cache_query": _news_cache_query,
            "news_hot": news_hot,
            "news_dedupe_items_for_voice": _news__dedupe_items_for_voice,
            "skill_miniflux_search": _skill_miniflux_search,
            "skill_debug_enabled": _skill_debug_enabled,
            "skill_debug_log": _skill_debug_log,
            "skill_web_lookup": _skill_web_lookup,
            "news_source_from_url": _news__source_from_url,
            "skill_source_item": _skill_source_item,
            "skill_news_summary": _skill_news_summary,
            "skill_news_topic_kind": _skill_news_topic_kind,
            "skill_news_topic_hit_count": _skill_news_topic_hit_count,
            "skill_text_is_weak_or_empty": _skill_text_is_weak_or_empty,
            "skill_result": _skill_result,
        },
    )


@mcp.tool(name="skill.news_brief", description="News brief skill: return facts only.")
def skill_news_brief(topic: str = "本地", limit: int = 10) -> dict:
    rid, started = _skill_call_begin("skill.news_brief", {"topic": str(topic or ""), "limit": int(limit or 0)})
    ok = True
    out = []
    try:
        core = _skill_news_brief_core(topic=topic, limit=limit)
        payload = build_news_facts_payload(core)
        out = payload.get("facts") if isinstance(payload, dict) else []
        if not isinstance(out, list):
            out = []
        return {"facts": out}
    except Exception as e:
        ok = False
        _skill_log_json("tool_call_error", request_id=rid, tool="skill.news_brief", data={"error": str(e)})
        return {"facts": ["新闻服务暂时不可用，请稍后再试。"]}
    finally:
        _skill_call_end("skill.news_brief", rid, started, ok=ok, data={"facts_count": len(out)})


@mcp.tool(name="skill.capabilities", description="Capability declaration for HA prompt routing and tool policy generation.")
def skill_capabilities() -> dict:
    rid, started = _skill_call_begin("skill.capabilities", {})
    try:
        caps = {
            "version": "2026-02-12",
            "assistant": "Jarvis",
            "tools": list(_SKILL_TOOL_NAMES),
            "routing": [
                {"intent": "music_control", "tool": "skill.music_control", "must": True, "examples": ["播放音乐", "暂停音乐", "在卧室播放周杰伦"]},
                {"intent": "weather_outdoor", "tool": "skill.answer_question", "must": True, "examples": ["今天天气", "明天会下雨吗"]},
                {"intent": "device_control_or_live_state", "tool": "assist.*", "must": True, "examples": ["打开客厅灯", "客厅空调开着吗"]},
                {"intent": "news", "tool": "skill.news_brief", "preferred": True, "examples": ["今天热门新闻", "本地新闻"]},
                {"intent": "knowledge_lookup", "tool": "skill.knowledge_lookup", "preferred": True, "examples": ["在家庭资料库里搜内容 发票"]},
                {"intent": "memory_write", "tool": "skill.memory_upsert", "preferred": True, "examples": ["记住：周三下午3点牙医复诊"]},
                {"intent": "memory_search", "tool": "skill.memory_search", "preferred": True, "examples": ["在记忆里搜索 牙医 预约"]},
                {"intent": "holiday", "tool": "skill.holiday_query", "preferred": True, "examples": ["下一个公众假期"]},
                {"intent": "finance_admin", "tool": "skill.finance_admin", "preferred": True, "examples": ["检查账单"]},
                {"intent": "general_info", "tool": "skill.answer_question", "default": True, "examples": ["人民币兑澳币汇率", "墨尔本停车费"]},
            ],
            "output": {
                "skill.news_brief": {"fields": ["facts"]},
                "other_skills": {"fields": ["final_text", "facts"]},
            },
            "defaults": {
                "language": "zh-CN",
                "location_context": "Doncaster East VIC 319",
            },
            "constraints": [
                "no_cloud_fallback",
                "short_answer",
                "no_tool_name_in_user_reply",
                "prefer_local_model",
            ],
        }
        return caps
    finally:
        _skill_call_end("skill.capabilities", rid, started, ok=True, data={"tools_count": len(_SKILL_TOOL_NAMES)})


@mcp.tool(name="skill.knowledge_lookup", description="Knowledge lookup skill: force local RAG only with optional scope.")
def skill_knowledge_lookup(query: str, scope: str = "") -> dict:
    rid, started = _skill_call_begin("skill.knowledge_lookup", {"query": str(query or ""), "scope": str(scope or "")})
    ok = True
    q_raw = str(query or "").strip()
    q_clean, _q_folder = _rag_extract_content_query(q_raw)
    q = str(q_clean or q_raw).strip()
    sc = str(scope or "").strip()
    lang = _skill_detect_lang(q, "zh")
    rr = _skill_rag_lookup_core(q, scope=sc, language=lang)
    final_text = str(rr.get("final_text") or "").strip()
    facts = rr.get("facts") or []
    sources = rr.get("sources") or []
    hit_count = int(rr.get("hit_count") or 0)
    vector_hit_count = int(rr.get("vector_hit_count") or 0)
    rag_route = str(rr.get("route") or "").strip()
    query_cn = str(rr.get("query_cn") or "").strip()
    query_en = str(rr.get("query_en") or "").strip()
    bilingual = bool(rr.get("bilingual"))
    next_actions = []
    if (hit_count <= 0) or _skill_text_is_weak_or_empty(final_text):
        ql = q.lower()
        rag_hint_hit = _skill_is_rag_hint_query(q)
        domain_hit = ("合同" in q) or ("条款" in q) or ("保修" in q) or ("发票" in q) or ("说明书" in q) or ("contract" in ql) or ("clause" in ql) or ("warranty" in ql) or ("invoice" in ql) or ("manual" in ql)
        if (hit_count <= 0) and (rag_hint_hit or domain_hit) and (_skill_rag_methodology_intent(q) or domain_hit):
            mf = _skill_rag_methodology_pack(q)
            return _skill_result(
                str(mf.get("final_text") or "资料库未命中。"),
                facts=(mf.get("facts") if isinstance(mf.get("facts"), list) else [])[:6],
                sources=[],
                next_actions=(mf.get("next_actions") if isinstance(mf.get("next_actions"), list) else []),
                meta={"skill": "knowledge_lookup", "query": q, "scope": sc, "hit_count": hit_count, "vector_hit_count": vector_hit_count, "route": "rag_methodology_fallback", "query_cn": query_cn, "query_en": query_en, "bilingual": bilingual},
            )
        hint = "可以换关键词，或先去掉目录限定再试。"
        if sc:
            hint = "当前限定目录为「" + sc + "」。你可以换关键词，或清空 scope 再试。"
        next_actions.append(_skill_next_action_item("ask_user", hint, {"scope": sc, "query": q}))
    try:
        return _skill_result(
            final_text if final_text else "资料库检索完成，但没有命中。",
            facts=facts[:5],
            sources=sources[:5],
            next_actions=next_actions,
            meta={"skill": "knowledge_lookup", "query": q, "scope": sc, "hit_count": hit_count, "vector_hit_count": vector_hit_count, "route": rag_route, "query_cn": query_cn, "query_en": query_en, "bilingual": bilingual},
        )
    except Exception as e:
        ok = False
        _skill_log_json("tool_call_error", request_id=rid, tool="skill.knowledge_lookup", data={"error": str(e)})
        return _skill_result("资料库查询失败。", facts=["资料库查询失败，请稍后再试。"])
    finally:
        _skill_call_end("skill.knowledge_lookup", rid, started, ok=ok, data={"hit_count": hit_count, "vector_hit_count": vector_hit_count, "route": rag_route})


@mcp.tool(name="skill.memory_upsert", description="Upsert one text memory into Qdrant with embedding.")
def skill_memory_upsert(text: str, source: str = "manual", user_id: str = "default", memory_type: str = "note", metadata_json: str = "") -> dict:
    rid, started = _skill_call_begin(
        "skill.memory_upsert",
        {
            "text": str(text or ""),
            "source": str(source or ""),
            "user_id": str(user_id or ""),
            "memory_type": str(memory_type or ""),
        },
    )
    ok = True
    try:
        q = str(text or "").strip()
        if not q:
            return _skill_result("写入失败：text 不能为空。", facts=["参数 text 不能为空。"])
        vec = _skill_embed_text(q)
        if not vec:
            return _skill_result("写入失败：embedding 失败或维度不匹配。", facts=["请确认 EMBED_MODEL 与 QDRANT_VECTOR_SIZE 一致。"])
        meta = {}
        try:
            raw_meta = str(metadata_json or "").strip()
            if raw_meta:
                obj = json.loads(raw_meta)
                if isinstance(obj, dict):
                    meta = obj
        except Exception:
            meta = {}
        point_id = str(meta.get("point_id") or "").strip()
        if not point_id:
            seed = str(source or "manual").strip() + "|" + str(user_id or "default").strip() + "|" + q
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
        payload = {
            "text": q,
            "source": str(source or "manual").strip() or "manual",
            "user_id": str(user_id or "default").strip() or "default",
            "type": str(memory_type or "note").strip() or "note",
            "created_at": datetime.now(ZoneInfo("Australia/Melbourne")).isoformat(),
        }
        for k, v in meta.items():
            if k in ("point_id",):
                continue
            payload[str(k)] = v
        rr = _skill_qdrant_upsert_points([{"id": point_id, "vector": vec, "payload": payload}])
        if not rr.get("ok"):
            ok = False
            return _skill_result(
                "写入失败：Qdrant upsert 失败。",
                facts=[str(rr.get("error") or "unknown_error")],
                meta={"skill": "memory_upsert", "collection": _skill_qdrant_collection(), "point_id": point_id},
            )
        return _skill_result(
            "写入成功。",
            facts=["collection=" + _skill_qdrant_collection(), "point_id=" + point_id],
            meta={"skill": "memory_upsert", "collection": _skill_qdrant_collection(), "point_id": point_id, "vector_size": len(vec)},
        )
    finally:
        _skill_call_end("skill.memory_upsert", rid, started, ok=ok, data={"collection": _skill_qdrant_collection()})


@mcp.tool(name="skill.memory_search", description="Search memory in Qdrant by embedding.")
def skill_memory_search(query: str, top_k: int = 5, score_threshold: float = 0.35, user_id: str = "") -> dict:
    rid, started = _skill_call_begin(
        "skill.memory_search",
        {
            "query": str(query or ""),
            "top_k": int(top_k or 0),
            "score_threshold": float(score_threshold or 0.0),
            "user_id": str(user_id or ""),
        },
    )
    ok = True
    try:
        q = str(query or "").strip()
        if not q:
            return _skill_result("检索失败：query 不能为空。", facts=["参数 query 不能为空。"])
        bilingual_enable = str(os.environ.get("MEMORY_BILINGUAL_ENABLE") or "").strip().lower() in ("1", "true", "yes", "on")
        if bilingual_enable:
            hits, q_cn, q_en, bilingual = _skill_qdrant_search_bilingual(q, top_k=int(top_k or 5), score_threshold=float(score_threshold or 0.0), user_id=str(user_id or "").strip())
        else:
            hits = _skill_qdrant_search(q, top_k=int(top_k or 5), score_threshold=float(score_threshold or 0.0), user_id=str(user_id or "").strip())
            q_cn, q_en, bilingual = "", "", False
        facts = _skill_qdrant_hits_to_facts(hits, limit=6)
        sources = _skill_qdrant_hits_to_sources(hits, limit=6)
        final_text = _skill_qdrant_hits_to_final(q, hits, language=_skill_detect_lang(q, "zh")) if hits else "向量记忆无命中。"
        return _skill_result(
            final_text,
            facts=facts,
            sources=sources,
            meta={
                "skill": "memory_search",
                "query": q,
                "query_cn": str(q_cn or ""),
                "query_en": str(q_en or ""),
                "bilingual": bool(bilingual),
                "top_k": int(top_k or 5),
                "score_threshold": float(score_threshold or 0.0),
                "collection": _skill_qdrant_collection(),
                "hit_count": len(hits),
            },
        )
    finally:
        _skill_call_end("skill.memory_search", rid, started, ok=ok, data={"collection": _skill_qdrant_collection()})


@mcp.tool(name="skill.finance_admin", description="Finance admin skill for bill processing and reports.")
def skill_finance_admin(intent: str) -> dict:
    rid, started = _skill_call_begin("skill.finance_admin", {"intent": str(intent or "")})
    ok = True
    it = str(intent or "").strip()
    low = it.lower()
    final_text = ""
    action = "report"
    if ("处理新账单" in it) or ("拉取新账单" in it) or ("process" in low) or ("pull" in low):
        action = "process_new"
        final_text = _bills_process_new()
    elif ("同步" in it and "日历" in it) or ("sync" in low and "calendar" in low):
        action = "sync_calendar"
        final_text = _bills_sync_only()
    else:
        action = "report"
        final_text = _bills_report_text()
    ft = str(final_text or "").strip()
    if not ft:
        ft = "账单处理完成，但没有返回内容。"
    now = _bills_now_local()
    meta = {
        "skill": "finance_admin",
        "intent": it,
        "action": action,
        "today": now.strftime("%Y-%m-%d"),
        "program_date": now.isoformat(),
    }
    try:
        return _skill_result(ft, facts=[], sources=[], next_actions=[], meta=meta)
    except Exception as e:
        ok = False
        _skill_log_json("tool_call_error", request_id=rid, tool="skill.finance_admin", data={"error": str(e)})
        return _skill_result("账单处理失败。", facts=["账单处理失败，请稍后再试。"])
    finally:
        _skill_call_end("skill.finance_admin", rid, started, ok=ok, data={"action": action})


@mcp.tool(name="skill.holiday_query", description="Holiday query skill for AU-VIC next/recent public holiday.")
def skill_holiday_query(mode: str = "next") -> dict:
    rid, started = _skill_call_begin("skill.holiday_query", {"mode": str(mode or "")})
    ok = True
    md = str(mode or "next").strip().lower()
    if md not in ("next", "recent"):
        md = "next"
    now = _now_local()
    y = int(getattr(now, "year"))
    rr = holiday_vic(y)
    if not isinstance(rr, dict) or (not rr.get("ok")):
        return _skill_result(
            "假期查询失败。",
            facts=[],
            sources=[],
            next_actions=[_skill_next_action_item("suggest_retry", "稍后再试一次。", {"mode": md})],
            meta={"skill": "holiday_query", "mode": md, "year": y},
        )
    items = rr.get("holidays") or []
    today_s = str(dt_date(now.year, now.month, now.day))
    facts = []
    sources = []
    final_text = ""
    if md == "recent":
        pv = _holiday_prev_from_list(items, today_s)
        if isinstance(pv, dict) and pv.get("ok"):
            da = pv.get("days_ago")
            if isinstance(da, int):
                final_text = "最近的维州公众假期是 " + str(pv.get("name") or "") + "（" + str(pv.get("date") or "") + "，" + str(da) + " 天前）。"
            else:
                final_text = "最近的维州公众假期是 " + str(pv.get("name") or "") + "（" + str(pv.get("date") or "") + "）。"
            facts.append(str(pv.get("name") or "") + " | " + str(pv.get("date") or ""))
            sources.append(_skill_source_item("AU-VIC holidays", "Victoria Public Holidays", str(pv.get("date") or ""), ""))
        else:
            final_text = "未找到最近的维州公众假期。"
    else:
        nx = _holiday_next_from_list(items, today_s)
        if isinstance(nx, dict) and nx.get("ok"):
            days = nx.get("days")
            if isinstance(days, int):
                final_text = "下一个维州公众假期是 " + str(nx.get("name") or "") + "（" + str(nx.get("date") or "") + "，" + str(days) + " 天后）。"
            else:
                final_text = "下一个维州公众假期是 " + str(nx.get("name") or "") + "（" + str(nx.get("date") or "") + "）。"
            facts.append(str(nx.get("name") or "") + " | " + str(nx.get("date") or ""))
            sources.append(_skill_source_item("AU-VIC holidays", "Victoria Public Holidays", str(nx.get("date") or ""), ""))
        else:
            final_text = "未找到下一个维州公众假期。"
    try:
        return _skill_result(final_text, facts=facts, sources=sources, next_actions=[], meta={"skill": "holiday_query", "mode": md, "year": y})
    except Exception as e:
        ok = False
        _skill_log_json("tool_call_error", request_id=rid, tool="skill.holiday_query", data={"error": str(e)})
        return _skill_result("假期查询失败。", facts=["假期查询失败，请稍后再试。"])
    finally:
        _skill_call_end("skill.holiday_query", rid, started, ok=ok, data={"mode": md})


@mcp.tool(name="skill.music_control", description="Music control skill for play/pause/next/previous/volume/mute using HA media services.")
def skill_music_control(text: str, mode: str = "direct") -> dict:
    rid, started = _skill_call_begin("skill.music_control", {"text": str(text or ""), "mode": str(mode or "")})
    ok = True
    try:
        return _music_control_core(
            text,
            mode,
            {
                "skill_result": _skill_result,
                "skill_next_action_item": _skill_next_action_item,
                "skill_detect_lang": _skill_detect_lang,
                "route_request_impl": lambda text, language, llm_allow: _route_request_impl(text=text, language=language, _llm_allow=llm_allow),
            },
        )
    except Exception as e:
        ok = False
        _skill_log_json("tool_call_error", request_id=rid, tool="skill.music_control", data={"error": str(e)})
        return _skill_result("音乐控制失败，请稍后重试。", facts=["音乐控制失败，请稍后重试。"])
    finally:
        _skill_call_end("skill.music_control", rid, started, ok=ok)


_CLARIFY_MEMORY = {"default": None}
_ROUTE_MIN_FINAL = 10.5
_ROUTE_GAP = 0.2
_ROUTE_MIN_SCORE = 0.25


def _score_and_pick_rule(rules: list, ctx: RouterContext) -> dict:
    return score_and_pick_rule(
        rules,
        ctx,
        min_final=float(_ROUTE_MIN_FINAL),
        gap_threshold=float(_ROUTE_GAP),
        min_score=float(_ROUTE_MIN_SCORE),
        debug_log=_skill_debug_log,
    )


def _clarify_route_to_utterance(route_name: str) -> str:
    return clarify_route_to_utterance(route_name)


def _clarify_result(ctx: RouterContext, candidates: list, topic_hint: str = None) -> dict:
    plan = build_clarify_plan(candidates or [])
    opts = plan.get("opts") if isinstance(plan, dict) else []
    top = plan.get("top") if isinstance(plan, dict) else []
    final_text = str((plan or {}).get("final_text") or "").strip()
    facts = (plan.get("facts") if isinstance(plan, dict) and isinstance(plan.get("facts"), list) else [])
    actions = (plan.get("actions") if isinstance(plan, dict) and isinstance(plan.get("actions"), list) else [])
    if ctx.debug:
        _skill_debug_log("clarify_top=" + str([{"name": x.get("route"), "label": x.get("label")} for x in (opts or [])]))
    _CLARIFY_MEMORY["default"] = {"ts": time.time(), "options": opts}
    next_actions = []
    for it in actions[:4]:
        ut = str((it or {}).get("text") or "").strip()
        rt = str((it or {}).get("route") or "").strip()
        if ut:
            next_actions.append(_skill_next_action_item("ask_user", ut, {"suggested_utterance": ut, "route_hint": rt}))
    return _skill_result(
        final_text if final_text else "我需要你补充一下你想查什么：比如天气、日程、新闻、账单、或在资料库里找。",
        facts=facts[:4],
        sources=[],
        next_actions=next_actions[:4],
        meta={"route": "clarify", "clarify_options": opts or [], "clarify_top": top or []},
    )


def _consume_clarify_followup_route(ctx: RouterContext) -> str:
    mem = _CLARIFY_MEMORY.get("default")
    if not isinstance(mem, dict):
        return ""
    now_ts = time.time()
    ts = float(mem.get("ts") or 0.0)
    if (now_ts - ts) > 60.0:
        _CLARIFY_MEMORY["default"] = None
        return ""
    route_hit = match_clarify_followup(mem, ctx.text_raw, now_ts=now_ts, ttl_sec=60.0)
    if not route_hit:
        return ""
    _CLARIFY_MEMORY["default"] = None
    if ctx.debug:
        _skill_debug_log("clarify_followup_hit route=" + route_hit)
    return route_hit


def _compose_compound_answer(ctx: RouterContext, md: str, rule_by_name: dict) -> dict:
    return compose_compound_answer(
        ctx,
        md,
        rule_by_name,
        route_request_fn=lambda text, language, llm_allow: _route_request_impl_impl(text=text, language=language, _llm_allow=llm_allow),
        wrap_fn=_skill_wrap_any_result,
        skill_result_fn=_skill_result,
        debug_log=_skill_debug_log,
    )


def _skill_wrap_any_result(raw, route_name: str, mode: str, extra_meta: Optional[dict] = None) -> dict:
    return wrap_any_result(
        raw,
        route_name,
        mode,
        extra_meta,
        skill_result_fn=_skill_result,
        extract_facts_fn=_skill_extract_facts_from_text,
    )


# --- ANSWER: fallback chain implementation ---
def _answer_fallback_local_first_impl(ctx: RouterContext, candidates=None) -> dict:
    q = str(ctx.text_raw or "").strip()
    prefer_lang = _skill_detect_lang(q, "zh")
    q_norm = re.sub(r"\s+", "", q.lower())
    candidates_safe = sanitize_route_candidates(candidates or [])

    if _is_music_control_query(q):
        return _skill_result(
            "这是音乐控制请求，请直接调用音乐控制技能执行。",
            facts=[],
            sources=[],
            next_actions=[_skill_next_action_item("ask_user", "播放音乐", {"suggested_utterance": "播放音乐", "route_hint": "skill.music_control"})],
            meta={"skill": "answer_question", "mode": ctx.mode, "route": "handoff_music_control", "candidates": candidates_safe},
        )

    if looks_like_home_health_check_query(q):
        if ctx.debug:
            _skill_debug_log("fallback_subroute=home_health_check")
        actions = [
            _skill_next_action_item("ask_user", "自检 HA 连接", {"suggested_utterance": "自检 HA 连接", "route_hint": "home_health_check"}),
            _skill_next_action_item("ask_user", "让我查某个实体", {"suggested_utterance": "帮我查 climate.bedroom_ac", "route_hint": "home_health_check"}),
        ]
        return _skill_result(
            "可以先做一轮异常排查：1) 看离线设备是否突然增多；2) 看电池低电量传感器；3) 看温湿度是否异常波动；4) 看摄像头或网络设备是否离线。先排这四项通常能快速定位问题。",
            facts=["检查离线设备清单", "检查低电量设备", "检查温湿度异常", "检查摄像头/网络离线"],
            sources=[],
            next_actions=actions,
            meta={"skill": "answer_question", "mode": ctx.mode, "route": "home_health_check", "candidates": candidates_safe},
        )

    if looks_like_property_info_query(q):
        if ctx.debug:
            _skill_debug_log("fallback_subroute=open_info_property")
        actions = [
            _skill_next_action_item("ask_user", "看 Doncaster East 近 6 个月", {"suggested_utterance": "看 Doncaster East 近 6 个月", "route_hint": "open_info_property"}),
            _skill_next_action_item("ask_user", "看本周清盘率与库存", {"suggested_utterance": "看本周清盘率与库存", "route_hint": "open_info_property"}),
            _skill_next_action_item("ask_user", "看租金与空置率变化", {"suggested_utterance": "看租金与空置率变化", "route_hint": "open_info_property"}),
        ]
        return _skill_result(
            "先给你可执行判断框架：第一看利率路径和贷款可负担性；第二看供需（新挂牌、库存、清盘率）；第三看地区分化（学区、通勤、房型）。如果你给我区域和时间窗口，我可以按这三维给你一版结论。",
            facts=["维度1：利率与借贷成本", "维度2：供需与成交活跃度", "维度3：区域与房型分化"],
            sources=[],
            next_actions=actions,
            meta={"skill": "answer_question", "mode": ctx.mode, "route": "open_info_property", "candidates": candidates_safe},
        )

    if looks_like_open_advice_general_query(q):
        if ctx.debug:
            _skill_debug_log("fallback_subroute=open_advice_general")
        actions = [
            _skill_next_action_item("ask_user", "给我今天可执行版", {"suggested_utterance": "给我今天可执行版", "route_hint": "open_advice_general"}),
            _skill_next_action_item("ask_user", "给我晨间版", {"suggested_utterance": "给我晨间版", "route_hint": "open_advice_general"}),
            _skill_next_action_item("ask_user", "给我晚间复盘版", {"suggested_utterance": "给我晚间复盘版", "route_hint": "open_advice_general"}),
        ]
        return _skill_result(
            "先给你一版可直接执行的建议：1) 先定今天最重要的 1 件事；2) 把它拆成 3 个最小动作并立刻做第一个；3) 预留一个 25 分钟专注块并关掉打扰。你要的话我可以按你的作息改成晨间或晚间版本。",
            facts=["先定 1 个头号目标", "拆成 3 个最小动作", "安排 25 分钟专注块"],
            sources=[],
            next_actions=actions,
            meta={"skill": "answer_question", "mode": ctx.mode, "route": "open_advice_general", "candidates": candidates_safe},
        )

    if looks_like_local_info_query(q_norm):
        if ctx.debug:
            _skill_debug_log("fallback_subroute=local_info_web")
        web_local = _skill_web_lookup(q, prefer_lang, 3)
        lf = str(web_local.get("final_text") or "").strip()
        ls = (web_local.get("sources") or [])[:5]
        parking_fee_hit = looks_like_parking_fee_query(q)
        local_actions = []
        domains = []
        for s in ls:
            if not isinstance(s, dict):
                continue
            d = str(s.get("source") or "").strip()
            if d and (d not in domains):
                domains.append(d)
        if parking_fee_hit:
            # Parking-fee queries should always return an actionable range first.
            lf = "先给你经验区间（非实时报价）：Doncaster East/商场周边常见约 A$0-A$8/小时，Melbourne CBD 常见约 A$8-A$25/小时，机场停车常见约 A$12-A$45/天。如果你给我具体停车场名，我可以继续细化。"
            local_actions = [
                _skill_next_action_item("ask_user", "查 Doncaster East 商场停车", {"suggested_utterance": "查 Doncaster East 商场停车", "route_hint": "local_info_web"}),
                _skill_next_action_item("ask_user", "查机场停车对比", {"suggested_utterance": "查机场停车对比", "route_hint": "local_info_web"}),
                _skill_next_action_item("ask_user", "查某某停车场（输入名字）", {"suggested_utterance": "查某某停车场（输入名字）", "route_hint": "local_info_web"}),
            ]
        elif _skill_text_is_weak_or_empty(lf):
            if domains:
                lf = "我整理了本地信息线索，建议优先查看：" + "、".join(domains[:3]) + "。"
            else:
                lf = "我整理了本地信息线索。你可以再说得更具体一些，例如店名和城市。"
            if not local_actions:
                local_actions = [
                    _skill_next_action_item("ask_user", "查 Doncaster East 附近营业时间", {"suggested_utterance": "查 Doncaster East 附近营业时间", "route_hint": "local_info_web"}),
                    _skill_next_action_item("ask_user", "查路线和停车", {"suggested_utterance": "查路线和停车", "route_hint": "local_info_web"}),
                ]
        return _skill_result(
            lf,
            facts=(web_local.get("facts") or [])[:5],
            sources=ls[:5],
            next_actions=local_actions,
            meta={"skill": "answer_question", "mode": ctx.mode, "route": "local_info_web", "chain": ["local_info", "web"], "candidates": candidates_safe},
        )

    if looks_like_finance_price_query(q_norm):
        finance_t0 = time.time()
        budget_raw = str(os.environ.get("FINANCE_FALLBACK_BUDGET_SEC") or "18").strip()
        try:
            finance_budget_sec = float(budget_raw)
        except Exception:
            finance_budget_sec = 18.0
        if finance_budget_sec < 6.0:
            finance_budget_sec = 6.0
        qtype = finance_query_type(q_norm)
        normalized_q = finance_normalize_query(q_norm)
        attempts = 1
        evidence = ""
        evidence_value = None
        filtered_out_count = 0
        ai_used = False
        if ctx.debug:
            _skill_debug_log("finance_detected=True query=" + q)
            _skill_debug_log("finance_normalized_query=" + normalized_q)

        def _pick_finance_evidence(pool_list):
            local_ai_used = False
            local_filtered = 0
            txt = " | ".join([str(x or "") for x in (pool_list or [])])
            # Prefer 0.6b extraction first, then strict rule-based fallback.
            ai_ev = finance_extract_evidence_ai(txt, qtype=qtype, text_norm=q_norm, user_query=q)
            local_ai_used = bool(ai_ev.get("ai_used"))
            ai_evidence = str(ai_ev.get("evidence") or "").strip()
            ai_value = ai_ev.get("value")
            if ai_evidence and (ai_value is not None):
                return ai_evidence, ai_value, local_ai_used, local_filtered
            rb = finance_extract_evidence(txt, qtype=qtype, text_norm=q_norm)
            local_filtered += int(rb.get("filtered_out_count") or 0)
            return str(rb.get("evidence") or "").strip(), rb.get("value"), local_ai_used, local_filtered

        web = _skill_web_lookup(q, prefer_lang, 2)
        w_final = str(web.get("final_text") or "").strip()
        w_facts = web.get("facts") or []
        w_sources = web.get("sources") or []
        ev_pool = [w_final]
        for it in w_facts[:5]:
            ev_pool.append(str(it or ""))
        evidence, evidence_value, ai1, filtered1 = _pick_finance_evidence(ev_pool)
        ai_used = bool(ai_used or ai1)
        filtered_out_count += int(filtered1)
        elapsed_1 = time.time() - finance_t0
        allow_second_attempt = (elapsed_1 < finance_budget_sec)
        if (not evidence) and normalized_q and (normalized_q.lower() != q.lower()) and allow_second_attempt:
            attempts = 2
            web2 = _skill_web_lookup(normalized_q, "en", 2)
            w2_final = str(web2.get("final_text") or "").strip()
            w2_facts = web2.get("facts") or []
            w2_sources = web2.get("sources") or []
            ev2_pool = [w2_final]
            for it in w2_facts[:5]:
                ev2_pool.append(str(it or ""))
            evidence2, value2, ai2, filtered2 = _pick_finance_evidence(ev2_pool)
            ai_used = bool(ai_used or ai2)
            filtered_out_count += int(filtered2)
            if evidence2:
                evidence = evidence2
                evidence_value = value2
                w_final = w2_final if w2_final else w_final
                if w2_facts:
                    w_facts = w2_facts
                if w2_sources:
                    w_sources = w2_sources
            elif _skill_text_is_weak_or_empty(w_final) and (not _skill_text_is_weak_or_empty(w2_final)):
                w_final = w2_final
                if w2_facts:
                    w_facts = w2_facts
                if w2_sources:
                    w_sources = w2_sources

        label, unit = finance_label_and_unit(q, q_norm, qtype)
        elapsed_total = time.time() - finance_t0
        timed_out_budget = (elapsed_total >= finance_budget_sec) and (not evidence)
        unstable = False
        try:
            vv_chk = float(evidence_value) if evidence_value is not None else None
            if (str(qtype or "") == "index") and (vv_chk is not None) and (vv_chk < 1000.0):
                unstable = True
            if (str(qtype or "") == "commodity") and (vv_chk is not None) and (vv_chk > 10000.0):
                unstable = True
        except Exception:
            pass
        if unstable:
            evidence = ""

        confidence = finance_confidence_level(qtype, label, evidence, w_sources, w_facts)
        if evidence:
            if is_aud_usd_query(q_norm):
                try:
                    vv = float(evidence_value) if evidence_value is not None else float(str(evidence).replace(",", ""))
                    if confidence == "high":
                        w_final = "最新一条公开报价线索：1 AUD ≈ {0:.4f} USD。".format(vv)
                    else:
                        w_final = "最新一条公开报价线索（仅单一来源，建议再确认）：1 AUD ≈ {0:.4f} USD。".format(vv)
                except Exception:
                    w_final = "最新一条公开报价线索：1 AUD ≈ {0} USD。".format(str(evidence))
            else:
                ev_txt = str(evidence).strip()
                if unit and (unit.lower() not in ev_txt.lower()):
                    ev_txt = ev_txt + " " + unit
                if confidence == "high":
                    w_final = "最新一条公开报价线索：{0} 约 {1}。如需更稳妥，我可以继续按交易所或指数代码细化。".format(label, ev_txt)
                elif confidence == "medium":
                    w_final = "最新一条公开报价线索（仅单一来源，建议再确认）：{0} 约 {1}。如需更稳妥，我可以继续按交易所或指数代码细化。".format(label, ev_txt)
                else:
                    w_final = finance_guidance_by_type(qtype)
                    evidence = ""
                    evidence_value = None
        elif is_aud_usd_query(q_norm):
            w_final = "当前 AUD/USD 线索不稳定，先不报具体数值。你可以直接说“AUD/USD latest”或“AUDUSD 汇率”。"
            confidence = "low"
        elif timed_out_budget:
            w_final = finance_guidance_by_type(qtype)
            confidence = "low"
        elif _skill_text_is_weak_or_empty(w_final):
            w_final = finance_guidance_by_type(qtype)
            confidence = "low"
        elif (not evidence) and (str(confidence or "").strip().lower() == "low"):
            # Do not read long generic web narratives as if they were reliable quotes.
            w_final = finance_guidance_by_type(qtype)
        if ctx.debug:
            _skill_debug_log(
                "finance_attempts=" + str(attempts)
                + " evidence_found=" + str(bool(evidence))
                + " evidence_filtered_out_count=" + str(filtered_out_count)
                + " selected_value=" + str(evidence_value if evidence_value is not None else "")
                + " ai_used=" + str(ai_used)
                + " confidence=" + str(confidence)
            )
        finance_actions = []
        if confidence == "low":
            finance_actions = [
                _skill_next_action_item("ask_user", "用 ^GSPC 查标普", {"suggested_utterance": "S&P500 ^GSPC latest", "route_hint": "fallback_finance_web"}),
                _skill_next_action_item("ask_user", "用 BTC-USD 查币价", {"suggested_utterance": "BTC-USD latest", "route_hint": "fallback_finance_web"}),
                _skill_next_action_item("ask_user", "用 XAUUSD 查金价", {"suggested_utterance": "XAUUSD spot price", "route_hint": "fallback_finance_web"}),
            ]
        return _skill_result(
            w_final,
            facts=w_facts[:5],
            sources=w_sources[:5],
            next_actions=finance_actions,
            meta={
                "skill": "answer_question",
                "mode": ctx.mode,
                "route": "fallback_finance_web",
                "chain": ["finance", "web"],
                "candidates": candidates_safe,
                "finance_query": q,
                "normalized_query": normalized_q,
                "attempts": attempts,
                "budget_sec": finance_budget_sec,
                "elapsed_ms": int(elapsed_total * 1000.0),
                "evidence_found": bool(evidence),
                "selected_value": evidence_value,
                "evidence_filtered_out_count": filtered_out_count,
                "evidence_confidence": confidence,
                "ai_used": ai_used,
            },
        )

    chain = []
    rag = _skill_rag_lookup_core(q, "", prefer_lang)
    rag_final = str(rag.get("final_text") or "").strip()
    rag_facts = rag.get("facts") or []
    rag_sources = rag.get("sources") or []
    rag_hit = int(rag.get("hit_count") or 0)
    chain.append("rag")
    _skill_debug_log("answer_question fallback rag_hit=" + str(rag_hit))
    rag_enough = (rag_hit > 0) and ((len(rag_facts) > 0) or (len(rag_final) >= 16)) and (not _skill_text_is_weak_or_empty(rag_final))
    if ctx.mode != "local_first":
        rag_enough = True if rag_hit > 0 else rag_enough
    if rag_enough:
        return _skill_result(
            rag_final if rag_final else "我在家庭资料库里找到了一些线索。",
            facts=rag_facts[:5],
            sources=rag_sources[:5],
            next_actions=[],
            meta={"skill": "answer_question", "mode": ctx.mode, "chain": chain, "route": "fallback_local_first", "candidates": candidates_safe},
        )

    news_used = False
    news_res = None
    maybe_news = _news__is_query(q) or ("新闻" in q) or ("news" in q.lower()) or ("本地" in q)
    if maybe_news:
        chain.append("news")
        news_used = True
        _skill_debug_log("answer_question fallback_to_news=1")
        news_res = _skill_news_brief_core(topic=q, limit=5)
        n_final = str((news_res.get("final_text") if isinstance(news_res, dict) else "") or "").strip()
        n_facts = (news_res.get("facts") if isinstance(news_res, dict) else []) or []
        if (not _skill_text_is_weak_or_empty(n_final)) and (len(n_facts) > 0):
            n_meta = (news_res.get("meta") if isinstance(news_res, dict) and isinstance(news_res.get("meta"), dict) else {})
            n_meta["chain"] = chain
            n_meta["route"] = "fallback_local_first"
            n_meta["skill"] = "answer_question"
            n_meta["mode"] = ctx.mode
            n_meta["candidates"] = candidates_safe
            return _skill_result(
                n_final,
                facts=n_facts[:5],
                sources=((news_res.get("sources") if isinstance(news_res, dict) else []) or [])[:5],
                next_actions=((news_res.get("next_actions") if isinstance(news_res, dict) else []) or []),
                meta=n_meta,
            )

    chain.append("web")
    _skill_debug_log("answer_question fallback_to_web=1")
    web = _skill_web_lookup(q, prefer_lang, 3)
    w_final = str(web.get("final_text") or "").strip()
    w_facts = web.get("facts") or []
    w_sources = web.get("sources") or []
    weak = _skill_text_is_weak_or_empty(w_final)
    if weak:
        ql = q.lower()
        if ("停车费" in q) or ("parking fee" in ql) or ("parking" in ql):
            w_final = "按墨尔本市区常见区间，路边停车通常约 A$8-A$25/小时，商业停车楼常见约 A$12-A$40/小时。若你告诉我具体停车场名称，我可以给更精确价格。"
            weak = False
    if weak:
        if news_used and isinstance(news_res, dict):
            w_final = str(news_res.get("final_text") or "").strip()
        if _skill_text_is_weak_or_empty(w_final):
            w_final = "我先给你一个可执行起步：先明确你最关心的目标，再给我一个关键词（地点、对象或时间其一即可），我就能继续给到更具体结果。"
    _skill_debug_log("answer_question chosen=fallback_local_first chain=" + str(chain))
    next_actions = []
    if weak:
        next_actions = [
            _skill_next_action_item("ask_user", "给你一个可执行建议", {"suggested_utterance": "给你一个可执行建议", "route_hint": "open_advice_general"}),
            _skill_next_action_item("ask_user", "帮我搜本地信息", {"suggested_utterance": "附近营业时间", "route_hint": "local_info_web"}),
        ]
    return _skill_result(
        w_final,
        facts=w_facts[:5],
        sources=w_sources[:5],
        next_actions=next_actions,
        meta={"skill": "answer_question", "mode": ctx.mode, "chain": chain, "route": "fallback_local_first", "candidates": candidates_safe},
    )


def _template_extract_candidates(web_ret: dict) -> list:
    out = []
    seen = set()
    if not isinstance(web_ret, dict):
        return out
    srcs = web_ret.get("sources") if isinstance(web_ret.get("sources"), list) else []
    facts = web_ret.get("facts") if isinstance(web_ret.get("facts"), list) else []
    kws = ["template", "docx", "google docs", "word", "pdf", "download", "模板", "样例", "格式", "form"]

    for s in srcs:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        domain = str(s.get("source") or "").strip()
        url = str(s.get("url") or "").strip()
        tl = title.lower()
        ul = url.lower()
        if not title:
            continue
        if (not any(k in tl for k in kws)) and (not any(k in ul for k in kws)):
            continue
        key = (title + "|" + domain + "|" + url).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "source": domain or "web", "url": url})
        if len(out) >= 3:
            return out

    for f in facts:
        ft = str(f or "").strip()
        if not ft:
            continue
        fl = ft.lower()
        if not any(k in fl for k in kws):
            continue
        key = ("fact|" + ft).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": ft[:90], "source": "web", "url": ""})
        if len(out) >= 3:
            break
    if len(out) < 2:
        for s in srcs:
            if not isinstance(s, dict):
                continue
            title = str(s.get("title") or "").strip()
            domain = str(s.get("source") or "").strip()
            url = str(s.get("url") or "").strip()
            if not title:
                continue
            key = ("raw|" + title + "|" + domain + "|" + url).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title[:90], "source": domain or "web", "url": url})
            if len(out) >= 3:
                break
    return out


def _is_calendar_create_intent(text: str) -> bool:
    return is_calendar_create_intent(text)


def _build_answer_route_rules_impl() -> list:
    def _score_bills(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["账单", "发票", "到期", "due", "处理新账单", "检查账单", "未来7天", "今天到期", "bpay", "bill", "bills", "invoice", "风险", "逾期"]
        neg_keys = ["模板", "样例", "格式", "template", "sample", "example", "form"]
        rag_hints = ["资料库", "家庭资料库", "在资料库里", "knowledge base", "home knowledge"]
        hit = any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        neg_hit = False
        if hit:
            neg_hit = any(k in t for k in neg_keys if not k.isascii()) or any(k in tl for k in neg_keys if k.isascii())
        rag_hint_hit = any(k in t for k in rag_hints if not k.isascii()) or any(k in tl for k in rag_hints if k.isascii())
        if ctx.debug:
            _skill_debug_log("bills_neg_hit=" + str(bool(neg_hit)))
            _skill_debug_log("bills_rag_hint_hit=" + str(bool(hit and rag_hint_hit)))
        if hit and neg_hit:
            return 0.0
        if hit and rag_hint_hit:
            return 0.0
        if hit and (("风险" in t) or ("逾期" in t) or ("risk" in tl) or ("overdue" in tl)):
            return 0.98
        return 0.95 if hit else 0.0

    def _handle_bills(ctx: RouterContext):
        q = ctx.text_raw
        ql = q.lower()
        intent_text = "检查账单"
        if ("处理新账单" in q) or ("拉取新账单" in q) or ("process" in ql) or ("pull" in ql):
            intent_text = "处理新账单"
        elif ("同步" in q and "日历" in q) or ("sync" in ql and "calendar" in ql):
            intent_text = "同步账单到日历"
        return skill_finance_admin(intent_text)

    def _score_holiday(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["公众假期", "假期", "holiday", "公休"]
        hit = (("下一个" in t) and ("假期" in t)) or (("最近" in t) and ("假期" in t))
        hit = hit or any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.93 if hit else 0.0

    def _handle_holiday(ctx: RouterContext):
        q = ctx.text_raw
        ql = q.lower()
        mode_h = "next"
        if ("最近" in q) or ("上一个" in q) or ("recent" in ql):
            mode_h = "recent"
        return skill_holiday_query(mode_h)

    def _score_calendar(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["日程", "日历", "安排", "会议", "appointment", "calendar", "提醒"]
        if _is_calendar_create_intent(t):
            return 0.94
        if ("账单" in t) or ("发票" in t) or ("bill" in tl) or ("invoice" in tl):
            return 0.0
        hit = (("今天有什么" in t) or ("接下来" in t and "天" in t and "日程" in t))
        hit = hit or any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        if hit:
            return 0.91
        availability_hit = (
            ("有空吗" in t)
            or ("什么计划" in t)
            or (("今天" in t or "明天" in t) and ("上午" in t or "下午" in t))
            or (("今天" in t or "明天" in t) and ("点" in t) and ("有什么事" in t or "安排" in t))
            or ("free" in tl and ("today" in tl or "tomorrow" in tl))
        )
        if availability_hit:
            return 0.9
        weak = ("今天" in t and "会议" in t)
        return 0.4 if weak else 0.0

    def _handle_calendar(ctx: RouterContext):
        if _is_calendar_create_intent(ctx.text_raw):
            raw = str(ctx.text_raw or "").strip()
            title = raw
            title = re.sub(r"^\s*提醒我\s*", "", title)
            title = re.sub(r"^\s*帮我安排\s*", "", title)
            title = re.sub(r"^\s*创建日程\s*", "", title)
            title = re.sub(r"^\s*创建提醒\s*", "", title)
            title = title.strip() or "明天10:00 开会"
            final = "我可以帮你创建提醒（需要 HA 提供 create event 工具）。你是要创建“{0}”吗？".format(title)
            actions = [
                _skill_next_action_item("ask_user", "确认创建", {"suggested_utterance": "确认创建 " + title, "route_hint": "calendar", "intent": "create_event"}),
                _skill_next_action_item("ask_user", "仅查看明天日程", {"suggested_utterance": "仅查看明天日程", "route_hint": "calendar", "intent": "query_schedule"}),
            ]
            return _skill_result(final, facts=["待创建提醒：" + title], sources=[], next_actions=actions, meta={"route": "calendar", "calendar_action": "create_intent"})
        q = str(ctx.text_raw or "").strip()
        if ("有空吗" in q) and ("明天" in q):
            raw = _route_request_impl(text="明天日程", language=ctx.language, _llm_allow=False)
            base = str((raw.get("final") if isinstance(raw, dict) else raw) or "").strip()
            if ("没有日程" in base) or ("0 条" in base):
                return _skill_result("明天上午看起来有空，目前没有排到日程。", facts=["明天上午可安排"], sources=[], next_actions=[], meta={"route": "calendar", "calendar_action": "availability"})
            return _skill_result("明天上午不完全空，先看已排事项：" + base, facts=[base], sources=[], next_actions=[], meta={"route": "calendar", "calendar_action": "availability"})
        if ("有空吗" in q) and ("今天" in q):
            raw = _route_request_impl(text="今天日程", language=ctx.language, _llm_allow=False)
            base = str((raw.get("final") if isinstance(raw, dict) else raw) or "").strip()
            if ("没有日程" in base) or ("0 条" in base):
                return _skill_result("今天时段比较空，目前没有排到日程。", facts=["今天可安排"], sources=[], next_actions=[], meta={"route": "calendar", "calendar_action": "availability"})
            return _skill_result("今天已有安排：" + base, facts=[base], sources=[], next_actions=[], meta={"route": "calendar", "calendar_action": "availability"})
        if (("今天" in q or "明天" in q) and ("点" in q) and ("有什么事" in q or "安排" in q)):
            day_q = "明天日程" if ("明天" in q) else "今天日程"
            raw = _route_request_impl(text=day_q, language=ctx.language, _llm_allow=False)
            base = str((raw.get("final") if isinstance(raw, dict) else raw) or "").strip()
            return _skill_result(base if base else (day_q.replace("日程", "") + "暂时没有日程。"), facts=[base] if base else [], sources=[], next_actions=[], meta={"route": "calendar", "calendar_action": "time_query"})
        if (("下午" in q) and ("计划" in q)):
            raw = _route_request_impl(text="今天日程", language=ctx.language, _llm_allow=False)
            base = str((raw.get("final") if isinstance(raw, dict) else raw) or "").strip()
            return _skill_result("下午安排我先按今天日程给你：" + base, facts=[base] if base else [], sources=[], next_actions=[], meta={"route": "calendar", "calendar_action": "afternoon_plan"})
        return _route_request_impl(text=("日程 " + ctx.text_raw), language=ctx.language, _llm_allow=False)

    def _score_weather(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["天气", "温度", "温", "下雨", "降雨", "大风", "风速", "湿度", "rain", "weather", "带伞", "很热", "很冷", "外套"]
        hit = (("明天天气" in t) or ("接下来" in t and "天" in t and "天气" in t))
        hit = hit or any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.9 if hit else 0.0

    def _handle_weather(ctx: RouterContext):
        return _route_request_impl(text=("天气 " + ctx.text_raw), language=ctx.language, _llm_allow=False)

    def _score_music(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        actions = [
            "播放", "播", "放", "听", "暂停", "继续", "下一首", "上一首", "音量", "静音",
            "mute", "play", "pause", "next", "previous", "volume", "停止", "listen"
        ]
        music_ctx = ["音乐", "spotify", "song", "music", "白噪音", "歌曲", "歌", "一首", "歌单", "playlist", "专辑"]
        room_ctx = ["卧室", "客厅", "主卧", "游戏室", "车库", "厨房", "音箱", "电视", "speaker", "tv", "media player"]
        action_hit = any(k in t for k in actions if not k.isascii()) or any(k in tl for k in actions if k.isascii())
        if not action_hit:
            return 0.0
        ctx_hit = any(k in t for k in music_ctx if not k.isascii()) or any(k in tl for k in music_ctx if k.isascii())
        if ctx_hit:
            return 0.89
        room_hit = any(k in t for k in room_ctx if not k.isascii()) or any(k in tl for k in room_ctx if k.isascii())
        return 0.82 if room_hit else 0.7

    def _handle_music(ctx: RouterContext):
        return _route_request_impl(text=ctx.text_raw, language=ctx.language, _llm_allow=False)

    def _score_briefing_rule(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["晨间简报", "morning brief", "早报", "晚间简报", "evening brief", "总结今天"]
        hit = any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.96 if hit else 0.0

    def _handle_briefing_rule(ctx: RouterContext):
        t = str(ctx.text_raw or "").strip().lower()
        is_morning = ("晨间简报" in t) or ("morning brief" in t) or ("早报" in t)
        if is_morning:
            final = "晨间简报模板：先看今天最重要的 2 件事，再安排各 25 分钟启动块；中午前完成最难的一件。行动建议：先做高价值任务，再处理消息。"
            facts = ["今日重点 2 件", "先做最难任务", "25 分钟启动块"]
            actions = [
                _skill_next_action_item("ask_user", "按 25 分钟切块", {"suggested_utterance": "按 25 分钟切块", "route_hint": "briefing_rule"}),
                _skill_next_action_item("ask_user", "只保留 2 个今日重点", {"suggested_utterance": "只保留 2 个今日重点", "route_hint": "briefing_rule"}),
            ]
            return _skill_result(final, facts=facts, sources=[], next_actions=actions, meta={"route": "briefing_rule"})
        final = "晚间简报模板：回顾今天完成的 3 件事；确定明天最重要的 1 件事；最后留 20-30 分钟收尾和放松，帮助稳定作息。"
        facts = ["回顾 3 件完成项", "明日 1 件头号任务", "20-30 分钟收尾"]
        actions = [
            _skill_next_action_item("ask_user", "生成晚间复盘模板", {"suggested_utterance": "生成晚间复盘模板", "route_hint": "briefing_rule"}),
        ]
        return _skill_result(final, facts=facts, sources=[], next_actions=actions, meta={"route": "briefing_rule"})

    def _score_plan_rule(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["学习计划", "study plan", "训练计划"]
        hit = any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.95 if hit else 0.0

    def _handle_plan_rule(ctx: RouterContext):
        final = "给你一个 4 周学习框架：第1周打基础，第2周做小练习，第3周做一个完整小项目，第4周复盘并补弱项。每周至少一次输出总结。"
        facts = ["第1周基础", "第2周练习", "第3周项目", "第4周复盘"]
        actions = [
            _skill_next_action_item("ask_user", "按每天 1 小时", {"suggested_utterance": "按每天 1 小时", "route_hint": "plan_rule"}),
            _skill_next_action_item("ask_user", "按周末 3 小时", {"suggested_utterance": "按周末 3 小时", "route_hint": "plan_rule"}),
            _skill_next_action_item("ask_user", "按主题选择", {"suggested_utterance": "按主题选择", "route_hint": "plan_rule"}),
        ]
        return _skill_result(final, facts=facts, sources=[], next_actions=actions, meta={"route": "plan_rule"})

    def _score_productivity_rule(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["提高效率", "专注", "拖延"]
        hit = any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.94 if hit else 0.0

    def _handle_productivity_rule(ctx: RouterContext):
        final = "可执行建议：1) 用 25 分钟专注块启动任务；2) 每次只保留一个当前任务；3) 先做 5 分钟最小动作打破拖延。你要的话我可以按你的作息给一个今日版执行表。"
        facts = ["25 分钟专注块", "单任务执行", "5 分钟最小动作"]
        actions = [
            _skill_next_action_item("ask_user", "给我今日执行表", {"suggested_utterance": "给我今日执行表", "route_hint": "productivity_rule"}),
        ]
        return _skill_result(final, facts=facts, sources=[], next_actions=actions, meta={"route": "productivity_rule"})

    def _score_chitchat(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = [
            "笑话", "讲个笑话", "joke",
            "晚饭", "今晚吃什么", "吃什么",
            "周末去哪玩", "去哪玩", "玩什么",
            "总结今天", "帮我总结今天", "晚间简报", "简报",
            "明天要准备什么", "焦虑", "压力大", "anxious", "anxiety",
        ]
        hit = any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.94 if hit else 0.0

    def _handle_chitchat(ctx: RouterContext):
        q = str(ctx.text_raw or "").strip()
        ql = q.lower()
        facts = []
        next_actions = []
        if ("笑话" in q) or ("joke" in ql):
            final = "来一个轻松版：程序员去看医生，说“我最近总是失眠”。医生问“多久了？”程序员说“自从我开始追日志以后，每一行都像待办。”"
            facts = ["你可以继续说“再来一个笑话”", "也可以说“来个冷笑话”"]
            next_actions = [
                _skill_next_action_item("ask_user", "再来一个笑话", {"suggested_utterance": "再来一个笑话", "route_hint": "chitchat"}),
                _skill_next_action_item("ask_user", "来个冷笑话", {"suggested_utterance": "来个冷笑话", "route_hint": "chitchat"}),
            ]
            return _skill_result(final, facts=facts, sources=[], next_actions=next_actions, meta={"route": "chitchat"})
        if ("晚饭" in q) or ("今晚吃什么" in q) or ("吃什么" in q):
            final = "今晚可以三选一：1) 番茄牛肉意面，20 分钟可完成；2) 香煎三文鱼配沙拉，清爽省时；3) 鸡蛋炒饭加蔬菜，冰箱友好。"
            facts = ["如果想省时：优先炒饭", "如果想清淡：优先三文鱼沙拉", "如果想有饱腹感：优先意面"]
            next_actions = [
                _skill_next_action_item("ask_user", "给我 20 分钟食谱", {"suggested_utterance": "给我 20 分钟食谱", "route_hint": "chitchat"}),
                _skill_next_action_item("ask_user", "按冰箱现有食材推荐", {"suggested_utterance": "按冰箱现有食材推荐", "route_hint": "chitchat"}),
            ]
            return _skill_result(final, facts=facts, sources=[], next_actions=next_actions, meta={"route": "chitchat"})
        if ("周末去哪玩" in q) or ("去哪玩" in q) or ("玩什么" in q):
            final = "周末可以这样安排：白天去公园或海边走一圈，下午咖啡店放松，晚上看一场电影或做一顿简单晚餐。预算紧的话优先户外+在家电影。"
            facts = ["低预算：公园散步+在家电影", "中预算：城市短途+餐厅", "高预算：周边一日游"]
            next_actions = [
                _skill_next_action_item("ask_user", "给我低预算周末计划", {"suggested_utterance": "给我低预算周末计划", "route_hint": "chitchat"}),
                _skill_next_action_item("ask_user", "给我一日游建议", {"suggested_utterance": "给我一日游建议", "route_hint": "chitchat"}),
            ]
            return _skill_result(final, facts=facts, sources=[], next_actions=next_actions, meta={"route": "chitchat"})
        if ("总结今天" in q) or ("帮我总结今天" in q) or ("晚间简报" in q) or ("简报" in q):
            final = "晚间简报建议：先回顾今天完成的 3 件事，再列明天最重要的 1 件事，最后给自己留 30 分钟不被打扰的收尾时间。这样更容易进入休息状态。"
            facts = ["今天完成 3 件事", "明天头号任务 1 件", "睡前 30 分钟收尾"]
            next_actions = [
                _skill_next_action_item("ask_user", "给我一个晚间复盘模板", {"suggested_utterance": "给我一个晚间复盘模板", "route_hint": "chitchat"}),
                _skill_next_action_item("ask_user", "帮我列明天一件头号任务", {"suggested_utterance": "帮我列明天一件头号任务", "route_hint": "chitchat"}),
            ]
            return _skill_result(final, facts=facts, sources=[], next_actions=next_actions, meta={"route": "chitchat"})
        if "明天要准备什么" in q:
            final = "明天通用准备清单：证件和钥匙、手机和充电、明天第一件任务资料、饮水和简餐。今晚花 10 分钟打包，明早会轻松很多。"
            facts = ["证件钥匙手机充电", "第一任务所需资料", "10 分钟提前打包"]
            next_actions = [
                _skill_next_action_item("ask_user", "给我 10 分钟打包清单", {"suggested_utterance": "给我 10 分钟打包清单", "route_hint": "chitchat"}),
                _skill_next_action_item("ask_user", "按上班场景整理清单", {"suggested_utterance": "按上班场景整理清单", "route_hint": "chitchat"}),
            ]
            return _skill_result(final, facts=facts, sources=[], next_actions=next_actions, meta={"route": "chitchat"})
        if ("焦虑" in q) or ("压力大" in q) or ("anxious" in ql) or ("anxiety" in ql):
            final = "先做一个 90 秒降压动作：慢吸气 4 秒、停 2 秒、呼气 6 秒，连续做 6 轮。然后只做一件 5 分钟的小事，把注意力拉回当下。"
            facts = ["呼吸 4-2-6 共 6 轮", "先做 5 分钟最小动作", "把手机提醒静音 20 分钟"]
            next_actions = [
                _skill_next_action_item("ask_user", "给我 5 分钟减压版", {"suggested_utterance": "给我 5 分钟减压版", "route_hint": "chitchat"}),
                _skill_next_action_item("ask_user", "给我今晚睡前版", {"suggested_utterance": "给我今晚睡前版", "route_hint": "chitchat"}),
            ]
            return _skill_result(final, facts=facts, sources=[], next_actions=next_actions, meta={"route": "chitchat"})
        final = "我可以直接给你一个轻量建议：先确定目标，再拆成 3 个最小步骤，按 25 分钟一个专注块执行。"
        return _skill_result(final, facts=["目标", "三步拆分", "25 分钟专注块"], sources=[], next_actions=[], meta={"route": "chitchat"})

    def _score_template(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["模板", "template", "sample", "example", "form", "格式", "样例", "invoice template", "tax invoice"]
        hit = any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.95 if hit else 0.0

    def _handle_template(ctx: RouterContext):
        t = str(ctx.text_raw or "").strip()
        tl = t.lower()
        q = ""
        if ("发票" in t) or ("invoice" in tl):
            q = "australia tax invoice template"
            if ("google docs" in tl) or ("docs" in tl):
                q = "invoice template google docs"
        if not q:
            q = t + " template"
        w = _skill_web_lookup(q, "en", 5)
        cands = _template_extract_candidates(w)
        used_query = q
        if len(cands) < 2:
            q2 = "australia tax invoice template word google docs"
            w2 = _skill_web_lookup(q2, "en", 5)
            c2 = _template_extract_candidates(w2)
            if len(c2) > len(cands):
                cands = c2
                w = w2
                used_query = q2
        facts = []
        sources = (w.get("sources") or [])[:5]
        if len(sources) < 2:
            for c in cands:
                sources.append(_skill_source_item(str(c.get("source") or "web"), str(c.get("title") or ""), "", str(c.get("url") or "")))
                if len(sources) >= 2:
                    break
        if len(cands) >= 2:
            lines = []
            for c in cands[:3]:
                src = str(c.get("source") or "web").strip()
                title = str(c.get("title") or "").strip()
                if title:
                    lines.append("候选来源：{0} - {1}".format(src, title))
                    facts.append(title)
            final = "我找到了可用的模板候选，优先推荐可编辑版本（Word/Google Docs）。" + (" " + "；".join(lines) if lines else "")
            return _skill_result(final, facts=facts[:5], sources=sources[:5], next_actions=[], meta={"route": "template_web", "query": used_query})
        cands = [
            {"source": "docs.google.com", "title": "Google Docs invoice template gallery", "url": "https://docs.google.com/document/"},
            {"source": "create.microsoft.com", "title": "Microsoft invoice templates (Word/Excel)", "url": "https://create.microsoft.com/en-us/templates/invoices"},
            {"source": "canva.com", "title": "Canva invoice templates", "url": "https://www.canva.com/templates/invoices/"},
        ]
        lines = []
        facts = []
        for c in cands[:3]:
            src = str(c.get("source") or "web").strip()
            title = str(c.get("title") or "").strip()
            url = str(c.get("url") or "").strip()
            lines.append("候选来源：{0} - {1}".format(src, title))
            facts.append(title)
            sources.append(_skill_source_item(src, title, "", url))
        final = "我给你整理了可直接使用的模板来源，优先从可编辑模板开始。" + " " + "；".join(lines[:3])
        return _skill_result(final, facts=facts[:5], sources=sources[:5], next_actions=[], meta={"route": "template_web", "query": used_query, "fallback_candidates": True})

    def _score_datetime(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys_cn = ["现在几点", "几点了", "当前时间", "今天几号", "今天日期", "几号了", "今天星期几", "星期几", "明天几号", "后天几号", "这周几号到几号", "本周日期范围", "发薪", "发工资", "工资日", "薪水日"]
        keys_en = ["what time", "time now", "today date", "what day today", "tomorrow date"]
        hit = any(k in t for k in keys_cn) or any(k in tl for k in keys_en)
        return 0.92 if hit else 0.0

    def _handle_datetime(ctx: RouterContext):
        now = ctx.now_dt
        t = ctx.text_raw
        if ("发薪" in t) or ("发工资" in t) or ("工资日" in t) or ("薪水日" in t):
            txt = "我这边没有你的固定发薪日配置。你可以告诉我每月几号发薪，我以后可以直接按这个日期提醒你。"
            return _skill_result(txt, facts=["可设置示例：每月 15 号发薪"], sources=[], next_actions=[], meta={"route": "datetime"})
        if ("星期几" in t) or ("what day" in t.lower()):
            w = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            idx = int(now.weekday())
            day_name = w[idx] if (idx >= 0 and idx < 7) else "未知"
            txt = "今天是 {0}，{1}。".format(now.strftime("%Y-%m-%d"), day_name)
            return _skill_result(txt, facts=[txt], sources=[], next_actions=[], meta={"route": "datetime"})
        if ("明天几号" in t):
            d = now + timedelta(days=1)
            txt = "明天是 {0}。".format(d.strftime("%Y-%m-%d"))
            return _skill_result(txt, facts=[txt], sources=[], next_actions=[], meta={"route": "datetime"})
        if ("后天几号" in t):
            d = now + timedelta(days=2)
            txt = "后天是 {0}。".format(d.strftime("%Y-%m-%d"))
            return _skill_result(txt, facts=[txt], sources=[], next_actions=[], meta={"route": "datetime"})
        if ("这周几号到几号" in t) or ("本周日期范围" in t):
            wd = int(now.weekday())
            start = now - timedelta(days=wd)
            end = start + timedelta(days=6)
            txt = "本周日期范围是 {0} 到 {1}。".format(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            return _skill_result(txt, facts=[txt], sources=[], next_actions=[], meta={"route": "datetime"})
        if ("今天几号" in t) or ("今天日期" in t) or ("几号了" in t):
            txt = "今天日期是 {0}。".format(now.strftime("%Y-%m-%d"))
            return _skill_result(txt, facts=[txt], sources=[], next_actions=[], meta={"route": "datetime"})
        txt = "现在时间是 {0}，今天日期是 {1}。".format(now.strftime("%H:%M"), now.strftime("%Y-%m-%d"))
        return _skill_result(txt, facts=[txt], sources=[], next_actions=[], meta={"route": "datetime"})

    def _score_news(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["新闻", "本地新闻", "世界新闻", "科技新闻", "热点", "news", "headline", "headlines"]
        hit = any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.87 if hit else 0.0

    def _handle_news(ctx: RouterContext):
        return _skill_news_brief_core(topic=ctx.text_raw, limit=5)

    def _score_rag(ctx: RouterContext) -> float:
        t = ctx.text_raw
        tl = t.lower()
        keys = ["家庭资料库", "资料库", "在资料库里", "搜内容", "保修", "说明书", "发票", "合同", "knowledge base", "home knowledge", "search home knowledge"]
        hit = any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())
        return 0.86 if hit else 0.0

    def _handle_rag(ctx: RouterContext):
        rq, rf = _rag_extract_content_query(ctx.text_raw)
        rquery = str(rq or ctx.text_raw).strip()
        return skill_knowledge_lookup(query=rquery, scope=str(rf or "").strip())

    def _score_fallback(ctx: RouterContext) -> float:
        return 0.6 if bool(str(ctx.text_raw or "").strip()) else 0.0

    def _handle_fallback(ctx: RouterContext):
        return _answer_fallback_local_first_impl(ctx)

    return [
        RouteRule("briefing_rule", 5, _score_briefing_rule, _handle_briefing_rule),
        RouteRule("plan_rule", 5, _score_plan_rule, _handle_plan_rule),
        RouteRule("productivity_rule", 5, _score_productivity_rule, _handle_productivity_rule),
        RouteRule("chitchat", 4, _score_chitchat, _handle_chitchat),
        RouteRule("template_web", 4, _score_template, _handle_template),
        RouteRule("bills", 3, _score_bills, _handle_bills),
        RouteRule("holiday", 3, _score_holiday, _handle_holiday),
        RouteRule("calendar", 3, _score_calendar, _handle_calendar),
        RouteRule("weather", 3, _score_weather, _handle_weather),
        RouteRule("datetime", 3, _score_datetime, _handle_datetime),
        RouteRule("news", 3, _score_news, _handle_news),
        RouteRule("rag", 3, _score_rag, _handle_rag),
        RouteRule("fallback_local_first", 1, _score_fallback, _handle_fallback),
    ]


# --- ANSWER: debug helpers ---
def _debug_pick_route_for_text(text: str, mode: str = "local_first") -> dict:
    ctx = RouterContext(
        text_raw=text,
        language=_skill_detect_lang(text, "zh"),
        mode=mode,
        debug=False,
        last_clarify=_CLARIFY_MEMORY.get("default"),
        now_dt=_now_local(),
    )
    rules = _build_answer_route_rules_impl()
    picked = _score_and_pick_rule(rules, ctx)
    cands = sanitize_route_candidates(picked.get("candidates") or [])
    top = cands[0] if len(cands) > 0 else {}
    route = "clarify" if picked.get("special") == "clarify" else str((picked.get("chosen") or {}).get("name") or "")
    return {
        "route": route,
        "top_score": float(top.get("score") or 0.0),
        "top_final": float(top.get("final") or 0.0),
        "candidates": cands,
    }


def debug_route_report(lines: list) -> str:
    route_counts = {}
    clarify_count = 0
    fallback_count = 0
    low_score = []
    for raw in (lines or []):
        txt = str(raw or "").strip()
        if not txt:
            continue
        row = _debug_pick_route_for_text(txt, mode="local_first")
        rt = str(row.get("route") or "")
        route_counts[rt] = int(route_counts.get(rt) or 0) + 1
        if rt == "clarify":
            clarify_count += 1
        if rt == "fallback_local_first":
            fallback_count += 1
        ts = float(row.get("top_score") or 0.0)
        if ts < 0.35:
            low_score.append({"text": txt, "route": rt, "top_score": ts, "top_final": float(row.get("top_final") or 0.0)})
    low_score.sort(key=lambda x: float(x.get("top_score") or 0.0))
    out = {
        "total": sum(route_counts.values()),
        "route_counts": route_counts,
        "clarify_count": clarify_count,
        "fallback_count": fallback_count,
        "fallback_chain_ratio": {"rag": 1.0, "news": 0.0, "web": 0.0},
        "top_failed_samples": low_score[:10],
    }
    try:
        return json.dumps(out, ensure_ascii=False, indent=2)
    except Exception:
        return str(out)


# --- ANSWER: MCP tool entry ---
@mcp.tool(name="skill.answer_question", description="General QA skill with local-first fallback: RAG -> news -> web.")
def _skill_answer_question_impl(text: str, mode: str = "local_first") -> dict:
    return skill_answer_question_core(
        text,
        mode,
        {
            "skill_call_begin": _skill_call_begin,
            "skill_call_end": _skill_call_end,
            "skill_log_json": _skill_log_json,
            "skill_result": _skill_result,
            "skill_next_action_item": _skill_next_action_item,
            "router_context_cls": RouterContext,
            "skill_detect_lang": _skill_detect_lang,
            "skill_debug_enabled": _skill_debug_enabled,
            "skill_debug_log": _skill_debug_log,
            "clarify_memory_get": lambda: _CLARIFY_MEMORY.get("default"),
            "now_local": _now_local,
            "consume_clarify_followup_route": _consume_clarify_followup_route,
            "build_answer_route_rules": _build_answer_route_rules_impl,
            "compose_compound_answer": _compose_compound_answer,
            "skill_wrap_any_result": _skill_wrap_any_result,
            "score_and_pick_rule": _score_and_pick_rule,
            "load_answer_route_whitelist": load_answer_route_whitelist,
            "enforce_answer_route_whitelist": enforce_answer_route_whitelist,
            "env_get": lambda k, d="": str(os.environ.get(k) or d),
            "clarify_result": _clarify_result,
            "answer_fallback_local_first": _answer_fallback_local_first_impl,
        },
    )


def skill_answer_question(text: str, mode: str = "local_first") -> dict:
    # External-call safe wrapper for the MCP tool implementation.
    return _skill_answer_question_impl(text, mode)


# --- ANSWER: HA-compatible thin wrappers ---
def route_request(text: str, language: str = "") -> str:
    """Thin wrapper: call skill.answer_question and return final_text only."""
    try:
        ret = skill_answer_question(text=text, mode="local_first")
        if isinstance(ret, dict):
            final = str(ret.get("final_text") or "").strip()
        else:
            final = ""
        if final:
            return final
        return "我先给你一个简短答复：请再具体一点。"
    except Exception:
        return "我先给你一个简短答复：请稍后重试。"

def _route_request_obj(text: str, language: str = "") -> dict:
    """Internal helper (debug/tests): return the full router dict.
    NOTE: this function MUST return a dict to avoid breaking callers that expect keys like ok/route_type/final.
    """
    ret = _route_request_impl(text=text, language=language)
    if isinstance(ret, dict):
        return ret
    return {"ok": True, "route_type": "open_domain", "final": str(ret or "")}


# --- MUSIC CONTROL INTERNAL HELPERS ---
def _music_extract_target_entity(user_text: str) -> str:
    return music_extract_target_entity(user_text)

def _is_music_control_query(user_text: str) -> bool:
    return is_music_control_query(user_text)

def _music_unmute_default() -> float:
    v = str(os.environ.get('MUSIC_UNMUTE_DEFAULT') or '0.3').strip()
    try:
        f = float(v)
    except Exception:
        f = 0.3
    if f < 0.0:
        f = 0.0
    if f > 1.0:
        f = 1.0
    return f

def _music_get_volume_level(ent: str):
    eid = str(ent or '').strip()
    if not eid:
        return None
    r = ha_get_state(eid, timeout_sec=10)
    if not isinstance(r, dict) or (not r.get('ok')):
        return None
    data = r.get('data') or {}
    attrs = data.get('attributes') or {}
    vl = attrs.get('volume_level')
    try:
        if vl is None:
            return None
        return float(vl)
    except Exception:
        return None

_MUSIC_SOFT_MUTE_CACHE = {}

def _music_soft_mute(ent: str, do_unmute: bool = False) -> dict:
    eid = str(ent or '').strip()
    if not eid:
        return {'ok': False, 'error': 'empty_entity'}
    if not do_unmute:
        cur = _music_get_volume_level(eid)
        if cur is None:
            cur = _music_unmute_default()
        _MUSIC_SOFT_MUTE_CACHE[eid] = cur
        rr = ha_call_service('media_player', 'volume_set', service_data={'entity_id': eid, 'volume_level': 0.0}, timeout_sec=10)
        if isinstance(rr, dict) and rr.get('ok'):
            return {'ok': True}
        return {'ok': False, 'error': 'volume_set_0_failed'}
    # unmute
    restore = _MUSIC_SOFT_MUTE_CACHE.get(eid)
    if restore is None:
        restore = _music_unmute_default()
    rr = ha_call_service('media_player', 'volume_set', service_data={'entity_id': eid, 'volume_level': float(restore)}, timeout_sec=10)
    if isinstance(rr, dict) and rr.get('ok'):
        return {'ok': True}
    return {'ok': False, 'error': 'volume_restore_failed'}
def _music_try_volume_updown(ent: str, direction: str = "up", steps: int = 1):
    """
    Fallback volume control using media_player.volume_up / volume_down.
    Returns dict: {ok, status_code?, data?}
    """
    d = "up" if str(direction or "up").lower().startswith("u") else "down"
    n = int(steps or 1)
    if n < 1:
        n = 1
    if n > 10:
        n = 10
    svc = "volume_up" if d == "up" else "volume_down"
    last = {"ok": False, "error": "not_called"}
    for _ in range(n):
        last = ha_call_service("media_player", svc, service_data={"entity_id": ent}, timeout_sec=10)
        if not (isinstance(last, dict) and last.get("ok")):
            return last
    return last

def _music_parse_volume(user_text: str):
    return music_parse_volume(user_text)
def _music_volume_step_default() -> float:
    return music_volume_step_default()

def _music_parse_volume_delta(user_text: str):
    return music_parse_volume_delta(user_text)


def debug_ha_connectivity() -> dict:
    base = str(os.environ.get("HA_BASE_URL") or "").strip()
    out = {
        "ha_base_url_exists": bool(base),
        "ha_base_url": base,
        "host_resolvable": False,
        "api_status": "",
        "ok": False,
    }
    if not base:
        return out
    try:
        pr = urlparse(base)
        host = str(pr.hostname or "").strip()
        if host:
            try:
                socket.getaddrinfo(host, pr.port or (443 if pr.scheme == "https" else 80))
                out["host_resolvable"] = True
            except Exception:
                out["host_resolvable"] = False
        token = str(os.environ.get("HA_TOKEN") or "").strip()
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        r = requests.get(base.rstrip("/") + "/api/", headers=headers, timeout=5)
        out["api_status"] = str(int(getattr(r, "status_code", 0) or 0))
        out["ok"] = bool(int(getattr(r, "status_code", 0) or 0) < 400)
    except Exception as e:
        out["api_status"] = "error:" + str(e)
    return out


# WEB_SEARCH_FALLBACK_V1_BEGIN
def _web__has_url(t: str) -> bool:
    try:
        return bool(re.search(r"https?://\S+", (t or ""), flags=re.I))
    except Exception:
        return False

def _web__extract_limit(t: str, default: int = 3) -> int:
    # common patterns: 5条/5个/5 results
    try:
        if not t:
            return default
        m = re.search(r"(\d{1,2})\s*(条|个|results|result)", t, flags=re.I)
        if m:
            n = int(m.group(1))
            if n < 1:
                n = 1
            if n > 5:
                n = 5
            return n
    except Exception:
        pass
    return default

def _web__time_range_from_text(t: str) -> str:
    # searxng: day/week/month/year
    tt = (t or "").lower()
    if ("24小时" in t) or ("今天" in t) or ("today" in tt) or ("last 24" in tt):
        return "day"
    if ("最近7天" in t) or ("本周" in t) or ("this week" in tt) or ("last week" in tt) or ("week" in tt):
        return "week"
    if ("本月" in t) or ("最近30天" in t) or ("this month" in tt) or ("month" in tt):
        return "month"
    if ("今年" in t) or ("this year" in tt) or ("year" in tt):
        return "year"
    return ""

def _web__clean_query(t: str) -> str:
    q = (t or "").strip()
    if not q:
        return ""
    # remove common leading verbs
    q = re.sub(r"^(帮我\s*)?(在网上\s*)?(搜索|搜一下|查一下|查查|查下|查|找一下|找找)\s*", "", q)
    q = re.sub(r"^(please\s+)?(search|google|look\s*up|find\s*out)\s+(for\s+)?", "", q, flags=re.I)
    q = q.strip(" ：:，,。.!?？")
    return q.strip()

def _web__should_fallback(t: str) -> bool:
    mode = (os.environ.get("WEB_SEARCH_FALLBACK_MODE") or "explicit").strip().lower()
    if mode in ("0", "off", "false", "disabled", "disable", "none"):
        return False

    if _web__has_url(t):
        return True

    tt = (t or "").lower()

    # explicit triggers (low-frequency, user intent)
    triggers = [
        "搜索", "搜一下", "查一下", "查查", "查下", "帮我查", "网上", "谷歌", "google", "search", "look up", "lookup", "find out",
        "官网", "官方", "链接", "网址", "source", "citation",
    ]
    try:
        for k in triggers:
            if k.lower() in tt or k in (t or ""):
                return True
    except Exception:
        pass

    if mode != "smart":
        return False

    # smart triggers (still conservative)
    smart_tokens = [
        "最新", "现在", "目前", "今天", "多少钱", "价格", "报价", "费用", "电话", "地址", "营业", "开放", "开门", "关门",
        "下载", "安装", "版本", "更新", "release", "price", "cost", "opening hours", "address", "phone", "where to buy",
    ]
    for k in smart_tokens:
        if k.lower() in tt or k in (t or ""):
            # avoid triggering on pure "解释/原理" style queries
            if ("解释" in (t or "")) or ("原理" in (t or "")) or ("为什么" in (t or "")) or ("how does" in tt):
                return False
            return True

    # question mark heuristic
    if ("？" in (t or "")) or ("?" in (t or "")):
        return True

    return False

def _web__clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)].rstrip() + "…"

def _web__format_results(results: list, limit: int = 3) -> str:
    if not isinstance(results, list) or len(results) == 0:
        return ""
    seen = set()
    out_lines = []
    idx = 0
    for r in results:
        if idx >= limit:
            break
        if not isinstance(r, dict):
            continue
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        snippet = (r.get("content") or r.get("snippet") or "").strip()
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        idx += 1
        if not title:
            title = url
        out_lines.append(str(idx) + ") " + _web__clip(title, 120))
        out_lines.append("   " + _web__clip(url, 220))
        if snippet:
            out_lines.append("   " + _web__clip(snippet.replace("\n", " "), 220))
    return "\n".join(out_lines).strip()


def _has_strong_lookup_intent(text: str) -> bool:
    return rh.has_strong_lookup_intent(text)


def _is_obvious_smalltalk(text: str) -> bool:
    return rh.is_obvious_smalltalk(text)


def _smalltalk_reply(text: str, prefer_lang: str) -> str:
    return rh.smalltalk_reply(text, prefer_lang)


def _is_life_advice_intent(text: str) -> bool:
    return rh.is_life_advice_intent(text)


def _life_advice_fallback(text: str, prefer_lang: str) -> str:
    return rh.life_advice_fallback(text, prefer_lang)


def _web__query_tokens(query: str) -> list:
    return rh.web_query_tokens(query)


def _web__reliable_results(query: str, items: list, limit: int = 3) -> list:
    if not isinstance(items, list):
        return []
    tokens = _web__query_tokens(query)
    if len(tokens) < 1:
        return []
    qraw = str(query or "")
    parking_query = ("停车" in qraw) or ("parking" in qraw.lower())
    out = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "")
        snippet = str(it.get("snippet") or it.get("content") or "")
        url = str(it.get("url") or "")
        blob = (title + " " + snippet + " " + url).lower()
        if not blob.strip():
            continue
        score = 0
        for tk in tokens:
            if tk and (str(tk).lower() in blob):
                score += 1
        if parking_query and ("parking" not in blob) and ("停车" not in (title + snippet)):
            continue
        if tokens and score < 1:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(it)
        if len(out) >= int(limit):
            break
    return out


def _web_search_answer(query: str, prefer_lang: str, limit: int = 3):
    q = _web__strip_search_prefix(query) or str(query or "")
    tr = _news__time_range_from_text(query)
    lang = _mcp__auto_language(q, prefer_lang or "")
    data = web_search(query=q, k=max(8, int(limit) * 3), categories="general", language=lang, time_range=tr)
    if not isinstance(data, dict) or (not data.get("ok")):
        return None, data
    raw = data.get("results") or []
    filtered = _web__reliable_results(q, raw, limit=int(limit))
    if len(filtered) < 1:
        # relaxed fallback for broad how-to / product lookup queries:
        # keep only items with non-empty URL/title and render top-N.
        if _has_strong_lookup_intent(q) and (not _is_life_advice_intent(q)):
            relaxed = []
            seen = set()
            for it in raw:
                if not isinstance(it, dict):
                    continue
                u = str(it.get("url") or "").strip()
                t = str(it.get("title") or "").strip()
                if not u:
                    continue
                if u in seen:
                    continue
                if not t:
                    t = u
                seen.add(u)
                relaxed.append(it)
                if len(relaxed) >= int(limit):
                    break
            if len(relaxed) > 0:
                final = _web__render_narrative(q, relaxed, lang)
                if str(final or "").strip():
                    return str(final), data
        return None, data
    final = _web__render_narrative(q, filtered, lang)
    if not str(final or "").strip():
        return None, data
    return str(final), data


def _is_poi_intent(text: str) -> bool:
    t = str(text or "")
    tl = t.lower()
    keys = [
        "营业时间", "几点开门", "几点关门", "地址", "电话", "官网", "附近", "怎么去",
        "停车", "停车费", "停车场", "收费", "收费标准", "商场", "餐厅", "店铺", "门店", "poi",
        "opening hours", "open", "close", "address", "phone", "website", "parking", "restaurant", "store", "shop",
    ]
    for k in keys:
        if (k in t) or (k in tl):
            return True
    return False


def _poi_api_key() -> str:
    return str(os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()


def _poi_region() -> str:
    x = str(os.environ.get("POI_REGION") or "AU").strip().upper()
    if not x:
        return "AU"
    return x


def _poi_lang() -> str:
    x = str(os.environ.get("POI_LANG") or "en").strip()
    if not x:
        return "en"
    return x


def _poi_max_results() -> int:
    raw = str(os.environ.get("POI_MAX_RESULTS") or "3").strip()
    try:
        n = int(raw)
    except Exception:
        n = 3
    if n < 1:
        n = 1
    if n > 5:
        n = 5
    return n


def _poi_default_suffix() -> str:
    x = str(os.environ.get("POI_DEFAULT_QUERY_SUFFIX") or "Melbourne VIC").strip()
    if not x:
        return "Melbourne VIC"
    return x


def _poi_cache_ttl() -> int:
    raw = str(os.environ.get("POI_CACHE_TTL_SECONDS") or "86400").strip()
    try:
        n = int(raw)
    except Exception:
        n = 86400
    if n < 60:
        n = 60
    if n > 604800:
        n = 604800
    return n


def _poi_cache_db_path() -> str:
    return "/app/data/poi_cache.sqlite3"


def _poi_cache_conn():
    p = _poi_cache_db_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(p)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS poi_cache(query_key TEXT PRIMARY KEY, ts INTEGER, text TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS poi_fee_cache(url_key TEXT PRIMARY KEY, ts INTEGER, domain TEXT, lines TEXT)")
    conn.commit()
    return conn


def _poi_cache_key(query: str) -> str:
    base = "{0}|{1}|{2}|{3}".format(str(query or "").strip().lower(), _poi_region(), _poi_lang(), _poi_default_suffix())
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()


def _poi_cache_get(query: str):
    key = _poi_cache_key(query)
    ttl = _poi_cache_ttl()
    now_i = int(time.time())
    conn = None
    try:
        conn = _poi_cache_conn()
        cur = conn.cursor()
        cur.execute("SELECT ts,text FROM poi_cache WHERE query_key=? LIMIT 1", (key,))
        r = cur.fetchone()
        conn.close()
        if not r:
            return None
        ts = int(r[0] or 0)
        txt = str(r[1] or "")
        if (now_i - ts) > ttl:
            return None
        if not txt.strip():
            return None
        return txt
    except Exception:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        return None


def _poi_cache_put(query: str, text_out: str):
    val = str(text_out or "").strip()
    if not val:
        return
    key = _poi_cache_key(query)
    conn = None
    try:
        conn = _poi_cache_conn()
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO poi_cache(query_key,ts,text) VALUES(?,?,?)", (key, int(time.time()), val))
        conn.commit()
        conn.close()
    except Exception:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _poi_clean_query(text: str) -> str:
    q = str(text or "").strip()
    q = re.sub(r"^(帮我\s*)?(查一下|查查|查|搜索|搜一下)\s*", "", q)
    q = q.strip(" ，。,.!?！？")
    return q


def _poi_extract_suburb(addr: str) -> str:
    a = str(addr or "").strip()
    if not a:
        return ""
    parts = [x.strip() for x in a.split(",") if str(x or "").strip()]
    if len(parts) >= 2:
        return parts[1]
    return ""


def _poi_short_addr(addr: str) -> str:
    a = str(addr or "").strip()
    if not a:
        return "地址待确认"
    parts = [x.strip() for x in a.split(",") if str(x or "").strip()]
    if len(parts) >= 2:
        return parts[0] + ", " + parts[1]
    return parts[0]


def _poi_today_opening_text(detail: dict) -> str:
    curh = detail.get("currentOpeningHours") if isinstance(detail, dict) else None
    regh = detail.get("regularOpeningHours") if isinstance(detail, dict) else None
    open_now = None
    if isinstance(curh, dict):
        if "openNow" in curh:
            open_now = bool(curh.get("openNow"))
    today_line = ""
    lines = []
    if isinstance(curh, dict):
        lines = curh.get("weekdayDescriptions") or []
    if (not lines) and isinstance(regh, dict):
        lines = regh.get("weekdayDescriptions") or []
    if isinstance(lines, list) and len(lines) > 0:
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        widx = _bills_now_local().weekday()
        if widx >= 0 and widx < len(names):
            pref = names[widx].lower() + ":"
            for ln in lines:
                s = str(ln or "").strip()
                if s.lower().startswith(pref):
                    today_line = s
                    break
        if not today_line:
            today_line = str(lines[0] or "")
    if open_now is True:
        if today_line:
            return "营业中；" + today_line
        return "营业中"
    if open_now is False:
        if today_line:
            return "休息中；" + today_line
        return "休息中"
    if today_line:
        return today_line
    return "营业时间请见链接"


def _poi_text_search(query: str, language_code: str):
    key = _poi_api_key()
    if not key:
        return {"ok": False, "error": "missing_api_key"}
    url = "https://places.googleapis.com/v1/places:searchText"
    body = {
        "textQuery": query,
        "regionCode": _poi_region(),
        "languageCode": language_code,
        "maxResultCount": _poi_max_results(),
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.name,places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.websiteUri",
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=10)
        code = int(getattr(r, "status_code", 0) or 0)
        if code < 200 or code >= 300:
            return {"ok": False, "error": "poi_text_search_failed", "status": code, "message": (r.text or "")[:200]}
        data = r.json()
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": "poi_text_search_exception", "message": str(e)[:180]}


def _poi_place_details(place_ref: dict, language_code: str):
    key = _poi_api_key()
    if not key:
        return {"ok": False, "error": "missing_api_key"}
    name_res = str(place_ref.get("name") or "").strip()
    pid = str(place_ref.get("id") or "").strip()
    if name_res.startswith("places/"):
        url = "https://places.googleapis.com/v1/" + name_res
    elif pid:
        url = "https://places.googleapis.com/v1/places/" + requests.utils.quote(pid)
    else:
        return {"ok": False, "error": "missing_place_id"}
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "id,displayName,formattedAddress,nationalPhoneNumber,regularOpeningHours,currentOpeningHours,websiteUri,googleMapsUri",
    }
    params = {"languageCode": language_code, "regionCode": _poi_region()}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        code = int(getattr(r, "status_code", 0) or 0)
        if code < 200 or code >= 300:
            return {"ok": False, "error": "poi_details_failed", "status": code, "message": (r.text or "")[:200]}
        return {"ok": True, "data": r.json()}
    except Exception as e:
        return {"ok": False, "error": "poi_details_exception", "message": str(e)[:180]}


def _poi_is_relevant(query: str, place_item: dict) -> bool:
    q = str(query or "")
    blob = (
        str(((place_item or {}).get("displayName") or {}).get("text") or "")
        + " " + str((place_item or {}).get("formattedAddress") or "")
        + " " + str((place_item or {}).get("websiteUri") or "")
    ).lower()
    tokens = _web__query_tokens(q)
    if not tokens:
        return True
    hits = 0
    for tk in tokens:
        if tk and (str(tk).lower() in blob):
            hits += 1
    if ("parking" in q.lower()) or ("停车" in q):
        if ("parking" not in blob) and ("停车" not in blob):
            return False
    return hits >= 1


def _poi_fee_url_key(url: str, stage_version: str = "v2") -> str:
    raw = str(url or "").strip().lower() + "|" + str(stage_version or "v2").strip().lower()
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _poi_fee_cache_get(url: str, stage_version: str = "v2"):
    u = str(url or "").strip()
    if not u:
        return None
    now_i = int(time.time())
    ttl = _poi_cache_ttl()
    conn = None
    try:
        conn = _poi_cache_conn()
        cur = conn.cursor()
        cur.execute("SELECT ts,domain,lines FROM poi_fee_cache WHERE url_key=? LIMIT 1", (_poi_fee_url_key(u, stage_version=stage_version),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        ts = int(row[0] or 0)
        if (now_i - ts) > ttl:
            return None
        domain = str(row[1] or "").strip()
        text_lines = str(row[2] or "")
        lines = [x.strip() for x in text_lines.split("\n") if str(x or "").strip()]
        return {"domain": domain, "lines": lines[:3]}
    except Exception:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        return None


def _poi_fee_cache_put(url: str, domain: str, lines: list, stage_version: str = "v2"):
    u = str(url or "").strip()
    if not u:
        return
    items = []
    if isinstance(lines, list):
        for s in lines:
            ss = str(s or "").strip()
            if ss:
                items.append(ss)
    if len(items) > 3:
        items = items[:3]
    conn = None
    try:
        conn = _poi_cache_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO poi_fee_cache(url_key,ts,domain,lines) VALUES(?,?,?,?)",
            (_poi_fee_url_key(u, stage_version=stage_version), int(time.time()), str(domain or "").strip(), "\n".join(items)),
        )
        conn.commit()
        conn.close()
    except Exception:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _poi_fee_amount_match(s: str) -> bool:
    text = str(s or "")
    if not text:
        return False
    pats = [
        r"\$\s*\d+(?:\.\d{1,2})?",
        r"\b\d+(?:\.\d{1,2})?\s*(?:AUD|A\$)\b",
        r"\bfrom\s+\$\s*\d+(?:\.\d{1,2})?\b",
    ]
    for p in pats:
        if re.search(p, text, flags=re.I):
            return True
    return False


def _poi_fee_has_semantic(s: str) -> bool:
    low = str(s or "").lower()
    keys = [
        "early bird", "weekend", "weekday", "hourly", "per hour", "all day", "maximum", "flat rate", "entry", "rates", "pricing", "tariff",
        "早鸟", "周末", "工作日", "每小时", "全天", "最高", "封顶", "费率", "收费", "价格", "停车费",
    ]
    for k in keys:
        if str(k).lower() in low:
            return True
    return False


def _poi_fee_negative_hit(s: str) -> bool:
    low = str(s or "").lower()
    neg_keys = [
        "privacy", "cookie", "policy", "terms", "careers", "job", "news", "media", "subscribe",
        "隐私", "条款", "招聘", "新闻", "cookie",
    ]
    for nk in neg_keys:
        if str(nk).lower() in low:
            return True
    return False


def _poi_fee_clean_snippet(s: str, max_len: int = 180) -> str:
    out = re.sub(r"\s+", " ", str(s or "")).strip()
    if not out:
        return ""
    if len(out) > int(max_len):
        out = out[: int(max_len)].rstrip() + "..."
    return out


def _poi_fee_pick_lines(text: str, max_lines: int = 3) -> list:
    src = str(text or "")
    if not src.strip():
        return []
    src = src.replace("\r", "\n")
    chunks = []
    for ln in src.split("\n"):
        part = str(ln or "").strip()
        if not part:
            continue
        sub = re.split(r"[。！？!?；;]+", part)
        for s in sub:
            ss = str(s or "").strip()
            if ss:
                chunks.append(ss)
    out = []
    seen = set()
    for c in chunks:
        s = _poi_fee_clean_snippet(c, max_len=180)
        if not s:
            continue
        if _poi_fee_negative_hit(s):
            continue
        if not _poi_fee_amount_match(s):
            continue
        if not _poi_fee_has_semantic(s):
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= int(max_lines):
            break
    return out


def _poi_fee_pick_from_html_windows(html_raw: str, max_lines: int = 3) -> list:
    raw = str(html_raw or "")
    if not raw:
        return []
    pats = [
        r"\$\s*\d+(?:\.\d{1,2})?",
        r"\b\d+(?:\.\d{1,2})?\s*(?:AUD|A\$)\b",
        r"\bfrom\s+\$\s*\d+(?:\.\d{1,2})?\b",
    ]
    hits = []
    for p in pats:
        try:
            for m in re.finditer(p, raw, flags=re.I):
                hits.append(int(m.start()))
        except Exception:
            pass
    if len(hits) < 1:
        return []
    hits = sorted(hits)[:20]
    out = []
    seen = set()
    for pos in hits:
        st = pos - 180
        ed = pos + 180
        if st < 0:
            st = 0
        if ed > len(raw):
            ed = len(raw)
        win = raw[st:ed]
        win = re.sub(r"(?is)<script.*?>.*?</script>", " ", win)
        win = re.sub(r"(?is)<style.*?>.*?</style>", " ", win)
        win = re.sub(r"(?is)<[^>]+>", " ", win)
        win = html.unescape(win)
        sn = _poi_fee_clean_snippet(win, max_len=180)
        if not sn:
            continue
        if _poi_fee_negative_hit(sn):
            continue
        if (not _poi_fee_amount_match(sn)) or (not _poi_fee_has_semantic(sn)):
            continue
        k = sn.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(sn)
        if len(out) >= int(max_lines):
            break
    return out


def _poi_fee_pick_from_site_search(domain: str, place_name: str, query_text: str, max_lines: int = 2) -> list:
    dm = str(domain or "").strip()
    if not dm:
        return []
    qn = str(place_name or "").strip()
    qq = str(query_text or "").strip()
    seed = qn or qq or "parking"
    q = "site:{0} {1} rate pricing early bird all day parking".format(dm, seed)
    try:
        data = web_search(query=q, k=8, categories="general", language="en", time_range="year")
    except Exception:
        data = {"ok": False}
    if not isinstance(data, dict) or (not data.get("ok")):
        return []
    items = data.get("results") or []
    if not isinstance(items, list):
        return []
    out = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "")
        ttl = str(it.get("title") or "")
        snp = str(it.get("snippet") or it.get("content") or "")
        mix = _poi_fee_clean_snippet((ttl + " " + snp), max_len=180)
        if not mix:
            continue
        if dm and (dm.lower() not in url.lower()) and (dm.lower() not in mix.lower()):
            continue
        if _poi_fee_negative_hit(mix):
            continue
        if (not _poi_fee_amount_match(mix)) or (not _poi_fee_has_semantic(mix)):
            continue
        k = mix.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(mix)
        if len(out) >= int(max_lines):
            break
    return out


def _poi_fee_extract_from_url(url: str, place_name: str = "", query_text: str = "", stage_version: str = "v2"):
    u = str(url or "").strip()
    if not u:
        return {"domain": "", "lines": []}
    domain = ""
    try:
        domain = str(urlparse(u).netloc or "").strip()
    except Exception:
        domain = ""
    cached = _poi_fee_cache_get(u, stage_version=stage_version)
    if isinstance(cached, dict):
        c_domain = str(cached.get("domain") or "").strip()
        c_lines = cached.get("lines") if isinstance(cached.get("lines"), list) else []
        return {"domain": c_domain or domain, "lines": c_lines[:3]}

    html_raw = ""

    # Stage-1: open_url_extract -> semantic + amount co-match.
    try:
        rr = open_url_extract(u, max_chars=6000, timeout_sec=12)
    except Exception:
        rr = {"ok": False}
    if not isinstance(rr, dict) or (not rr.get("ok")):
        _poi_fee_cache_put(u, domain, [], stage_version=stage_version)
        return {"domain": domain, "lines": []}
    txt = str(rr.get("text") or rr.get("content") or "")
    lines = _poi_fee_pick_lines(txt, max_lines=3)

    # Stage-2: raw HTML windows around amount markers.
    if len(lines) < 1:
        try:
            hdr = {
                "User-Agent": "Mozilla/5.0 (compatible; mcp-hello/1.0; +https://localhost)",
                "Accept": "text/html,application/xhtml+xml",
            }
            rp = requests.get(u, headers=hdr, timeout=12)
            if int(getattr(rp, "status_code", 0) or 0) >= 200 and int(getattr(rp, "status_code", 0) or 0) < 300:
                html_raw = str(rp.text or "")
        except Exception:
            html_raw = ""
        if html_raw:
            lines = _poi_fee_pick_from_html_windows(html_raw, max_lines=3)

    # Stage-3: site search snippets as last-resort with source.
    if len(lines) < 1:
        lines = _poi_fee_pick_from_site_search(domain, place_name, query_text, max_lines=2)

    _poi_fee_cache_put(u, domain, lines, stage_version=stage_version)
    return {"domain": domain, "lines": lines}


def _poi_answer(query: str, prefer_lang: str):
    cached = _poi_cache_get(query)
    if cached:
        return cached
    q_raw = _poi_clean_query(query)
    if not q_raw:
        return ""
    suffix = _poi_default_suffix()
    q_final = q_raw
    if suffix and (suffix.lower() not in q_raw.lower()):
        q_final = q_raw + " " + suffix
    lang_first = _poi_lang() or ("en" if prefer_lang != "zh" else "en")
    s1 = _poi_text_search(q_final, lang_first)
    places = []
    if s1.get("ok"):
        places = ((s1.get("data") or {}).get("places") or [])
    if (not places) and (lang_first != "zh"):
        s2 = _poi_text_search(q_final, "zh")
        if s2.get("ok"):
            places = ((s2.get("data") or {}).get("places") or [])
    if not isinstance(places, list) or len(places) == 0:
        return ""
    rel = []
    for p in places:
        if _poi_is_relevant(q_raw, p):
            rel.append(p)
    if len(rel) == 0:
        return ""
    max_n = _poi_max_results()
    if max_n > 3:
        max_n = 3
    rel = rel[:max_n]
    lines = []
    fee_query = (("停车费" in q_raw) or ("收费" in q_raw) or ("多少钱" in q_raw) or ("parking" in q_raw.lower()) or ("rate" in q_raw.lower()) or ("price" in q_raw.lower()))
    fee_info = None
    for i, p in enumerate(rel, 1):
        d = _poi_place_details(p, lang_first)
        detail = {}
        if d.get("ok"):
            detail = d.get("data") or {}
        else:
            detail = p or {}
        nm = str((detail.get("displayName") or {}).get("text") or (p.get("displayName") or {}).get("text") or "").strip()
        addr = str(detail.get("formattedAddress") or p.get("formattedAddress") or "").strip()
        suburb = _poi_extract_suburb(addr)
        hours = _poi_today_opening_text(detail)
        phone = str(detail.get("nationalPhoneNumber") or "").strip() or "无"
        website = str(detail.get("websiteUri") or p.get("websiteUri") or "").strip()
        maps = str(detail.get("googleMapsUri") or p.get("googleMapsUri") or "").strip()
        source = ""
        if website:
            try:
                source = urlparse(website).netloc or website
            except Exception:
                source = website
        elif maps:
            source = maps
        else:
            source = "Google Maps"
        name_show = nm or "地点"
        if suburb:
            name_show = name_show + "（" + suburb + "）"
        line = "{0}) {1} — 今天营业：{2} — {3} — 电话：{4} — {5}".format(
            i, name_show, hours, _poi_short_addr(addr), phone, source
        )
        lines.append(line)
        if fee_query and (fee_info is None):
            site_to_read = website or maps
            if site_to_read:
                fee_info = _poi_fee_extract_from_url(site_to_read, place_name=nm, query_text=q_raw, stage_version="v2")
    if fee_query:
        fee_lines = []
        fee_domain = ""
        if isinstance(fee_info, dict):
            fee_domain = str(fee_info.get("domain") or "").strip()
            v = fee_info.get("lines")
            if isinstance(v, list):
                fee_lines = [str(x or "").strip() for x in v if str(x or "").strip()]
        if fee_lines:
            if fee_domain:
                lines.append("费率摘录（来源：{0}）：".format(fee_domain))
            else:
                lines.append("费率摘录：")
            for s in fee_lines[:3]:
                if fee_domain:
                    lines.append("- {0}（来源：{1}）".format(s, fee_domain))
                else:
                    lines.append("- {0}".format(s))
        else:
            lines.append("收费标准可能按时段变化，建议查看官网或地图页面确认（早鸟/高峰/全天）。")
    if len(lines) < 1:
        return ""
    final = "\n".join(lines)
    if len(final) > 800:
        final = final[:800].rstrip() + "…"
    if final.strip():
        _poi_cache_put(query, final)
    return final
# WEB_SEARCH_FALLBACK_V1_END

_BILLS_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_BILLS_CRED_PATH = "/app/secrets/gmail/credentials.json"
_BILLS_TOKEN_PATH = "/app/secrets/gmail/token.json"
_BILLS_DB_PATH = "/app/data/bills.sqlite3"
_BILLS_ATTACH_ROOT = "/app/data/bills"


def _bills_now_local():
    try:
        return datetime.now(ZoneInfo("Australia/Melbourne"))
    except Exception:
        return datetime.now()


def _bills_calendar_entity_id() -> str:
    raw = str(os.environ.get("BILLS_CALENDAR_ENTITY_ID") or "").strip()
    if raw:
        return raw
    return "calendar.vs888home_gmail_com"


def _bills_remind_days() -> int:
    raw = str(os.environ.get("BILLS_REMIND_DAYS") or "").strip()
    if not raw:
        return 7
    try:
        val = int(raw)
    except Exception:
        return 7
    if val < 0:
        return 0
    if val > 30:
        return 30
    return val


def _bills_event_hhmm() -> str:
    raw = str(os.environ.get("BILLS_EVENT_TIME") or "").strip()
    if not raw:
        return "09:00"
    m = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if not m:
        return "09:00"
    h = int(m.group(1))
    mi = int(m.group(2))
    if h < 0 or h > 23 or mi < 0 or mi > 59:
        return "09:00"
    return "{0:02d}:{1:02d}".format(h, mi)


def _bills_due_days_default() -> int:
    raw = str(os.environ.get("BILLS_DUE_DAYS") or "").strip()
    if not raw:
        return 7
    try:
        val = int(raw)
    except Exception:
        return 7
    if val < 1:
        return 7
    if val > 30:
        return 30
    return val


def _bills_db_connect():
    try:
        os.makedirs(os.path.dirname(_BILLS_DB_PATH), exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(_BILLS_DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS processed_messages(message_id TEXT PRIMARY KEY, processed_at TEXT)")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS bills("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "vendor TEXT, subject TEXT, from_addr TEXT, msg_date TEXT, "
        "amount REAL, currency TEXT, due_date TEXT, issue_date TEXT, "
        "status TEXT, message_id TEXT, attachment_path TEXT, created_at TEXT, failure_reason TEXT)"
    )
    try:
        cur.execute("PRAGMA table_info(bills)")
        cols = [str((x or [None])[1] or "") for x in (cur.fetchall() or [])]
        if "failure_reason" not in cols:
            cur.execute("ALTER TABLE bills ADD COLUMN failure_reason TEXT")
    except Exception:
        pass
    cur.execute(
        "CREATE TABLE IF NOT EXISTS bills_calendar_sync("
        "bill_id INTEGER PRIMARY KEY, "
        "calendar_entity TEXT, "
        "sync_key TEXT, "
        "due_event_created INTEGER DEFAULT 0, "
        "due_event_key TEXT, "
        "due_event_at TEXT, "
        "remind_event_created INTEGER DEFAULT 0, "
        "remind_event_key TEXT, "
        "remind_event_at TEXT, "
        "last_sync_at TEXT, "
        "last_error TEXT)"
    )
    try:
        cur.execute("PRAGMA table_info(bills_calendar_sync)")
        bcols = [str((x or [None])[1] or "") for x in (cur.fetchall() or [])]
        if "calendar_entity" not in bcols:
            cur.execute("ALTER TABLE bills_calendar_sync ADD COLUMN calendar_entity TEXT")
    except Exception:
        pass
    conn.commit()
    return conn


def _bills_is_processed(conn, message_id: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM processed_messages WHERE message_id=? LIMIT 1", (str(message_id or ""),))
    return cur.fetchone() is not None


def _bills_mark_processed(conn, message_id: str):
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO processed_messages(message_id, processed_at) VALUES(?,?)",
        (str(message_id or ""), _bills_now_local().isoformat()),
    )


def _bills_insert_row(conn, row: dict):
    cur = conn.cursor()
    due_raw = row.get("due_date")
    due_str = None
    if due_raw:
        due_norm = _bill_norm_date(due_raw)
        if due_norm is not None:
            due_str = due_norm.strftime("%Y-%m-%d")
    cur.execute(
        "INSERT INTO bills(vendor,subject,from_addr,msg_date,amount,currency,due_date,issue_date,status,message_id,attachment_path,created_at,failure_reason) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(row.get("vendor") or ""),
            str(row.get("subject") or ""),
            str(row.get("from_addr") or ""),
            str(row.get("msg_date") or ""),
            row.get("amount"),
            str(row.get("currency") or "AUD"),
            due_str,
            str(row.get("issue_date") or ""),
            str(row.get("status") or "new"),
            str(row.get("message_id") or ""),
            str(row.get("attachment_path") or ""),
            _bills_now_local().isoformat(),
            str(row.get("failure_reason") or ""),
        ),
    )


def _bills_gmail_service():
    if (GoogleCredentials is None) or (GoogleRequest is None) or (google_build is None):
        return None, "缺少 Gmail 依赖。"
    if not os.path.exists(_BILLS_TOKEN_PATH):
        return None, "未找到 Gmail token.json。"
    if not os.path.exists(_BILLS_CRED_PATH):
        return None, "未找到 Gmail credentials.json。"
    try:
        creds = GoogleCredentials.from_authorized_user_file(_BILLS_TOKEN_PATH, _BILLS_SCOPES)
    except Exception:
        return None, "Gmail token 无法读取。"
    try:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            try:
                with open(_BILLS_TOKEN_PATH, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            except Exception:
                pass
    except Exception:
        return None, "Gmail token 刷新失败。"
    try:
        svc = google_build("gmail", "v1", credentials=creds, cache_discovery=False)
        return svc, ""
    except Exception:
        return None, "Gmail 客户端初始化失败。"


def _bills_query_builder() -> str:
    base = "has:attachment newer_than:90d"
    block_globird = "(from:customerservice@globirdenergy.com.au OR from:cs@globirdenergy.com.au OR subject:globird)"
    block_generic = (
        "(subject:invoice OR subject:\"tax invoice\" OR subject:bill OR subject:statement "
        "OR subject:\"instalment notice\" OR subject:\"levy notice\" OR subject:\"owners corporation\" "
        "OR subject:\"yarra valley water\" OR subject:superloop OR subject:\"energy locals\" OR subject:\"manningham council\")"
    )
    return base + " (" + block_globird + " OR " + block_generic + ")"


def _bills_header_value(headers: list, name: str) -> str:
    target = str(name or "").strip().lower()
    for h in headers or []:
        hn = str((h or {}).get("name") or "").strip().lower()
        if hn == target:
            return str((h or {}).get("value") or "").strip()
    return ""


def _bills_vendor(subject: str, from_addr: str) -> str:
    s = str(subject or "").lower()
    f = str(from_addr or "").lower()
    if ("customerservice@globirdenergy.com.au" in f) or ("cs@globirdenergy.com.au" in f) or ("globird" in s):
        return "Globird"
    if "energy locals" in s:
        return "Energy Locals"
    if "yarra valley water" in s:
        return "Yarra Valley Water"
    if "superloop" in s:
        return "Superloop"
    if "manningham" in s:
        return "Manningham Council"
    if ("owners corporation" in s) or ("levy" in s):
        return "Owners Corporation"
    return "Unknown"


def _bills_walk_parts(payload: dict) -> list:
    out = []
    stack = [payload or {}]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        out.append(node)
        for p in node.get("parts") or []:
            stack.append(p)
    return out


def _bills_extract_pdf_text(path: str) -> str:
    if PdfReader is None:
        return ""
    try:
        logging.getLogger("pypdf").setLevel(logging.ERROR)
    except Exception:
        pass
    try:
        reader = PdfReader(path)
    except Exception:
        return ""
    pieces = []
    total = 0
    max_pages = 20
    max_chars = 200000
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        try:
            part = page.extract_text() or ""
        except Exception:
            part = ""
        if not part:
            continue
        left = max_chars - total
        if left <= 0:
            break
        if len(part) > left:
            part = part[:left]
        pieces.append(part)
        total += len(part)
    return "\n".join(pieces)


def _bills_rel_attachment_path(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    root = str(_BILLS_ATTACH_ROOT or "").rstrip("/\\")
    if root and p.startswith(root):
        rel = p[len(root):].lstrip("/\\")
        return rel.replace("\\", "/")
    return p


def _bills_clean_money(v: str):
    s = str(v or "").strip().replace(",", "")
    s = re.sub(r"[^0-9.]", "", s)
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _bills_money_sane(amount):
    try:
        v = float(amount)
    except Exception:
        return False
    return (v > 0.0) and (v < 100000.0)


def _bills_money_round(amount):
    try:
        return round(float(amount), 2)
    except Exception:
        return None


def _bills_extract_money_candidates(text: str):
    s = str(text or "")
    out = []
    pat_cur = r"(?:(AUD)\s*|\$)\s*([0-9][0-9,]*\.?[0-9]{0,2})"
    for m in re.finditer(pat_cur, s, flags=re.IGNORECASE):
        raw = str(m.group(2) or "")
        val = _bills_clean_money(raw)
        if not _bills_money_sane(val):
            continue
        full = str(m.group(0) or "")
        cur = "AUD"
        if ("AUD" in full.upper()) or ("$" in full):
            cur = "AUD"
        out.append({"start": int(m.start()), "end": int(m.end()), "amount": _bills_money_round(val), "currency": cur})
    pat_plain = r"\b([0-9][0-9,]*\.[0-9]{2})\b"
    for m in re.finditer(pat_plain, s):
        val = _bills_clean_money(m.group(1))
        if not _bills_money_sane(val):
            continue
        out.append({"start": int(m.start()), "end": int(m.end()), "amount": _bills_money_round(val), "currency": ""})
    out.sort(key=lambda x: int(x.get("start") or 0))
    return out


def _bills_near_negative(text_lower: str, pos: int, negatives: list, window: int = 120) -> bool:
    for nk in negatives or []:
        key = str(nk or "").lower()
        if not key:
            continue
        start = 0
        while True:
            idx = text_lower.find(key, start)
            if idx < 0:
                break
            if abs(int(pos) - int(idx)) <= int(window):
                return True
            start = idx + len(key)
    return False


def _bills_pick_money_after_key(text: str, key: str, candidates: list, negatives: list, window: int = 250):
    low = str(text or "").lower()
    k = str(key or "").lower()
    if not k:
        return None
    idx = low.find(k)
    if idx < 0:
        return None
    for c in candidates:
        st = int(c.get("start") or 0)
        if st < idx:
            continue
        if st > (idx + int(window)):
            continue
        if _bills_near_negative(low, st, negatives, 120):
            continue
        return c
    return None


def _bills_detect_amount_bad_with_yarra_rule(vendor: str, amount, text: str) -> bool:
    if not str(vendor or "").lower().strip().startswith("yarra valley water"):
        return False
    if not _bills_money_sane(amount):
        return True
    cands = _bills_extract_money_candidates(text)
    if not cands:
        return False
    prev = None
    for k in ["previous bill", "previousbill"]:
        prev = _bills_pick_money_after_key(text, k, cands, [], 300)
        if prev is not None:
            break
    due = None
    for k in ["amount due", "amountdue", "total this bill", "totalthisbill", "total balance", "totalbalance", "total due", "totaldue", "total payable", "totalpayable"]:
        due = _bills_pick_money_after_key(text, k, cands, [], 300)
        if due is not None:
            break
    if (prev is None) or (due is None):
        return False
    try:
        a = float(amount)
        p = float(prev.get("amount") or 0.0)
        d = float(due.get("amount") or 0.0)
    except Exception:
        return False
    if abs(a - p) < 0.01 and abs(d - p) >= 0.01:
        return True
    return False


def _bills_make_date(year: int, month: int, day: int):
    try:
        y = int(year)
        m = int(month)
        d = int(day)
    except Exception:
        return None
    if y < 2000 or y > 2100:
        return None
    try:
        return date(y, m, d)
    except Exception:
        return None


_BILLS_MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _bills_parse_year_token(y: str):
    yy = str(y or "").strip()
    if not yy:
        return None
    try:
        if len(yy) == 2:
            year = 2000 + int(yy)
        else:
            year = int(yy)
    except Exception:
        return None
    if year < 2000 or year > 2100:
        return None
    return year


def _bills_month_token_to_num(token: str):
    t = str(token or "").strip().lower()
    if not t:
        return None
    return _BILLS_MONTH_MAP.get(t)


def _bills_month_regex():
    return (
        "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
        "January|February|March|April|May|June|July|August|September|October|November|December"
    )


def _bills_extract_date_candidates(text: str):
    s = str(text or "")
    out = []
    for m in re.finditer(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", s):
        y = _bills_parse_year_token(m.group(1))
        if y is None:
            continue
        d = _bills_make_date(y, m.group(2), m.group(3))
        if d is not None:
            out.append({"start": int(m.start()), "date": d})
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b", s):
        y = _bills_parse_year_token(m.group(3))
        if y is None:
            continue
        d = _bills_make_date(y, m.group(2), m.group(1))
        if d is not None:
            out.append({"start": int(m.start()), "date": d})
    mrx = _bills_month_regex()
    pat_joined = r"\b(\d{1,2})(" + mrx + r")(\d{2}|\d{4})\b"
    for m in re.finditer(pat_joined, s, flags=re.IGNORECASE):
        mon = _bills_month_token_to_num(m.group(2).lower())
        if mon is None:
            continue
        y = _bills_parse_year_token(m.group(3))
        if y is None:
            continue
        d = _bills_make_date(y, mon, m.group(1))
        if d is not None:
            out.append({"start": int(m.start()), "date": d})
    pat_spaced = r"\b(\d{1,2})[\s\-\u00A0]+(" + mrx + r")[\s\-\u00A0,\.]+(\d{2}|\d{4})\b"
    for m in re.finditer(pat_spaced, s, flags=re.IGNORECASE):
        mon = _bills_month_token_to_num(m.group(2).lower())
        if mon is None:
            continue
        y = _bills_parse_year_token(m.group(3))
        if y is None:
            continue
        d = _bills_make_date(y, mon, m.group(1))
        if d is not None:
            out.append({"start": int(m.start()), "date": d})
    out.sort(key=lambda x: int(x.get("start") or 0))
    return out


def _bills_pick_date_after_keywords(text: str, candidates: list, keywords: list, window_after: int = 400):
    s = str(text or "")
    low = s.lower()
    if not candidates:
        return None
    key_positions = []
    for kw in keywords or []:
        k = str(kw or "").lower()
        if not k:
            continue
        start = 0
        while True:
            idx = low.find(k, start)
            if idx < 0:
                break
            key_positions.append(int(idx))
            start = idx + len(k)
    if not key_positions:
        return None
    best = None
    best_dist = None
    for kp in key_positions:
        for c in candidates:
            cp = int(c.get("start") or 0)
            if cp < kp:
                continue
            dist = cp - kp
            if dist > int(window_after):
                continue
            if (best is None) or (best_dist is None) or (dist < best_dist):
                best = c
                best_dist = dist
    if best is None:
        return None
    return best.get("date")


def _bills_extract_due_date(text: str):
    s = str(text or "")
    candidates = _bills_extract_date_candidates(s)
    if not candidates:
        return None
    d1 = _bills_pick_date_after_keywords(s, candidates, ["directdebit", "direct debit"], 400)
    if d1 is not None:
        return d1
    d2 = _bills_pick_date_after_keywords(
        s,
        candidates,
        ["amount due", "payment due", "pay by", "due", "total amount payable", "invoice total"],
        400,
    )
    if d2 is not None:
        return d2
    return candidates[0].get("date")


def _bills_find_date(text: str, keys: list) -> str:
    s = str(text or "")
    cands = _bills_extract_date_candidates(s)
    if not cands:
        return ""
    d = _bills_pick_date_after_keywords(s, cands, keys or [], 400)
    if d is not None:
        return d.strftime("%Y-%m-%d")
    d0 = cands[0].get("date")
    if d0 is not None:
        return d0.strftime("%Y-%m-%d")
    return ""


def _bills_find_amount(text: str):
    s = str(text or "")
    low = s.lower()
    cands = _bills_extract_money_candidates(s)
    if not cands:
        return None, ""
    negatives = [
        "previous bill", "previousbill",
        "payment received", "paymentreceived",
        "balance carried forward", "balancecarriedforward",
        "adjustments",
    ]
    primary = [
        "amount due", "amountdue",
        "total this bill", "totalthisbill",
        "total balance", "totalbalance",
        "total due", "totaldue",
        "total payable", "totalpayable",
    ]
    secondary = ["this bill", "thisbill"]
    for k in primary:
        c = _bills_pick_money_after_key(s, k, cands, negatives, 300)
        if c is not None:
            return c.get("amount"), (c.get("currency") or "AUD")
    for k in secondary:
        c = _bills_pick_money_after_key(s, k, cands, negatives, 300)
        if c is not None:
            return c.get("amount"), (c.get("currency") or "AUD")
    for c in cands:
        st = int(c.get("start") or 0)
        if _bills_near_negative(low, st, negatives, 120):
            continue
        return c.get("amount"), (c.get("currency") or "AUD")
    return None, ""


def _bills_parse_message_date(date_hdr: str) -> str:
    d = str(date_hdr or "").strip()
    if not d:
        return _bills_now_local().strftime("%Y-%m-%d")
    try:
        dt = parsedate_to_datetime(d)
        if dt.tzinfo is None:
            return dt.strftime("%Y-%m-%d")
        local = dt.astimezone(ZoneInfo("Australia/Melbourne"))
        return local.strftime("%Y-%m-%d")
    except Exception:
        return _bills_now_local().strftime("%Y-%m-%d")


def _bills_short_subject(s: str) -> str:
    t = str(s or "").strip().replace("\n", " ")
    if len(t) <= 50:
        return t
    return t[:50].rstrip() + "..."


def _bills_bill_name(vendor: str, subject: str) -> str:
    v = str(vendor or "").lower()
    s = str(subject or "").lower()
    t = v + " " + s
    if ("water" in t) or ("yarra valley water" in t):
        return "水费"
    if ("owner" in t) or ("owners corporation" in t) or ("levy" in t) or ("strata" in t) or ("body corporate" in t):
        return "物业费"
    if ("electric" in t) or ("electricity" in t) or ("energy locals" in t) or ("globird" in t):
        return "电费"
    if ("gas" in t):
        return "燃气费"
    if ("superloop" in t) or ("internet" in t) or ("broadband" in t) or ("nbn" in t):
        return "网费"
    if ("phone" in t) or ("mobile" in t) or ("telstra" in t) or ("optus" in t) or ("vodafone" in t):
        return "话费"
    if ("council" in t) or ("manningham" in t) or ("rate notice" in t) or ("rates notice" in t) or ("land tax" in t):
        return "市政费"
    return "账单"


def _bills_amount_title_text(amount, currency: str) -> str:
    try:
        if amount is None:
            return "金额待确认"
        v = float(amount)
        cur = str(currency or "").strip().upper()
        if not cur:
            cur = "AUD"
        return "{0} {1:.2f}".format(cur, v)
    except Exception:
        return "金额待确认"


def _bills_event_time_range_for_day(day_obj):
    hhmm = _bills_event_hhmm()
    parts = hhmm.split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1])
    except Exception:
        hh = 9
        mm = 0
    try:
        tz = ZoneInfo("Australia/Melbourne")
    except Exception:
        tz = None
    if tz is not None:
        start = datetime(day_obj.year, day_obj.month, day_obj.day, hh, mm, 0, tzinfo=tz)
    else:
        start = datetime(day_obj.year, day_obj.month, day_obj.day, hh, mm, 0)
    end = start + timedelta(minutes=10)
    # HA calendar/google create_event is more tolerant with local naive datetime strings.
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def _bills_service_exists(domain: str, service: str) -> bool:
    d = str(domain or "").strip()
    s = str(service or "").strip()
    if (not d) or (not s):
        return False
    idx = _ha_services_index_cached()
    if not isinstance(idx, dict):
        return False
    sv = idx.get(d)
    if not isinstance(sv, set):
        return False
    return s in sv


_HA_SERVICES_CACHE = {"ts": 0.0, "index": None}


def _ha_services_index_cached(ttl_sec: int = 60) -> dict:
    now_ts = float(time.time())
    try:
        ts = float(_HA_SERVICES_CACHE.get("ts") or 0.0)
    except Exception:
        ts = 0.0
    idx_old = _HA_SERVICES_CACHE.get("index")
    if isinstance(idx_old, dict) and ((now_ts - ts) <= float(ttl_sec)):
        return idx_old
    rr = _ha_request("GET", "/api/services", timeout_sec=8)
    if not rr.get("ok"):
        if isinstance(idx_old, dict):
            return idx_old
        return {}
    data = rr.get("data") or []
    out = {}
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            dom = str(row.get("domain") or "").strip()
            if not dom:
                continue
            sv = row.get("services") or {}
            keys = set()
            if isinstance(sv, dict):
                for k in sv.keys():
                    kk = str(k or "").strip()
                    if kk:
                        keys.add(kk)
            out[dom] = keys
    _HA_SERVICES_CACHE["ts"] = now_ts
    _HA_SERVICES_CACHE["index"] = out
    return out


def _ha_calendar_service_capabilities() -> dict:
    def _yes(domain: str, service: str) -> bool:
        return bool(_bills_service_exists(domain, service))

    caps = {
        "calendar_create_event": _yes("calendar", "create_event"),
        "calendar_update_event": _yes("calendar", "update_event") or _yes("calendar", "edit_event"),
        "calendar_delete_event": _yes("calendar", "delete_event") or _yes("calendar", "remove_event"),
        "google_create_event": _yes("google", "create_event"),
        "google_update_event": _yes("google", "update_event") or _yes("google", "edit_event"),
        "google_delete_event": _yes("google", "delete_event") or _yes("google", "remove_event"),
    }
    caps["calendar_mutation_supported"] = bool(caps["calendar_update_event"] or caps["calendar_delete_event"] or caps["google_update_event"] or caps["google_delete_event"])
    return caps


def _calendar_capability_hint_text(action: str) -> str:
    caps = _ha_calendar_service_capabilities()
    return _calendar_capability_hint_text_core(action, caps)


def _bills_ha_event_create(entity_id: str, summary: str, description: str, start_iso: str, end_iso: str) -> dict:
    eid = str(entity_id or "").strip()
    payload = {
        "entity_id": eid,
        "summary": str(summary or "").strip(),
        "description": str(description or "").strip(),
        "start_date_time": str(start_iso or "").strip(),
        "end_date_time": str(end_iso or "").strip(),
    }
    if _bills_service_exists("calendar", "create_event"):
        r1 = ha_call_service("calendar", "create_event", service_data=payload, timeout_sec=12)
        if r1.get("ok"):
            return {"ok": True, "service": "calendar.create_event"}
        code1 = str(r1.get("status_code") or "")
        msg1 = str(r1.get("data") or r1.get("error") or "")
        if len(msg1) > 160:
            msg1 = msg1[:160]
        if _bills_service_exists("google", "create_event"):
            r2 = ha_call_service("google", "create_event", service_data=payload, timeout_sec=12)
            if r2.get("ok"):
                return {"ok": True, "service": "google.create_event"}
            code2 = str(r2.get("status_code") or "")
            msg2 = str(r2.get("data") or r2.get("error") or "")
            if len(msg2) > 160:
                msg2 = msg2[:160]
            return {
                "ok": False,
                "error": "calendar.create_event({0})失败；google.create_event({1})失败".format(code1 or "-", code2 or "-"),
                "status": code2 or code1,
                "message": "calendar={0}; google={1}".format(msg1, msg2),
            }
        return {
            "ok": False,
            "error": "calendar.create_event({0})失败".format(code1 or "-"),
            "status": code1,
            "message": msg1,
        }
    if _bills_service_exists("google", "create_event"):
        r3 = ha_call_service("google", "create_event", service_data=payload, timeout_sec=12)
        if r3.get("ok"):
            return {"ok": True, "service": "google.create_event"}
        code3 = str(r3.get("status_code") or "")
        msg3 = str(r3.get("data") or r3.get("error") or "")
        if len(msg3) > 160:
            msg3 = msg3[:160]
        return {"ok": False, "error": "google.create_event({0})失败".format(code3 or "-"), "status": code3, "message": msg3}
    return {"ok": False, "error": "create_event_service_missing", "message": "未发现 calendar.create_event/google.create_event"}


def _calendar_event_id_candidates(ev: dict) -> dict:
    return _calendar_event_id_candidates_core(ev)


def _calendar_service_call_variants(domain: str, services: list, payloads: list) -> dict:
    return _calendar_service_call_variants_core(
        domain,
        services,
        payloads,
        {
            "bills_service_exists": _bills_service_exists,
            "ha_call_service": ha_call_service,
        },
    )


def _calendar_ha_event_delete(entity_id: str, ev: dict) -> dict:
    return _calendar_ha_event_delete_core(
        entity_id,
        ev,
        {
            "bills_service_exists": _bills_service_exists,
            "ha_call_service": ha_call_service,
        },
    )


def _calendar_parse_update_target_window(text: str, ev: dict, now_local: object = None) -> tuple:
    return _calendar_parse_update_target_window_core(
        text,
        ev,
        now_local if now_local is not None else _now_local(),
        {
            "calendar_event_start_dt": _calendar_event_start_dt,
            "dt_from_iso": _dt_from_iso,
            "tzinfo": _tzinfo,
        },
    )


def _calendar_ha_event_update(entity_id: str, ev: dict, text: str, now_local: object = None) -> dict:
    return _calendar_ha_event_update_core(
        entity_id,
        ev,
        text,
        now_local if now_local is not None else _now_local(),
        {
            "bills_service_exists": _bills_service_exists,
            "ha_call_service": ha_call_service,
            "calendar_event_summary": _calendar_event_summary,
            "calendar_event_start_dt": _calendar_event_start_dt,
            "dt_from_iso": _dt_from_iso,
            "tzinfo": _tzinfo,
        },
    )


def _bills_sync_row_get(conn, bill_id: int):
    cur = conn.cursor()
    cur.execute(
        "SELECT bill_id,calendar_entity,sync_key,due_event_created,due_event_key,due_event_at,remind_event_created,remind_event_key,remind_event_at,last_sync_at,last_error "
        "FROM bills_calendar_sync WHERE bill_id=? LIMIT 1",
        (int(bill_id),),
    )
    r = cur.fetchone()
    if not r:
        return None
    return {
        "bill_id": int(r[0] or 0),
        "calendar_entity": str(r[1] or ""),
        "sync_key": str(r[2] or ""),
        "due_event_created": int(r[3] or 0),
        "due_event_key": str(r[4] or ""),
        "due_event_at": str(r[5] or ""),
        "remind_event_created": int(r[6] or 0),
        "remind_event_key": str(r[7] or ""),
        "remind_event_at": str(r[8] or ""),
        "last_sync_at": str(r[9] or ""),
        "last_error": str(r[10] or ""),
    }


def _bills_sync_row_upsert(conn, row: dict):
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO bills_calendar_sync("
        "bill_id,calendar_entity,sync_key,due_event_created,due_event_key,due_event_at,remind_event_created,remind_event_key,remind_event_at,last_sync_at,last_error"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            int(row.get("bill_id") or 0),
            str(row.get("calendar_entity") or ""),
            str(row.get("sync_key") or ""),
            int(row.get("due_event_created") or 0),
            str(row.get("due_event_key") or ""),
            str(row.get("due_event_at") or ""),
            int(row.get("remind_event_created") or 0),
            str(row.get("remind_event_key") or ""),
            str(row.get("remind_event_at") or ""),
            str(row.get("last_sync_at") or ""),
            str(row.get("last_error") or ""),
        ),
    )


def _bills_sync_calendar(conn) -> dict:
    stats = {
        "created_due": 0,
        "created_remind": 0,
        "already_synced": 0,
        "skipped": 0,
        "failed": 0,
        "error_hint": "",
    }
    cal_entity = _bills_calendar_entity_id()
    remind_days = _bills_remind_days()
    today = _bills_now_local().date()
    now_iso = _bills_now_local().isoformat()
    cur = conn.cursor()
    cur.execute(
        "SELECT id,vendor,subject,msg_date,amount,currency,due_date FROM bills ORDER BY id DESC LIMIT 300"
    )
    rows = cur.fetchall()
    for r in rows:
        bill_id = int(r[0] or 0)
        vendor = str(r[1] or "")
        subject = str(r[2] or "")
        msg_date = str(r[3] or "")
        amount = r[4]
        currency = str(r[5] or "AUD")
        due_raw = str(r[6] or "")
        due_dt = _bill_norm_date(due_raw)
        if due_dt is None:
            stats["skipped"] += 1
            continue
        if due_dt < today:
            stats["skipped"] += 1
            continue
        remind_date = due_dt - timedelta(days=remind_days)
        bill_name = _bills_bill_name(vendor, subject)
        amount_txt = _bills_amount_title_text(amount, currency)
        due_event_key = "bill:{0}:due:{1}:{2}".format(bill_id, due_dt.strftime("%Y-%m-%d"), amount_txt)
        remind_event_key = "bill:{0}:remind:{1}:{2}".format(bill_id, remind_date.strftime("%Y-%m-%d"), amount_txt)
        sync_key = "{0}|{1}|{2}|{3}".format(vendor, due_dt.strftime("%Y-%m-%d"), amount_txt, bill_name)
        row = _bills_sync_row_get(conn, bill_id)
        if row is None:
            row = {
                "bill_id": bill_id,
                "calendar_entity": "",
                "sync_key": "",
                "due_event_created": 0,
                "due_event_key": "",
                "due_event_at": "",
                "remind_event_created": 0,
                "remind_event_key": "",
                "remind_event_at": "",
                "last_sync_at": "",
                "last_error": "",
            }
        if str(row.get("calendar_entity") or "") != cal_entity:
            row["calendar_entity"] = cal_entity
            row["sync_key"] = ""
            row["due_event_created"] = 0
            row["due_event_key"] = ""
            row["due_event_at"] = ""
            row["remind_event_created"] = 0
            row["remind_event_key"] = ""
            row["remind_event_at"] = ""
        if str(row.get("sync_key") or "") != sync_key:
            row["sync_key"] = sync_key
            row["due_event_created"] = 0
            row["due_event_key"] = ""
            row["due_event_at"] = ""
            row["remind_event_created"] = 0
            row["remind_event_key"] = ""
            row["remind_event_at"] = ""
        due_done = int(row.get("due_event_created") or 0) == 1 and str(row.get("due_event_key") or "") == due_event_key
        remind_done = int(row.get("remind_event_created") or 0) == 1 and str(row.get("remind_event_key") or "") == remind_event_key
        any_created = False
        failed_reason = ""
        if not due_done:
            s_iso, e_iso = _bills_event_time_range_for_day(due_dt)
            summary = "【{0}】到期：{1}（{2}）".format(bill_name, amount_txt, (vendor or "账单"))
            desc = "账单名称：{0}\n供应商：{1}\n主题：{2}\n到期日：{3}\n金额：{4}\n邮件日期：{5}".format(
                bill_name,
                vendor or "Unknown",
                subject or "",
                due_dt.strftime("%Y-%m-%d"),
                amount_txt,
                msg_date or "",
            )
            rs = _bills_ha_event_create(cal_entity, summary, desc, s_iso, e_iso)
            if rs.get("ok"):
                row["due_event_created"] = 1
                row["due_event_key"] = due_event_key
                row["due_event_at"] = now_iso
                stats["created_due"] += 1
                any_created = True
            else:
                failed_reason = "due:{0};status={1};{2}".format(
                    str(rs.get("error") or "due_create_failed"),
                    str(rs.get("status") or "-"),
                    str(rs.get("message") or ""),
                )
        if (not failed_reason) and (remind_date >= today) and (not remind_done):
            s2, e2 = _bills_event_time_range_for_day(remind_date)
            summary2 = "提醒：【{0}】将于 {1} 到期（{2}）".format(bill_name, due_dt.strftime("%Y-%m-%d"), amount_txt)
            desc2 = "账单名称：{0}\n供应商：{1}\n主题：{2}\n到期日：{3}\n提醒日：{4}\n金额：{5}\n邮件日期：{6}".format(
                bill_name,
                vendor or "Unknown",
                subject or "",
                due_dt.strftime("%Y-%m-%d"),
                remind_date.strftime("%Y-%m-%d"),
                amount_txt,
                msg_date or "",
            )
            rr = _bills_ha_event_create(cal_entity, summary2, desc2, s2, e2)
            if rr.get("ok"):
                row["remind_event_created"] = 1
                row["remind_event_key"] = remind_event_key
                row["remind_event_at"] = now_iso
                stats["created_remind"] += 1
                any_created = True
            else:
                failed_reason = "remind:{0};status={1};{2}".format(
                    str(rr.get("error") or "remind_create_failed"),
                    str(rr.get("status") or "-"),
                    str(rr.get("message") or ""),
                )
        row["last_sync_at"] = now_iso
        if failed_reason:
            if len(failed_reason) > 160:
                failed_reason = failed_reason[:160]
            row["last_error"] = failed_reason
            stats["failed"] += 1
            stats["error_hint"] = failed_reason
        else:
            row["last_error"] = ""
            if not any_created:
                stats["already_synced"] += 1
        _bills_sync_row_upsert(conn, row)
    return stats


def _bills_sync_stats_text(stats: dict) -> str:
    base = "账单日历同步：新建到期={0}；新建提醒={1}；已同步={2}；跳过={3}；失败={4}。".format(
        int(stats.get("created_due") or 0),
        int(stats.get("created_remind") or 0),
        int(stats.get("already_synced") or 0),
        int(stats.get("skipped") or 0),
        int(stats.get("failed") or 0),
    )
    hint = str(stats.get("error_hint") or "").strip()
    if hint:
        return base + "\n日历同步失败：" + hint
    return base


def _bill_norm_date(s: str):
    raw = str(s or "").strip()
    if not raw:
        return None
    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", raw)
    if m:
        y = _bills_parse_year_token(m.group(1))
        if y is not None:
            return _bills_make_date(y, m.group(2), m.group(3))
    m2 = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b", raw)
    if m2:
        y = _bills_parse_year_token(m2.group(3))
        if y is not None:
            return _bills_make_date(y, m2.group(2), m2.group(1))
    mrx = _bills_month_regex()
    m3 = re.search(r"\b(\d{1,2})(" + mrx + r")(\d{2}|\d{4})\b", raw, flags=re.IGNORECASE)
    if m3:
        mon = _bills_month_token_to_num(str(m3.group(2) or "").lower())
        if mon is not None:
            y = _bills_parse_year_token(m3.group(3))
            if y is not None:
                return _bills_make_date(y, mon, m3.group(1))
    m4 = re.search(r"\b(\d{1,2})[\s\-\u00A0]+(" + mrx + r")[\s\-\u00A0,\.]+(\d{2}|\d{4})\b", raw, flags=re.IGNORECASE)
    if m4:
        mon = _bills_month_token_to_num(str(m4.group(2) or "").lower())
        if mon is not None:
            y = _bills_parse_year_token(m4.group(3))
            if y is not None:
                return _bills_make_date(y, mon, m4.group(1))
    return None


def _bills_backfill_recent_due_dates(conn, limit_rows: int = 50):
    try:
        lim = int(limit_rows or 50)
    except Exception:
        lim = 50
    if lim < 1:
        lim = 50
    if lim > 200:
        lim = 200
    cur = conn.cursor()
    cur.execute(
        "SELECT id,due_date,attachment_path FROM bills ORDER BY id DESC LIMIT ?",
        (lim,),
    )
    rows = cur.fetchall()
    fixed = 0
    nulled = 0
    unchanged = 0
    for r in rows:
        bid = int(r[0] or 0)
        due_raw = r[1]
        att = str(r[2] or "").strip()
        due_ok = _bill_norm_date(due_raw)
        if due_ok is not None:
            unchanged += 1
            continue
        if (not att) or (not os.path.exists(att)) or (not os.path.isfile(att)):
            cur.execute("UPDATE bills SET due_date=NULL WHERE id=?", (bid,))
            nulled += 1
            continue
        text = _bills_extract_pdf_text(att)
        if not str(text or "").strip():
            cur.execute("UPDATE bills SET due_date=NULL WHERE id=?", (bid,))
            nulled += 1
            continue
        due_new = _bills_extract_due_date(text)
        if due_new is None:
            cur.execute("UPDATE bills SET due_date=NULL WHERE id=?", (bid,))
            nulled += 1
            continue
        cur.execute(
            "UPDATE bills SET due_date=? WHERE id=?",
            (due_new.strftime("%Y-%m-%d"), bid),
        )
        fixed += 1
    return {"fixed": fixed, "nulled": nulled, "unchanged": unchanged}


def _bills_backfill_recent_amounts(conn, limit_rows: int = 50):
    try:
        lim = int(limit_rows or 50)
    except Exception:
        lim = 50
    if lim < 1:
        lim = 50
    if lim > 200:
        lim = 200
    cur = conn.cursor()
    cur.execute(
        "SELECT id,vendor,amount,currency,attachment_path FROM bills ORDER BY id DESC LIMIT ?",
        (lim,),
    )
    rows = cur.fetchall()
    fixed = 0
    nulled = 0
    unchanged = 0
    for r in rows:
        bid = int(r[0] or 0)
        vendor = str(r[1] or "")
        amt = r[2]
        att = str(r[4] or "").strip()
        bad = False
        if (amt is None) or (not _bills_money_sane(amt)):
            bad = True
        text = ""
        if bad or vendor.lower().startswith("yarra valley water"):
            if att and os.path.exists(att) and os.path.isfile(att):
                text = _bills_extract_pdf_text(att)
            else:
                text = ""
        if (not bad) and vendor.lower().startswith("yarra valley water"):
            if _bills_detect_amount_bad_with_yarra_rule(vendor, amt, text):
                bad = True
        if not bad:
            unchanged += 1
            continue
        if not str(text or "").strip():
            cur.execute("UPDATE bills SET amount=NULL,currency='' WHERE id=?", (bid,))
            nulled += 1
            continue
        new_amt, new_cur = _bills_find_amount(text)
        if _bills_money_sane(new_amt):
            cur.execute(
                "UPDATE bills SET amount=?,currency=? WHERE id=?",
                (_bills_money_round(new_amt), (new_cur or "AUD"), bid),
            )
            fixed += 1
        else:
            cur.execute("UPDATE bills SET amount=NULL,currency='' WHERE id=?", (bid,))
            nulled += 1
    return {"fixed": fixed, "nulled": nulled, "unchanged": unchanged}


def _bills_process_new() -> str:
    service, err = _bills_gmail_service()
    if service is None:
        return "账单拉取失败：" + str(err or "Gmail 不可用")
    try:
        conn = _bills_db_connect()
    except Exception:
        return "账单拉取失败：本地数据库不可用"
    added = 0
    failed = 0
    skipped = 0
    fail_items = []
    backfill_stats = {"fixed": 0, "nulled": 0, "unchanged": 0}
    amount_backfill_stats = {"fixed": 0, "nulled": 0, "unchanged": 0}
    cal_sync_stats = {"created_due": 0, "created_remind": 0, "already_synced": 0, "skipped": 0, "failed": 0, "error_hint": ""}
    try:
        query = _bills_query_builder()
        resp = service.users().messages().list(userId="me", q=query, maxResults=20).execute()
        msgs = resp.get("messages") or []
        for m in msgs:
            mid = str((m or {}).get("id") or "").strip()
            if not mid:
                continue
            if _bills_is_processed(conn, mid):
                skipped += 1
                continue
            try:
                full = service.users().messages().get(userId="me", id=mid, format="full").execute()
                payload = full.get("payload") or {}
                headers = payload.get("headers") or []
                subject = _bills_header_value(headers, "Subject")
                from_addr = _bills_header_value(headers, "From")
                msg_date = _bills_parse_message_date(_bills_header_value(headers, "Date"))
                vendor = _bills_vendor(subject, from_addr)
                fail_reason = ""
                attach_rel = ""
                parts = _bills_walk_parts(payload)
                pdf_part = None
                for p in parts:
                    fn = str(p.get("filename") or "")
                    body = p.get("body") or {}
                    if fn.lower().endswith(".pdf") and ((body.get("attachmentId")) or (body.get("data"))):
                        pdf_part = p
                        break
                if pdf_part is None:
                    failed += 1
                    fail_reason = "未找到PDF附件"
                    _bills_insert_row(
                        conn,
                        {
                            "vendor": vendor,
                            "subject": subject,
                            "from_addr": from_addr,
                            "msg_date": msg_date,
                            "amount": None,
                            "currency": "AUD",
                            "due_date": None,
                            "issue_date": msg_date,
                            "status": "failed",
                            "message_id": mid,
                            "attachment_path": "",
                            "failure_reason": fail_reason,
                        },
                    )
                    if len(fail_items) < 5:
                        fail_items.append(vendor + " | " + _bills_short_subject(subject) + " | 原因=" + fail_reason + " | 附件=-")
                    _bills_mark_processed(conn, mid)
                    continue

                body = pdf_part.get("body") or {}
                fname = str(pdf_part.get("filename") or "bill.pdf")
                fname = re.sub(r"[^0-9A-Za-z._-]+", "_", fname)
                now = _bills_now_local()
                y = now.strftime("%Y")
                mo = now.strftime("%m")
                save_dir = os.path.join(_BILLS_ATTACH_ROOT, y, mo)
                os.makedirs(save_dir, exist_ok=True)
                local_path = os.path.join(save_dir, str(mid) + "_" + fname)

                raw = ""
                if body.get("data"):
                    raw = str(body.get("data") or "")
                elif body.get("attachmentId"):
                    att = service.users().messages().attachments().get(
                        userId="me", messageId=mid, id=str(body.get("attachmentId"))
                    ).execute()
                    raw = str((att or {}).get("data") or "")
                if not raw:
                    failed += 1
                    fail_reason = "附件内容为空"
                    _bills_insert_row(
                        conn,
                        {
                            "vendor": vendor,
                            "subject": subject,
                            "from_addr": from_addr,
                            "msg_date": msg_date,
                            "amount": None,
                            "currency": "AUD",
                            "due_date": None,
                            "issue_date": msg_date,
                            "status": "failed",
                            "message_id": mid,
                            "attachment_path": "",
                            "failure_reason": fail_reason,
                        },
                    )
                    if len(fail_items) < 5:
                        fail_items.append(vendor + " | " + _bills_short_subject(subject) + " | 原因=" + fail_reason + " | 附件=-")
                    _bills_mark_processed(conn, mid)
                    continue
                try:
                    bin_data = base64.urlsafe_b64decode(raw + "===")
                    with open(local_path, "wb") as f:
                        f.write(bin_data)
                    attach_rel = _bills_rel_attachment_path(local_path)
                except Exception:
                    failed += 1
                    fail_reason = "附件保存失败"
                    _bills_insert_row(
                        conn,
                        {
                            "vendor": vendor,
                            "subject": subject,
                            "from_addr": from_addr,
                            "msg_date": msg_date,
                            "amount": None,
                            "currency": "AUD",
                            "due_date": None,
                            "issue_date": msg_date,
                            "status": "failed",
                            "message_id": mid,
                            "attachment_path": local_path,
                            "failure_reason": fail_reason,
                        },
                    )
                    if len(fail_items) < 5:
                        fail_items.append(vendor + " | " + _bills_short_subject(subject) + " | 原因=" + fail_reason + " | 附件=" + (attach_rel or "-"))
                    _bills_mark_processed(conn, mid)
                    continue

                text = _bills_extract_pdf_text(local_path)
                amount, currency = _bills_find_amount(text)
                due_dt = _bills_extract_due_date(text)
                due_date = ""
                if due_dt is not None:
                    due_date = due_dt.strftime("%Y-%m-%d")
                issue_date = _bills_find_date(text, ["issuedate", "issue date", "invoice date", "date issued"])
                if not issue_date:
                    issue_date = msg_date
                status = "ok" if text.strip() else "failed_text"
                _bills_insert_row(
                    conn,
                    {
                        "vendor": vendor,
                        "subject": subject,
                        "from_addr": from_addr,
                        "msg_date": msg_date,
                        "amount": amount,
                        "currency": currency or "AUD",
                        "due_date": due_date,
                        "issue_date": issue_date,
                        "status": status,
                        "message_id": mid,
                        "attachment_path": local_path,
                        "failure_reason": ("文本提取为空" if status == "failed_text" else ""),
                    },
                )
                if status != "ok":
                    failed += 1
                    if len(fail_items) < 5:
                        fail_items.append(vendor + " | " + _bills_short_subject(subject) + " | 原因=文本提取为空 | 附件=" + (attach_rel or "-"))
                _bills_mark_processed(conn, mid)
                added += 1
            except Exception:
                failed += 1
                if len(fail_items) < 5:
                    fail_items.append("Unknown | Unknown | 原因=处理异常 | 附件=-")
                try:
                    try:
                        _bills_insert_row(
                            conn,
                            {
                                "vendor": "Unknown",
                                "subject": "",
                                "from_addr": "",
                                "msg_date": _bills_now_local().strftime("%Y-%m-%d"),
                                "amount": None,
                                "currency": "AUD",
                                "due_date": None,
                                "issue_date": "",
                                "status": "failed",
                                "message_id": mid,
                                "attachment_path": "",
                                "failure_reason": "处理异常",
                            },
                        )
                    except Exception:
                        pass
                    _bills_mark_processed(conn, mid)
                except Exception:
                    pass
        try:
            backfill_stats = _bills_backfill_recent_due_dates(conn, 50) or {"fixed": 0, "nulled": 0, "unchanged": 0}
        except Exception:
            pass
        try:
            amount_backfill_stats = _bills_backfill_recent_amounts(conn, 50) or {"fixed": 0, "nulled": 0, "unchanged": 0}
        except Exception:
            pass
        try:
            cal_sync_stats = _bills_sync_calendar(conn) or cal_sync_stats
        except Exception:
            cal_sync_stats = {"created_due": 0, "created_remind": 0, "already_synced": 0, "skipped": 0, "failed": 1, "error_hint": "sync_failed"}
        conn.commit()
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return "账单拉取失败：Gmail 读取失败"
    summary = "账单处理完成：新增={0}；失败={1}；跳过已处理={2}。".format(added, failed, skipped)
    if failed > 0 and fail_items:
        summary = summary + "\n失败："
        for it in fail_items[:5]:
            summary = summary + "\n- " + str(it)
    summary = summary + "\n回填修正={0}；置空={1}；保持不变={2}".format(
        int(backfill_stats.get("fixed") or 0),
        int(backfill_stats.get("nulled") or 0),
        int(backfill_stats.get("unchanged") or 0),
    )
    summary = summary + "\n回填金额修正={0}；置空={1}；保持不变={2}".format(
        int(amount_backfill_stats.get("fixed") or 0),
        int(amount_backfill_stats.get("nulled") or 0),
        int(amount_backfill_stats.get("unchanged") or 0),
    )
    summary = summary + "\n" + _bills_sync_stats_text(cal_sync_stats)
    return summary


def _bills_sync_only() -> str:
    try:
        conn = _bills_db_connect()
    except Exception:
        return "账单日历同步失败：本地数据库不可用"
    try:
        stats = _bills_sync_calendar(conn)
        conn.commit()
        conn.close()
        final = _bills_sync_stats_text(stats)
        if not str(final or "").strip():
            return "账单日历同步失败：未知原因"
        return final
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return "账单日历同步失败：请检查 Home Assistant 日历服务配置。"


def _bills_report_text() -> str:
    try:
        conn = _bills_db_connect()
    except Exception:
        return "账单查询失败：本地数据库不可用"
    due_days = 7
    try:
        now_dt = datetime.now(ZoneInfo("Australia/Melbourne"))
    except Exception:
        now_dt = datetime.now()
    now = now_dt.date()
    upcoming_end = now + timedelta(days=7)
    lines = []

    def _amt_text(currency, amount):
        curc = str(currency or "").strip()
        try:
            if amount is not None:
                val = "{0:.2f}".format(float(amount))
                if curc:
                    return curc + " " + val
                return val
        except Exception:
            pass
        return ""

    def _line_vendor_amt_subject(vendor, currency, amount, subject):
        v = str(vendor or "Unknown")
        s = _bills_short_subject(subject or "")
        a = _amt_text(currency, amount)
        if a:
            return "- " + v + " | " + a + " | " + s
        return "- " + v + " | " + s

    def _line_date_vendor_amt_subject(due_date, vendor, currency, amount, subject):
        d = str(due_date or "")
        v = str(vendor or "Unknown")
        s = _bills_short_subject(subject or "")
        a = _amt_text(currency, amount)
        if a:
            return "- " + d + " | " + v + " | " + a + " | " + s
        return "- " + d + " | " + v + " | " + s

    def _recent_line(due_date_text, vendor, currency, amount, subject):
        d = str(due_date_text or "").strip()
        if not d:
            d = "到期未知"
        else:
            d = d + " 到期"
        v = str(vendor or "Unknown")
        s = _bills_short_subject(subject or "")
        a = _amt_text(currency, amount)
        if a:
            return d + " | " + v + " | " + a + " | " + s
        return d + " | " + v + " | " + s

    try:
        cur = conn.cursor()
        lines.append("今天（按程序口径）：{0}".format(now.strftime("%Y-%m-%d")))

        cur.execute(
            "SELECT due_date,vendor,amount,currency,subject FROM bills "
            "WHERE due_date <> '' "
            "ORDER BY id DESC LIMIT 200",
        )
        due_rows = cur.fetchall()
        today_due = []
        upcoming = []
        for r in due_rows:
            nd = _bill_norm_date(r[0])
            if nd is None:
                continue
            if nd == now:
                today_due.append((nd, r))
            elif (nd > now) and (nd <= upcoming_end):
                upcoming.append((nd, r))

        lines.append("今天到期：")
        if today_due:
            for _d, r in today_due:
                lines.append(_line_vendor_amt_subject(r[1], r[3], r[2], r[4]))
        else:
            lines.append("- 目前没有到期项")

        upcoming.sort(key=lambda x: x[0])
        if upcoming:
            lines.append("未来7天到期：")
            for _d, r in upcoming:
                lines.append(_line_date_vendor_amt_subject(_d.strftime("%Y-%m-%d"), r[1], r[3], r[2], r[4]))
        else:
            lines.append("未来7天到期：目前没有到期项")

        cur.execute(
            "SELECT "
            "CASE WHEN msg_date <> '' THEN msg_date ELSE substr(created_at,1,10) END AS d, "
            "vendor,amount,currency,subject,due_date "
            "FROM bills "
            "ORDER BY d DESC, id DESC LIMIT 3"
        )
        latest = cur.fetchall()
        lines.append("最近账单：")
        if latest:
            for r in latest:
                nd = _bill_norm_date(r[5])
                due_show = ""
                if nd is not None:
                    due_show = nd.strftime("%Y-%m-%d")
                lines.append(_recent_line(due_show, r[1], r[3], r[2], r[4]))
        else:
            lines.append("- 目前没有账单记录")
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return "账单查询失败：读取数据失败"
    out = "\n".join([x for x in lines if str(x or "").strip()])
    if out.strip():
        return out
    return "目前没有账单数据。"


def _is_bills_process_intent(text: str) -> bool:
    s = str(text or "").strip()
    return ("处理新账单" in s) or ("拉取新账单" in s)


def _is_bills_report_intent(text: str) -> bool:
    s = str(text or "").strip()
    return ("检查账单" in s) or ("最近账单" in s)


def _is_bills_calendar_sync_intent(text: str) -> bool:
    s = str(text or "").strip().lower()
    return (
        ("同步账单到日历" in s) or ("同步账单到日曆" in s) or ("账单同步到日历" in s)
        or ("同步一下账单日历" in s) or ("同步账单日历" in s) or ("把账单同步到日历" in s)
        or ("账单加到日历" in s) or ("把账单加到日历" in s)
        or ("sync bills calendar" in s) or ("sync bill calendar" in s)
    )


def _is_home_control_like_intent(text: str) -> bool:
    return rh.is_home_control_like_intent(text)


def _route_request_impl_impl(text: str, language: str = None, _llm_allow: bool = True) -> dict:
    return _answer_route_request_core(
        text,
        language or "",
        _llm_allow,
        {
            "env_get": lambda k, d="": str(os.environ.get(k) or d),
            "is_bills_process_intent": _is_bills_process_intent,
            "is_bills_report_intent": _is_bills_report_intent,
            "is_bills_calendar_sync_intent": _is_bills_calendar_sync_intent,
            "bills_process_new": _bills_process_new,
            "bills_report_text": _bills_report_text,
            "bills_sync_only": _bills_sync_only,
            "should_handoff_control": rp.should_handoff_control,
            "is_home_control_like_intent": _is_home_control_like_intent,
            "is_music_control_query": _is_music_control_query,
            "control_handoff_response": rp.control_handoff_response,
            "is_holiday_query": _is_holiday_query,
            "route_holiday_request": _answer_route_holiday_core,
            "now_local": _now_local,
            "holiday_vic": holiday_vic,
            "holiday_next_from_list": _holiday_next_from_list,
            "holiday_prev_from_list": _holiday_prev_from_list,
            "is_weather_query": _is_weather_query,
            "route_weather_request": _answer_route_weather_core,
            "tzinfo": _tzinfo,
            "weather_range_from_text": _weather_range_from_text,
            "ha_weather_forecast": ha_weather_forecast,
            "local_date_from_forecast_item": _local_date_from_forecast_item,
            "safe_int": _safe_int,
            "summarise_weather_range": _summarise_weather_range,
            "pick_daily_forecast_by_local_date": _pick_daily_forecast_by_local_date,
            "summarise_weather_item": _summarise_weather_item,
            "is_calendar_query": _is_calendar_query,
            "route_calendar_request": _calendar_route_request_core,
            "calendar_entities_for_query": _calendar_entities_for_query,
            "calendar_is_delete_intent": _calendar_is_delete_intent,
            "calendar_is_update_intent": _calendar_is_update_intent,
            "calendar_range_from_text": _calendar_range_from_text,
            "iso_day_start_end": _iso_day_start_end,
            "calendar_fetch_merged_events": _calendar_fetch_merged_events,
            "calendar_pick_event_for_text": _calendar_pick_event_for_text,
            "calendar_event_summary": _calendar_event_summary,
            "calendar_ha_event_delete": _calendar_ha_event_delete,
            "calendar_ha_event_update": _calendar_ha_event_update,
            "calendar_is_create_intent": _calendar_is_create_intent,
            "calendar_build_create_event": _calendar_build_create_event,
            "bills_calendar_entity_id": _bills_calendar_entity_id,
            "bills_ha_event_create": _bills_ha_event_create,
            "summarise_calendar_events": _summarise_calendar_events,
            "news_is_query": _news__is_query,
            "route_news_request": _news_route_request_core,
            "news_category_from_text": _news__category_from_text,
            "news_time_range_from_text": _news__time_range_from_text,
            "news_hot": news_hot,
            "news_digest": news_digest,
            "news_extract_limit": _news__extract_limit,
            "route_music_request": _music_route_request_core,
            "music_extract_target_entity": _music_extract_target_entity,
            "music_apply_aliases": _music_apply_aliases,
            "ha_call_service": ha_call_service,
            "music_soft_mute": _music_soft_mute,
            "music_get_volume_level": _music_get_volume_level,
            "music_unmute_default": _music_unmute_default,
            "music_parse_volume": _music_parse_volume,
            "music_try_volume_updown": _music_try_volume_updown,
            "music_parse_volume_delta": _music_parse_volume_delta,
            "is_rag_disable_intent": _is_rag_disable_intent,
            "rag_handle_management": _rag_handle_management,
            "is_rag_config_intent": _is_rag_config_intent,
            "rag_parse_config_draft": _rag_parse_config_draft,
            "rag_save_json_atomic": _rag_save_json_atomic,
            "rag_draft_path": _rag_draft_path,
            "rag_config_draft_text": _rag_config_draft_text,
            "is_rag_intent": _is_rag_intent,
            "rag_mode": _rag_mode,
            "rag_stub_answer": _rag_stub_answer,
            "llm_route_decide": _llm_route_decide,
            "llm_router_conf_threshold": _llm_router_conf_threshold,
            "route_request_impl": _route_request_impl,
            "smalltalk_reply": _smalltalk_reply,
            "poi_answer": _poi_answer,
            "web_search_answer": _web_search_answer,
            "default_fallback": rp.handle_default_fallback,
            "is_obvious_smalltalk": _is_obvious_smalltalk,
            "is_poi_intent": _is_poi_intent,
            "has_strong_lookup_intent": _has_strong_lookup_intent,
            "is_life_advice_intent": _is_life_advice_intent,
            "life_advice_fallback": _life_advice_fallback,
        },
    )


def _route_request_impl(text: str, language: str = None, _llm_allow: bool = True) -> dict:
    return _route_request_impl_impl(text, language, _llm_allow)


# @mcp.tool(description="(Debug) Return enabled tools and key env configuration for self-check.")
def tools_selfcheck() -> dict:
    out = {
        "ok": True,
        "service": "mcp-hello",
        "tools": list(_SKILL_TOOL_NAMES),
        "tools_count": len(_SKILL_TOOL_NAMES),
        "port": os.environ.get("PORT") or os.environ.get("MCP_PORT") or "19090",
        "TZ": os.environ.get("TZ") or "",
        "HA_BASE_URL": os.environ.get("HA_BASE_URL") or "",
        "HA_DEFAULT_WEATHER_ENTITY": os.environ.get("HA_DEFAULT_WEATHER_ENTITY") or "",
        "HA_DEFAULT_CALENDAR_ENTITY": os.environ.get("HA_DEFAULT_CALENDAR_ENTITY") or "",
        "SEARXNG_URL": os.environ.get("SEARXNG_URL") or "http://192.168.1.162:8081",
        "WEB_SEARCH_FALLBACK_MODE": os.environ.get("WEB_SEARCH_FALLBACK_MODE") or "explicit",
        "note": "Externally exposed MCP tools are skill.* only.",
    }
    return out

def _build_asgi_app_from_mcp():
    try:
        a = getattr(mcp, "app", None)
        if a is not None:
            return a
    except Exception:
        pass
    for nm in ["asgi_app", "get_asgi_app", "sse_app", "get_app", "create_app"]:
        try:
            fn = getattr(mcp, nm, None)
            if fn is None:
                continue
            if callable(fn):
                try:
                    return fn()
                except TypeError:
                    return fn
        except Exception:
            continue
    return None

if __name__ == "__main__":
    host = os.environ.get("HOST") or "0.0.0.0"
    port = _safe_int(os.environ.get("PORT") or os.environ.get("MCP_PORT") or "19090", 19090)

    # In Docker/HA MCP Server usage, we want an HTTP(SSE/ASGI) server.
    # Do NOT call mcp.run() here (it may default to STDIO and exit cleanly in containers).
    asgi = _build_asgi_app_from_mcp()
    if asgi is None:
        raise RuntimeError("Cannot build ASGI app from FastMCP. FastMCP API mismatch.")

    import uvicorn
    uvicorn.run(asgi, host=host, port=port)
