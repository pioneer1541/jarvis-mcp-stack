import re

P = "app.py"
s = open(P, "r", encoding="utf-8").read()

# 1) 确保存在一个“无前缀”的 open_url_extract 工具
#    你的文件里可能已经有 open_url_extract，但它可能被注册成带前缀名；
#    为避免撞名，我们只在“没有 @mcp.tool 装饰的 open_url_extract”时，改名为 impl 并补一个 tool。
need_shim = False

m_def = re.search(r"(?m)^\s*def\s+open_url_extract\s*\(", s)
if m_def:
    # 看看 def open_url_extract 前面几行是否有 @mcp.tool
    start = max(0, m_def.start() - 400)
    ctx = s[start:m_def.start()]
    if "@mcp.tool" not in ctx:
        # 这通常是 helper 函数，不是 tool；我们把它改名为 open_url_extract_impl，然后补一个 tool 版 open_url_extract
        s = re.sub(r"(?m)^\s*def\s+open_url_extract\s*\(",
                   "def open_url_extract_impl(",
                   s, count=1)
        need_shim = True
else:
    # 文件里根本没有 open_url_extract，就补一个 shim（优先复用 open_url / open_url_impl）
    need_shim = True

if need_shim:
    shim = r'''

# ---- open_url_extract (unprefixed tool for HA) ----
@mcp.tool(description="Open a URL and return a short extracted excerpt.")
def open_url_extract(url: str, max_chars: int = 4000, timeout_sec: int = 10) -> dict:
    fn = globals().get("open_url")
    if fn is not None:
        return fn(url=url, max_chars=max_chars, timeout_sec=timeout_sec)

    fn2 = globals().get("open_url_extract_impl")
    if fn2 is not None:
        return fn2(url=url, max_chars=max_chars, timeout_sec=timeout_sec)

    raise NameError("open_url/open_url_extract_impl is not defined")
'''
    # 插到 if __name__ == "__main__" 前
    mm = re.search(r'(?m)^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*$',
                   s)
    if not mm:
        raise SystemExit("cannot find __main__ block to insert shim")
    s = s[:mm.start()] + shim + s[mm.start():]

# 2) 启动时清理所有以 "mcp-hello__" 开头的工具名（避免 HA 双前缀）
#    这段会尽量兼容不同 FastMCP 内部字段结构
prune = r'''

def _prune_prefixed_tools(mcp_obj, prefix):
    # Find internal tool dict
    tool_dict = None
    for attr in ["_tools", "tools", "_tool_manager", "tool_manager", "_tool_registry", "_registry"]:
        if hasattr(mcp_obj, attr):
            v = getattr(mcp_obj, attr)
            if isinstance(v, dict):
                tool_dict = v
                break
            for sub in ["_tools", "tools", "registry", "_registry"]:
                if hasattr(v, sub):
                    vv = getattr(v, sub)
                    if isinstance(vv, dict):
                        tool_dict = vv
                        break
        if tool_dict is not None:
            break

    if tool_dict is None:
        return

    keys = list(tool_dict.keys())
    removed = []
    for k in keys:
        if isinstance(k, str) and k.startswith(prefix):
            removed.append(k)
            try:
                del tool_dict[k]
            except Exception:
                pass

    if removed:
        try:
            print("[mcp-hello] pruned_prefixed_tools =", removed)
        except Exception:
            pass

# prune once at import time
try:
    _prune_prefixed_tools(mcp, "mcp-hello__")
except Exception as _e:
    try:
        print("[mcp-hello] prune_error =", str(_e))
    except Exception:
        pass
'''
if "_prune_prefixed_tools" not in s:
    # 插到 if __name__ == "__main__" 前
    mm = re.search(r'(?m)^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*$',
                   s)
    if not mm:
        raise SystemExit("cannot find __main__ block to insert prune")
    s = s[:mm.start()] + prune + s[mm.start():]

open(P, "w", encoding="utf-8").write(s)
print("patched: shim open_url_extract + prune prefixed tools")
