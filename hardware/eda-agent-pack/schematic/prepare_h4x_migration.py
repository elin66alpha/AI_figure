import json
from pathlib import Path

ROOT = Path(__file__).parent
SOURCE = ROOT / 'h4x-before-20261004.json'
before = json.loads(SOURCE.read_text(encoding='utf-8-sig'))
assert before['ok'] and before['result']['pinNetsAvailable']
data = before['result']
parts = {c['designator']: c for c in data['components'] if c.get('designator')}
remove = ['Y1', 'C17', 'C18', 'L2', 'L3', 'C20', 'C21', 'J4', 'C9', 'C10', 'C11', 'C12', 'C14']
old_owner = set(remove + ['U1'])
assert parts['U1']['supplierId'] == 'C2858491'
assert all(ref in parts for ref in remove)
segments = data['wires']
wire_ids = list(dict.fromkeys(w['primitiveId'] for w in segments))
parent = {pid: pid for pid in wire_ids}

def find(pid):
    while parent[pid] != pid:
        parent[pid] = parent[parent[pid]]
        pid = parent[pid]
    return pid

def on(x, y, s):
    if abs(s['x0'] - s['x1']) < 1e-5:
        return abs(x - s['x0']) < 1e-5 and min(s['y0'], s['y1']) - 1e-5 <= y <= max(s['y0'], s['y1']) + 1e-5
    assert abs(s['y0'] - s['y1']) < 1e-5, s
    return abs(y - s['y0']) < 1e-5 and min(s['x0'], s['x1']) - 1e-5 <= x <= max(s['x0'], s['x1']) + 1e-5

for i, a in enumerate(segments):
    for b in segments[i+1:]:
        # Endpoint/T/collinear contact joins trees; interior X alone does not.
        if any(on(x, y, b) for x, y in [(a['x0'], a['y0']), (a['x1'], a['y1'])]) or any(on(x, y, a) for x, y in [(b['x0'], b['y0']), (b['x1'], b['y1'])]):
            parent[find(a['primitiveId'])] = find(b['primitiveId'])
trees = {}
for s in segments:
    trees.setdefault(find(s['primitiveId']), {'wireIds': set(), 'segments': [], 'pins': [], 'markers': []})
    trees[find(s['primitiveId'])]['wireIds'].add(s['primitiveId'])
    trees[find(s['primitiveId'])]['segments'].append(s)
for t in trees.values():
    for ref, c in parts.items():
        for p in c.get('pins', []):
            if any(on(p['x'], p['y'], s) for s in t['segments']):
                t['pins'].append({'ref': ref, 'pin': p['pinNumber'], 'net': p['net']})
    for c in data['pagePrimitives']['components']:
        if c['componentType'] in ['netflag', 'netport'] and any(on(c['x'], c['y'], s) for s in t['segments']):
            t['markers'].append(c['primitiveId'])
exclusive = [t for t in trees.values() if t['pins'] and all(p['ref'] in old_owner for p in t['pins'])]
shared = [t for t in trees.values() if any(p['ref'] in old_owner for p in t['pins']) and any(p['ref'] not in old_owner for p in t['pins'])]
delete_wires = sorted({pid for t in exclusive for pid in t['wireIds']})
delete_markers = sorted({pid for t in exclusive for pid in t['markers']})
mapping = {'3': '3V3', '5': 'BOOT_GPIO2', '6': 'REC_KEY', '8': 'CHIP_EN', '13': 'SYS_ADC', '16': 'AMP_CTRL', '18': 'I2S_BCLK', '19': 'I2S_WS', '20': 'MIC_SD', '21': 'AMP_DIN', '22': 'LED_GPIO8', '23': 'BOOT_GPIO9', '26': 'USB_DM', '27': 'USB_DP', '30': 'UART_RX', '31': 'UART_TX'}
ground = [1, 2, 11, 14, *range(36, 54)]
nc = [4, 7, 9, 10, 12, 15, 17, 24, 25, 28, 29, 32, 33, 34, 35]
for pin in ground:
    mapping[str(pin)] = 'GND'
assert set(mapping) | {str(p) for p in nc} == {str(p) for p in range(1, 54)}
assert not set(mapping) & {str(p) for p in nc}
plan = {'status': 'source-only', 'source': SOURCE.name, 'project': before['context']['projectUuid'], 'doc': before['context']['documentUuid'], 'module': {'mpn': 'ESP32-C3-MINI-1-H4X', 'lcsc': 'C41349510'}, 'replace': {'id': parts['U1']['primitiveId'], 'uniqueId': parts['U1']['uniqueId']}, 'removeParts': [{k: parts[r][k] for k in ['designator', 'primitiveId', 'uniqueId', 'supplierId']} for r in remove], 'deleteExclusiveWireIds': delete_wires, 'deleteExclusiveMarkerIds': delete_markers, 'exclusiveTrees': [{k: sorted(v) if isinstance(v, set) else v for k, v in t.items() if k != 'segments'} for t in exclusive], 'sharedTrees': [{k: sorted(v) if isinstance(v, set) else v for k, v in t.items() if k != 'segments'} for t in shared], 'pinToNet': mapping, 'noConnectPins': nc, 'retainDecoupling': ['C13', 'C16'], 'protectedParts': [r for r in parts if r not in old_owner], 'datasheet': 'https://documentation.espressif.com/esp32-c3-mini-1_datasheet_cn.html'}
(ROOT/'h4x-migration-plan-20261004.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
cleanup = {'version': 1, 'meta': {'name': 'Remove verified exclusive bare ESP32 circuitry and stubs', 'project': plan['project'], 'doc': plan['doc']}, 'steps': [{'id': 'remove-old-exclusive-wires-and-markers', 'run': 'sch prim-delete', 'flags': {'ids': ','.join(delete_wires + delete_markers)}}, {'id': 'remove-integrated-peripherals', 'run': 'sch prim-delete', 'flags': {'ids': ','.join(parts[r]['primitiveId'] for r in remove)}}, {'id': 'save', 'action': 'schematic.save', 'payload': {}}]}
(ROOT/'h4x-cleanup.playbook.json').write_text(json.dumps(cleanup, indent=2), encoding='utf-8')
connections = [{'pin': 'U1:'+pin, 'kind': 'gnd' if net == 'GND' else 'power' if net == '3V3' else 'netport', 'net': net} for pin, net in mapping.items()]
(ROOT/'h4x-connections.json').write_text(json.dumps({'connections': connections, 'rules': {'avoidTitleBlock': True, 'avoidPinFanout': True, 'staggerLabels': True, 'offsetRange': [20, 80], 'offsetStep': 5, 'minLabelGap': 12}}, indent=2), encoding='utf-8')
print(json.dumps({'parts': len(parts), 'remove': remove, 'exclusiveWires': len(delete_wires), 'exclusiveMarkers': len(delete_markers), 'sharedTrees': plan['sharedTrees'], 'moduleConnections': len(mapping), 'moduleNC': len(nc)}, ensure_ascii=False, indent=2))
