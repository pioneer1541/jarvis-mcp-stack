import json
import os
import re
import time
import uuid
from typing import Any, Dict, List

import requests
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route


# Lazy-import app so startup stays fast and we only bind to stable wrappers.
_APP_MODULE = None
_ENTITY_ID_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
_HA_AREA_CACHE = {"ts": 0.0, "map": {}}
_HA_ASSIST_VISIBLE_CACHE = {"ts": 0.0, "names": []}
_ALLOWED_STATE_DOMAINS = ["light", "climate", "cover", "media_player", "sensor"]


def _load_app_module():
    global _APP_MODULE
    if _APP_MODULE is None:
        import app as app_module

        _APP_MODULE = app_module
    return _APP_MODULE


def _now_ts() -> int:
    return int(time.time())


def _chat_id() -> str:
    return "chatcmpl-{}".format(uuid.uuid4().hex[:24])


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


def _last_user_text(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        if str(m.get("role") or "") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, list):
            parts = []
            for it in c:
                if isinstance(it, dict) and str(it.get("type") or "") == "text":
                    parts.append(str(it.get("text") or ""))
            return " ".join([p for p in parts if p]).strip()
    return ""


def _last_tool_content(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        if str(m.get("role") or "") != "tool":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c.strip()
        return _to_str(c)
    return ""


def _ha_base_url() -> str:
    return str(os.environ.get("HA_BASE_URL") or "").strip().rstrip("/")


def _ha_token() -> str:
    return str(os.environ.get("HA_TOKEN") or "").strip()


def _ha_timeout() -> float:
    raw = str(os.environ.get("HA_TIMEOUT") or "8").strip()
    try:
        v = float(raw)
    except Exception:
        v = 8.0
    if v < 1.0:
        v = 1.0
    if v > 30.0:
        v = 30.0
    return v


def _ha_headers() -> Dict[str, str]:
    tk = _ha_token()
    if not tk:
        return {}
    return {"Authorization": "Bearer {}".format(tk), "Content-Type": "application/json"}


def _is_valid_entity_id(entity_id: str) -> bool:
    return bool(_ENTITY_ID_RE.match(str(entity_id or "").strip()))


def _allowed_services() -> List[str]:
    raw = str(
        os.environ.get("HA_SERVICE_WHITELIST")
        or "light.turn_on,light.turn_off,climate.turn_on,climate.turn_off,climate.set_temperature,cover.open_cover,cover.close_cover,media_player.media_play,media_player.media_pause,media_player.volume_set"
    ).strip()
    out = []
    for p in raw.split(","):
        s = str(p or "").strip().lower()
        if s:
            out.append(s)
    return out


def _normalize_domain(domain: str) -> str:
    d = str(domain or "").strip().lower()
    if not d:
        return ""
    if d in _ALLOWED_STATE_DOMAINS:
        return d
    alias = {
        "灯": "light",
        "灯光": "light",
        "空调": "climate",
        "窗帘": "cover",
        "电视": "media_player",
        "音箱": "media_player",
        "音响": "media_player",
        "speaker": "media_player",
        "温度": "sensor",
        "太阳能": "sensor",
    }
    return alias.get(d, d)


def _ha_get_json(path: str):
    base = _ha_base_url()
    headers = _ha_headers()
    if not base or (not headers):
        return None
    url = "{}/{}".format(base, str(path or "").lstrip("/"))
    try:
        resp = requests.get(url, headers=headers, timeout=_ha_timeout())
        if int(resp.status_code) < 200 or int(resp.status_code) >= 300:
            return None
        return resp.json()
    except Exception:
        return None


def _ha_entity_area_map() -> Dict[str, str]:
    now = time.time()
    ts = float(_HA_AREA_CACHE.get("ts") or 0.0)
    mp = _HA_AREA_CACHE.get("map") if isinstance(_HA_AREA_CACHE.get("map"), dict) else {}
    if (now - ts) <= 60.0 and mp:
        return mp
    entities = _ha_get_json("/api/config/entity_registry/list")
    areas = _ha_get_json("/api/config/area_registry/list")
    devices = _ha_get_json("/api/config/device_registry/list")
    if not isinstance(entities, list):
        return {}
    area_id_to_name = {}
    for a in (areas if isinstance(areas, list) else []):
        if not isinstance(a, dict):
            continue
        aid = str(a.get("area_id") or "").strip()
        nm = str(a.get("name") or "").strip()
        if aid and nm:
            area_id_to_name[aid] = nm
    dev_to_area = {}
    for d in (devices if isinstance(devices, list) else []):
        if not isinstance(d, dict):
            continue
        did = str(d.get("id") or "").strip()
        aid = str(d.get("area_id") or "").strip()
        if did and aid:
            dev_to_area[did] = aid
    out = {}
    for e in entities:
        if not isinstance(e, dict):
            continue
        eid = str(e.get("entity_id") or "").strip()
        if not eid:
            continue
        aid = str(e.get("area_id") or "").strip()
        if (not aid) and str(e.get("device_id") or "").strip():
            aid = dev_to_area.get(str(e.get("device_id") or "").strip(), "")
        area_name = area_id_to_name.get(aid, "") if aid else ""
        if area_name:
            out[eid] = area_name
    _HA_AREA_CACHE["ts"] = now
    _HA_AREA_CACHE["map"] = out
    return out


def _norm_match_text(s: str) -> str:
    t = str(s or "").strip().lower()
    if not t:
        return ""
    t = re.sub(r"[\s\-_]+", "", t)
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t)
    return t


