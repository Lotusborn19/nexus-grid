#!/usr/bin/env python3
"""
NEXUS ROBOT SERVER  —  turns ORACLE's [[do:ACTION]] commands into real servo moves.

This is the /do endpoint ORACLE talks to. Run it on the Raspberry Pi (or a phone with
a USB/I2C PCA9685). ORACLE (NEXUS → ORACLE → setup → Robot URL) POSTs {"action":"wave"}
here and the matching move plays on your PCA9685 servos.

SETUP (Raspberry Pi):
  sudo raspi-config         # Interface Options -> I2C -> enable
  pip install adafruit-circuitpython-servokit
  python3 robot-server.py
Then in NEXUS set the Robot URL to  http://<pi-ip>:8799

No hardware yet? It still runs in MOCK mode and prints every move, so you can wire the
brain first and the body later. Loopback+LAN; add a token if you expose it.

Shape your robot by editing SERVOS (which joint is on which channel) and MOVES (the
choreography). Angles are clamped to each joint's safe range.
"""
import http.server, socketserver, json, os, time, threading

PORT = int(os.environ.get("ROBOT_PORT", "8799"))
TOKEN = os.environ.get("ROBOT_TOKEN", "")          # optional; "" = open on your LAN
OLLAMA_URL = os.environ.get("OLLAMA_URL", "")      # optional: let the robot think for itself

# ── 1. YOUR BODY: logical joint -> (channel, min_deg, max_deg, home_deg) ─────────────
SERVOS = {
    "head_pan":   (0,  0, 180, 90),
    "head_tilt":  (1, 45, 135, 90),
    "r_shoulder": (2,  0, 180, 20),
    "r_elbow":    (3,  0, 180, 90),
    "l_shoulder": (4,  0, 180, 20),
    "l_elbow":    (5,  0, 180, 90),
    "waist":      (6, 30, 150, 90),
    "gripper":    (7, 10, 110, 30),
}

# ── 2. CHOREOGRAPHY: action -> list of frames. Each frame sets joints, then holds. ───
#     {"set": {joint: angle, ...}, "hold": seconds}
MOVES = {
    "home":    [{"set": {j: SERVOS[j][3] for j in SERVOS}, "hold": 0.4}],
    "wave":    [{"set": {"r_shoulder": 150}, "hold": 0.3},
                {"set": {"r_elbow": 150}, "hold": 0.25}, {"set": {"r_elbow": 60}, "hold": 0.25},
                {"set": {"r_elbow": 150}, "hold": 0.25}, {"set": {"r_elbow": 60}, "hold": 0.25},
                {"set": {"r_shoulder": 20, "r_elbow": 90}, "hold": 0.3}],
    "nod":     [{"set": {"head_tilt": 120}, "hold": 0.25}, {"set": {"head_tilt": 70}, "hold": 0.25},
                {"set": {"head_tilt": 120}, "hold": 0.25}, {"set": {"head_tilt": 90}, "hold": 0.2}],
    "shake":   [{"set": {"head_pan": 60}, "hold": 0.25}, {"set": {"head_pan": 120}, "hold": 0.25},
                {"set": {"head_pan": 60}, "hold": 0.25}, {"set": {"head_pan": 90}, "hold": 0.2}],
    "no":      "shake",                         # alias
    "yes":     "nod",                           # alias
    "point":   [{"set": {"r_shoulder": 90, "r_elbow": 170}, "hold": 0.8},
                {"set": {"r_shoulder": 20, "r_elbow": 90}, "hold": 0.3}],
    "grab":    [{"set": {"gripper": 105}, "hold": 0.4}],
    "release": [{"set": {"gripper": 20}, "hold": 0.4}],
    "dance":   [{"set": {"waist": 60, "r_shoulder": 140, "l_shoulder": 40}, "hold": 0.3},
                {"set": {"waist": 120, "r_shoulder": 40, "l_shoulder": 140}, "hold": 0.3},
                {"set": {"waist": 60, "r_shoulder": 140, "l_shoulder": 40}, "hold": 0.3},
                {"set": {"waist": 90, "r_shoulder": 20, "l_shoulder": 20}, "hold": 0.3}],
    "bow":     [{"set": {"waist": 130, "head_tilt": 120}, "hold": 0.8},
                {"set": {"waist": 90, "head_tilt": 90}, "hold": 0.3}],
}

STEP_DEG = 4          # degrees per interpolation step (smaller = smoother/slower)
STEP_DELAY = 0.012    # seconds between steps

# ── 3. HARDWARE (real PCA9685, or a mock that prints) ────────────────────────────────
class MockKit:
    class _S:
        def __init__(s, i): s.i = i; s._a = None
        @property
        def angle(s): return s._a
        @angle.setter
        def angle(s, v): s._a = v
    def __init__(self): self.servo = [MockKit._S(i) for i in range(16)]

