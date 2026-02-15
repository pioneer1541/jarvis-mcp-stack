import re
import os


def music_default_player() -> str:
    return (
        os.environ.get("HA_DEFAULT_MEDIA_PLAYER_ENTITY")
        or os.environ.get("HA_DEFAULT_MEDIA_PLAYER")
        or "media_player.living_room_speaker_2"
    )


def music_load_aliases() -> dict:
    raw = str(os.environ.get("HA_MEDIA_PLAYER_ALIASES") or "").strip()
    m = {}
    if not raw:
        return m
    parts = raw.split(",")
    for p in parts:
        p = str(p or "").strip()
        if (not p) or (":" not in p):
            continue
        k, v = p.split(":", 1)
        k = str(k or "").strip().lower()
        v = str(v or "").strip()
        if k and v:
            m[k] = v
    return m


def music_extract_target_entity(user_text: str) -> str:
    t = str(user_text or "")
    m = re.search(r"(media_player\.[a-zA-Z0-9_]+)", t)
    if m:
        return str(m.group(1) or "").strip()
    aliases = music_load_aliases()
    if aliases:
        tl = t.strip().lower()
        keys = sorted(list(aliases.keys()), key=lambda x: len(x), reverse=True)
        for k in keys:
            if k and (k in tl):
                v = aliases.get(k) or ""
                v = str(v).strip()
                if v:
                    return v
    return music_default_player()


def is_music_control_query(user_text: str) -> bool:
    t = str(user_text or "").strip().lower()
    if not t:
        return False

    room_or_player_words = [
        "卧室", "客厅", "主卧", "游戏室", "车库", "厨房", "音箱", "电视", "speaker", "tv", "media player"
    ]
    music_ctx_words = [
        "音乐", "听歌", "歌曲", "歌", "一首", "一曲", "歌单", "playlist", "spotify", "radio", "白噪音", "专辑"
    ]
    play_verbs = [
        "播放", "播", "放", "听", "来一首", "放一首", "放首", "来首", "来点", "放点",
        "play", "listen"
    ]

    keys = [
        "播放", "继续", "暂停", "停一下", "停止", "下一首", "下一曲", "上一首", "上一曲",
        "音量", "静音", "取消静音",
        "mute", "unmute", "pause", "resume", "play", "stop", "next", "previous",
        "我想听", "我想要听", "来一首", "放一首", "来点", "来首", "放首", "放点", "听歌", "听音乐", "放音乐", "播音乐", "播一下"
    ]
    for k in keys:
        if k in t:
            return True

    try:
        if re.search(r"想.{0,10}听", t):
            return True
    except Exception:
        pass

    if "听" in t:
        for w in ["歌", "音乐", "歌曲", "曲", "一首", "一曲", "播放", "来", "放"]:
            if w in t:
                return True

    has_verb = False
    for v in play_verbs:
        if v in t:
            has_verb = True
            break
    if has_verb:
        for w in music_ctx_words:
            if w in t:
                return True
        for w in room_or_player_words:
            if w in t:
                return True

    if "media_player." in t:
        return True

    return False


def music_parse_volume(user_text: str):
    t = str(user_text or "").strip().lower()
    if not t:
        return None
    has_volume_intent = (
        ("音量" in t) or ("volume" in t) or ("vol" in t)
        or ("调到" in t) or ("调成" in t) or ("设置到" in t)
        or ("set to" in t) or ("调至" in t)
    )
    m = re.search(r"(音量|volume|vol|调到|调成|设置到|set to|调至)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(%?)", t)
    if m:
        num = m.group(2)
        pct = m.group(3)
        try:
            v = float(num)
        except Exception:
            v = None
        if v is None:
            return None
        if (pct == "%") and has_volume_intent:
            v = v / 100.0
        else:
            if has_volume_intent and (v > 1.0):
                v = v / 100.0
            elif not has_volume_intent:
                return None
        if v < 0.0:
            v = 0.0
        if v > 1.0:
            v = 1.0
        return v
    if "一半" in t:
        return 0.5
    if "最大" in t:
        return 1.0
    if "最小" in t:
        return 0.0
    return None