def _collect_text_nodes(obj: Any, out: List[str], depth: int = 0):
    if depth > 8:
        return
    if isinstance(obj, str):
        s = obj.strip()
        if s:
            out.append(s)
        return
    if isinstance(obj, list):
        for it in obj:
            _collect_text_nodes(it, out, depth + 1)
        return
    if isinstance(obj, dict):
        for _, v in obj.items():
            _collect_text_nodes(v, out, depth + 1)
        return


def _extract_names_from_assist_text(text: str) -> List[str]:
    raw = str(text or "")
    names = []
    pattern = re.compile(r"^\s*-\s*names:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    for m in pattern.finditer(raw):
        chunk = str(m.group(1) or "").strip()
        if not chunk:
            continue
        parts = [str(x or "").strip() for x in chunk.split(",")]
        for p in parts:
            if p:
                names.append(p)
    # Fallback for short list-style answers: "名称：A, B, C"
    if not names:
        pattern2 = re.compile(r"(?:名称|names?)\s*[:：]\s*(.+)", re.IGNORECASE)
        m2 = pattern2.search(raw)
        if m2:
            parts = [str(x or "").strip() for x in str(m2.group(1) or "").split(",")]
            for p in parts:
                if p:
                    names.append(p)
    dedup = []
    seen = set()
    for n in names:
        k = _norm_match_text(n)
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        dedup.append(n)
    return dedup


def _ha_assist_visible_names() -> List[str]:
    now = time.time()
    ts = float(_HA_ASSIST_VISIBLE_CACHE.get("ts") or 0.0)
    cached = _HA_ASSIST_VISIBLE_CACHE.get("names")
    if (now - ts) <= 60.0 and isinstance(cached, list) and cached:
        return cached

    base = _ha_base_url()
    headers = _ha_headers()
    if not base or (not headers):
        return []

    payload = {
        "agent_id": str(os.environ.get("HA_ASSIST_AGENT_ID") or "conversation.ollama_conversation").strip(),
        "language": "zh-CN",
        "text": "请只返回当前会话可见设备清单，逐行使用“- names: 名称1, 名称2”格式，不要其它说明。",
    }
    url = "{}/api/conversation/process".format(base)
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=_ha_timeout())
        if int(resp.status_code) < 200 or int(resp.status_code) >= 300:
            return []
        data = resp.json()
        nodes = []
        _collect_text_nodes(data, nodes, 0)
        names = []
        for txt in nodes:
            extracted = _extract_names_from_assist_text(txt)
            if extracted:
                names.extend(extracted)
        dedup = []
        seen = set()
        for n in names:
            k = _norm_match_text(n)
            if not k:
                continue
            if k in seen:
                continue
            seen.add(k)
            dedup.append(n)
        if dedup:
            _HA_ASSIST_VISIBLE_CACHE["ts"] = now
            _HA_ASSIST_VISIBLE_CACHE["names"] = dedup
        return dedup
    except Exception:
        return []


def _area_alias_tokens(area_text: str) -> List[str]:
    a = str(area_text or "").strip().lower()
    if not a:
        return []
    alias = {
        "客厅": ["客厅", "living room", "living"],
        "卧室": ["卧室", "master bedroom", "bedroom"],
        "主卧": ["主卧", "master bedroom", "bedroom"],
        "车库": ["车库", "garage"],
        "厨房": ["厨房", "kitchen"],
        "学习室": ["学习室", "study", "study room"],
        "游戏室": ["游戏室", "gaming room", "game room"],
        "花园": ["花园", "garden"],
        "一楼": ["一楼", "1st floor", "ground floor"],
        "二楼": ["二楼", "2nd floor"],
        "三楼": ["三楼", "3rd floor"],
    }
    if a in alias:
        return alias.get(a, [])
    return [a]


def _name_alias_tokens(name_text: str) -> List[str]:
    n = str(name_text or "").strip().lower()
    if not n:
        return []
    alias = {
        "客厅": ["客厅", "living room", "living"],
        "卧室": ["卧室", "bedroom", "master bedroom"],
        "主卧": ["主卧", "master bedroom", "bedroom"],
        "车库": ["车库", "garage"],
        "厨房": ["厨房", "kitchen"],
        "学习室": ["学习室", "study", "study room"],
        "游戏室": ["游戏室", "gaming room", "game room"],
        "花园": ["花园", "garden"],
        "温度": ["温度", "temperature"],
        "空调": ["空调", "climate", "aircon", "ac"],
        "灯": ["灯", "light", "lightswitch"],
        "电视": ["电视", "tv"],
        "音箱": ["音箱", "speaker", "media player"],
        "太阳能": ["太阳能", "solar", "pv", "solax"],
    }
    if n in alias:
        return alias.get(n, [])
    return [n]


