# patch_fix_entrypoint_only_v1.py
# -*- coding: utf-8 -*-

import os

APP = "app.py"


def main():
    with open(APP, "r", encoding="utf-8") as f:
        s = f.read()

    # 已经有入口就不动
    if "__name__" in s and "== \"__main__\"" in s:
        print("already_has_entrypoint=1")
        return

    entry = r"""

# --- MCP_ENTRYPOINT_V1 BEGIN ---
def _mcp_http_serve():
    # Keep defaults aligned with docker-compose port mapping
    host = (os.environ.get("MCP_HOST") or "0.0.0.0").strip()
    try:
        port = int((os.environ.get("MCP_PORT") or "19090").strip())
    except Exception:
        port = 19090

    # Prefer streamable-http for Home Assistant MCP integration
    transport = (os.environ.get("MCP_TRANSPORT") or "streamable-http").strip().lower()
    mount_path = (os.environ.get("MCP_MOUNT_PATH") or "/mcp").strip()

    # 1) Try FastMCP built-in runner if available
    try:
        # Some versions accept host/port/mount_path
        try:
            mcp.run(transport=transport, host=host, port=port, mount_path=mount_path)
            return
        except TypeError:
            pass

        # Some versions only accept transport
        mcp.run(transport=transport)
        return
    except Exception:
        pass

    # 2) Fallback: build Starlette ASGI app and run uvicorn
    asgi_app = None
    try:
        from mcp.server.http import create_streamable_http_app, create_sse_app  # type: ignore
    except Exception:
        try:
            from fastmcp.server.http import create_streamable_http_app, create_sse_app  # type: ignore
        except Exception:
            create_streamable_http_app = None
            create_sse_app = None

    if transport in ("streamable-http", "streamable_http", "streamablehttp"):
        if create_streamable_http_app is None:
            raise RuntimeError("No HTTP app builder available for streamable-http transport")
        asgi_app = create_streamable_http_app(server=mcp, streamable_http_path=mount_path)
    else:
        if create_sse_app is None:
            raise RuntimeError("No HTTP app builder available for SSE transport")
        # SSE needs two paths: one for connect, one for messages
        sse_path = mount_path
        msg_path = mount_path.rstrip("/") + "/message"
        asgi_app = create_sse_app(server=mcp, message_path=msg_path, sse_path=sse_path)

    import uvicorn  # local import
    uvicorn.run(asgi_app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    _mcp_http_serve()
# --- MCP_ENTRYPOINT_V1 END ---
"""

    # 确保文件末尾有换行再追加
    if not s.endswith("\n"):
        s = s + "\n"
    s2 = s + entry

    with open(APP, "w", encoding="utf-8") as f:
        f.write(s2)

    print("patched_ok=1")
    print("appended_entrypoint=1")


if __name__ == "__main__":
    main()
