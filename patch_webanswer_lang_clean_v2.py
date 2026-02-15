import sys
import re

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()

if "MCP_LANG_CLEAN_V1" not in s:
    die("Cannot find MCP_LANG_CLEAN_V1 block to upgrade")

# Replace the whole V1 block with V2 (broad but safe replace between markers)
pat = re.compile(
    r"\n\s*# MCP_LANG_CLEAN_V1:.*?\n\s*except Exception:\n\s*pass\n",
    re.DOTALL
)
m = pat.search(s)
if not m:
    die("Cannot locate exact MCP_LANG_CLEAN_V1 block region")

v2 = (
"\n    # MCP_LANG_CLEAN_V2: enforce answer language consistency (generic, zh-only output)\n"
"    try:\n"
"        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
"        if want_zh and isinstance(answer, str) and answer:\n"
"            # 1) Normalize common tech terms into Chinese (generic mapping)\n"
"            rep = [\n"
"                (r\"\\bllm\\b\", \"大模型\"),\n"
"                (r\"\\bollama\\b\", \"本地模型服务\"),\n"
"                (r\"\\bapi\\b\", \"接口\"),\n"
"                (r\"\\bgpu\\b\", \"显卡\"),\n"
"                (r\"\\bcpu\\b\", \"处理器\"),\n"
"                (r\"\\bcore\\b\", \"核心组件\"),\n"
"                (r\"\\bcommit\\b\", \"提交\"),\n"
"                (r\"\\bissue\\b\", \"问题\"),\n"
"                (r\"\\bupdate\\b\", \"更新\"),\n"
"                (r\"\\bfix\\b\", \"修复\"),\n"
"                (r\"\\bvoice\\b\", \"语音\"),\n"
"                (r\"\\bcontinued\\b\", \"持续\"),\n"
"                (r\"\\bconversation\\b\", \"对话\"),\n"
"                (r\"\\bhome\\s+assistant\\b\", \"家庭助理系统\"),\n"
"                (r\"\\bha\\b\", \"家庭助理系统\"),\n"
"            ]\n"
"            x = answer\n"
"            for rx, rr in rep:\n"
"                x = re.sub(rx, rr, x, flags=re.I)\n"
"\n"
"            # 2) Remove urls\n"
"            x = re.sub(r\"https?://\\S+\", \"\", x)\n"
"\n"
"            # 3) Remove english month/day tokens, then strip leading date-like leftovers\n"
"            x = re.sub(r\"\\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\\b\", \"\", x, flags=re.I)\n"
"            x = re.sub(r\"\\b(?:mon|tue|tues|wed|thu|thur|fri|sat|sun)\\b\", \"\", x, flags=re.I)\n"
"            # Remove leading patterns like '11 2025' or '2025 11' (generic)\n"
"            x = re.sub(r\"^\\s*(?:\\d{1,2}\\s+\\d{4}|\\d{4}\\s+\\d{1,2})\\s*\", \"\", x)\n"
"\n"
"            # 4) Final zh-only keep: Chinese, numbers, spaces, and common punctuation\n"
"            x = re.sub(r\"[^\\u4e00-\\u9fff0-9\\s，。！？；：、（）《》【】“”‘’…—\\-]\", \" \", x)\n"
"            x = re.sub(r\"\\s{2,}\", \" \", x).strip()\n"
"\n"
"            answer = x\n"
"    except Exception:\n"
"        pass\n"
)

s2 = s[:m.start()] + v2 + s[m.end():]
open(PATH, "w", encoding="utf-8").write(s2)
print("OK: upgraded to MCP_LANG_CLEAN_V2")
