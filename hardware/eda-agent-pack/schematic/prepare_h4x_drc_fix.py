import json
from pathlib import Path
p=Path(__file__).parent
def read(n):return json.loads((p/n).read_text(encoding='utf-8-sig'))
s=read('h4x-before-drc-fix.json')
assert s['ok'] and s['result']['pinNetsAvailable']
target_ids=['3c674cac21ac6829','c5cdac816d9bebfc','c227e06341eb3333']
assert set(target_ids).issubset({w['primitiveId'] for w in s['result']['wires']})
b=read('h4x-buses.playbook.json')
wire_steps=[]
for old in b['steps']:
    if old.get('action')=='schematic.wire.create':
        step=json.loads(json.dumps(old))
        step['payload'].pop('net')
        wire_steps.append(step)
steps=[{'id':'remove-multiply-named-wire-trees','run':'sch prim-delete','flags':{'ids':','.join(target_ids)}}]+wire_steps
steps.append({'id':'save','action':'schematic.save','payload':{}})
(p/'h4x-drc-fix.playbook.json').write_text(json.dumps({'version':1,'meta':{'name':'Rebuild H4X buses using one existing flag name per tree','project':s['context']['projectUuid'],'doc':s['context']['documentUuid']},'steps':steps},indent=2),encoding='utf-8')
(p/'h4x-canonical-name.json').write_text(json.dumps({'name':read('h4x-device-20261004.json')['result']['device']['property']['otherProperty']['Name']},indent=2),encoding='utf-8')
print('Prepared',len(wire_steps),'wire branches without explicit per-branch name attributes')
