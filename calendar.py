import importlib.util
import os
import sys
import sysconfig
import re
from datetime import datetime, timedelta, date as dt_date


def _load_std_calendar_module():
    stdlib_dir = sysconfig.get_paths().get("stdlib") or ""
    cal_path = os.path.join(stdlib_dir, "calendar.py")
    mod_name = "_stdlib_calendar"
    spec = importlib.util.spec_from_file_location(mod_name, cal_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


_STD_CALENDAR = _load_std_calendar_module()
if _STD_CALENDAR is not None:
    for _name in dir(_STD_CALENDAR):
        if _name.startswith("__"):
            continue
        if _name in globals():
            continue
        globals()[_name] = getattr(_STD_CALENDAR, _name)


def is_calendar_create_intent(text: str) -> bool:
    t = str(text or "").strip()
    tl = t.lower()
    keys = ["提醒我", "帮我安排", "创建日程", "创建提醒", "添加日程", "add event", "create reminder", "remind me"]
    return any(k in t for k in keys if not k.isascii()) or any(k in tl for k in keys if k.isascii())


def calendar_capability_hint_text(action: str, caps: dict) -> str:
    action_s = str(action or "").strip().lower()
    if action_s == "delete":
        ok = bool(caps.get("calendar_delete_event") or caps.get("google_delete_event"))
        if ok:
            return "delete_event 服务已存在。"
        return "当前未发现 delete/remove_event 服务。"
    if action_s == "update":
        ok = bool(caps.get("calendar_update_event") or caps.get("google_update_event"))
        if ok:
            return "update_event 服务已存在。"
        return "当前未发现 update/edit_event 服务。"
    return "请检查 calendar/google 的事件服务能力。"


def calendar_event_id_candidates(ev: dict) -> dict:
    out = {}
    if not isinstance(ev, dict):
        return out
    for k in ["uid", "event_id", "id", "recurrence_id"]:
        v = str(ev.get(k) or "").strip()
        if v:
            out[k] = v
    return out


def calendar_parse_update_target_window(text: str, ev: dict, now_local, h) -> tuple:
    t = str(text or "").strip()
    now_dt = now_local if now_local is not None else datetime.now()
    old_start = h["calendar_event_start_dt"](ev)
    old_end = None
    if isinstance(ev, dict):
        en = ev.get("end") or {}
        if isinstance(en, dict):
            old_end = h["dt_from_iso"](en.get("dateTime") or en.get("datetime"))
    if old_start is None:
        old_start = now_dt
    if old_end is None:
        old_end = old_start + timedelta(minutes=30)

    base_date = dt_date(old_start.year, old_start.month, old_start.day)
    date_offset = 0
    if ("大后天" in t) or ("大後天" in t):
        date_offset = 3
    elif ("后天" in t) or ("後天" in t):
        date_offset = 2
    elif "明天" in t:
        date_offset = 1
    elif ("今天" in t) or ("今日" in t):
        date_offset = 0

    hh = int(old_start.hour)
    mm = int(old_start.minute)
    time_found = False
    m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})", t)
    if m:
        try:
            hh = int(m.group(1))
            mm = int(m.group(2))
            time_found = True
        except Exception:
            pass
    else:
        m2 = re.search(r"(\d{1,2})\s*点\s*(半|[0-5]?\d\s*分?)?", t)
        if m2:
            try:
                hh = int(m2.group(1))
                time_found = True
            except Exception:
                pass
            tail = str(m2.group(2) or "").strip()
            if "半" in tail:
                mm = 30
            else:
                m3 = re.search(r"([0-5]?\d)", tail)
                if m3:
                    try:
                        mm = int(m3.group(1))
                    except Exception:
                        pass
    if ("下午" in t) or ("晚上" in t):
        if hh < 12:
            hh = hh + 12
    if "中午" in t and hh < 11:
        hh = hh + 12
    if hh < 0 or hh > 23:
        hh = int(old_start.hour)
    if mm < 0 or mm > 59:
        mm = int(old_start.minute)

    try:
        d2 = base_date + timedelta(days=int(date_offset))
    except Exception:
        d2 = base_date
    tz = h["tzinfo"]()
    if tz:
        ns = datetime(d2.year, d2.month, d2.day, hh, mm, 0, tzinfo=tz)
    else:
        ns = datetime(d2.year, d2.month, d2.day, hh, mm, 0)
    duration = old_end - old_start
    if (not isinstance(duration, timedelta)) or (int(duration.total_seconds()) <= 0):
        duration = timedelta(minutes=30)
    ne = ns + duration
    return ns.strftime("%Y-%m-%d %H:%M:%S"), ne.strftime("%Y-%m-%d %H:%M:%S"), bool(time_found or (date_offset != 0))


