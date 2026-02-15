import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# 1) 插入一个 helper：_holiday_next_from_list(items, today)
# 放在 holiday_vic() 之后（锚点稳定：def holiday_vic(...)）
m = re.search(r"(?ms)^def holiday_vic\([^\)]*\) -> dict:\n.*?\n(?=^\S|\Z)", s)
if not m:
    raise RuntimeError("cannot find holiday_vic() block")

insert_pos = m.end()

helper = r'''

def _holiday_next_from_list(items: list, today_ymd: str) -> dict:
    """
    items: [{"date":"YYYY-MM-DD","name":"..."}]
    today_ymd: "YYYY-MM-DD"
    return {"ok":True,"date":...,"name":...,"days":int} or {"ok":False}
    """
    try:
        from datetime import date as _date
    except Exception:
        return {"ok": False}

    try:
        y = int(today_ymd[0:4]); mo = int(today_ymd[5:7]); da = int(today_ymd[8:10])
        today = _date(y, mo, da)
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
            d = _date(yy, mm, dd)
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

'''
s = s[:insert_pos] + helper + s[insert_pos:]

# 2) 修改 route_request() 里的 structured_holiday 分支口播：
# - 若用户问“下一个/最近/下一次/下次/next/coming”等，输出 next holiday
# - 否则保持原样
# 用“if rt == "structured_holiday":”作为锚点，替换该分支内的 final 生成部分（只替换一小段）
pat = r'(?ms)^( {4}if rt == "structured_holiday":\n)(.*?)(\n {4}if rt == "structured_calendar":)'
m2 = re.search(pat, s)
if not m2:
    raise RuntimeError("cannot find structured_holiday branch before structured_calendar in route_request")

head = m2.group(1)
body = m2.group(2)
tail = m2.group(3)

# 在 holiday 分支里，我们保留你现有调用 holiday_vic(year) 的逻辑，只“重写 final 文案”部分。
# 用一个较稳的方式：找到 return {"ok": True, "route_type": rt, "final": ...} 这一段并替换 final 生成。

# 如果你原先 holiday 分支结构有差异，我们就整体覆盖 body 为一个确定正确的版本（仍只在分支内部，不影响其他分支）。
new_body = r'''        # try parse year from text; default to current year
        y = None
        try:
            m = re.search(r"(19\d{2}|20\d{2})", user_text or "")
            if m:
                y = int(m.group(1))
        except Exception:
            y = None
        if y is None:
            try:
                y = int(_now_local().year)
            except Exception:
                y = int(datetime.now().year)

        r = holiday_vic(y)
        if not r.get("ok"):
            return {"ok": True, "route_type": rt, "final": "无法获取维州公众假期。", "data": r}

        items = r.get("holidays") or []
        if not isinstance(items, list):
            items = []

        # decide whether user is asking "next holiday"
        t = (user_text or "").strip().lower()
        ask_next = False
        for kw in ["下一个", "下次", "最近", "下一次", "next", "coming", "upcoming", "soon"]:
            if kw in t:
                ask_next = True
                break

        if ask_next:
            today_ymd = ""
            try:
                today_ymd = _now_local().date().isoformat()
            except Exception:
                today_ymd = str(datetime.now().date())

            nx = _holiday_next_from_list(items, today_ymd)
            if nx.get("ok"):
                nm = str(nx.get("name") or "").strip()
                ds = str(nx.get("date") or "").strip()
                days = nx.get("days")
                if isinstance(days, int):
                    if days == 0:
                        final = "今天就是维州公众假期：" + nm + "（" + ds + "）。"
                    else:
                        final = "下一个维州公众假期是 " + nm + "，" + ds + "（距离今天 " + str(days) + " 天）。"
                else:
                    final = "下一个维州公众假期是 " + nm + "，" + ds + "。"
                return {"ok": True, "route_type": rt, "final": final, "data": r}
            # fallback if cannot compute
            return {"ok": True, "route_type": rt, "final": "已获取维州公众假期（AU-VIC），年份 " + str(r.get("year")) + "。", "data": r}

        # default summary for year list query
        try:
            cnt = len(items)
        except Exception:
            cnt = 0
        final = "已获取维州公众假期（AU-VIC），年份 " + str(r.get("year")) + "，共 " + str(cnt) + " 天。"
        return {"ok": True, "route_type": rt, "final": final, "data": r}'''

s = s[:m2.start()] + head + new_body + tail + s[m2.end():]

if s == orig:
    raise RuntimeError("no changes applied")

open(p, "w", encoding="utf-8").write(s)
print("patched_ok=1")
