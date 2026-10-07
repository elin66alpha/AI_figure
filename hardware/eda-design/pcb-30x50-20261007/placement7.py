"""Front battery (500 mAh, 30x30x6) + USB-C in the middle of the back.

mm, front-view coordinates, origin board top-left, y down.
  FRONT: U1 + mic + small parts around the module; TH headers in the strip
         between module and battery; battery x 0-30, y 19.5-50.
  BACK : J1 centred, USB protection + charger around it, amp left, 3V3 LDO and
         module-pin passives under the module edge, test pads beside the module.
Writes placement7.json and zones7.json.
"""
import json, math, sys

MIL = 0.0254
board = json.load(open("board17.json", encoding="utf-8"))
C = {c["designator"]: c for c in board["components"]}

def size_mm(d, rot):
    c = C[d]; b = c["bbox"]
    w = (b["maxX"] - b["minX"]) * MIL; h = (b["maxY"] - b["minY"]) * MIL
    if (c["rotation"] - rot) % 180:
        w, h = h, w
    return w, h

T, B = "TOP", "BOTTOM"
PLAN = {
    # ---------- FRONT: module, mic, parts that hug the module ----------
    "U1": (8.725, 7.67, 90, T),
    "U4": (24.5, 6.0, 180, T),
    "R6": (18.1, 1.55, 90, T), "R7": (18.1, 3.75, 90, T),
    "R12": (18.1, 5.95, 90, T), "R11": (18.1, 8.15, 90, T),
    "R2": (18.1, 10.35, 90, T), "R14": (18.1, 12.55, 90, T),
    "R15": (19.5, 10.6, 90, T), "C19": (19.5, 12.8, 90, T),
    "R1": (21.8, 12.6, 0, T), "C13": (24.5, 12.1, 0, T),
    "R13": (26.2, 13.6, 90, T), "D3": (28.0, 13.6, 90, T),
    # TH headers in the strip between module and battery (pins stay out of the battery on both sides)
    "J4": (3.25, 17.3, 0, T), "J2": (20.85, 17.3, 0, T), "J3": (26.55, 17.3, 0, T),
    # ---------- BACK ----------
    # module-pin passives right under the module edge (3V3 / EN / straps)
    "C2": (8.5, 16.0, 0, B), "C3": (10.7, 16.0, 0, B),
    "R9": (13.0, 16.0, 0, B), "C15": (15.2, 16.0, 0, B),
    "R10": (13.0, 17.5, 0, B), "R18": (15.3, 17.5, 0, B),
    "U3": (8.5, 21.0, 180, B), "C16": (12.3, 21.0, 90, B),
    # test pads beside the module (back stays reachable with the battery on the front)
    "TP1": (27.9, 2.0, 0, B), "TP2": (27.9, 5.2, 0, B), "TP3": (27.9, 8.4, 0, B),
    # USB-C in the middle + protection
    "J1": (15.0, 30.0, 180, B),
    "R4": (7.6, 28.3, 90, B), "R5": (7.6, 31.7, 90, B),
    "D1": (9.3, 28.6, 90, B), "D2": (9.3, 31.4, 90, B),
    "F1": (21.0, 30.0, 90, B), "R8": (23.0, 30.0, 90, B), "D4": (25.0, 30.0, 90, B),
    # amplifier block, left
    "U7": (2.4, 22.5, 180, B), "C4": (4.8, 22.5, 90, B), "C23": (2.4, 25.4, 0, B),
    "U5": (3.6, 30.5, 180, B), "C5": (3.6, 35.6, 0, B),
    # charger block below J1
    "C6": (17.3, 35.3, 0, B), "C7": (12.6, 35.3, 180, B),
    "L1": (12.6, 40.5, 270, B), "U2": (18.0, 40.5, 0, B),
    "C8": (22.4, 38.0, 90, B), "R3": (22.4, 41.0, 270, B),
    "C1": (12.6, 46.0, 0, B),
}
TH = {"J1", "J2", "J3", "J4"}

W, H, EDGE, GAP = 30.0, 50.0, 0.3, 0.15
MIC = (24.5, 6.0, 5.0)
ZONES = {
    "antenna": ((0.0, 0.0, 5.5, 15.3), "BOTH"),
    "module-back": ((0.3, 0.5, 17.17, 14.83), B),
    "battery": ((0.0, 19.5, 30.0, 50.0), T),
}

def rect(d, cx, cy, rot):
    w, h = size_mm(d, rot)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

R = {d: (rect(d, cx, cy, rot), side) for d, (cx, cy, rot, side) in PLAN.items()}
sides = lambda d, s: {T, B} if d in TH else {s}
ov = lambda a, b, g=0.0: a[0] < b[2] + g and b[0] < a[2] + g and a[1] < b[3] + g and b[1] < a[3] + g

def circle_hits(r, c):
    nx = min(max(c[0], r[0]), r[2]); ny = min(max(c[1], r[1]), r[3])
    return math.hypot(nx - c[0], ny - c[1]) < c[2]

prob = []
names = list(R)
for i, a in enumerate(names):
    ra, sa = R[a]
    if ra[0] < EDGE - 0.05 or ra[1] < EDGE - 0.05 or ra[2] > W - EDGE + 0.05 or ra[3] > H - EDGE + 0.05:
        prob.append(f"{a} edge {tuple(round(v, 2) for v in ra)}")
    for b in names[i + 1:]:
        rb, sb = R[b]
        if sides(a, sa) & sides(b, sb) and ov(ra, rb, GAP):
            prob.append(f"{a} <-> {b}")
    for z, (zr, zs) in ZONES.items():
        if a == "U1" and z in ("antenna", "module-back"):
            continue
        if (zs == "BOTH" or zs in sides(a, sa)) and ov(ra, zr):
            if not (a == "J1" and z == "battery"):   # J1 body is on the back; its leg tips need tape
                prob.append(f"{a} in {z}")
    if T in sides(a, sa) and a not in ("U4", "J1") and circle_hits(ra, MIC):
        prob.append(f"{a} in mic ring")

print("unplanned:", sorted(set(C) - set(PLAN)))
print("\n".join(prob) or "OK: no overlap / edge / zone problems")
print(f"front {sum(1 for d,(r,s) in R.items() if T in sides(d,s))}, back {sum(1 for d,(r,s) in R.items() if B in sides(d,s))} (TH on both)")
json.dump([{"designator": d, "rotation": rot, "side": side,
            "cx_mil": round(cx / MIL, 2), "cy_mil": round(-cy / MIL, 2)}
           for d, (cx, cy, rot, side) in PLAN.items()],
          open("placement7.json", "w", encoding="utf-8"), indent=1)
mm2mil = lambda r: [round(r[0] / MIL, 1), round(-r[3] / MIL, 1), round(r[2] / MIL, 1), round(-r[1] / MIL, 1)]
json.dump({"battery_rect_mil": mm2mil(ZONES["battery"][0])}, open("zones7.json", "w"), indent=1)
sys.exit(1 if prob else 0)
