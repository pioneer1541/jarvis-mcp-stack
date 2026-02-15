import re

P = "app.py"
s = open(P, "r", encoding="utf-8").read()

mark_v1 = r"# --- MCP_TOOL_PREFIX_ALIASES_V1 ---"
mark_v2 = r"# --- MCP_TOOL_PREFIX_ALIASES_V2 ---"

# 找 if __name__ 位置
m_main = re.search(r'^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*$', s, re.M)
if not m_main:
    raise SystemExit("cannot find __main__ block")

insert_pos = m_main.start()

# 如果已有 V2，就不重复打
if mark_v2 in s:
    print("already patched v2")
    raise SystemExit(0)

# 如果有 V1 块：删除 V1 块到 __main__ 之前的内容（只删我们加的那段）
if mark_v1 in s:
    # 从 V1 marker 开始，到 __main__ 前结束
    pat = r"(?s)" + re.escape(mark_v1) + r".*?(?=^\s*if\s+__name__\s*==\s*[\"']__main__[\"']\s*:)"
    s2, n = re.subn(pat, "", s, flags=re.M)
    if n > 0:
        s = s2
        # 重新计算 __main__ 位置
        m_main = re.search(r'^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*$', s, re.M)
        if not m_main:
            raise SystemExit("cannot find __main__ block after removing v1")
        insert_pos = m_main.start()

block = r'''
{mark}
# HA MCP client will namespace tool names as "<entry>__<tool>".
# If the model already includes the prefix, HA may add it again -> double prefix.
# We register aliases for: base, 1x prefix, 2x prefix.
import importlib

_MCP_TOOL_PREFIX = os.getenv("MCP_TOOL_PREFIX", "mcp-hello").strip()

def _alias_names(base_name: str):
    names = [base_name]
    if _MCP_TOOL_PREFIX:
        names.append(_MCP_TOOL_PREFIX + "__" + base_name)
        names.append(_MCP_TOOL_PREFIX + "__" + _MCP_TOOL_PREFIX + "__" + base_name)
    # 去重但保持顺序
    out = []
    for n in names:
        if n not in out:
            out.append(n)
    return out

def _resolve_fn(fn_name: str):
    # resolve at runtime to avoid import order / scope issues
    mod = importlib.import_module(__name__)
    fn = getattr(mod, fn_name, None)
    if fn is None:
        raise NameError(fn_name + " is not defined")
    return fn

# ---- open_url_extract aliases ----
for _n in _alias_names("open_url_extract"):
    if _n == "open_url_extract":
        continue

    @mcp.tool(name=_n, description="Alias of open_url_extract (compat for HA tool name prefixing).")
    def _open_url_extract_alias(url: str, max_chars: int = 4000, timeout_sec: int = 10) -> dict:
        fn = _resolve_fn("open_url_extract")
        return fn(url=url, max_chars=max_chars, timeout_sec=timeout_sec)

# ---- web_search aliases ----
for _n in _alias_names("web_search"):
    if _n == "web_search":
        continue

    @mcp.tool(name=_n, description="Alias of web_search (compat for HA tool name prefixing).")
    def _web_search_alias(query: str, max_results: int = 5, timeout_sec: int = 15) -> dict:
        fn = _resolve_fn("web_search")
        return fn(query=query, max_results=max_results, timeout_sec=timeout_sec)

# ---- tools_selfcheck aliases ----
for _n in _alias_names("tools_selfcheck"):
    if _n == "tools_selfcheck":
        continue

    @mcp.tool(name=_n, description="Alias of tools_selfcheck (compat for HA tool name prefixing).")
    def _tools_selfcheck_alias() -> dict:
        fn = _resolve_fn("tools_selfcheck")
        return fn()
'''.format(mark=mark_v2)

s = s[:insert_pos] + block + "\n" + s[insert_pos:]
open(P, "w", encoding="utf-8").write(s)
print("patched v2")