def calendar_service_call_variants(domain: str, services: list, payloads: list, h) -> dict:
    for svc in (services or []):
        if not h["bills_service_exists"](domain, svc):
            continue
        for p in (payloads or []):
            try:
                data = dict(p or {})
            except Exception:
                data = {}
            rr = h["ha_call_service"](domain, svc, service_data=data, timeout_sec=12)
            if rr.get("ok"):
                return {"ok": True, "service": domain + "." + svc}
    return {"ok": False}


def calendar_ha_event_delete(entity_id: str, ev: dict, h) -> dict:
    eid = str(entity_id or "").strip()
    ids = calendar_event_id_candidates(ev)
    payloads = []
    if eid:
        payloads.append({"entity_id": eid})
    for _, v in ids.items():
        payloads.append({"entity_id": eid, "uid": v})
        payloads.append({"entity_id": eid, "event_id": v})
        payloads.append({"entity_id": eid, "id": v})
    r1 = calendar_service_call_variants("calendar", ["delete_event", "remove_event"], payloads, h)
    if r1.get("ok"):
        return r1
    r2 = calendar_service_call_variants("google", ["delete_event", "remove_event"], payloads, h)
    if r2.get("ok"):
        return r2
    return {"ok": False, "error": "delete_event_service_missing_or_failed", "message": "未找到或无法执行 delete/remove_event 服务"}


def calendar_ha_event_update(entity_id: str, ev: dict, text: str, now_local, h) -> dict:
    eid = str(entity_id or "").strip()
    ids = calendar_event_id_candidates(ev)
    summary = h["calendar_event_summary"](ev)
    desc = str((ev.get("description") if isinstance(ev, dict) else "") or "").strip()
    ns, ne, changed = calendar_parse_update_target_window(text, ev, now_local=now_local, h=h)
    if not changed:
        return {"ok": False, "error": "update_time_not_found", "message": "未识别到新的时间信息"}
    payloads = []
    base = {"entity_id": eid, "summary": summary, "description": desc, "start_date_time": ns, "end_date_time": ne}
    payloads.append(base)
    for _, v in ids.items():
        p1 = dict(base)
        p1["uid"] = v
        payloads.append(p1)
        p2 = dict(base)
        p2["event_id"] = v
        payloads.append(p2)
        p3 = dict(base)
        p3["id"] = v
        payloads.append(p3)
    r1 = calendar_service_call_variants("calendar", ["update_event", "edit_event"], payloads, h)
    if r1.get("ok"):
        r1["start"] = ns
        return r1
    r2 = calendar_service_call_variants("google", ["update_event", "edit_event"], payloads, h)
    if r2.get("ok"):
        r2["start"] = ns
        return r2
    return {"ok": False, "error": "update_event_service_missing_or_failed", "message": "未找到或无法执行 update/edit_event 服务"}


