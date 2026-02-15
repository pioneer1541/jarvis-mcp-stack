#!/usr/bin/env python3
import subprocess
import json

TESTS = [
  # weather
  "今天天气怎么样",
  "明天天气怎么样",
  "接下来3天天气怎么样",
  "这个周末天气怎么样",

  # calendar
  "今天有什么日程",
  "明天有什么日程",
  "接下来7天有什么日程",

  # holiday
  "下一个公众假期是什么时候",
  "今年还有哪些公众假期",

  # news
  "今天墨尔本的新闻有哪些",
  "今天世界新闻有哪些",
  "澳洲政治新闻3条",
  "数码新闻3条",
  "游戏新闻3条",
  "中国经济新闻3条",
  "热门新闻10条",
]

def run_in_container(py_code: str):
    cmd = ["docker", "exec", "-i", "mcp-hello", "python3", "-"]
    p = subprocess.run(cmd, input=py_code.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", errors="replace")

def main():
    tests_json = json.dumps(TESTS, ensure_ascii=False)
    py_code = """
import time, os, json
import app

tests = json.loads({tests_json!r})

print("SERVICE= mcp-hello")
print("TZ=", os.environ.get("TZ"))
print("ROUTE_RETURN_TEXT=", os.environ.get("ROUTE_RETURN_TEXT"))
print("ROUTE_RETURN_DATA=", os.environ.get("ROUTE_RETURN_DATA"))
print("MINIFLUX_BASE_URL=", os.environ.get("MINIFLUX_BASE_URL"))
print("MINIFLUX_DEFAULT_LIMIT=", os.environ.get("MINIFLUX_DEFAULT_LIMIT"))
print("HA_BASE_URL set? ", "YES" if (os.environ.get("HA_BASE_URL") or "").strip() else "NO")
print("HA_TOKEN set?    ", "YES" if (os.environ.get("HA_TOKEN") or "").strip() else "NO")

fails = 0
slow = 0

for t in tests:
    t0 = time.time()
    try:
        r = app.route_request(t)
        dt = time.time() - t0
        ok_type = isinstance(r, str)
        empty = (not r) or (not str(r).strip())

        print("\\n==", t, "==")
        print("type=", type(r), "secs=", round(dt, 3))
        print("repr=", repr(r))
        print(r)

        if dt > 8.0:
            slow += 1
            print("!! SLOW (>8s)")

        if (not ok_type) or empty:
            fails += 1
            print("!! FAIL: return_type_or_empty")

    except Exception as e:
        dt = time.time() - t0
        fails += 1
        print("\\n==", t, "==")
        print("!! EXCEPTION secs=", round(dt, 3), "err=", repr(e))

print("\\n=== SUMMARY ===")
print("fails=", fails, "slow=", slow, "total=", len(tests))
""".format(tests_json=tests_json)

    rc, out = run_in_container(py_code)
    print(out)
    raise SystemExit(rc)

if __name__ == "__main__":
    main()
