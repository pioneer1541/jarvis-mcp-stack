import os
import sys

def read_lines(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().splitlines(True)

def write_lines(path, lines):
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def find_func_block(lines, func_name):
    start = -1
    for i, ln in enumerate(lines):
        if ln.startswith("def " + func_name + "("):
            start = i
            break
    if start < 0:
        return (-1, -1)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("def "):
            end = j
            break
    return (start, end)

def patch_next_ndays_exclude_today(lines):
    s, e = find_func_block(lines, "_weather_range_from_text")
    if s < 0:
        return (lines, False)

    changed = False
    for i in range(s, e):
        ln = lines[i]
        if "out[\"start_date\"] = start_d" in ln:
            pass

        if 'return {"mode": "range", "days": int(n), "label": m.group(1) + str(n) + "天"}' in ln:
            indent = ln[:len(ln) - len(ln.lstrip())]
            block = []
            block.append(indent + "start_d = None\n")
            block.append(indent + "try:\n")
            block.append(indent + "    from datetime import timedelta as _td\n")
            block.append(indent + "    if now_d is not None:\n")
            block.append(indent + "        start_d = now_d + _td(days=1)\n")
            block.append(indent + "except Exception:\n")
            block.append(indent + "    start_d = None\n")
            block.append(indent + "out = {\"mode\": \"range\", \"days\": int(n), \"label\": m.group(1) + str(n) + \"天\"}\n")
            block.append(indent + "if start_d is not None:\n")
            block.append(indent + "    out[\"start_date\"] = start_d\n")
            block.append(indent + "return out\n")
            lines = lines[:i] + block + lines[i+1:]
            changed = True
            break

    return (lines, changed)

def insert_guard_before_line(lines, func_name, needle_line_startswith, guard_lines, marker):
    s, e = find_func_block(lines, func_name)
    if s < 0:
        return (lines, False)

    for i in range(s, e):
        if marker in lines[i]:
            return (lines, False)

    for i in range(s, e):
        ln = lines[i]
        if ln.lstrip().startswith(needle_line_startswith):
            indent = ln[:len(ln) - len(ln.lstrip())]
            block = []
            for gl in guard_lines:
                block.append(indent + gl + "\n")
            lines = lines[:i] + block + lines[i:]
            return (lines, True)

    return (lines, False)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    if not os.path.exists(path):
        print("ERROR: file not found:", path)
        sys.exit(2)

    lines = read_lines(path)

    # A) “接下来/未来N天”从明天开始（不含今天）
    lines, ok_a = patch_next_ndays_exclude_today(lines)

    # B) weather.get_forecasts 前先检查实体存在，避免 HA 500
    weather_guard = [
        "",
        "# Guard: avoid HA 500 when entity_id is missing (service return_response expects a matching entity)",
        "st = ha_get_state(eid, timeout_sec=int(timeout_sec))",
        "if not st.get(\"ok\"):",
        "    return {\"ok\": False, \"status_code\": st.get(\"status_code\", 404), \"error\": \"entity_missing\", \"entity_id\": eid, \"data\": st.get(\"data\")}",
    ]
    lines, ok_b = insert_guard_before_line(
        lines,
        "ha_weather_forecast",
        "body = {\"entity_id\": eid, \"type\": ftype}",
        weather_guard,
        "Guard: avoid HA 500 when entity_id is missing"
    )

    # C) calendar events 前先检查实体存在（更清晰的错误）
    cal_guard = [
        "",
        "# Guard: return a clean error if calendar entity is missing",
        "st = ha_get_state(eid, timeout_sec=int(timeout_sec))",
        "if not st.get(\"ok\"):",
        "    return {\"ok\": False, \"status_code\": st.get(\"status_code\", 404), \"error\": \"entity_missing\", \"entity_id\": eid, \"data\": st.get(\"data\")}",
    ]
    lines, ok_c = insert_guard_before_line(
        lines,
        "ha_calendar_events",
        "s = str(start or \"\").strip()",
        cal_guard,
        "Guard: return a clean error if calendar entity is missing"
    )

    write_lines(path, lines)
    print("Patched: next_ndays_exclude_today=%s weather_entity_guard=%s calendar_entity_guard=%s" % (ok_a, ok_b, ok_c))

if __name__ == "__main__":
    main()
