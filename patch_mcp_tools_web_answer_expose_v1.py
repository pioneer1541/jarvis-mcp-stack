import io
import re
import sys
from datetime import datetime

PATH = "app.py"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

src = read_text(PATH)

# 0) 备份
bak = PATH + ".bak." + datetime.now().strftime("%Y%m%d-%H%M%S")
write_text(bak, src)

# 1) 移除过早创建 SSE app 的块（后面会重新加到文件末尾）
#    目标块通常长这样：
#    app = mcp.sse_app()
#    if os.environ.get("MCP_LOCAL_DEV") == "1":
#        import uvicorn
#        uvicorn.run(...)
pattern_app_block = re.compile(
    r"\napp\s*=\s*mcp\.sse_app\(\)\n"
    r"(?:\n|.)*?"
    r"\nif\s+os\.environ\.get\(\s*[\"']MCP_LOCAL_DEV[\"']\s*\)\s*==\s*[\"']1[\"']\s*:\n"
    r"(?:\n|.)*?"
    r"\n\s*uvicorn\.run\((?:\n|.)*?\)\n",
    re.MULTILINE
)

m = pattern_app_block.search(src)
app_block = None
if m:
    app_block = m.group(0)
    src = src[:m.start()] + "\n\n" + src[m.end():]

# 2) 把 web_answer 变成 MCP tool：去掉 async，添加 @mcp.tool
#    并让它使用参数 categories/language/time_range，而不是写死 auto
#    以及保证 max_sources 默认 3
if "def web_answer(" not in src and "async def web_answer(" not in src:
    print("ERR: cannot find web_answer definition in app.py", file=sys.stderr)
    sys.exit(2)

# 2.1 把 `async def web_answer(` 改成装饰器 + `def web_answer(`
#     若已打过补丁，避免重复加装饰器
if "mcp.tool" not in src or "@mcp.tool" not in src:
    src = src.replace(
        "async def web_answer(",
        '@mcp.tool(description="Search the web and extract key info (voice-friendly).")\n'
        "def web_answer("
    )
else:
    # 已有装饰器则只保证是 sync def
    src = src.replace("async def web_answer(", "def web_answer(")

# 2.2 在 web_answer 参数里补上 categories/language/time_range（如果还没有）
#     简单做法：如果签名里没有 categories，就插入
sig_pat = re.compile(r"def web_answer\(\n(?P<body>(?:.|\n)*?)\n\)\s*->\s*dict\s*:", re.MULTILINE)
m2 = sig_pat.search(src)
if not m2:
    print("ERR: cannot locate web_answer signature block", file=sys.stderr)
    sys.exit(3)

sig_body = m2.group("body")
if "categories:" not in sig_body:
    # 在 max_sources 之后插入
    sig_body = sig_body.replace(
        "max_sources: int = 3,",
        "max_sources: int = 3,\n"
        "    categories: str = \"general\",\n"
        "    language: str = \"zh-CN\",\n"
        "    time_range: str = \"\","
    )
    src = src[:m2.start("body")] + sig_body + src[m2.end("body"):]

# 2.3 把 web_answer 内部对 web_search 的调用从写死 auto 改为使用参数
src = src.replace(
    "sr = web_search(q, k=max_sources, categories=\"auto\", language=\"auto\", time_range=\"\")",
    "sr = web_search(q, k=int(max_sources), categories=str(categories or \"general\"), language=str(language or \"zh-CN\"), time_range=str(time_range or \"\"))"
)

# 3) 修正 legacy defaults 那段可能把 categories 传错的隐患（若存在该行）
src = src.replace(
    "cat_used = _mcp__auto_categories(q, \"zh-CN\")",
    "cat_used = _mcp__auto_categories(q, categories)"
)

# 4) 重新在文件末尾创建 SSE app（确保包含 web_answer）
#    如果之前没找到 app_block，就用一段标准块
if app_block is None:
    app_block = "\napp = mcp.sse_app()\n\nif os.environ.get(\"MCP_LOCAL_DEV\") == \"1\":\n    import uvicorn\n    uvicorn.run(app, host=\"0.0.0.0\", port=int(os.environ.get(\"PORT\", \"8000\")))\n"

# 防止重复追加
if "app = mcp.sse_app()" not in src:
    src = src.rstrip() + "\n\n" + app_block.lstrip()

write_text(PATH, src)
print("OK: patch applied. Backup:", bak)