def route_calendar_request(user_text: str, route_return_data: bool, h) -> dict:
    cal = str(h["env_get"]("HA_DEFAULT_CALENDAR_ENTITY", "") or "").strip()
    if not cal:
        return {"ok": True, "route_type": "structured_calendar", "final": "未配置默认日历实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY。", "error": "missing_default_calendar_entity"}
    cals = h["calendar_entities_for_query"](cal)
    if not cals:
        cals = [cal]
    tzinfo = h["tzinfo"]()
    now = h["now_local"]()
    base_d = dt_date(now.year, now.month, now.day)

    if h["calendar_is_delete_intent"](user_text) or h["calendar_is_update_intent"](user_text):
        q_mut = h["calendar_range_from_text"](user_text, now_local=now)
        td_mut = q_mut.get("target_date")
        if not isinstance(td_mut, dt_date):
            td_mut = None
        if isinstance(td_mut, dt_date):
            s_iso_mut, e_iso_mut = h["iso_day_start_end"](td_mut, tzinfo)
        else:
            try:
                end_d_mut = base_d + timedelta(days=14)
            except Exception:
                end_d_mut = base_d
            s_iso_mut, _ = h["iso_day_start_end"](base_d, tzinfo)
            e_iso_mut, _ = h["iso_day_start_end"](end_d_mut, tzinfo)
        ev_mut, errs_mut = h["calendar_fetch_merged_events"](cals, s_iso_mut, e_iso_mut)
        if len(ev_mut) == 0:
            if len(errs_mut) == len(cals):
                rr0 = errs_mut[0] if errs_mut else {"ok": False}
                return {"ok": True, "route_type": "structured_calendar", "final": "我现在联网查询失败了，请稍后再试。", "data": rr0}
            return {"ok": True, "route_type": "structured_calendar", "final": "没有找到可操作的日程。"}
        pick = h["calendar_pick_event_for_text"](ev_mut, user_text, td_mut)
        if not isinstance(pick, dict):
            names = []
            for it in ev_mut[:3]:
                sm = h["calendar_event_summary"](it)
                if sm:
                    names.append(sm)
            if names:
                return {
                    "ok": True,
                    "route_type": "structured_calendar",
                    "final": "我找到多条候选日程，请补充标题关键词。候选包括：" + "；".join(names) + "。",
                }
            return {"ok": True, "route_type": "structured_calendar", "final": "我没法唯一定位要操作的日程，请补充标题关键词。"}

        op_entity = str(pick.get("__entity_id") or cal).strip() or cal
        summary_pick = h["calendar_event_summary"](pick)

        if h["calendar_is_delete_intent"](user_text):
            dr = h["calendar_ha_event_delete"](op_entity, pick)
            if dr.get("ok"):
                return {"ok": True, "route_type": "structured_calendar", "final": "已为你删除日程：" + (summary_pick if summary_pick else "该事件") + "。"}
            msg_d = str(dr.get("message") or dr.get("error") or "未知错误")
            if len(msg_d) > 80:
                msg_d = msg_d[:80]
            return {"ok": True, "route_type": "structured_calendar", "final": "删除日程失败：" + msg_d + "。请检查 calendar/google 的 delete_event 服务。"}

        ur = h["calendar_ha_event_update"](op_entity, pick, user_text, now_local=now)
        if ur.get("ok"):
            st_txt = str(ur.get("start") or "")[:16]
            return {"ok": True, "route_type": "structured_calendar", "final": "已为你修改日程：" + (summary_pick if summary_pick else "该事件") + "（新时间 " + st_txt + "）。"}
        msg_u = str(ur.get("message") or ur.get("error") or "未知错误")
        if len(msg_u) > 80:
            msg_u = msg_u[:80]
        return {"ok": True, "route_type": "structured_calendar", "final": "修改日程失败：" + msg_u + "。请检查 calendar/google 的 update_event 服务。"}

    if h["calendar_is_create_intent"](user_text):
        evt = h["calendar_build_create_event"](user_text, now_local=now)
        if not evt.get("ok"):
            return {"ok": True, "route_type": "structured_calendar", "final": "我没听清提醒时间。你可以说：提醒我明天上午十点开会。"}
        summary = str(evt.get("summary") or "事项提醒")
        start_dt = str(evt.get("start_date_time") or "")
        end_dt = str(evt.get("end_date_time") or "")
        desc = "由语音提醒创建：" + str(user_text or "")
        create_cal = str(h["bills_calendar_entity_id"]() or cal).strip()
        if not create_cal:
            create_cal = cal
        cr = h["bills_ha_event_create"](create_cal, summary, desc, start_dt, end_dt)
        if cr.get("ok"):
            return {"ok": True, "route_type": "structured_calendar", "final": "已为你添加日程：" + summary + "（" + start_dt[:16] + "）。"}
        msg = str(cr.get("message") or cr.get("error") or "未知错误")
        if len(msg) > 80:
            msg = msg[:80]
        return {"ok": True, "route_type": "structured_calendar", "final": "添加日程失败：" + msg + "。请检查 calendar.create_event 服务是否可用。"}

    q = h["calendar_range_from_text"](user_text, now_local=now)
    mode = q.get("mode") or "single"
    label = str((q.get("label") or "")).strip()
    if mode == "range":
        start_d = q.get("start_date")
        end_d = q.get("end_date")
        if not isinstance(start_d, dt_date):
            start_d = base_d
        if isinstance(end_d, dt_date):
            try:
                end_excl = end_d + timedelta(days=1)
            except Exception:
                end_excl = end_d
            s_iso, _ = h["iso_day_start_end"](start_d, tzinfo)
            e_iso, _ = h["iso_day_start_end"](end_excl, tzinfo)
        else:
            days_i = h["safe_int"](q.get("days"), 3)
            if days_i < 1:
                days_i = 1
            if days_i > 14:
                days_i = 14
            try:
                end_excl_d = start_d + timedelta(days=days_i)
            except Exception:
                end_excl_d = start_d
            s_iso, _ = h["iso_day_start_end"](start_d, tzinfo)
            e_iso, _ = h["iso_day_start_end"](end_excl_d, tzinfo)
        ev, errs = h["calendar_fetch_merged_events"](cals, s_iso, e_iso)
        if len(ev) == 0 and len(errs) == len(cals):
            rr = errs[0] if errs else {"ok": False}
            return {"ok": True, "route_type": "structured_calendar", "final": "我现在联网查询失败了，请稍后再试。", "data": rr}
        head = (label + "有 " + str(len(ev)) + " 条日程：" if label else "共有 " + str(len(ev)) + " 条日程：")
        final = head + h["summarise_calendar_events"](ev)
        ret = {"ok": True, "route_type": "structured_calendar", "final": final}
        if route_return_data:
            ret["data"] = {"ok": True, "data": ev, "errors": errs}
            ret["range"] = {"start": s_iso, "end": e_iso}
        return ret

    td = q.get("target_date")
    if not isinstance(td, dt_date):
        off = h["safe_int"](q.get("offset"), 0)
        try:
            td = base_d + timedelta(days=off)
        except Exception:
            td = base_d
    s_iso, e_iso = h["iso_day_start_end"](td, tzinfo)
    ev, errs = h["calendar_fetch_merged_events"](cals, s_iso, e_iso)
    if len(ev) == 0 and len(errs) == len(cals):
        rr = errs[0] if errs else {"ok": False}
        return {"ok": True, "route_type": "structured_calendar", "final": "我现在联网查询失败了，请稍后再试。", "data": rr}
    if len(ev) == 0:
        final = (label + "没有日程。" if label else "没有日程。")
    else:
        final = (label + "有 " + str(len(ev)) + " 条日程：" if label else "有 " + str(len(ev)) + " 条日程：") + h["summarise_calendar_events"](ev)
    ret = {"ok": True, "route_type": "structured_calendar", "final": final}
    if route_return_data:
        ret["data"] = {"ok": True, "data": ev, "errors": errs}
        ret["range"] = {"start": s_iso, "end": e_iso}
    return ret
