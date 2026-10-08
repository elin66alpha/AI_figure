import json
from pathlib import Path

p = Path(__file__).parent
def read(n): return json.loads((p/n).read_text(encoding='utf-8-sig'))
snap = read('h4x-placed-pins.json')
assert snap['ok'] and snap['result']['pinNetsAvailable']
u = next(c for c in snap['result']['components'] if c.get('designator') == 'U1')
pins = {v['pinNumber']: v for v in u['pins']}
assert len(pins) == 53 and u['uniqueId'] == 'gge1'
bus_x, flag_y = 570, 1310
steps = [{'id': 'replace-long-decoupling-buses', 'run': 'sch prim-delete', 'flags': {'ids': 'bfc7e2d98b438813,a744284dd5d6a047'}}]
paths = [('cap-power', '3V3', [[520,1110],[520,1130],[620,1130],[620,1150]]), ('cap-power-branch', '3V3', [[620,1110],[620,1130]]), ('cap-ground', 'GND', [[520,1070],[520,1050],[620,1050],[620,1030]]), ('cap-ground-branch', 'GND', [[620,1070],[620,1050]])]
paths.append(('module-ground-trunk', 'GND', [[bus_x,flag_y],[bus_x,1500]]))
for n, net, points in paths:
    steps.append({'id': n, 'action': 'schematic.wire.create', 'payload': {'points': points, 'net': net}})
steps.append({'id': 'module-ground-flag', 'run': 'sch netflag', 'flags': {'kind':'gnd','net':'GND','x':bus_x,'y':flag_y,'rotation':0}})
for number in range(36,54):
    pin=pins[str(number)]
    assert pin['pinName']=='GND' and pin['x']==530 and pin['rotation']==0 and pin['y']>=1330
    steps.append({'id': 'ground-pin-'+str(number), 'action':'schematic.wire.create','payload':{'points':[[pin['x'],pin['y']],[bus_x,pin['y']]],'net':'GND'}})
steps.append({'id':'save','action':'schematic.save','payload':{}})
meta={'name':'H4X shared ground and compact retained decoupling', 'project':snap['context']['projectUuid'],'doc':snap['context']['documentUuid']}
(p/'h4x-buses.playbook.json').write_text(json.dumps({'version':1,'meta':meta,'steps':steps},indent=2),encoding='utf-8')
spec=read('h4x-connections.json')
spec['connections']=[c for c in spec['connections'] if int(c['pin'].split(':')[1])<36]
(p/'h4x-signal-connections.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
print('Planned ground bus for 18 pins, 4 compact capacitor wire branches, and',len(spec['connections']),'remaining pin connections')
