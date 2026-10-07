"""Two-sided 30x50 placement (mm; front-view coordinates, origin top-left, y down).

Zones reserved for things that are not on the PCB yet:
  - mic seal ring: front, circle r=5 mm around the mic
  - speaker: front, 22x22 mm (fits a D20 speaker), above the USB jack
  - battery: back, 20x30 mm (fits a 302030-class cell)
Writes placement6.json (moves) and zones6.json (keep-out regions to create).
"""
import json, math, sys

MIL = 0.0254
board = json.load(open("board15.json", encoding="utf-8"))
C = {c["designator"]: c for c in board["components"]}

def size_mm(d, rot):
    c = C[d]; b = c["bbox"]
    w = (b["maxX"] - b["minX"]) * MIL; h = (b["maxY"] - b["minY"]) * MIL
    if (c["rotation"] - rot) % 180:
        w, h = h, w
    return w, h

T, B = "TOP", "BOTTOM"
# designator: (cx, cy, rotation, side)
PLAN = {
    # ---------- FRONT ----------
    "U1": (8.725, 7.67, 90, T),
    "U4": (24.5, 6.0, 180, T),                       # mic, centre of the seal ring
    # column 1 next to U1's right-hand pins
    "R6": (18.1, 1.55, 90, T), "R7": (18.1, 3.75, 90, T),
    "R12": (18.1, 5.95, 90, T), "R11": (18.1, 8.15, 90, T),
    "R2": (18.1, 10.35, 90, T), "R14": (18.1, 12.55, 90, T),
    # column 2 (only where it stays outside the mic ring)
    "R15": (19.5, 10.6, 90, T), "C19": (19.5, 12.8, 90, T),
    "R1": (21.8, 12.6, 0, T), "C13": (24.5, 12.1, 0, T),
    "R13": (26.2, 13.6, 90, T), "D3": (28.0, 13.6, 90, T),
    "TP1": (28.2, 18.0, 0, T), "TP2": (28.2, 21.0, 0, T), "TP3": (28.2, 24.0, 0, T),
    # row right under the module (3V3 decoupling, EN RC, strap pull-ups)
    "C2": (8.5, 15.9, 0, T), "C3": (10.7, 15.9, 0, T),
    "R9": (13.0, 15.9, 0, T), "C15": (15.2, 15.9, 0, T),
    "R10": (13.0, 17.4, 0, T), "R18": (15.3, 17.4, 0, T),
    # TH headers: bottom-right corner, below the speaker, outside the battery
    "J3": (25.25, 46.15, 90, T), "J4": (28.25, 46.15, 90, T),
    # ---------- moved to FRONT (battery now covers the back down to y 42.5) ----------
    "U3": (3.0, 20.6, 180, T), "C16": (6.8, 20.6, 90, T),
    "U5": (3.6, 29.0, 0, T), "C5": (3.6, 34.3, 0, T),
    "U7": (8.9, 25.0, 0, T), "C4": (11.6, 25.0, 90, T), "C23": (8.9, 28.0, 0, T), "C1": (9.5, 30.5, 0, T),
    "L1": (14.6, 28.0, 90, T), "U2": (20.0, 28.0, 0, T),
    "C6": (18.8, 23.0, 0, T), "C7": (14.4, 22.6, 0, T), "C8": (23.6, 26.5, 90, T), "R3": (23.6, 23.0, 90, T),
    "D4": (20.0, 36.5, 0, T),
    # ---------- BACK: only below the battery ----------
    "F1": (8.3, 46.4, 90, B), "R8": (10.25, 44.3, 90, B),
    "R4": (21.2, 44.0, 90, B), "R5": (21.2, 46.3, 90, B),
    "D1": (22.9, 44.0, 90, B), "D2": (22.9, 45.8, 90, B),
}
FIXED = {"J1": B, "J2": B}
TH = {"J1", "J2", "J3", "J4"}            # through-hole: occupy both sides

