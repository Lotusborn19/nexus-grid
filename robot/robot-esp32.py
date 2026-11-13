# NEXUS ROBOT — ESP32 / MicroPython
# A tiny Wi-Fi server that turns ORACLE's {"action":"wave"} into PCA9685 servo moves.
# No pip: a minimal PCA9685 driver is built in. Flash this as main.py (or run it).
#
# FLASH (on your computer, once):
#   - Put MicroPython on the ESP32 (esptool), then copy this file as main.py (ampy/Thonny).
# WIRING:
#   ESP32 SDA->GPIO21, SCL->GPIO22, 3V3->PCA VCC(logic), GND->GND (shared!),
#   PCA V+ -> SEPARATE 5-6V servo supply. Servos into channels 0..7.
# USE:
#   Set WIFI below. On boot it prints its IP. In NEXUS -> ORACLE -> setup, set
#   Robot URL to  http://<that-ip>   (port 80). ORACLE POSTs /do and it moves.

import network, socket, ujson, time
from machine import Pin, I2C

WIFI_SSID = "YOUR_WIFI"
WIFI_PASS = "YOUR_PASSWORD"

# ---- joint -> (channel, min_deg, max_deg, home_deg) ----
SERVOS = {
    "head_pan": (0, 0, 180, 90), "head_tilt": (1, 45, 135, 90),
    "r_shoulder": (2, 0, 180, 20), "r_elbow": (3, 0, 180, 90),
    "l_shoulder": (4, 0, 180, 20), "l_elbow": (5, 0, 180, 90),
    "waist": (6, 30, 150, 90), "gripper": (7, 10, 110, 30),
}
# ---- action -> list of frames {"set":{joint:angle}, "hold":sec} ; strings are aliases ----
MOVES = {
    "home": [{"set": {j: SERVOS[j][3] for j in SERVOS}, "hold": 0.4}],
    "wave": [{"set": {"r_shoulder": 150}, "hold": 0.3},
             {"set": {"r_elbow": 150}, "hold": 0.25}, {"set": {"r_elbow": 60}, "hold": 0.25},
             {"set": {"r_elbow": 150}, "hold": 0.25}, {"set": {"r_elbow": 60}, "hold": 0.25},
             {"set": {"r_shoulder": 20, "r_elbow": 90}, "hold": 0.3}],
    "nod": [{"set": {"head_tilt": 120}, "hold": 0.25}, {"set": {"head_tilt": 70}, "hold": 0.25},
            {"set": {"head_tilt": 90}, "hold": 0.2}],
    "shake": [{"set": {"head_pan": 60}, "hold": 0.25}, {"set": {"head_pan": 120}, "hold": 0.25},
              {"set": {"head_pan": 90}, "hold": 0.2}],
    "yes": "nod", "no": "shake",
    "point": [{"set": {"r_shoulder": 90, "r_elbow": 170}, "hold": 0.8},
              {"set": {"r_shoulder": 20, "r_elbow": 90}, "hold": 0.3}],
    "grab": [{"set": {"gripper": 105}, "hold": 0.4}],
    "release": [{"set": {"gripper": 20}, "hold": 0.4}],
    "dance": [{"set": {"waist": 60, "r_shoulder": 140, "l_shoulder": 40}, "hold": 0.3},
              {"set": {"waist": 120, "r_shoulder": 40, "l_shoulder": 140}, "hold": 0.3},
              {"set": {"waist": 90, "r_shoulder": 20, "l_shoulder": 20}, "hold": 0.3}],
}

# ---- minimal PCA9685 driver (50Hz servo PWM) ----
class PCA9685:
    def __init__(self, i2c, addr=0x40):
        self.i2c, self.addr = i2c, addr
        self._w(0x00, 0x00); time.sleep_ms(5)
        self.freq(50)
    def _w(self, reg, val): self.i2c.writeto_mem(self.addr, reg, bytes([val]))
    def _r(self, reg): return self.i2c.readfrom_mem(self.addr, reg, 1)[0]
    def freq(self, hz):
        prescale = int(25000000.0 / (4096 * hz) - 1 + 0.5)
        old = self._r(0x00)
        self._w(0x00, (old & 0x7F) | 0x10)   # sleep
        self._w(0xFE, prescale)              # prescale
        self._w(0x00, old); time.sleep_ms(5)
        self._w(0x00, old | 0xA0)            # restart + auto-increment
    def duty(self, ch, on, off):
        base = 0x06 + 4 * ch
        self.i2c.writeto_mem(self.addr, base, bytes([on & 0xFF, on >> 8, off & 0xFF, off >> 8]))
    def angle(self, ch, deg):
        # 0..180deg -> ~0.5ms..2.5ms pulse over 20ms (4096 ticks)
        us = 500 + (deg / 180.0) * 2000
        off = int(4096 * us / 20000)
        self.duty(ch, 0, off)

i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
pca = PCA9685(i2c)
_cur = {j: SERVOS[j][3] for j in SERVOS}

def clamp(j, a):
    lo, hi = SERVOS[j][1], SERVOS[j][2]
    return max(lo, min(hi, a))

def set_joint(j, target):
    if j not in SERVOS: return
    ch = SERVOS[j][0]; target = clamp(j, target); cur = _cur[j]
    step = 4 if target >= cur else -4
    a = cur
    while abs(target - a) > abs(step):
        a += step; pca.angle(ch, a); time.sleep_ms(12)
    pca.angle(ch, target); _cur[j] = target

def play(action):
    seen = set()
    while isinstance(MOVES.get(action), str):
        if action in seen: break
        seen.add(action); action = MOVES[action]
    frames = MOVES.get(action)
    if not frames: return False
    print("move:", action)
    for fr in frames:
        for j, a in fr.get("set", {}).items():
            set_joint(j, a)
        time.sleep(fr.get("hold", 0.2))
    return True

def wifi():
    w = network.WLAN(network.STA_IF); w.active(True)
    if not w.isconnected():
        w.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(40):
            if w.isconnected(): break
            time.sleep(0.5)
    print("IP:", w.ifconfig()[0], "-> set this as ORACLE Robot URL (http://IP)")
    return w

def serve():
    wifi(); play("home")
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", 80)); s.listen(2)
    while True:
        try:
            c, _ = s.accept(); req = c.recv(1024)
            body = b""
            if b"\r\n\r\n" in req: body = req.split(b"\r\n\r\n", 1)[1]
            action, ok = "", False
            try: action = ujson.loads(body).get("action", "")
            except Exception: pass
            if b"/ping" in req and b"GET" in req:
                payload = ujson.dumps({"ok": True, "name": "NEXUS ROBOT ESP32",
                                       "actions": list(MOVES.keys())})
            else:
                ok = play(action.lower()) if action else False
                payload = ujson.dumps({"ok": ok, "action": action})
            c.send(b"HTTP/1.1 200 OK\r\nAccess-Control-Allow-Origin: *\r\n"
                   b"Access-Control-Allow-Headers: *\r\nContent-Type: application/json\r\n\r\n")
            c.send(payload); c.close()
        except Exception as e:
            print("err", e)
            try: c.close()
            except Exception: pass

serve()
