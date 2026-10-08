"""Prepare typed property patches from the supplier identities read from EDA."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
current = json.loads((ROOT / "after-bulk-stock.json").read_text(encoding="utf-8-sig"))["result"]["components"]
old = {c["designator"]: c for c in json.loads((ROOT / "before.json").read_text(encoding="utf-8-sig"))["result"]["components"] if c.get("designator")}
steps = []
manifest = []
for c in current:
    ref = c.get("designator")
    if not ref or ref not in old or c.get("supplierId") == old[ref].get("supplierId"):
        continue
    code = c["supplierId"]
    pkg = c["footprint"]["name"]
    props = {"Supplier Footprint": pkg}
    if ref.startswith("R"):
        value = old[ref]["otherProperty"]["Value"]
        props.update({"Value": value, "Tolerance": "±1%", "Power(Watts)": "0.0625W", "Voltage-Supply(Max)": "50V", "Description": f"厚膜电阻 {value}, 0402, ±1%, 62.5mW"})
        if ref == "R8":
            props.update({"Jumper Rated Current": "1A", "Description": "0Ω jumper, 0402, rated current 1A (same as previous 0603 family)"})
    elif ref.startswith("C"):
        if code == "C1525":
            value, voltage, dielectric = "100nF", "16V", "X7R"
        elif code == "C52923":
            value, voltage, dielectric = "1uF", "25V", "X5R"
        elif code == "C307418":
            value, voltage, dielectric = "2.2uF", "25V", "X5R"
        elif code == "C19103847":
            value, voltage, dielectric = "10uF", "25V", "X5R"
        else:
            raise ValueError(f"Unreviewed capacitor {ref}: {code}")
        props.update({"Value": value, "Tolerance": "±10%", "Voltage Rating": voltage, "Temperature Coefficient": dielectric, "Description": f"{value}, {voltage}, {dielectric}, ±10%, {pkg}"})
    elif ref == "Q1":
        value = "8205A"
        props.update({"Value": value, "Description": "Dual N-MOS, common drain, TSSOP-8, 20V; Rds(on) max 25mΩ @4.5V / 30mΩ @2.5V per FET", "Datasheet": "https://item.szlcsc.com/datasheet/8205A/8392681.html"})
    else:
        raise ValueError(f"Unexpected changed component {ref}")
    patch_path = ROOT / f"properties-{ref}.json"
    patch_path.write_text(json.dumps({"name": "={Value}", "otherProperty": props}, ensure_ascii=False, indent=2), encoding="utf-8")
    steps.append({"id": f"properties-{ref}", "run": "sch modify", "flags": {"id": c["primitiveId"], "patch-file": str(patch_path)}})
    manifest.append({"ref": ref, "old_code": old[ref].get("supplierId"), "new_code": code, "mpn": c["manufacturerId"], "footprint": pkg, "value": value, "properties": props})
playbook = {"version": 1, "meta": {"name": "Restore verified BOM values after library replacements", "project": "8c5d0d86032348a0a6c85102fe97607e", "doc": "98cfe13509bc1f5c"}, "steps": steps}
(ROOT / "properties.playbook.json").write_text(json.dumps(playbook, ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "changes.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Prepared {len(steps)} component patches; source supplier IDs are live readback identities.")
