import re

P = "app.py"
s = open(P, "r", encoding="utf-8").read()

# 如果已经有 open_url_extract 工具/函数，就不重复加
if re.search(r"^\s*def\s+open_url_extract\s*\(", s, re.M):
    print("open_url_extract function already exists; no patch needed")
    raise SystemExit(0)

# 找一个稳的插入点：在 tools_selfcheck 定义之后插入（通常都在 tool 区域里）
m = re.search(r"^\s*def\s+tools_selfcheck\s*\([^)]*\)\s*->\s*dict\s*:\s*$", s, re.M)
if not m:
    # 兜底：插在 if __name__ == "__main__" 前
    m = re.search(r'^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*$', s, re.M)
    if not m:
        raise SystemExit("cannot find insertion point (tools_selfcheck or __main__)")

# 插入在 tools_selfcheck 函数块结束后：简单做法是在 tools_selfcheck 的 return 结束后插入
# 先尝试定位 tools_selfcheck 函数的结束：找到其下一段以 "def " 或 "@mcp.tool" 或 "if __name__" 开头的行
if "def tools_selfcheck" in s:
    # 从 tools_selfcheck 起点开始，找下一段顶层定义
    start = m.start()
    rest = s[start:]
    m2 = re.search(r"(?m)^\s*(?:@mcp\.tool|def\s+\w+|if\s+__name__)\b", rest)
    # m2 会匹配到 tools_selfcheck 自己，因此找第二个匹配
    it = list(re.finditer(r"(?m)^\s*(?:@mcp\.tool|def\s+\w+|if\s+__name__)\b", rest))
    if len(it) >= 2:
        insert_pos = start + it[1].start()
    else:
        insert_pos = start + len(rest)
else:
    insert_pos = m.start()

block = r'''

# ---- open_url_extract (compat shim) ----
# Some clients/LLMs call "open_url_extract". If you already have "open_url",
# provide open_url_extract as a stable alias that returns the same shape.
@mcp.tool(description="Open a URL and return a short extracted excerpt (compat name: open_url_extract).")
def open_url_extract(url: str, max_chars: int = 4000, timeout_sec: int = 10) -> dict:
    # Reuse existing open_url tool/function if present; otherwise reuse open_url_extract(url...) below.
    fn = globals().get("open_url")
    if fn is None:
        # If open_url does not exist, fall back to open_url_extract_impl if present
        fn2 = globals().get("open_url_extract_impl")
        if fn2 is None:
            raise NameError("open_url is not defined and no fallback exists")
        return fn2(url=url, max_chars=max_chars, timeout_sec=timeout_sec)
    return fn(url=url, max_chars=max_chars, timeout_sec=timeout_sec)
'''

s2 = s[:insert_pos] + block + s[insert_pos:]
open(P, "w", encoding="utf-8").write(s2)
print("patched: added open_url_extract")