def _route_tool_name(user_text: str) -> str:
    t = str(user_text or "").strip().lower()
    if not t:
        return "skill.answer_question"
    if ("记住" in t) or ("记一下" in t) or ("存一下" in t) or ("remember" in t):
        return "skill.memory_upsert"
    if ("记忆" in t and "搜索" in t) or ("memory search" in t):
        return "skill.memory_search"
    if ("新闻" in t) or ("news" in t) or ("热点" in t):
        return "skill.news_brief"
    if ("假期" in t) or ("holiday" in t) or ("公众假期" in t):
        return "skill.holiday_query"
    if ("账单" in t) or ("发票" in t and "模板" not in t) or ("due" in t):
        return "skill.finance_admin"
    if ("资料库" in t) or ("说明书" in t) or ("合同" in t) or ("保修" in t):
        return "skill.knowledge_lookup"
    if ("播放" in t) or ("暂停" in t) or ("下一首" in t) or ("上一首" in t) or ("音量" in t) or ("mute" in t):
        return "skill.music_control"
    return "skill.answer_question"


def _normalize_declared_tools(tools: Any) -> List[Dict[str, Any]]:
    out = []
    for it in (tools if isinstance(tools, list) else []):
        if not isinstance(it, dict):
            continue
        if str(it.get("type") or "") != "function":
            continue
        fn = it.get("function")
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        out.append({"name": name, "function": fn})
    return out


def _pick_declared_tool(tools: List[Dict[str, Any]], tool_choice: Any, user_text: str) -> str:
    names = [str((x or {}).get("name") or "") for x in (tools or [])]
    names = [n for n in names if n]
    if not names:
        return ""
    if isinstance(tool_choice, str):
        if tool_choice == "none":
            return ""
        if tool_choice == "required":
            routed = _route_tool_name(user_text)
            return routed if routed in names else names[0]
        if tool_choice == "auto":
            routed = _route_tool_name(user_text)
            return routed if routed in names else ""
    if isinstance(tool_choice, dict):
        if str(tool_choice.get("type") or "") == "function":
            fn = tool_choice.get("function")
            if isinstance(fn, dict):
                req_name = str(fn.get("name") or "").strip()
                if req_name in names:
                    return req_name
    routed = _route_tool_name(user_text)
    return routed if routed in names else ""


def _tool_args_for_name(tool_name: str, user_text: str) -> Dict[str, Any]:
    name = str(tool_name or "").strip()
    if name == "skill.memory_upsert":
        return {"text": user_text or "", "source": "gateway", "user_id": "default", "memory_type": "note", "metadata_json": "{}"}
    if name == "skill.memory_search":
        return {"query": user_text or "", "top_k": 5, "score_threshold": 0.35, "user_id": ""}
    if name == "skill.news_brief":
        return {"topic": user_text or "today", "limit": 10}
    if name == "skill.holiday_query":
        return {"mode": "next"}
    if name == "skill.finance_admin":
        return {"intent": user_text or "检查账单"}
    if name == "skill.knowledge_lookup":
        return {"query": user_text or "", "scope": ""}
    if name == "skill.music_control":
        return {"text": user_text or "", "mode": "direct"}
    return {"text": user_text or "", "mode": "local_first"}


def _dispatch_tool(tool_name: str, user_text: str) -> Dict[str, Any]:
    app_module = _load_app_module()
    name = str(tool_name or "skill.answer_question").strip()

    if name == "skill.memory_upsert":
        out = app_module.skill_memory_upsert(text=user_text or "", source="gateway", user_id="default", memory_type="note", metadata_json="{}")
        return {
            "tool": name,
            "payload": out,
            "final_text": _to_str((out or {}).get("final_text") if isinstance(out, dict) else out),
        }

    if name == "skill.memory_search":
        out = app_module.skill_memory_search(query=user_text or "", top_k=5, score_threshold=0.35, user_id="")
        return {
            "tool": name,
            "payload": out,
            "final_text": _to_str((out or {}).get("final_text") if isinstance(out, dict) else out),
        }

    if name == "skill.news_brief":
        out = app_module.skill_news_brief(topic=user_text or "today", limit=10)
        facts = out.get("facts") if isinstance(out, dict) else []
        if not isinstance(facts, list):
            facts = []
        return {
            "tool": name,
            "payload": out,
            "final_text": "；".join([str(x) for x in facts[:10]]) if facts else "暂无新闻结果。",
        }

    if name == "skill.holiday_query":
        out = app_module.skill_holiday_query(mode="next")
        return {
            "tool": name,
            "payload": out,
            "final_text": _to_str((out or {}).get("final_text") if isinstance(out, dict) else out),
        }

    if name == "skill.finance_admin":
        out = app_module.skill_finance_admin(intent=user_text or "检查账单")
        return {
            "tool": name,
            "payload": out,
            "final_text": _to_str((out or {}).get("final_text") if isinstance(out, dict) else out),
        }

    if name == "skill.knowledge_lookup":
        out = app_module.skill_knowledge_lookup(query=user_text or "", scope="")
        return {
            "tool": name,
            "payload": out,
            "final_text": _to_str((out or {}).get("final_text") if isinstance(out, dict) else out),
        }

    if name == "skill.music_control":
        out = app_module.skill_music_control(text=user_text or "", mode="direct")
        return {
            "tool": name,
            "payload": out,
            "final_text": _to_str((out or {}).get("final_text") if isinstance(out, dict) else out),
        }

    out = app_module.skill_answer_question(text=user_text or "", mode="local_first")
    return {
        "tool": "skill.answer_question",
        "payload": out,
        "final_text": _to_str((out or {}).get("final_text") if isinstance(out, dict) else out),
    }