try:
    from adafruit_servokit import ServoKit
    kit = ServoKit(channels=16); HW = True
except Exception as e:
    kit = MockKit(); HW = False
    print("  [mock mode] no PCA9685 found (%s) — moves will print, not drive servos." % type(e).__name__)

_cur = {j: SERVOS[j][3] for j in SERVOS}          # current angle per joint
_lock = threading.Lock()

def _clamp(j, a):
    lo, hi = SERVOS[j][1], SERVOS[j][2]
    return max(lo, min(hi, a))

def _write(j, a):
    ch = SERVOS[j][0]
    try: kit.servo[ch].angle = a
    except Exception: pass

def set_joint(j, target):
    """Move one joint smoothly from current to target."""
    if j not in SERVOS: return
    target = _clamp(j, float(target))
    cur = _cur[j]
    step = STEP_DEG if target >= cur else -STEP_DEG
    a = cur
    while abs(target - a) > abs(step):
        a += step; _write(j, a); time.sleep(STEP_DELAY)
    _write(j, target); _cur[j] = target

def play(action):
    """Resolve aliases and run a choreography. Returns (ok, message)."""
    seen = set()
    while isinstance(MOVES.get(action), str):      # follow aliases
        if action in seen: break
        seen.add(action); action = MOVES[action]
    frames = MOVES.get(action)
    if not frames:
        return False, "unknown action '%s'" % action
    with _lock:
        print("  ▶ %s" % action + ("" if HW else "  (mock)"))
        for fr in frames:
            targets = fr.get("set", {})
            # move the joints in this frame (sequentially keeps current cheap servos sane)
            for j, a in targets.items():
                set_joint(j, a)
                if not HW: print("     %-11s -> %s°" % (j, _clamp(j, a)))
            time.sleep(fr.get("hold", 0.2))
    return True, "played %s" % action

# ── 4. OPTIONAL: let the robot think for itself via local Ollama ─────────────────────
def think(prompt):
    if not OLLAMA_URL: return {"ok": False, "err": "OLLAMA_URL not set"}
    import urllib.request, re
    sys = ("You are this robot's brain. Reply in one short sentence. If a physical "
           "action fits, end with a tag like [[do:wave]] using one of: " + ", ".join(MOVES.keys()) + ".")
    body = json.dumps({"model": os.environ.get("OLLAMA_MODEL", "llama3.2:1b"),
                       "messages": [{"role": "system", "content": sys},
                                    {"role": "user", "content": prompt}], "stream": False}).encode()
    req = urllib.request.Request(OLLAMA_URL.rstrip("/") + "/api/chat", body,
                                 {"Content-Type": "application/json"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())
        text = (d.get("message") or {}).get("content", "")
    except Exception as e:
        return {"ok": False, "err": str(e)}
    acts = re.findall(r"\[\[do:([a-z0-9_-]+)\]\]", text, re.I)
    for a in acts: play(a.lower())
    return {"ok": True, "said": re.sub(r"\[\[do:[^\]]+\]\]", "", text).strip(), "did": acts}

# ── 5. HTTP API ──────────────────────────────────────────────────────────────────────
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Nexus-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(204); self._cors(); self.end_headers()
    def _auth(self): return (not TOKEN) or self.headers.get("X-Nexus-Token", "") == TOKEN
    def do_GET(self):
        if self.path == "/ping":
            return self._send({"ok": True, "name": "NEXUS ROBOT", "hardware": HW, "actions": list(MOVES.keys())})
        if self.path == "/actions":
            return self._send({"ok": True, "actions": list(MOVES.keys())})
        self._send({"ok": False, "err": "unknown"}, 404)
    def do_POST(self):
        if not self._auth(): return self._send({"ok": False, "err": "bad token"}, 401)
        ln = int(self.headers.get("Content-Length", 0))
        try: body = json.loads(self.rfile.read(ln) or "{}")
        except Exception: body = {}
        if self.path == "/do":
            ok, msg = play(str(body.get("action", "")).lower())
            return self._send({"ok": ok, "msg": msg}, 200 if ok else 400)
        if self.path == "/think":
            return self._send(think(str(body.get("prompt", ""))))
        self._send({"ok": False, "err": "unknown"}, 404)

if __name__ == "__main__":
    print("\n  ╔════════════════════════════════════════════╗")
    print("  ║   NEXUS ROBOT SERVER  —  :%d  %s   ║" % (PORT, "LIVE " if HW else "MOCK "))
    print("  ╚════════════════════════════════════════════╝")
    print("  actions:", ", ".join(MOVES.keys()))
    print("  point NEXUS → ORACLE → setup → Robot URL at  http://<this-ip>:%d\n" % PORT)
    play("home")
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), H) as s:
        try: s.serve_forever()
        except KeyboardInterrupt: print("\n  robot offline.\n")
