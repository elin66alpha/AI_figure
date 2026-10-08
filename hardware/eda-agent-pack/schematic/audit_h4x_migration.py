import json
from pathlib import Path
p=Path(__file__).parent
def read(n):return json.loads((p/n).read_text(encoding='utf-8-sig'))
b=read('h4x-before-20261004.json')['result']
response=read('h4x-final-readback.json')
assert response['ok']
a=response['result']
assert a['pinNetsAvailable'] and a['wiresAvailable']
plan=read('h4x-migration-plan-20261004.json')
before={c['designator']:c for c in b['components'] if c.get('designator')}
after={c['designator']:c for c in a['components'] if c.get('designator')}
errors=[]
def check(condition, message):
    if not condition:errors.append(message)
removed={c['designator'] for c in plan['removeParts']}
check(set(after)==set(before)-removed,'Unexpected component additions/deletions')
checked=0
for ref in plan['protectedParts']:
    old,new=before[ref],after.get(ref,{})
    for key in ['primitiveId','uniqueId','x','y','rotation','mirror','manufacturer','manufacturerId','supplier','supplierId','symbol','footprint','otherProperty','addIntoBom','addIntoPcb']:
        check(old.get(key)==new.get(key),f'{ref}: changed {key}')
    oldpins={pin['pinNumber']:pin for pin in old['pins']}
    newpins={pin['pinNumber']:pin for pin in new.get('pins',[])}
    check(set(oldpins)==set(newpins),f'{ref}: pin inventory changed')
    for n,oldpin in oldpins.items():
        newpin=newpins.get(n,{})
        for key in ['net','noConnected','x','y','rotation','pinName','otherProperty']:
            check(oldpin.get(key)==newpin.get(key),f'{ref}:{n}: changed {key}')
        checked+=1
u=after['U1']
check(u['uniqueId']==before['U1']['uniqueId'],'U1 association changed')
check(u['manufacturerId']=='ESP32-C3-MINI-1-H4X' and u['supplierId']=='C41349510','U1 identity mismatch')
check(u['footprint']['name']=='WIFIM-SMD_ESP32-C3-MINI-1','U1 footprint mismatch')
pins={pin['pinNumber']:pin for pin in u['pins']}
check(set(pins)=={str(n) for n in range(1,54)},'U1 pin inventory mismatch')
for n,net in plan['pinToNet'].items():
    check(pins[n]['net']==net and pins[n]['noConnected'] is False,f'U1:{n}: expected {net}')
for n in plan['noConnectPins']:
    check(pins[str(n)]['net']=='' and pins[str(n)]['noConnected'] is True,f'U1:{n}: expected NC')
report={'passed':not errors,'beforeParts':len(before),'afterParts':len(after),'removedParts':sorted(removed),'protectedParts':len(plan['protectedParts']),'protectedPins':checked,'modulePins':len(pins),'connectedModulePins':len(plan['pinToNet']),'moduleNC':len(plan['noConnectPins']),'groundModulePins':sum(pin['net']=='GND' for pin in pins.values()),'freshReadbackCreatedAt':response['createdAt'],'errors':errors}
(p/'h4x-pin-intent-audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(report,indent=2,ensure_ascii=False))
assert not errors
