#!/usr/bin/env python3
"""
NEXUS BRIDGE v2  —  the companion that gives NEXUS // GRID real control of YOUR phone.

Runs inside Termux on your own device. Loopback-only + token-protected, so only
apps on this phone that know your token can talk to it. This is what turns the
web UI's "Device" apps from a demo into real control.

SETUP (in Termux):
  pkg update && pkg upgrade -y
  pkg install python termux-api -y
  # also install the "Termux:API" app from F-Droid (the companion APK)
  python nexus-bridge.py
It prints a TOKEN. Paste that into NEXUS → Bridge. Keep this running (termux-wake-lock
keeps it alive with the screen off).

Security: binds 127.0.0.1 only and every call needs your token. The Shell app can run
any command as your Termux user — set ALLOW_SHELL = False below to turn that off.
"""
import http.server, socketserver, json, subprocess, os, secrets, urllib.parse, shlex

HOST, PORT = "127.0.0.1", 8787
HOME = os.path.expanduser("~")
CFG = os.path.join(HOME, ".nexus")
os.makedirs(os.path.join(CFG, "auto"), exist_ok=True)
TOKEN_FILE = os.path.join(CFG, "token")
if os.path.exists(TOKEN_FILE):
    TOKEN = open(TOKEN_FILE).read().strip()
else:
    TOKEN = secrets.token_urlsafe(18)
    open(TOKEN_FILE, "w").write(TOKEN)

# allow arbitrary shell from the Shell app? your device, your call. Default: on.
ALLOW_SHELL = True
# termux-api commands the Control Deck may run (safe, parameterised)
TERMUX = {
    "torch_on":     ["termux-torch", "on"],
    "torch_off":    ["termux-torch", "off"],
    "vibrate":      ["termux-vibrate", "-d", "500"],
    "battery":      ["termux-battery-status"],
    "wifi":         ["termux-wifi-connectioninfo"],
    "location":     ["termux-location", "-p", "network"],
    "clipboard_get":["termux-clipboard-get"],
    "volume":       ["termux-volume"],
    "toast":        ["termux-toast", "NEXUS online"],
}

def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "out": p.stdout, "err": p.stderr, "code": p.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": "", "err": "timed out", "code": -1}
    except FileNotFoundError as e:
        return {"ok": False, "out": "", "err": "not found: %s (is termux-api installed?)" % e, "code": -1}
    except Exception as e:
        return {"ok": False, "out": "", "err": str(e), "code": -1}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "X-Nexus-Token, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")   # lets an https page reach this loopback server in Chrome
    def _send(self, obj, code=200):
        body = (obj if isinstance(obj, str) else json.dumps(obj)).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def _auth(self):
        return self.headers.get("X-Nexus-Token", "") == TOKEN
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); path = u.path
        q = urllib.parse.parse_qs(u.query)
        if path == "/ping":
            return self._send({"ok": True, "name": "NEXUS BRIDGE", "version": 2})
        if not self._auth():
            return self._send({"ok": False, "err": "bad token"}, 401)
        if path == "/sys":
            mem = {}
            try:
                for ln in open("/proc/meminfo"):
                    k, v = ln.split(":"); mem[k.strip()] = v.strip()
            except Exception: pass
            return self._send({"ok": True, "battery": run(["termux-battery-status"]),
                               "mem": {k: mem.get(k) for k in ("MemTotal","MemAvailable")},
                               "uptime": open("/proc/uptime").read().split()[0] if os.path.exists("/proc/uptime") else None})
        if path == "/procs":
            r = run(["ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pcpu"]) if os.name != "nt" else run(["ps"])
            return self._send(r)
        if path == "/net":
            return self._send({"ok": True, "ip": run(["ip", "addr"]), "route": run(["ip", "route"])})
        if path == "/ls":
            p = q.get("path", [HOME])[0]
            try:
                items = []
                for n in sorted(os.listdir(p)):
                    fp = os.path.join(p, n)
                    items.append({"name": n, "dir": os.path.isdir(fp),
                                  "size": os.path.getsize(fp) if os.path.isfile(fp) else 0})
                return self._send({"ok": True, "path": p, "items": items})
            except Exception as e:
                return self._send({"ok": False, "err": str(e)})
        if path == "/read":
            p = q.get("path", [""])[0]
            try:
                return self._send({"ok": True, "path": p, "text": open(p, "r", errors="replace").read(20000)})
            except Exception as e:
                return self._send({"ok": False, "err": str(e)})
        return self._send({"ok": False, "err": "unknown endpoint"}, 404)
    def do_POST(self):
        if not self._auth():
            return self._send({"ok": False, "err": "bad token"}, 401)
        ln = int(self.headers.get("Content-Length", 0))
        try: body = json.loads(self.rfile.read(ln) or "{}")
        except Exception: body = {}
        path = urllib.parse.urlparse(self.path).path
        if path == "/termux":
            act = body.get("action")
            if act not in TERMUX:
                return self._send({"ok": False, "err": "unknown action"}, 400)
            cmd = list(TERMUX[act])
            if act == "toast" and body.get("text"): cmd[-1] = str(body["text"])[:80]
            if act == "vibrate" and body.get("ms"): cmd = ["termux-vibrate", "-d", str(int(body["ms"]))]
            return self._send(run(cmd))
        if path == "/speak":
            return self._send(run(["termux-tts-speak", str(body.get("text", "hello operator"))[:200]]))
        if path == "/notify":
            return self._send(run(["termux-notification", "--title", str(body.get("title","NEXUS"))[:60],
                                   "--content", str(body.get("content",""))[:200]]))
        if path == "/clipboard":
            return self._send(run(["termux-clipboard-set", str(body.get("text",""))[:5000]]))
        if path == "/run":
            if not ALLOW_SHELL:
                return self._send({"ok": False, "err": "shell disabled"}, 403)
            cmd = body.get("cmd", "")
            if not cmd: return self._send({"ok": False, "err": "empty"}, 400)
            return self._send(run(["bash", "-lc", cmd], timeout=30))
        if path == "/automation":
            name = "".join(c for c in body.get("name","job") if c.isalnum() or c in "-_")[:40] or "job"
            script = body.get("script", "")
            period = int(body.get("period_ms", 0))
            sp = os.path.join(CFG, "auto", name + ".sh")
            open(sp, "w").write("#!/data/data/com.termux/files/usr/bin/bash\n" + script + "\n")
            os.chmod(sp, 0o755)
            res = {"ok": True, "saved": sp}
            if period >= 900000:  # termux-job-scheduler minimum ~15 min
                res["schedule"] = run(["termux-job-scheduler", "--script", sp,
                                       "--period-ms", str(period), "--persisted", "true"])
            return self._send(res)
        return self._send({"ok": False, "err": "unknown endpoint"}, 404)

if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════════╗")
    print("  ║   NEXUS BRIDGE v2  —  online on :%d     ║" % PORT)
    print("  ╚══════════════════════════════════════════╝")
    print("\n  Your TOKEN (paste into NEXUS → Bridge):\n")
    print("      " + TOKEN + "\n")
    print("  Keep this running. Tip: run `termux-wake-lock` first.\n")
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((HOST, PORT), H) as s:
        try: s.serve_forever()
        except KeyboardInterrupt: print("\n  bridge offline.\n")
