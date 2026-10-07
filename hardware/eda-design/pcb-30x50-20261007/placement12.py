"""Antenna-up module, front battery, USB-C centred on the back.

mm, front-view coordinates, origin board top-left, y down.
U1 rot 0 = antenna (pad-free end) up. Pins (centre 9.665, 8.825):
  left col x 4.2 : 3V3 9.13 | BOOT2 10.73 | REC 11.53 | EN 13.13
  bottom row y 16.43: MIC_DATA 5.3 | SYS_ADC 6.1 | AMP_CTRL 8.5 | BCLK 10.1 | WS 10.9 |
                      MIC_CLK 11.7 | AMP_DIN 12.5 | LED 13.3 | BOOT9 14.1
  right col x 16.0: USB_DP 13.93 | USB_DM 14.73
"""
import json, math, sys

MIL = 0.0254
board = json.load(open("board29.json", encoding="utf-8"))
C = {c["designator"]: c for c in board["components"]}

def size_mm(d, rot):
    c = C[d]; b = c["bbox"]
    w = (b["maxX"] - b["minX"]) * MIL; h = (b["maxY"] - b["minY"]) * MIL
    if (c["rotation"] - rot) % 180:
        w, h = h, w
    return w, h

T, B = "TOP", "BOTTOM"
PLAN = {
    # ===== FRONT =====
    "U1": (9.665, 8.825, 0, T),
    # 3V3 / EN parts that must hug the module's left pins (front strip, 2 mm wide)
    "C3": (1.3, 8.4, 90, T), "C2": (1.3, 10.6, 90, T), "C15": (1.3, 12.8, 90, T), "R9": (1.3, 15.0, 90, T),
    "U4": (24.5, 6.0, 180, T),
    "D3": (27.6, 12.05, 0, T),
    # TH headers right of the module, under the mic ring, above the battery
    "J4": (26.96, 14.6, 0, T), "J2": (19.84, 18.0, 0, T), "J3": (26.96, 18.0, 0, T),
    # ===== BACK =====
    # beside the module (behind the mic): test pads, mic decoupling, LED resistor, USB series R
    "TP1": (27.9, 2.0, 0, B), "TP2": (27.9, 5.2, 0, B), "TP3": (27.9, 8.4, 0, B),
    "C13": (24.5, 9.3, 0, B), "R13": (27.6, 11.4, 0, B),
    "R6": (18.2, 13.0, 0, B), "R7": (18.2, 14.5, 0, B),
    # right under the module's bottom edge: 3V3 LDO + GPIO pull resistors, ordered like the pins
    "U3": (4.0, 21.3, 180, B), "C16": (7.6, 21.3, 90, B),
    "R2": (10.0, 18.2, 0, B), "R11": (12.2, 18.2, 0, B), "R12": (14.4, 18.2, 0, B),
    "R1": (10.0, 19.7, 0, B), "R14": (12.2, 19.7, 0, B), "R15": (14.4, 19.7, 0, B),
    "C19": (10.0, 21.2, 0, B), "R10": (12.2, 21.2, 0, B), "R18": (14.4, 21.2, 0, B),
    # USB-C in the middle; protection just outside a 2.5 mm clearance ring, on its left
    "J1": (15.0, 30.0, 180, B),
    "D1": (15.9, 23.6, 90, B), "D2": (16.9, 23.6, 90, B),
    "R4": (5.7, 28.3, 90, B), "R5": (5.7, 31.7, 90, B),
    "F1": (3.6, 30.0, 90, B), "R8": (1.2, 28.0, 90, B), "D4": (3.0, 35.0, 0, B),
    # amplifier next to the speaker header (short class-D outputs)
    "U5": (26.0, 23.1, 0, B), "C5": (26.0, 28.0, 0, B),
    "U7": (24.0, 32.0, 180, B), "C4": (26.6, 32.0, 90, B), "C23": (28.2, 32.0, 90, B),
    # charger below J1 (unchanged block)
    "L1": (12.6, 40.5, 90, B), "U2": (18.0, 40.5, 0, B),
    "C6": (17.3, 45.6, 0, B), "C7": (12.6, 44.9, 180, B),
    "C8": (21.3, 45.5, 180, B), "R3": (21.3, 47.0, 0, B),
    "C1": (12.6, 47.6, 0, B),
}
TH = {"J1", "J2", "J3", "J4"}
W, H, EDGE, GAP = 30.0, 50.0, 0.3, 0.15
MIC = (24.5, 6.0, 5.0)
ZONES = {
    "antenna": ((0.0, 0.0, 17.2, 5.7), "BOTH"),
    "module-back": ((2.5, 0.4, 16.83, 17.25), B),
    "battery": ((0.0, 19.5, 30.0, 50.0), T),
    "usb-clearance": ((7.9, 24.8, 22.1, 35.2), B),
}

R = {}
for d, (cx, cy, rot, side) in PLAN.items():
    w, h = size_mm(d, rot)
    R[d] = ((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), side)
sides = lambda d, s: {T, B} if d in TH else {s}
ov = lambda a, b, g=0.0: a[0] < b[2] + g and b[0] < a[2] + g and a[1] < b[3] + g and b[1] < a[3] + g
def circle_hits(r, c):
    nx = min(max(c[0], r[0]), r[2]); ny = min(max(c[1], r[1]), r[3])
    return math.hypot(nx - c[0], ny - c[1]) < c[2]

prob = []
names = list(R)
for i, a in enumerate(names):
    ra, sa = R[a]
    if ra[0] < EDGE - 0.05 or ra[1] < EDGE - 0.1 or ra[2] > W - EDGE + 0.05 or ra[3] > H - EDGE + 0.05:
        prob.append(f"{a} edge {tuple(round(v, 2) for v in ra)}")
    for b in names[i + 1:]:
        rb, sb = R[b]
        if sides(a, sa) & sides(b, sb) and ov(ra, rb, GAP):
            prob.append(f"{a} <-> {b}")
    for z, (zr, zs) in ZONES.items():
        if a == "U1" and z in ("antenna", "module-back"): continue
        if a == "J1" and z in ("battery", "usb-clearance"): continue
        if (zs == "BOTH" or zs in sides(a, sa)) and ov(ra, zr):
            prob.append(f"{a} in {z}")
    if T in sides(a, sa) and a not in ("U4",) and circle_hits(ra, MIC):
        prob.append(f"{a} in mic ring")

print("unplanned:", sorted(set(C) - set(PLAN)))
print("\n".join(prob) or "OK: no overlap / edge / zone problems")
print("front:", sorted(d for d, (r, s) in R.items() if s == T and d not in TH))
print("back :", sorted(d for d, (r, s) in R.items() if s == B and d not in TH))
json.dump([{"designator": d, "rotation": rot, "side": side,
            "cx_mil": round(cx / MIL, 2), "cy_mil": round(-cy / MIL, 2)}
           for d, (cx, cy, rot, side) in PLAN.items()],
          open("placement12.json", "w", encoding="utf-8"), indent=1)
mm2mil = lambda r: [round(r[0] / MIL, 1), round(-r[3] / MIL, 1), round(r[2] / MIL, 1), round(-r[1] / MIL, 1)]
json.dump({"antenna_rect_mil": mm2mil(ZONES["antenna"][0])}, open("zones12.json", "w"), indent=1)
sys.exit(1 if prob else 0)


