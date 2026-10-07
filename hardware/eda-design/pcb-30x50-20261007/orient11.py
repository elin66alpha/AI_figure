"""Choose 0/180-degree flips (bbox-preserving) per part to shorten critical pad pairs."""
import json, math, itertools

MIL = 0.0254
b = {c["designator"]: c for c in json.load(open("board11.json", encoding="utf-8"))["components"]}

def center(d):
    bb = b[d]["bbox"]; return ((bb["minX"] + bb["maxX"]) / 2, (bb["minY"] + bb["maxY"]) / 2)

PLAN = {}

def pads(d, flip):
    ox, oy = center(d)
    cx, cy = (PLAN[d]["cx_mil"], PLAN[d]["cy_mil"]) if d in PLAN else (ox, oy)
    out = []
    for p in b[d]["pads"]:
        x, y = p["x"] - ox + cx, p["y"] - oy + cy
        if flip:
            x, y = 2 * cx - x, 2 * cy - y
        out.append((p["net"], x, y))
    return out

def d_min(a, fa, na, c, fc, nc):
    best = 1e9
    for n1, x1, y1 in pads(a, fa):
        if n1 != na: continue
        for n2, x2, y2 in pads(c, fc):
            if n2 == nc:
                best = min(best, math.hypot(x1 - x2, y1 - y2) * MIL)
    return best

GROUPS = {
    "charger": (["U2", "L1", "C6", "C7", "C8", "R3"], [
        ("L1", "$1N181", "U2", "$1N181", 5), ("L1", "SYS", "U2", "SYS", 5),
        ("C6", "VBUS_CHG", "U2", "VBUS_CHG", 3), ("C6", "GND", "U2", "GND", 2),
        ("C7", "SYS", "U2", "SYS", 3), ("C7", "SYS", "L1", "SYS", 2),
        ("C8", "VBAT", "U2", "VBAT", 2), ("R3", "$1N189", "U2", "$1N189", 1)]),
    "ldo3v3": (["U3", "C16"], [
        ("C16", "3V3", "U3", "3V3", 3), ("C16", "GND", "U3", "GND", 2), ("U3", "3V3", "U1", "3V3", 1)]),
    "amp": (["U5", "U7", "C4", "C5", "C23", "C1"], [
        ("C5", "3V3_AMP", "U5", "3V3_AMP", 3), ("C5", "GND", "U5", "GND", 2),
        ("C4", "3V3_AMP", "U7", "3V3_AMP", 3), ("C23", "SYS", "U7", "SYS", 2),
        ("U7", "3V3_AMP", "U5", "3V3_AMP", 2), ("C1", "SYS", "U7", "SYS", 1), ("U5", "I2S_BCLK", "U1", "I2S_BCLK", 1)]),
    "usb": (["F1", "R8", "D1", "D2", "R4", "R5"], [
        ("F1", "VBUS_USB", "J1", "VBUS_USB", 2), ("R8", "$1N222", "F1", "$1N222", 2),
        ("D1", "USB_DP_CONN", "J1", "USB_DP_CONN", 2), ("D2", "USB_DM_CONN", "J1", "USB_DM_CONN", 2),
        ("R4", "USB_CC1", "J1", "USB_CC1", 1), ("R5", "USB_CC2", "J1", "USB_CC2", 1)]),
}

result = {}
for g, (parts, pairs) in GROUPS.items():
    best = None
    for flips in itertools.product([0, 1], repeat=len(parts)):
        f = dict(zip(parts, flips))
        cost = sum(w * d_min(a, f.get(a, 0), na, c, f.get(c, 0), nc) for a, na, c, nc, w in pairs)
        if best is None or cost < best[0]:
            best = (cost, f)
    base = sum(w * d_min(a, 0, na, c, 0, nc) for a, na, c, nc, w in pairs)
    print(f"{g}: cost {base:.1f} -> {best[0]:.1f}; flip {[p for p, v in best[1].items() if v]}")
    for a, na, c, nc, w in pairs:
        print(f"    {a}.{na}->{c}.{nc}: {d_min(a, 0, na, c, 0, nc):.1f} -> {d_min(a, best[1].get(a, 0), na, c, best[1].get(c, 0), nc):.1f} mm")
    result.update({p: v for p, v in best[1].items() if v})
json.dump(sorted(result), open("flips11.json", "w"))



