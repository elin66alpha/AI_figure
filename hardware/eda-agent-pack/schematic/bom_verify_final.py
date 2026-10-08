"""Audit saved schematic connectivity and export supplier identities from readback."""
import csv
import json
import re
import shutil
from pathlib import Path
from collections import defaultdict

root = Path(__file__).resolve().parent
def read(name):
    return json.loads((root / name).read_text(encoding='utf-8-sig'))
def parts(snapshot):
    return {c['designator']: c for c in snapshot['result']['components'] if c.get('designator')}
before, after = parts(read('before.json')), parts(read('final-readback.json'))
errors = []
if set(before) != set(after):
    errors.append('Designator set changed')
def pin_signature(c):
    pins = c['pins']
    if re.fullmatch(r'[RC]\d+', c['designator']):
        return sorted((p['net'], p['noConnected']) for p in pins)
    return sorted((p['pinNumber'], p['net'], p['noConnected']) for p in pins)
for ref, old in before.items():
    new = after[ref]
    if pin_signature(old) != pin_signature(new):
        errors.append({'ref': ref, 'before': pin_signature(old), 'after': pin_signature(new)})
    for key in ('uniqueId', 'addIntoBom', 'addIntoPcb'):
        if old.get(key) != new.get(key):
            errors.append(f'{ref}: {key} changed')
rc = [c for r,c in after.items() if re.fullmatch(r'[RC]\d+', r)]
small = [c for c in rc if '0402' in c['footprint']['name']]
for c in rc:
    if not c.get('otherProperty', {}).get('Value'):
        errors.append(f"Missing value: {c['designator']}")
changed = []
for ref, c in after.items():
    if c.get('supplierId') != before[ref].get('supplierId'):
        changed.append({'ref':ref,'old_code':before[ref].get('supplierId'), 'new_code':c.get('supplierId'), 'mpn':c['manufacturerId'], 'footprint':c['footprint']['name'], 'value':c['otherProperty'].get('Value'), 'properties':c['otherProperty']})
(root / 'changes.json').write_text(json.dumps(changed,ensure_ascii=False,indent=2),encoding='utf-8')
audit = {'errors':errors,'parts':len(after),'bom_instances':sum(bool(c.get('addIntoBom')) for c in after.values()),'rc_instances':len(rc),'rc_0402':len(small),'changed_instances':len(changed),'microphone_unchanged':after['U4']['supplierId']==before['U4']['supplierId'],'larger_capacitors':[c['designator'] for c in rc if c not in small]}
(root / 'final-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(audit,ensure_ascii=False,indent=2))
if errors:
    raise SystemExit('Connectivity / identity audit failed')
groups = defaultdict(list)
for ref,c in after.items():
    if c.get('addIntoBom'):
        key=(c['supplierId'],c['manufacturer'],c['manufacturerId'],c['footprint']['name'],c['otherProperty'].get('Value',''))
        groups[key].append(ref)
target = root.parent.parent / 'BOM' / 'BOM_0402_2026-10-05.csv'
with target.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f)
    w.writerow(['LCSC Part Number','Manufacturer','Manufacturer Part Number','Footprint','Value','Quantity','Designator'])
    for (code,maker,mpn,pkg,value),refs in groups.items():
        w.writerow([code,maker,mpn,pkg,value,len(refs),','.join(refs)])
print(f'Exported {len(groups)} procurement rows: {target}')
native_path = Path(read('native-bom-export.json')['result']['artifactPath'])
native_encoding = 'utf-16' if native_path.read_bytes().startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
with native_path.open(encoding=native_encoding,newline='') as f:
    native_rows = list(csv.DictReader(f,delimiter='\t'))
native_refs = {}
for row in native_rows:
    refs = row['Designator'].split(',')
    assert len(refs) == int(row['Quantity']), row
    for ref in refs:
        native_refs[ref] = row
expected_refs = {r for r,c in after.items() if c.get('addIntoBom')}
assert set(native_refs) == expected_refs, 'Native BOM reference set differs'
for ref, row in native_refs.items():
    c = after[ref]
    assert row['Supplier Part'] == c['supplierId'], (ref,'supplier')
    assert row['Manufacturer Part'] == c['manufacturerId'], (ref,'mpn')
    assert row['Footprint'] == c['footprint']['name'], (ref,'footprint')
    assert row['Value'] == c['otherProperty'].get('Value',''), (ref,'value')
shutil.copyfile(native_path,root/'native-bom.tsv')
audit.update({'native_bom_matches_saved_readback':True,'procurement_rows':len(groups)})
(root / 'final-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
print('Native BOM and procurement CSV agree with saved readback for every reference.')