W, H, EDGE, GAP = 30.0, 50.0, 0.3, 0.15
MIC = (24.5, 6.0, 5.0)
ZONES = {
    "antenna": ((0.0, 0.0, 5.5, 15.3), "BOTH"),
    "module-back": ((0.3, 0.5, 17.17, 14.83), B),   # Espressif: nothing under the module
    
    "battery": ((0.0, 2.0, 30.0, 42.5), B),
}

def rect(d, cx, cy, rot):
    w, h = size_mm(d, rot)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

R = {d: (rect(d, cx, cy, rot), side) for d, (cx, cy, rot, side) in PLAN.items()}
for d, side in FIXED.items():
    b = C[d]["bbox"]
    R[d] = ((b["minX"] * MIL, -b["maxY"] * MIL, b["maxX"] * MIL, -b["minY"] * MIL), side)

def sides(d, side):
    return {T, B} if d in TH else {side}

def ov(a, b, g=0.0):
    return a[0] < b[2] + g and b[0] < a[2] + g and a[1] < b[3] + g and b[1] < a[3] + g

def circle_hits(r, c):
    cx, cy, rad = c
    nx = min(max(cx, r[0]), r[2]); ny = min(max(cy, r[1]), r[3])
    return math.hypot(nx - cx, ny - cy) < rad

prob = []
names = list(R)
for i, a in enumerate(names):
    ra, sa = R[a]
    if a in PLAN and (ra[0] < EDGE - 0.05 or ra[1] < EDGE - 0.05 or ra[2] > W - EDGE + 0.05 or ra[3] > H - EDGE + 0.05):
        prob.append(f"{a} edge {tuple(round(v, 2) for v in ra)}")
    for b in names[i + 1:]:
        rb, sb = R[b]
        if sides(a, sa) & sides(b, sb) and ov(ra, rb, GAP):
            prob.append(f"{a} <-> {b}")
    for z, (zr, zs) in ZONES.items():
        if a == "U1" and z in ("antenna", "module-back"):
            continue
        if (zs == "BOTH" or zs in sides(a, sa)) and ov(ra, zr):
            prob.append(f"{a} in {z}")
    if T in sides(a, sa) and a != "U4" and circle_hits(ra, MIC):
        prob.append(f"{a} in mic ring")

print("unplanned:", sorted(set(C) - set(PLAN) - set(FIXED)))
print("\n".join(prob) or "OK: no overlap / edge / zone problems")
front = [d for d, (_, s) in R.items() if T in sides(d, s)]
back = [d for d, (_, s) in R.items() if B in sides(d, s)]
print(f"front parts {len(front)}, back parts {len(back)} (TH counted on both)")

json.dump([{"designator": d, "id": C[d]["primitiveId"], "rotation": rot, "side": side,
            "curRotation": C[d]["rotation"], "curLayer": C[d]["layer"],
            "cx_mil": round(cx / MIL, 2), "cy_mil": round(-cy / MIL, 2)}
           for d, (cx, cy, rot, side) in PLAN.items()],
          open("placement6.json", "w", encoding="utf-8"), indent=1)
ring = [[round((MIC[0] + MIC[2] * math.cos(a * math.pi / 12)) / MIL, 1),
         round(-(MIC[1] + MIC[2] * math.sin(a * math.pi / 12)) / MIL, 1)] for a in range(24)]
mm2mil = lambda r: [round(r[0] / MIL, 1), round(-r[3] / MIL, 1), round(r[2] / MIL, 1), round(-r[1] / MIL, 1)]
json.dump({"mic_ring_points_mil": ring,
           "speaker_rect_mil": None,
           "battery_rect_mil": mm2mil(ZONES["battery"][0]),
           "rects_mm": {d: [round(v, 2) for v in r] + [s] for d, (r, s) in R.items()}},
          open("zones6.json", "w", encoding="utf-8"), indent=1)
sys.exit(1 if prob else 0)





