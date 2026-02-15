import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# 已经暴露过就直接退出
if re.search(r"(?m)^@mcp\.tool\(.*\)\s*\ndef\s+route_request\(", s):
    print("patched_ok=1 (already exposed)")
    raise SystemExit(0)

m = re.search(r"(?m)^def\s+route_request\(", s)
if not m:
    raise RuntimeError("cannot find def route_request(")

insert = '@mcp.tool(description="(Router) Route user text into structured/local tools (weather/calendar/holiday/state). Return {route_type, final, data}. Use this first for any user input.")\n'
s2 = s[:m.start()] + insert + s[m.start():]

open(p, "w", encoding="utf-8").write(s2)
print("patched_ok=1")