def music_volume_step_default() -> float:
    v = str(os.environ.get("MUSIC_VOLUME_STEP") or "0.1").strip()
    try:
        f = float(v)
    except Exception:
        f = 0.1
    if f <= 0.0:
        f = 0.1
    if f > 1.0:
        f = 1.0
    return f


def music_parse_volume_delta(user_text: str):
    t = str(user_text or "").strip().lower()
    if not t:
        return None

    m = re.search(r"(加|提高|增大|增|大)\s*(\d{1,3})\s*%", t)
    if m:
        try:
            dv = float(m.group(2)) / 100.0
        except Exception:
            dv = None
        if dv is None:
            return None
        return abs(dv)

    m = re.search(r"(减|降低|减小|小)\s*(\d{1,3})\s*%", t)
    if m:
        try:
            dv = float(m.group(2)) / 100.0
        except Exception:
            dv = None
        if dv is None:
            return None
        return -abs(dv)

    up_keys = ["大一点", "大点", "调大", "提高音量", "声音大一点", " louder", "turn up", "volume up", "up "]
    down_keys = ["小一点", "小点", "调小", "降低音量", "声音小一点", " quieter", "turn down", "volume down", "down "]

    step = music_volume_step_default()

    for k in up_keys:
        if k.strip() and (k.strip() in t):
            return step
    for k in down_keys:
        if k.strip() and (k.strip() in t):
            return -step

    if ("调大" in t) or ("提高" in t) or ("增大" in t):
        return step
    if ("调小" in t) or ("降低" in t) or ("减小" in t):
        return -step

    return None


def music_control_core(text: str, mode: str, h) -> dict:
    q = str(text or "").strip()
    md = str(mode or "direct").strip().lower()
    if not q:
        return h["skill_result"](
            "请告诉我要执行的播放指令。",
            facts=[],
            sources=[],
            next_actions=[h["skill_next_action_item"]("ask_user", "例如：在卧室播放周杰伦。", {})],
            meta={"skill": "music_control", "mode": md},
        )
    if not is_music_control_query(q):
        return h["skill_result"](
            "这不是明确的音乐控制指令。你可以说“播放音乐”或“音量调到30%”。",
            facts=[],
            sources=[],
            next_actions=[h["skill_next_action_item"]("ask_user", "例如：在卧室播放周杰伦。", {})],
            meta={"skill": "music_control", "mode": md, "route": "not_music_intent"},
        )
    raw = h["route_request_impl"](text=q, language=h["skill_detect_lang"](q, "zh"), llm_allow=False)
    final = ""
    route_type = ""
    if isinstance(raw, dict):
        final = str(raw.get("final") or "").strip()
        route_type = str(raw.get("route_type") or "").strip()
    if not final:
        final = "音乐控制执行失败，请重试。"
    return h["skill_result"](
        final,
        facts=[],
        sources=[],
        next_actions=[],
        meta={"skill": "music_control", "mode": md, "route_type": route_type},
    )


