import io
import os
import re

APP = "app.py"

def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write(path, s):
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)

def main():
    src = _read(APP)

    # -----------------------------
    # 1) Add ha_list_calendars tool (if not present)
    # -----------------------------
    if "def ha_list_calendars(" not in src:
        anchor = "@mcp.tool(description=\"(Structured) List events for a HA calendar entity."
        idx = src.find(anchor)
        if idx < 0:
            raise RuntimeError("Cannot find anchor for ha_calendar_events tool block.")
        # insert before ha_calendar_events tool
        ins = []
        ins.append("@mcp.tool(description=\"(Structured) List available HA calendars (entity_id + name).\")\n")
        ins.append("def ha_list_calendars(timeout_sec: int = 12) -> dict:\n")
        ins.append("    return _ha_request(\"GET\", \"/api/calendars\", timeout_sec=int(timeout_sec))\n\n\n")
        src = src[:idx] + "".join(ins) + src[idx:]

    # -----------------------------
    # 2) Fix _holiday_next_from_list + add _holiday_prev_from_list
    # -----------------------------
    pat = r"def _holiday_next_from_list\\(items: list, today_ymd: str\\) -> dict:\\n(?s).*?return out\\n"
    m = re.search(pat, src)
    if not m:
        raise RuntimeError("Cannot find _holiday_next_from_list block to replace.")

    new_block = []
    new_block.append("def _holiday_next_from_list(items: list, today_ymd: str) -> dict:\n")
    new_block.append("    \"\"\"\n")
    new_block.append("    items: [{\"date\":\"YYYY-MM-DD\",\"name\":\"...\"}]\n")
    new_block.append("    today_ymd: \"YYYY-MM-DD\"\n")
    new_block.append("    return {\"ok\":True,\"date\":...,\"name\":...,\"days\":int} or {\"ok\":False}\n")
    new_block.append("    \"\"\"\n\n")
    new_block.append("    try:\n")
    new_block.append("        y = int(today_ymd[0:4]); mo = int(today_ymd[5:7]); da = int(today_ymd[8:10])\n")
    new_block.append("        today = dt_date(y, mo, da)\n")
    new_block.append("    except Exception:\n")
    new_block.append("        return {\"ok\": False}\n\n")
    new_block.append("    best = None\n")
    new_block.append("    best_d = None\n")
    new_block.append("    for x in items or []:\n")
    new_block.append("        if not isinstance(x, dict):\n")
    new_block.append("            continue\n")
    new_block.append("        ds = str(x.get(\"date\") or \"\").strip()\n")
    new_block.append("        nm = str(x.get(\"name\") or \"\").strip()\n")
    new_block.append("        if len(ds) != 10:\n")
    new_block.append("            continue\n")
    new_block.append("        try:\n")
    new_block.append("            yy = int(ds[0:4]); mm = int(ds[5:7]); dd = int(ds[8:10])\n")
    new_block.append("            d = dt_date(yy, mm, dd)\n")
    new_block.append("        except Exception:\n")
    new_block.append("            continue\n")
    new_block.append("        if d < today:\n")
    new_block.append("            continue\n")
    new_block.append("        if (best_d is None) or (d < best_d):\n")
    new_block.append("            best_d = d\n")
    new_block.append("            best = {\"date\": ds, \"name\": nm}\n")
    new_block.append("    if not best or (best_d is None):\n")
    new_block.append("        return {\"ok\": False}\n\n")
    new_block.append("    try:\n")
    new_block.append("        days = (best_d - today).days\n")
    new_block.append("    except Exception:\n")
    new_block.append("        days = None\n\n")
    new_block.append("    out = {\"ok\": True, \"date\": best.get(\"date\"), \"name\": best.get(\"name\")}\n")
    new_block.append("    if isinstance(days, int):\n")
    new_block.append("        out[\"days\"] = days\n")
    new_block.append("    return out\n\n")
    new_block.append("def _holiday_prev_from_list(items: list, today_ymd: str) -> dict:\n")
    new_block.append("    \"\"\"\n")
    new_block.append("    Nearest past (including today): latest date <= today.\n")
    new_block.append("    return {\"ok\":True,\"date\":...,\"name\":...,\"days_ago\":int} or {\"ok\":False}\n")
    new_block.append("    \"\"\"\n\n")
    new_block.append("    try:\n")
    new_block.append("        y = int(today_ymd[0:4]); mo = int(today_ymd[5:7]); da = int(today_ymd[8:10])\n")
    new_block.append("        today = dt_date(y, mo, da)\n")
    new_block.append("    except Exception:\n")
    new_block.append("        return {\"ok\": False}\n\n")
    new_block.append("    best = None\n")
    new_block.append("    best_d = None\n")
    new_block.append("    for x in items or []:\n")
    new_block.append("        if not isinstance(x, dict):\n")
    new_block.append("            continue\n")
    new_block.append("        ds = str(x.get(\"date\") or \"\").strip()\n")
    new_block.append("        nm = str(x.get(\"name\") or \"\").strip()\n")
    new_block.append("        if len(ds) != 10:\n")
    new_block.append("            continue\n")
    new_block.append("        try:\n")
    new_block.append("            yy = int(ds[0:4]); mm = int(ds[5:7]); dd = int(ds[8:10])\n")
    new_block.append("            d = dt_date(yy, mm, dd)\n")
    new_block.append("        except Exception:\n")
    new_block.append("            continue\n")
    new_block.append("        if d > today:\n")
    new_block.append("            continue\n")
    new_block.append("        if (best_d is None) or (d > best_d):\n")
    new_block.append("            best_d = d\n")
    new_block.append("            best = {\"date\": ds, \"name\": nm}\n")
    new_block.append("    if not best or (best_d is None):\n")
    new_block.append("        return {\"ok\": False}\n\n")
    new_block.append("    try:\n")
    new_block.append("        days_ago = (today - best_d).days\n")
    new_block.append("    except Exception:\n")
    new_block.append("        days_ago = None\n\n")
    new_block.append("    out = {\"ok\": True, \"date\": best.get(\"date\"), \"name\": best.get(\"name\")}\n")
    new_block.append("    if isinstance(days_ago, int):\n")
    new_block.append("        out[\"days_ago\"] = days_ago\n")
    new_block.append("    return out\n")

    src = src[:m.start()] + "".join(new_block) + src[m.end():]

    # -----------------------------
    # 3) Upgrade route_request holiday branch: next/prev handling
    # -----------------------------
    pat2 = r"# holiday\\n\\s*if _is_holiday_query\\(user_text\\):\\n(?s).*?return \\{\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": \"已获取维州公众假期（AU-VIC），年份 \" \\+ str\\(y\\) \\+ \"，共 \" \\+ str\\(len\\(items\\)\\) \\+ \" 天。\", \"data\": rr\\}\\n"
    m2 = re.search(pat2, src)
    if not m2:
        raise RuntimeError("Cannot find route_request holiday branch to replace.")

    rb = []
    rb.append("# holiday\n")
    rb.append("    if _is_holiday_query(user_text):\n")
    rb.append("        m = re.search(r\"(20\\d{2})\", user_text)\n")
    rb.append("        y = None\n")
    rb.append("        if m:\n")
    rb.append("            try:\n")
    rb.append("                y = int(m.group(1))\n")
    rb.append("            except Exception:\n")
    rb.append("                y = None\n")
    rb.append("        now = _now_local()\n")
    rb.append("        if y is None:\n")
    rb.append("            try:\n")
    rb.append("                y = int(getattr(now, \"year\"))\n")
    rb.append("            except Exception:\n")
    rb.append("                y = 2026\n")
    rb.append("        rr = holiday_vic(y)\n")
    rb.append("        if not rr.get(\"ok\"):\n")
    rb.append("            return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": \"假期查询失败。\", \"data\": rr}\n")
    rb.append("        items = rr.get(\"holidays\") or []\n")
    rb.append("        today_d = dt_date(now.year, now.month, now.day)\n")
    rb.append("        today_s = str(today_d)\n")
    rb.append("\n")
    rb.append("        t = str(user_text or \"\")\n")
    rb.append("        want_next = (\"下一个\" in t) or (\"下個\" in t) or (\"next\" in t.lower())\n")
    rb.append("        want_recent = (\"最近\" in t) or (\"上一个\" in t) or (\"上個\" in t) or (\"刚刚\" in t) or (\"剛剛\" in t)\n")
    rb.append("\n")
    rb.append("        if want_next:\n")
    rb.append("            nx = _holiday_next_from_list(items, today_s)\n")
    rb.append("            if not nx.get(\"ok\"):\n")
    rb.append("                final = \"未找到下一个维州公众假期。\"\n")
    rb.append("                return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": final, \"data\": rr}\n")
    rb.append("            days = nx.get(\"days\")\n")
    rb.append("            if isinstance(days, int):\n")
    rb.append("                final = \"下一个维州公众假期：\" + str(nx.get(\"name\") or \"\") + \"（\" + str(nx.get(\"date\") or \"\") + \"，\" + str(days) + \" 天后）\"\n")
    rb.append("            else:\n")
    rb.append("                final = \"下一个维州公众假期：\" + str(nx.get(\"name\") or \"\") + \"（\" + str(nx.get(\"date\") or \"\") + \"）\"\n")
    rb.append("            return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": final, \"data\": rr, \"next\": nx}\n")
    rb.append("\n")
    rb.append("        if want_recent:\n")
    rb.append("            pv = _holiday_prev_from_list(items, today_s)\n")
    rb.append("            if not pv.get(\"ok\"):\n")
    rb.append("                final = \"未找到最近的维州公众假期。\"\n")
    rb.append("                return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": final, \"data\": rr}\n")
    rb.append("            da = pv.get(\"days_ago\")\n")
    rb.append("            if isinstance(da, int):\n")
    rb.append("                final = \"最近的维州公众假期：\" + str(pv.get(\"name\") or \"\") + \"（\" + str(pv.get(\"date\") or \"\") + \"，\" + str(da) + \" 天前）\"\n")
    rb.append("            else:\n")
    rb.append("                final = \"最近的维州公众假期：\" + str(pv.get(\"name\") or \"\") + \"（\" + str(pv.get(\"date\") or \"\") + \"）\"\n")
    rb.append("            return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": final, \"data\": rr, \"recent\": pv}\n")
    rb.append("\n")
    rb.append("        # default: year summary (keep deterministic)\n")
    rb.append("        return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": \"已获取维州公众假期（AU-VIC），年份 \" + str(y) + \"，共 \" + str(len(items)) + \" 天。\", \"data\": rr}\n")

    src = src[:m2.start()] + "".join(rb) + src[m2.end():]

    _write(APP, src)
    print("OK: patched", APP)

if __name__ == "__main__":
    main()