def _openai_chat_response(model: str, content: str, request_tool: str = "") -> Dict[str, Any]:
    msg = {
        "role": "assistant",
        "content": str(content or "").strip() or "我这次没有拿到可用结果。",
    }
    if request_tool:
        msg["annotations"] = {"tool": request_tool}
    return {
        "id": _chat_id(),
        "object": "chat.completion",
        "created": _now_ts(),
        "model": str(model or "jarvis_mcp"),
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _openapi_doc() -> Dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Jarvis MCP OpenAPI Gateway",
            "version": "1.0.0",
            "description": "OpenAPI facade for calling local skill tools.",
        },
        "servers": [
            {"url": "http://192.168.1.162:19100"},
            {"url": "http://127.0.0.1:19100"},
        ],
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health check",
                    "operationId": "healthCheck",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/invoke": {
                "post": {
                    "summary": "Invoke one local skill tool",
                    "operationId": "invokeSkill",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "tool": {
                                            "type": "string",
                                            "description": "Tool name, e.g. skill.answer_question",
                                            "enum": [
                                                "skill.answer_question",
                                                "skill.memory_upsert",
                                                "skill.memory_search",
                                                "skill.news_brief",
                                                "skill.knowledge_lookup",
                                                "skill.finance_admin",
                                                "skill.holiday_query",
                                                "skill.music_control",
                                            ],
                                        },
                                        "text": {"type": "string", "description": "Primary input text"},
                                        "mode": {"type": "string", "description": "Optional mode"},
                                        "topic": {"type": "string", "description": "News topic"},
                                        "limit": {"type": "integer", "description": "News limit"},
                                        "query": {"type": "string", "description": "Knowledge query"},
                                        "scope": {"type": "string", "description": "Knowledge scope"},
                                        "intent": {"type": "string", "description": "Finance intent"},
                                        "source": {"type": "string", "description": "Memory source tag"},
                                        "user_id": {"type": "string", "description": "Memory user id"},
                                        "memory_type": {"type": "string", "description": "Memory type"},
                                        "metadata_json": {"type": "string", "description": "Memory metadata JSON object string"},
                                        "top_k": {"type": "integer", "description": "Memory search top-k"},
                                        "score_threshold": {"type": "number", "description": "Memory search score threshold"},
                                    },
                                    "required": ["tool"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Invocation result",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "tool": {"type": "string"},
                                            "final_text": {"type": "string"},
                                            "result": {"type": "object"},
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"description": "Bad request"},
                    },
                }
            },
            "/invoke/news_brief": {
                "post": {
                    "summary": "Invoke skill.news_brief",
                    "operationId": "invokeNewsBrief",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "topic": {"type": "string", "description": "News topic, default today"},
                                        "limit": {"type": "integer", "description": "News limit, default 10"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/answer_question": {
                "post": {
                    "summary": "Invoke skill.answer_question",
                    "operationId": "invokeAnswerQuestion",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "Question text"},
                                        "mode": {"type": "string", "description": "Mode, default local_first"},
                                    },
                                    "required": ["text"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/knowledge_lookup": {
                "post": {
                    "summary": "Invoke skill.knowledge_lookup",
                    "operationId": "invokeKnowledgeLookup",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string", "description": "Knowledge query"},
                                        "scope": {"type": "string", "description": "Optional scope"},
                                    },
                                    "required": ["query"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/memory_upsert": {
                "post": {
                    "summary": "Invoke skill.memory_upsert",
                    "operationId": "invokeMemoryUpsert",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "Memory text"},
                                        "source": {"type": "string", "description": "Memory source"},
                                        "user_id": {"type": "string", "description": "User id"},
                                        "memory_type": {"type": "string", "description": "Memory type"},
                                        "metadata_json": {"type": "string", "description": "JSON string metadata"},
                                    },
                                    "required": ["text"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/memory_search": {
                "post": {
                    "summary": "Invoke skill.memory_search",
                    "operationId": "invokeMemorySearch",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string", "description": "Search query"},
                                        "top_k": {"type": "integer", "description": "Top K"},
                                        "score_threshold": {"type": "number", "description": "Score threshold"},
                                        "user_id": {"type": "string", "description": "Optional user filter"},
                                    },
                                    "required": ["query"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/holiday_query": {
                "post": {
                    "summary": "Invoke skill.holiday_query",
                    "operationId": "invokeHolidayQuery",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "mode": {"type": "string", "description": "next or recent"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/finance_admin": {
                "post": {
                    "summary": "Invoke skill.finance_admin",
                    "operationId": "invokeFinanceAdmin",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "intent": {"type": "string", "description": "Finance intent"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/music_control": {
                "post": {
                    "summary": "Invoke skill.music_control",
                    "operationId": "invokeMusicControl",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "Music control text"},
                                        "mode": {"type": "string", "description": "Mode, default direct"},
                                    },
                                    "required": ["text"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/ha_execute_service": {
                "post": {
                    "summary": "Execute Home Assistant service",
                    "operationId": "haExecuteService",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "domain": {"type": "string", "description": "Service domain, e.g. light"},
                                        "service": {"type": "string", "description": "Service name, e.g. turn_on"},
                                        "service_data": {
                                            "type": "object",
                                            "description": "Service data payload",
                                            "properties": {"entity_id": {"type": "string", "description": "Entity ID"}},
                                        },
                                    },
                                    "required": ["domain", "service"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/ha_get_state": {
                "post": {
                    "summary": "Read Home Assistant state",
                    "operationId": "haGetState",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "entity_id": {"type": "string", "description": "Optional entity ID"},
                                        "name": {"type": "string", "description": "Optional fuzzy name (friendly_name/entity_id)"},
                                        "domain": {"type": "string", "description": "Domain filter: light/climate/cover/media_player/sensor"},
                                        "area": {"type": "string", "description": "Optional area filter, e.g. 客厅/卧室"},
                                        "limit": {"type": "integer", "description": "Optional list limit, max 50, default 50"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/invoke/ha_assist_context": {
                "post": {
                    "summary": "Get Home Assistant Assist conversation context",
                    "operationId": "haAssistContext",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "Prompt for conversation.process"},
                                        "language": {"type": "string", "description": "Language, default zh-CN"},
                                        "agent_id": {"type": "string", "description": "Conversation agent id"},
                                        "conversation_id": {"type": "string", "description": "Optional conversation id"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/v1/models": {
                "get": {
                    "summary": "OpenAI-compatible model list",
                    "operationId": "listModels",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/v1/chat/completions": {
                "post": {
                    "summary": "OpenAI-compatible chat completions",
                    "operationId": "chatCompletions",
                    "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }


def _openai_tool_call_response(model: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    call_id = "call_{}".format(uuid.uuid4().hex[:24])
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": str(tool_name or ""),
                    "arguments": json.dumps(arguments or {}, ensure_ascii=False),
                },
            }
        ],
    }
    return {
        "id": _chat_id(),
        "object": "chat.completion",
        "created": _now_ts(),
        "model": str(model or "jarvis_mcp"),
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _render_tool_content_as_text(raw: str) -> str:
    txt = str(raw or "").strip()
    if not txt:
        return "我这次没有拿到可用结果。"
    try:
        obj = json.loads(txt)
    except Exception:
        return txt
    if isinstance(obj, dict):
        if str(obj.get("final_text") or "").strip():
            return str(obj.get("final_text") or "").strip()
        facts = obj.get("facts")
        if isinstance(facts, list) and facts:
            return "；".join([str(x) for x in facts[:10]])
        result = obj.get("result")
        if isinstance(result, dict):
            if str(result.get("final_text") or "").strip():
                return str(result.get("final_text") or "").strip()
            facts2 = result.get("facts")
            if isinstance(facts2, list) and facts2:
                return "；".join([str(x) for x in facts2[:10]])
    return txt


async def health(_: Any):
    return JSONResponse({"ok": True, "service": "openai-compat-gateway"})


async def openapi_json(_: Any):
    return JSONResponse(_openapi_doc())


async def models(_: Any):
    model_id = os.environ.get("OPENAI_COMPAT_MODEL_ID", "jarvis_mcp")
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                    "created": _now_ts(),
                    "owned_by": "mcp-tools",
                }
            ],
        }
    )


async def chat_completions(request: Any):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": {"message": "Invalid JSON body"}}, status_code=400)

    if bool(body.get("stream")):
        return JSONResponse(
            {
                "error": {
                    "message": "stream=true is not supported in this gateway yet",
                    "type": "invalid_request_error",
                }
            },
            status_code=400,
        )

    model = str(body.get("model") or os.environ.get("OPENAI_COMPAT_MODEL_ID", "jarvis_mcp"))
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    declared_tools = _normalize_declared_tools(body.get("tools"))
    tool_choice = body.get("tool_choice")
    enable_tool_calls = str(os.environ.get("OPENAI_COMPAT_ENABLE_TOOL_CALLS") or "1").strip().lower() not in ("0", "false", "no")
    auto_execute_tools = str(os.environ.get("OPENAI_COMPAT_AUTO_EXECUTE_TOOLS") or "1").strip().lower() not in ("0", "false", "no")

    tool_content = _last_tool_content(messages)
    if tool_content:
        return JSONResponse(_openai_chat_response(model, _render_tool_content_as_text(tool_content)))

    user_text = _last_user_text(messages)
    if not user_text:
        return JSONResponse(_openai_chat_response(model, "请先给我一个问题。"))

    if enable_tool_calls and declared_tools:
        selected_tool = _pick_declared_tool(declared_tools, tool_choice, user_text)
        if selected_tool:
            arguments = _tool_args_for_name(selected_tool, user_text)
            if not auto_execute_tools:
                return JSONResponse(_openai_tool_call_response(model, selected_tool, arguments))
            try:
                tool_ret = _dispatch_tool(selected_tool, user_text)
                content2 = _to_str((tool_ret or {}).get("final_text"))
                return JSONResponse(_openai_chat_response(model, content2, request_tool=selected_tool))
            except Exception as e:
                return JSONResponse(_openai_chat_response(model, "服务暂时不可用：{}".format(str(e))))

    tool_name = _route_tool_name(user_text)
    try:
        tool_ret = _dispatch_tool(tool_name, user_text)
        content = _to_str((tool_ret or {}).get("final_text"))
        return JSONResponse(_openai_chat_response(model, content, request_tool=tool_name))
    except Exception as e:
        return JSONResponse(_openai_chat_response(model, "服务暂时不可用：{}".format(str(e))))


async def invoke(request: Any):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)

    tool = str(body.get("tool") or "").strip()
    if not tool:
        return JSONResponse({"success": False, "error": "tool is required"}, status_code=400)

    app_module = _load_app_module()
    try:
        if tool == "skill.news_brief":
            topic = str(body.get("topic") or body.get("text") or "today")
            if not topic.strip():
                topic = "today"
            limit = int(body.get("limit") or 10)
            out = app_module.skill_news_brief(topic=topic, limit=limit)
            facts = out.get("facts") if isinstance(out, dict) else []
            final_text = "；".join([str(x) for x in (facts or [])[:10]]) if isinstance(facts, list) else ""
            return JSONResponse({"success": True, "tool": tool, "final_text": final_text, "result": out})
        if tool == "skill.knowledge_lookup":
            query = str(body.get("query") or body.get("text") or "")
            scope = str(body.get("scope") or "")
            out = app_module.skill_knowledge_lookup(query=query, scope=scope)
            return JSONResponse({"success": True, "tool": tool, "final_text": _to_str((out or {}).get("final_text")), "result": out})
        if tool == "skill.memory_upsert":
            text = str(body.get("text") or "")
            source = str(body.get("source") or "gateway")
            user_id = str(body.get("user_id") or "default")
            memory_type = str(body.get("memory_type") or "note")
            metadata_json = str(body.get("metadata_json") or "{}")
            out = app_module.skill_memory_upsert(text=text, source=source, user_id=user_id, memory_type=memory_type, metadata_json=metadata_json)
            return JSONResponse({"success": True, "tool": tool, "final_text": _to_str((out or {}).get("final_text")), "result": out})
        if tool == "skill.memory_search":
            query = str(body.get("query") or body.get("text") or "")
            top_k = int(body.get("top_k") or 5)
            score_threshold = float(body.get("score_threshold") or 0.35)
            user_id = str(body.get("user_id") or "")
            out = app_module.skill_memory_search(query=query, top_k=top_k, score_threshold=score_threshold, user_id=user_id)
            return JSONResponse({"success": True, "tool": tool, "final_text": _to_str((out or {}).get("final_text")), "result": out})
        if tool == "skill.finance_admin":
            intent = str(body.get("intent") or body.get("text") or "检查账单")
            out = app_module.skill_finance_admin(intent=intent)
            return JSONResponse({"success": True, "tool": tool, "final_text": _to_str((out or {}).get("final_text")), "result": out})
        if tool == "skill.holiday_query":
            mode = str(body.get("mode") or "next")
            out = app_module.skill_holiday_query(mode=mode)
            return JSONResponse({"success": True, "tool": tool, "final_text": _to_str((out or {}).get("final_text")), "result": out})
        if tool == "skill.music_control":
            text = str(body.get("text") or "")
            mode = str(body.get("mode") or "direct")
            out = app_module.skill_music_control(text=text, mode=mode)
            return JSONResponse({"success": True, "tool": tool, "final_text": _to_str((out or {}).get("final_text")), "result": out})
        if tool == "skill.answer_question":
            text = str(body.get("text") or "")
            mode = str(body.get("mode") or "local_first")
            out = app_module.skill_answer_question(text=text, mode=mode)
            return JSONResponse({"success": True, "tool": tool, "final_text": _to_str((out or {}).get("final_text")), "result": out})
        return JSONResponse({"success": False, "error": "unsupported tool: {}".format(tool)}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "tool": tool, "error": str(e)}, status_code=500)


async def invoke_news_brief(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}
    app_module = _load_app_module()
    topic = str(body.get("topic") or "today").strip()
    if not topic:
        topic = "today"
    limit = int(body.get("limit") or 10)
    out = app_module.skill_news_brief(topic=topic, limit=limit)
    facts = out.get("facts") if isinstance(out, dict) else []
    if not isinstance(facts, list):
        facts = []
    final_text = "；".join([str(x) for x in facts[:limit if limit > 0 else 10]])
    return JSONResponse({"success": True, "tool": "skill.news_brief", "final_text": final_text, "result": out})


async def invoke_answer_question(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}
    app_module = _load_app_module()
    text = str(body.get("text") or "").strip()
    mode = str(body.get("mode") or "local_first")
    out = app_module.skill_answer_question(text=text, mode=mode)
    return JSONResponse({"success": True, "tool": "skill.answer_question", "final_text": _to_str((out or {}).get("final_text")), "result": out})


async def invoke_knowledge_lookup(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}
    app_module = _load_app_module()
    query = str(body.get("query") or "").strip()
    scope = str(body.get("scope") or "")
    out = app_module.skill_knowledge_lookup(query=query, scope=scope)
    return JSONResponse({"success": True, "tool": "skill.knowledge_lookup", "final_text": _to_str((out or {}).get("final_text")), "result": out})


async def invoke_memory_upsert(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}
    app_module = _load_app_module()
    text = str(body.get("text") or "").strip()
    source = str(body.get("source") or "gateway")
    user_id = str(body.get("user_id") or "default")
    memory_type = str(body.get("memory_type") or "note")
    metadata_json = str(body.get("metadata_json") or "{}")
    out = app_module.skill_memory_upsert(text=text, source=source, user_id=user_id, memory_type=memory_type, metadata_json=metadata_json)
    return JSONResponse({"success": True, "tool": "skill.memory_upsert", "final_text": _to_str((out or {}).get("final_text")), "result": out})


async def invoke_memory_search(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}
    app_module = _load_app_module()
    query = str(body.get("query") or "").strip()
    top_k = int(body.get("top_k") or 5)
    score_threshold = float(body.get("score_threshold") or 0.35)
    user_id = str(body.get("user_id") or "")
    out = app_module.skill_memory_search(query=query, top_k=top_k, score_threshold=score_threshold, user_id=user_id)
    return JSONResponse({"success": True, "tool": "skill.memory_search", "final_text": _to_str((out or {}).get("final_text")), "result": out})


async def invoke_holiday_query(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}
    app_module = _load_app_module()
    mode = str(body.get("mode") or "next")
    out = app_module.skill_holiday_query(mode=mode)
    return JSONResponse({"success": True, "tool": "skill.holiday_query", "final_text": _to_str((out or {}).get("final_text")), "result": out})


async def invoke_finance_admin(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}
    app_module = _load_app_module()
    intent = str(body.get("intent") or "检查账单")
    out = app_module.skill_finance_admin(intent=intent)
    return JSONResponse({"success": True, "tool": "skill.finance_admin", "final_text": _to_str((out or {}).get("final_text")), "result": out})


async def invoke_music_control(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}
    app_module = _load_app_module()
    text = str(body.get("text") or "").strip()
    mode = str(body.get("mode") or "direct")
    out = app_module.skill_music_control(text=text, mode=mode)
    return JSONResponse({"success": True, "tool": "skill.music_control", "final_text": _to_str((out or {}).get("final_text")), "result": out})


async def invoke_ha_execute_service(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}

    domain = str(body.get("domain") or "").strip().lower()
    service = str(body.get("service") or "").strip().lower()
    service_data = body.get("service_data") if isinstance(body.get("service_data"), dict) else {}
    if not domain or not service:
        return JSONResponse({"success": False, "error": "domain and service are required"}, status_code=400)

    key = "{}.{}".format(domain, service)
    if key not in _allowed_services():
        return JSONResponse({"success": False, "error": "service not allowed: {}".format(key)}, status_code=400)

    entity_id = str(service_data.get("entity_id") or "").strip()
    if entity_id and (not _is_valid_entity_id(entity_id)):
        return JSONResponse({"success": False, "error": "invalid entity_id format"}, status_code=400)

    base = _ha_base_url()
    headers = _ha_headers()
    if not base or (not headers):
        return JSONResponse({"success": False, "error": "HA_BASE_URL/HA_TOKEN is not configured"}, status_code=500)

    url = "{}/api/services/{}/{}".format(base, domain, service)
    try:
        resp = requests.post(url, headers=headers, json=service_data, timeout=_ha_timeout())
        ok = int(resp.status_code) >= 200 and int(resp.status_code) < 300
        try:
            payload = resp.json()
        except Exception:
            payload = {"text": str(resp.text or "")[:500]}
        return JSONResponse(
            {
                "success": bool(ok),
                "tool": "ha_execute_service",
                "service": key,
                "status_code": int(resp.status_code),
                "result": payload,
            },
            status_code=(200 if ok else 502),
        )
    except Exception as e:
        return JSONResponse({"success": False, "tool": "ha_execute_service", "error": str(e)}, status_code=502)


async def invoke_ha_get_state(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}

    entity_id = str(body.get("entity_id") or "").strip()
    name = str(body.get("name") or "").strip()
    domain = _normalize_domain(str(body.get("domain") or ""))
    area = str(body.get("area") or "").strip()
    limit_raw = body.get("limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else 50
    except Exception:
        limit = 50
    if limit < 1:
        limit = 1
    if limit > 50:
        limit = 50

    if entity_id and (not _is_valid_entity_id(entity_id)):
        return JSONResponse({"success": False, "error": "invalid entity_id format"}, status_code=400)
    if domain and (domain not in _ALLOWED_STATE_DOMAINS):
        return JSONResponse({"success": False, "error": "unsupported domain. allowed: {}".format(",".join(_ALLOWED_STATE_DOMAINS))}, status_code=400)

    base = _ha_base_url()
    headers = _ha_headers()
    if not base or (not headers):
        return JSONResponse({"success": False, "error": "HA_BASE_URL/HA_TOKEN is not configured"}, status_code=500)

    try:
        if entity_id:
            url = "{}/api/states/{}".format(base, entity_id)
            resp = requests.get(url, headers=headers, timeout=_ha_timeout())
            try:
                payload = resp.json()
            except Exception:
                payload = {"text": str(resp.text or "")[:500]}
            ok = int(resp.status_code) >= 200 and int(resp.status_code) < 300
            return JSONResponse(
                {"success": bool(ok), "tool": "ha_get_state", "entity_id": entity_id, "status_code": int(resp.status_code), "result": payload},
                status_code=(200 if ok else 502),
            )

        url = "{}/api/states".format(base)
        resp = requests.get(url, headers=headers, timeout=_ha_timeout())
        ok = int(resp.status_code) >= 200 and int(resp.status_code) < 300
        if not ok:
            return JSONResponse({"success": False, "tool": "ha_get_state", "status_code": int(resp.status_code), "error": str(resp.text or "")[:500]}, status_code=502)
        data = resp.json()
        rows = data if isinstance(data, list) else []
        name_norm = str(name or "").strip().lower()
        name_tokens = _name_alias_tokens(name_norm)
        area_norm = str(area or "").strip().lower()
        area_tokens = _area_alias_tokens(area_norm)
        entity_area_map = _ha_entity_area_map() if area_norm else {}
        assist_names = _ha_assist_visible_names() if (not entity_id) else []
        assist_name_keys = [_norm_match_text(x) for x in assist_names if _norm_match_text(x)]
        assist_filter_applied = bool(assist_name_keys)
        out = []
        for it in rows:
            if not isinstance(it, dict):
                continue
            eid = str(it.get("entity_id") or "")
            if not eid:
                continue
            eid_domain = eid.split(".", 1)[0]
            if eid_domain not in _ALLOWED_STATE_DOMAINS:
                continue
            if domain and (eid_domain != domain):
                continue
            attrs = it.get("attributes") if isinstance(it.get("attributes"), dict) else {}
            fname = str(attrs.get("friendly_name") or "")
            if assist_filter_applied:
                hay_visible = _norm_match_text(fname + " " + eid)
                hit_visible = False
                for k in assist_name_keys:
                    if k and (k in hay_visible):
                        hit_visible = True
                        break
                if not hit_visible:
                    continue
            if area_norm:
                mapped_area = str(entity_area_map.get(eid) or "").strip().lower()
                hay_area = (mapped_area + " " + fname + " " + eid).lower()
                hit = False
                for tk in area_tokens:
                    if str(tk or "").strip() and (str(tk).lower() in hay_area):
                        hit = True
                        break
                if not hit:
                    continue
            if name_norm:
                hay = (eid + " " + fname).lower()
                hit_name = False
                for tk in name_tokens:
                    if str(tk or "").strip() and (str(tk).lower() in hay):
                        hit_name = True
                        break
                if not hit_name:
                    continue
            out.append(
                {
                    "entity_id": eid,
                    "state": it.get("state"),
                    "friendly_name": fname,
                }
            )
            if len(out) >= limit:
                break
        return JSONResponse(
            {
                "success": True,
                "tool": "ha_get_state",
                "count": len(out),
                "result": out,
                "filters": {"domain": domain, "name": name, "area": area},
                "assist_first": {
                    "enabled": True,
                    "applied": bool(assist_filter_applied),
                    "visible_name_count": len(assist_name_keys),
                },
            }
        )
    except Exception as e:
        return JSONResponse({"success": False, "tool": "ha_get_state", "error": str(e)}, status_code=502)


async def invoke_ha_assist_context(request: Any):
    try:
        body = await request.json()
    except Exception:
        body = {}

    base = _ha_base_url()
    headers = _ha_headers()
    if not base or (not headers):
        return JSONResponse({"success": False, "error": "HA_BASE_URL/HA_TOKEN is not configured"}, status_code=500)

    text = str(body.get("text") or "请返回当前会话可见的设备与区域上下文。").strip()
    language = str(body.get("language") or "zh-CN").strip()
    agent_id = str(body.get("agent_id") or "conversation.ollama_conversation").strip()
    conversation_id = str(body.get("conversation_id") or "").strip()

    payload = {
        "agent_id": agent_id,
        "language": language,
        "text": text,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id

    url = "{}/api/conversation/process".format(base)
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=_ha_timeout())
        ok = int(resp.status_code) >= 200 and int(resp.status_code) < 300
        try:
            data = resp.json()
        except Exception:
            data = {"text": str(resp.text or "")[:2000]}
        return JSONResponse(
            {
                "success": bool(ok),
                "tool": "ha_assist_context",
                "status_code": int(resp.status_code),
                "request": {
                    "agent_id": agent_id,
                    "language": language,
                    "conversation_id": conversation_id,
                },
                "result": data,
            },
            status_code=(200 if ok else 502),
        )
    except Exception as e:
        return JSONResponse({"success": False, "tool": "ha_assist_context", "error": str(e)}, status_code=502)


async def not_found(_: Any, __: Exception):
    return PlainTextResponse("Not Found", status_code=404)


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/openapi.json", openapi_json, methods=["GET"]),
        Route("/invoke", invoke, methods=["POST"]),
        Route("/invoke/news_brief", invoke_news_brief, methods=["POST"]),
        Route("/invoke/answer_question", invoke_answer_question, methods=["POST"]),
        Route("/invoke/knowledge_lookup", invoke_knowledge_lookup, methods=["POST"]),
        Route("/invoke/memory_upsert", invoke_memory_upsert, methods=["POST"]),
        Route("/invoke/memory_search", invoke_memory_search, methods=["POST"]),
        Route("/invoke/holiday_query", invoke_holiday_query, methods=["POST"]),
        Route("/invoke/finance_admin", invoke_finance_admin, methods=["POST"]),
        Route("/invoke/music_control", invoke_music_control, methods=["POST"]),
        Route("/invoke/ha_execute_service", invoke_ha_execute_service, methods=["POST"]),
        Route("/invoke/ha_get_state", invoke_ha_get_state, methods=["POST"]),
        Route("/invoke/ha_assist_context", invoke_ha_assist_context, methods=["POST"]),
        Route("/v1/models", models, methods=["GET"]),
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
    ],
    exception_handlers={404: not_found},
)


if __name__ == "__main__":
    import uvicorn

    host = str(os.environ.get("HOST") or "0.0.0.0")
    port = int(os.environ.get("PORT") or "19100")
    uvicorn.run(app, host=host, port=port)