def route_music_request(user_text: str, h) -> dict:
    ent = h["music_extract_target_entity"](user_text)
    if not ent:
        return {"ok": True, "route_type": "structured_music", "final": "未配置默认播放器。请在容器环境变量中设置 HA_DEFAULT_MEDIA_PLAYER（例如 media_player.living_room）。"}

    t0 = str(user_text or "").strip().lower()
    if ("取消静音" in t0) or ("unmute" in t0):
        try:
            ent = h["music_apply_aliases"](user_text, ent)
        except Exception:
            pass
        r = h["ha_call_service"]("media_player", "volume_mute", service_data={"entity_id": ent, "is_volume_muted": False}, timeout_sec=10)
        if isinstance(r, dict) and r.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已取消静音。"}
        rr = h["music_soft_mute"](ent, do_unmute=True)
        if isinstance(rr, dict) and rr.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已取消静音。"}
        return {"ok": True, "route_type": "structured_music", "final": "当前播放器不支持静音。"}

    if ("静音" in t0) or ("mute" in t0):
        r = h["ha_call_service"]("media_player", "volume_mute", service_data={"entity_id": ent, "is_volume_muted": True}, timeout_sec=10)
        if isinstance(r, dict) and r.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已静音。"}
        rr = h["music_soft_mute"](ent, do_unmute=False)
        if isinstance(rr, dict) and rr.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已静音。"}
        return {"ok": True, "route_type": "structured_music", "final": "当前播放器不支持静音。"}

    t00 = str(user_text or "").strip().lower()
    is_up = False
    is_dn = False
    for _k in ["大一点", "大声", "大声点", "调大", "提高音量", "louder", "volume up", "turn up"]:
        if _k in t00:
            is_up = True
            break
    for _k in ["小一点", "小声", "小声点", "调小", "降低音量", "quieter", "volume down", "turn down"]:
        if _k in t00:
            is_dn = True
            break
    if is_up or is_dn:
        cur = h["music_get_volume_level"](ent)
        if cur is None:
            cur = h["music_unmute_default"]()
        step_s = str(h["env_get"]("MUSIC_VOLUME_STEP", "0.05") or "0.05").strip()
        try:
            step = float(step_s)
        except Exception:
            step = 0.05
        if step <= 0.0:
            step = 0.05
        if step > 0.5:
            step = 0.5
        target = cur + (step if is_up else (-step))
        if target < 0.0:
            target = 0.0
        if target > 1.0:
            target = 1.0
        r = h["ha_call_service"]("media_player", "volume_set", service_data={"entity_id": ent, "volume_level": float(target)}, timeout_sec=10)
        if isinstance(r, dict) and r.get("ok"):
            pct = int(round(float(target) * 100.0))
            return {"ok": True, "route_type": "structured_music", "final": "已设置音量为 {0}%。".format(pct)}
        return {"ok": True, "route_type": "structured_music", "final": "调整音量失败。"}

    vol = h["music_parse_volume"](user_text)
    if vol is not None:
        try:
            vol = float(vol)
        except Exception:
            vol = None
        if vol is None:
            return {"ok": True, "route_type": "structured_music", "final": "设置音量失败。"}
        if vol < 0.0:
            vol = 0.0
        if vol > 1.0:
            vol = 1.0
        r = h["ha_call_service"]("media_player", "volume_set", service_data={"entity_id": ent, "volume_level": vol}, timeout_sec=10)
        if isinstance(r, dict) and r.get("ok"):
            pct = int(round(float(vol) * 100.0))
            return {"ok": True, "route_type": "structured_music", "final": "已设置音量为 {0}%。".format(pct)}
        cur = h["music_get_volume_level"](ent)
        if cur is None:
            cur = h["music_unmute_default"]()
        try:
            cur = float(cur)
        except Exception:
            cur = h["music_unmute_default"]()
        direction = "up" if float(vol) > float(cur) else "down"
        steps = int(round(abs(float(vol) - float(cur)) / 0.05))
        if steps < 1:
            steps = 1
        if steps > 10:
            steps = 10
        rr = h["music_try_volume_updown"](ent, direction=direction, steps=steps)
        if isinstance(rr, dict) and rr.get("ok"):
            if direction == "up":
                return {"ok": True, "route_type": "structured_music", "final": "已调高音量。"}
            return {"ok": True, "route_type": "structured_music", "final": "已调低音量。"}
        sc = ""
        if isinstance(r, dict) and ("status_code" in r):
            sc = "（HTTP {0}）".format(r.get("status_code"))
        return {"ok": True, "route_type": "structured_music", "final": "设置音量失败{0}。".format(sc)}

    dvol = h["music_parse_volume_delta"](user_text)
    if dvol is not None:
        try:
            dvol = float(dvol)
        except Exception:
            dvol = None
        if dvol is None:
            return {"ok": True, "route_type": "structured_music", "final": "调整音量失败。"}
        cur = h["music_get_volume_level"](ent)
        if cur is None:
            cur = h["music_unmute_default"]()
        try:
            cur = float(cur)
        except Exception:
            cur = h["music_unmute_default"]()
        nv = cur + dvol
        if nv < 0.0:
            nv = 0.0
        if nv > 1.0:
            nv = 1.0
        r = h["ha_call_service"]("media_player", "volume_set", service_data={"entity_id": ent, "volume_level": nv}, timeout_sec=10)
        if isinstance(r, dict) and r.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已调整音量。"}
        rr = h["music_try_volume_updown"](ent, direction=("up" if dvol > 0 else "down"), steps=1)
        if isinstance(rr, dict) and rr.get("ok"):
            if dvol > 0:
                return {"ok": True, "route_type": "structured_music", "final": "已调高音量。"}
            return {"ok": True, "route_type": "structured_music", "final": "已调低音量。"}
        sc = ""
        if isinstance(r, dict) and ("status_code" in r):
            sc = "（HTTP {0}）".format(r.get("status_code"))
        return {"ok": True, "route_type": "structured_music", "final": "调整音量失败{0}。".format(sc)}

    if ("下一首" in t0) or ("下一曲" in t0) or ("next" in t0):
        r = h["ha_call_service"]("media_player", "media_next_track", service_data={"entity_id": ent}, timeout_sec=10)
        if r.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已切到下一首。"}
        return {"ok": True, "route_type": "structured_music", "final": "切歌失败。"}
    if ("上一首" in t0) or ("上一曲" in t0) or ("previous" in t0) or ("prev" in t0):
        r = h["ha_call_service"]("media_player", "media_previous_track", service_data={"entity_id": ent}, timeout_sec=10)
        if r.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已切到上一首。"}
        return {"ok": True, "route_type": "structured_music", "final": "切歌失败。"}
    if ("暂停" in t0) or ("pause" in t0) or ("停一下" in t0):
        r = h["ha_call_service"]("media_player", "media_pause", service_data={"entity_id": ent}, timeout_sec=10)
        if r.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已暂停。"}
        return {"ok": True, "route_type": "structured_music", "final": "暂停失败。"}
    if ("停止" in t0) or ("stop" in t0):
        r = h["ha_call_service"]("media_player", "media_stop", service_data={"entity_id": ent}, timeout_sec=10)
        if r.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已停止播放。"}
        return {"ok": True, "route_type": "structured_music", "final": "停止失败。"}

    if ("播放" in t0) or ("继续" in t0) or ("play" in t0) or ("resume" in t0) or True:
        if ("播放" in t0) or ("我想听" in t0) or ("我想要听" in t0) or ("来一首" in t0) or ("放一首" in t0) or ("来点" in t0) or (t0.strip().startswith("play")):
            q = t0
            _i_play = (t0 or "").rfind("播放")
            _i_listen = (t0 or "").rfind("听")
            _i = _i_play if _i_play > _i_listen else _i_listen
            if _i >= 0:
                _off = 1
                try:
                    if (_i_play >= 0) and (_i == _i_play):
                        _off = 2
                except Exception:
                    pass
                q = (t0 or "")[_i + _off:].strip()
            for _kw in ["开始播放", "播放一下", "帮我放", "我想听", "我想要听", "来一首", "放一首", "来点", "播放", "play", "resume"]:
                q = q.replace(_kw, " ")
            q = q.strip().strip("，。,.!?！？\"“”'")
            if q:
                artist = ""
                name = q
                if "的" in q:
                    _p = q.split("的", 1)
                    artist = (_p[0] or "").strip()
                    name = (_p[1] or "").strip() or q.strip()
                media_type = "track"
                svc = {"entity_id": ent, "media_id": name, "media_type": media_type, "enqueue": "replace"}
                if artist:
                    svc["artist"] = artist
                if ("的歌" in (t0 or "")) or ("的歌曲" in (t0 or "")):
                    svc["media_type"] = "artist"
                    svc["media_id"] = artist or name
                    svc["radio_mode"] = True
                try:
                    ent = h["music_apply_aliases"](user_text, ent)
                except Exception:
                    pass
                rr = h["ha_call_service"]("music_assistant", "play_media", service_data=svc, timeout_sec=25)
                if isinstance(rr, dict) and rr.get("ok"):
                    return {"ok": True, "route_type": "structured_music", "final": "已开始播放。"}
        r = h["ha_call_service"]("media_player", "media_play", service_data={"entity_id": ent}, timeout_sec=10)
        if r.get("ok"):
            return {"ok": True, "route_type": "structured_music", "final": "已开始播放。"}
        return {"ok": True, "route_type": "structured_music", "final": "播放失败。"}
