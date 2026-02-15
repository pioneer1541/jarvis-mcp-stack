import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()

# 把： (if rt == "structured_calendar"):
# 修成： if rt == "structured_calendar":
s2, n = re.subn(
    r'(?m)^([ \t]*)\(\s*if\s+rt\s*==\s*["\']structured_calendar["\']\s*\)\s*:\s*$',
    r'\1if rt == "structured_calendar":',
    s,
)

if n == 0:
    raise RuntimeError("no match: cannot find '(if rt == \"structured_calendar\"):' line to fix")
open(p, "w", encoding="utf-8").write(s2)
print("fixed_ok=1", "replaced=", n)
