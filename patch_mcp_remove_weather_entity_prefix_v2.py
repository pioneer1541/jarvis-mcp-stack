import io
import re

APP = "app.py"

def _read():
    with io.open(APP, "r", encoding="utf-8") as f:
        return f.read()

def _write(s):
    with io.open(APP, "w", encoding="utf-8") as f:
        f.write(s)

def main():
    src = _read()

    # keep indentation
    pat = r'^(\s*)head\s*=\s*"\uff08"\s*\+\s*eid\s*\+\s*"\uff09"\s*$'
    hits = len(re.findall(pat, src, flags=re.M))
    if hits == 0:
        raise RuntimeError("Cannot find weather head prefix line with indentation anchor.")

    repl = r'\1head = ""  # removed weather entity prefix'
    out = re.sub(pat, repl, src, flags=re.M)

    with io.open(APP + ".bak.remove_weather_prefix_v2", "w", encoding="utf-8") as f:
        f.write(src)

    _write(out)
    print("Patched OK. Replaced:", hits, "Backup:", APP + ".bak.remove_weather_prefix_v2")

if __name__ == "__main__":
    main()
