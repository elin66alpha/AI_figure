"""30x50 placement plan (mm; origin = board top-left, y down) + offline checks.

Writes placement.json: [{designator, id, rotation, cx_mil, cy_mil}] for `pcb modify`.
Sizes come from the live dump (bbox at the part's current rotation, swapped for 90/270).
"""
import json, sys

MIL = 0.0254
board = json.load(open("board2.json", encoding="utf-8"))
C = {c["designator"]: c for c in board["components"]}

def size_mm(d, rot):
    c = C[d]; b = c["bbox"]
    w = (b["maxX"] - b["minX"]) * MIL; h = (b["maxY"] - b["minY"]) * MIL
    if (c["rotation"] - rot) % 180:  # quarter turn swaps the box
        w, h = h, w
    return w, h

# designator: (cx, cy, rotation)  -- TOP side unless noted
PLAN = {
    # top band: module top-left (antenna = pad-free left end on the corner)
    "U1": (8.725, 7.67, 90),
    "R6": (18.1, 1.6, 90), "R7": (19.4, 1.6, 90),          # USB series R at chip side
    "D3": (22.2, 1.5, 180), "R13": (19.0, 3.4, 0),
    "U4": (25.9, 3.0, 180), "C13": (23.6, 4.6, 90), "R1": (22.1, 4.6, 90),
    "R11": (19.0, 4.8, 0), "R12": (19.0, 6.2, 0), "R2": (19.0, 8.8, 0),
    "R14": (19.0, 10.2, 0), "R15": (19.0, 11.6, 0), "C19": (19.0, 13.0, 0),
    "TP1": (27.9, 7.0, 0), "TP2": (27.9, 10.0, 0), "TP3": (27.9, 13.0, 0),
    # just below the module: 3V3 decoupling, EN RC, strap pull-ups
    "C2": (8.5, 15.6, 0), "C3": (10.7, 15.6, 0),
    "R9": (13.0, 15.6, 0), "C15": (15.2, 15.6, 0),
    "R10": (13.0, 17.0, 0), "R18": (15.3, 17.0, 0),
    "J4": (28.2, 18.0, 90),
    # 3V3 LDO
    "U3": (9.4, 20.0, 0), "C16": (5.6, 19.0, 90),
    # audio: amp + its LDO + bulk, outputs facing J3 (bottom-left)
    "U5": (4.0, 26.9, 180), "U7": (9.4, 26.0, 0), "C23": (12.0, 25.5, 90),
    "C4": (9.0, 29.0, 0), "C5": (4.0, 32.0, 0),
    # charger
    "C6": (15.0, 22.4, 0), "C7": (20.0, 22.0, 0),
    "L1": (15.0, 27.0, 270), "U2": (20.5, 27.0, 0),
    "C1": (25.9, 26.0, 90), "R3": (24.1, 25.5, 90), "C8": (24.1, 29.6, 90),
    "D4": (20.0, 33.5, 0),
    # USB input protection, right above J1 (J1 is on the back)
    "F1": (13.5, 38.0, 0), "R8": (17.3, 38.0, 0),
    "R4": (11.2, 40.3, 0), "R5": (13.4, 40.3, 0), "D1": (15.3, 40.3, 0), "D2": (16.9, 40.3, 0),
}
FIXED = ["J1", "J2", "J3"]  # user-placed; J1/J2 back, J3 front (TH)

W, H, EDGE, GAP = 30.0, 50.0, 0.3, 0.15

def rect_of_fixed(d):
    b = C[d]["bbox"]
    return (b["minX"] * MIL, -b["maxY"] * MIL, b["maxX"] * MIL, -b["minY"] * MIL)

rects = {}
for d, (cx, cy, rot) in PLAN.items():
    w, h = size_mm(d, rot)
    rects[d] = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
front_keepouts = {
    "antenna": (0.0, 0.0, 6.6, 14.9),            # pad-free module end, all layers
    "J1-TH": rect_of_fixed("J1"), "J2-TH": rect_of_fixed("J2"), "J3": rect_of_fixed("J3"),
}

def overlap(a, b, gap=0.0):
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap

problems = []
names = list(rects)
for i, a in enumerate(names):
    r = rects[a]
    if r[0] < EDGE - 0.05 or r[1] < EDGE - 0.35 or r[2] > W - EDGE or r[3] > H - EDGE:
        problems.append(f"{a} too close to board edge {tuple(round(v,2) for v in r)}")
    for b in names[i + 1:]:
        if overlap(r, rects[b], GAP):
            problems.append(f"{a} <-> {b} overlap/too close")
    for k, ko in front_keepouts.items():
        if a == "U1" and k == "antenna":
            continue
        if overlap(r, ko):
            problems.append(f"{a} intrudes {k}")

missing = sorted(set(C) - set(PLAN) - set(FIXED))
print("unplanned parts:", missing)
print("\n".join(problems) or "no overlaps / edge / keep-out problems")

out = []
for d, (cx, cy, rot) in PLAN.items():
    out.append({"designator": d, "id": C[d]["primitiveId"], "rotation": rot,
                "currentRotation": C[d]["rotation"], "layer": C[d]["layer"],
                "cx_mil": round(cx / MIL, 2), "cy_mil": round(-cy / MIL, 2)})
json.dump(out, open("placement.json", "w", encoding="utf-8"), indent=1)
json.dump({k: [round(v, 3) for v in r] for k, r in {**rects, **front_keepouts}.items()},
          open("placement-rects.json", "w", encoding="utf-8"), indent=1)
sys.exit(1 if problems or missing else 0)
