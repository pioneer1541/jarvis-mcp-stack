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

    pat = r'head\s*=\s*"\uff08"\s*\+\s*eid\s*\+\s*"\uff09"\s*'
    hits = len(re.findall(pat, src))
    if hits == 0:
        raise RuntimeError("Cannot find weather head prefix line: head = \"（\" + eid + \"）\"")
    if hits < 2:
        # still patch, but warn
        pass

    out = re.sub(pat, 'head = ""  # removed weather entity prefix', src)

    with io.open(APP + ".bak.remove_weather_prefix_v1", "w", encoding="utf-8") as f:
        f.write(src)

    _write(out)
    print("Patched OK. Replaced:", hits, "Backup:", APP + ".bak.remove_weather_prefix_v1")

if __name__ == "__main__":
    main()
