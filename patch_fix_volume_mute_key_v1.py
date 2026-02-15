#!/usr/bin/env python3
# patch_fix_volume_mute_key_v1.py
# 목적: Home Assistant media_player.volume_mute 参数 key 修正: mute -> is_volume_muted
# 规则: 备份 + 替换 + py_compile

import os
import shutil
import subprocess
from datetime import datetime

TARGET = os.environ.get("TARGET_PY") or "app.py"

def backup_file(path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.fix_mute_key_v1." + ts
    shutil.copy2(path, bak)
    return bak

def patch_lines(lines):
    changed = 0
    out = []
    for line in lines:
        # 常见：{"mute": True} 或 {'mute': False}
        if '"mute"' in line or "'mute'" in line:
            # 尽量只在与 volume_mute 相关区域做替换：简单策略是只替换字典键形式
            # 替换 "mute": -> "is_volume_muted":
            new_line = line
            new_line = new_line.replace('"mute":', '"is_volume_muted":')
            new_line = new_line.replace("'mute':", "'is_volume_muted':")
            if new_line != line:
                changed += 1
                line = new_line
        out.append(line)
    return out, changed

def main():
    if not os.path.exists(TARGET):
        raise SystemExit("ERROR: target not found: " + TARGET)

    with open(TARGET, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 如果文件里压根没有 volume_mute，提示用户：当前文件不是包含音乐控制逻辑的那份
    joined = "".join(lines)
    if "volume_mute" not in joined:
        print("WARN: no 'volume_mute' found in " + TARGET + ". This may not be the file that contains music control logic.")
        print("HINT: run: docker exec -i mcp-hello python - <<'PY'\nimport app\nprint(app.__file__)\nPY")
        # 仍然允许继续（可能是用别的封装调用），但大概率不会生效
    bak = backup_file(TARGET)

    new_lines, changed = patch_lines(lines)

    if changed == 0:
        print("WARN: nothing changed. No dict key 'mute' found to replace.")
    else:
        with open(TARGET, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print("OK: patched lines =", changed)

    # syntax check
    try:
        subprocess.check_call(["python3", "-m", "py_compile", TARGET])
        print("OK: py_compile passed")
    except subprocess.CalledProcessError:
        print("ERROR: py_compile failed. Restoring backup:", bak)
        shutil.copy2(bak, TARGET)
        raise

if __name__ == "__main__":
    main()
