#!/usr/bin/env python3
import os
import sys
import json
import subprocess


def _load_capabilities():
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if root not in sys.path:
            sys.path.insert(0, root)
        import app
        return app.skill_capabilities()
    except Exception as e:
        err_local = str(e)
    try:
        cmd = [
            "docker",
            "exec",
            "-i",
            "mcp-hello",
            "python",
            "-c",
            "import app, json; print(json.dumps(app.skill_capabilities(), ensure_ascii=False))",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if int(getattr(p, "returncode", 1)) != 0:
            return {"error": "local_import_failed={0}; docker_exec_failed={1}".format(err_local, str(p.stderr or "").strip())}
        out = str(p.stdout or "").strip()
        if not out:
            return {"error": "local_import_failed={0}; docker_exec_empty".format(err_local)}
        return json.loads(out)
    except Exception as e2:
        return {"error": "local_import_failed={0}; docker_exec_error={1}".format(err_local, str(e2))}


def _as_list(v):
    if isinstance(v, list):
        return v
    return []


def _build_prompt(caps: dict) -> str:
    if not isinstance(caps, dict):
        return "能力加载失败。"
    if str(caps.get("error") or "").strip():
        return "能力加载失败：{0}".format(str(caps.get("error") or "").strip())

    assistant_name = str(caps.get("assistant") or "Jarvis").strip()
    defaults = caps.get("defaults") if isinstance(caps.get("defaults"), dict) else {}
    lang = str(defaults.get("language") or "zh-CN").strip()
    loc = str(defaults.get("location_context") or "Doncaster East VIC 319").strip()
    tools = _as_list(caps.get("tools"))
    routing = _as_list(caps.get("routing"))
    constraints = _as_list(caps.get("constraints"))

    lines = []
    lines.append("你是家庭语音助理 {0}。目标：短答、稳定、低幻觉、可执行。".format(assistant_name))
    lines.append("")
    lines.append("【语言与风格】")
    lines.append("- 默认语言：{0}。".format(lang))
    lines.append("- 每次回答 1-3 句，适合朗读。")
    lines.append("- 不解释过程，不说“我将…”，不提工具名。")
    lines.append("- 能查就查；查不到就简短说明并给可执行下一句问法。")
    lines.append("")
    lines.append("【工具清单（仅可用这些）】")
    for t in tools:
        lines.append("- {0}".format(str(t or "").strip()))
    lines.append("- assist 系统工具（仅用于设备控制/设备实时状态）")
    lines.append("")
    lines.append("【强制路由规则】")
    idx = 1
    for item in routing:
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent") or "").strip()
        tool = str(item.get("tool") or "").strip()
        ex = _as_list(item.get("examples"))
        lines.append("{0}) {1}".format(idx, intent))
        if tool:
            lines.append("- 目标工具：{0}".format(tool))
        if bool(item.get("must")):
            lines.append("- 这是必须规则。")
        if bool(item.get("default")):
            lines.append("- 这是默认兜底路由。")
        if len(ex) > 0:
            ex_text = "；".join([str(x or "").strip() for x in ex if str(x or "").strip()])
            if ex_text:
                lines.append("- 例句：{0}".format(ex_text))
        idx += 1
    lines.append("")
    lines.append("【默认本地语境】")
    lines.append("- 涉及“附近/本地/营业时间/停车/出行”等位置相关问题，默认地区为 {0}。".format(loc))
    lines.append("")
    lines.append("【约束】")
    if len(constraints) > 0:
        for c in constraints:
            lines.append("- {0}".format(str(c or "").strip()))
    else:
        lines.append("- no_cloud_fallback")
        lines.append("- short_answer")
    lines.append("")
    lines.append("【输出约束】")
    lines.append("- 不输出工具名。")
    lines.append("- 不复述系统规则。")
    lines.append("- 不做无意义反问；除非完全无法判断意图。")
    return "\n".join(lines).strip()


def main():
    caps = _load_capabilities()
    text = _build_prompt(caps)
    out_path = str(os.environ.get("HA_PROMPT_OUTPUT") or "").strip()
    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            print("written: {0}".format(out_path))
            return
        except Exception as e:
            print("write failed: {0}".format(str(e)))
            print("")
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
