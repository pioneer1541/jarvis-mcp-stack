# patch_fix_restart_exit0_v1.py
# -*- coding: utf-8 -*-
import hashlib

def sha256_text(t):
    return hashlib.sha256(t.encode("utf-8", errors="ignore")).hexdigest()

def main():
    path = "app.py"
    s = open(path, "r", encoding="utf-8").read()

    mark = 'if __name__ == "__main__":'
    i = s.find(mark)
    if i < 0:
        raise RuntimeError("cannot find __main__ block")

    # keep everything before __main__
    head = s[:i].rstrip() + "\n\n"

    new_tail = r'''if __name__ == "__main__":
    host = os.environ.get("HOST") or "0.0.0.0"
    port = _safe_int(os.environ.get("PORT") or os.environ.get("MCP_PORT") or "19090", 19090)

    # In Docker/HA MCP Server usage, we want an HTTP(SSE/ASGI) server.
    # Do NOT call mcp.run() here (it may default to STDIO and exit cleanly in containers).
    asgi = _build_asgi_app_from_mcp()
    if asgi is None:
        raise RuntimeError("Cannot build ASGI app from FastMCP. FastMCP API mismatch.")

    import uvicorn
    uvicorn.run(asgi, host=host, port=port)
'''

    out = head + new_tail

    bak = "app.py.bak.fix_restart_exit0_v1"
    open(bak, "w", encoding="utf-8").write(s)
    open(path, "w", encoding="utf-8").write(out)

    print("patched_ok=1")
    print("backup=" + bak)
    print("sha256_before=" + sha256_text(s))
    print("sha256_after=" + sha256_text(out))

if __name__ == "__main__":
    main()
