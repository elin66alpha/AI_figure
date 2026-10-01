import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def read(n): return json.loads((ROOT/n).read_text(encoding='utf-8-sig'))
snap=read('peripheral-readback.json')
assert snap['ok']
parts=[c for c in snap['result']['components'] if c['componentType']=='part']
des={d['parentId']:d['bbox'] for d in read('peripheral-designators.json')['designators']}
sources={}
for n in ['core-library.json','peripheral-library.json','resistor-candidates.json']:
    sources.update({p['lcsc']:p for p in read(n)['result']['components']})
intent={
 'U1':{'9':'I2S_BCLK','10':'I2S_WS','12':'MIC_SD','13':'AMP_DIN','16':'AMP_CTRL'},
 'U3':{'1':None,'2':'GND','3':'SYS_SW','4':'SYS_SW','5':'3V3'},
 'C1':{'1':'SYS_SW','2':'GND'}, 'C2':{'1':'3V3','2':'GND'},
 'U4':{'1':'I2S_WS','2':'GND','3':'GND','4':'I2S_BCLK','5':'3V3','6':'MIC_SD'},
 'C3':{'1':'3V3','2':'GND'}, 'R1':{'1':'MIC_SD','2':'GND'},
 'U5':{'1':'AMP_CTRL','2':'I2S_WS','3':'I2S_BCLK','4':'AMP_DIN','5':'SPK_N','6':'3V3','7':'GND','8':'SPK_P','9':'GND'},
 'C4':{'1':'3V3','2':'GND'},'C5':{'1':'3V3','2':'GND'},'R2':{'1':'AMP_CTRL','2':'GND'},
}
modules=[('mcu','ESP32-C3','U1',[]),
 ('charger','Battery charger','U2',[]),
 ('ldo','3.3V regulator','U3',['C1','C2']),
 ('microphone','I2S microphone','U4',['C3','R1']),
 ('amplifier','I2S amplifier','U5',['C4','C5','R2']),
 ('usb','USB-C','J1',[]),
 ('crystal','40MHz crystal','Y1',[])]
components=[]; measurements=[]; connections=[]; nets=set()
for p in parts:
    ref=p['designator']; lib=sources[p['supplierId']]
    if p.get('deviceIdentityError'): raise ValueError(p['deviceIdentityError'])
    cp=[]; mp=[]
    for pin in p['pins']:
        num=pin['pinNumber']; mapped=intent.get(ref,{})
        c=dict(number=num,name=pin['pinName'])
        net=mapped.get(num,'')
        if num not in mapped: c['connectionState']='unconnected'
        elif net is None: c['noConnected']=True
        else:
            nets.add(net);connections.append(dict(componentId='cmp-'+ref,pinNumber=num,netId=net,kind='netlist'))
        cp.append(c)
        mp.append(dict(number=num,name=pin['pinName'],net=net or '',x=pin['x'],y=pin['y'],rotation=pin['rotation']))
    components.append(dict(id='cmp-'+ref,ref=ref,device=dict(libraryUuid=lib['libraryUuid'],deviceUuid=lib['uuid'],name=lib['manufacturerId']),pins=cp))
    measurements.append(dict(designator=ref,value=lib.get('value',lib['manufacturerId']),x=p['x'],y=p['y'],rotation=p['rotation'],mirror=p['mirror'],bbox=p['bbox'],pins=mp,textBboxes=[des[p['primitiveId']]]))
ir=dict(schemaVersion='1.4',projectId=snap['context']['projectUuid'],documentId=snap['context']['documentUuid'],components=components,
 nets=[dict(id=n,name=n) for n in sorted(nets)],connections=connections,modules=[])
layouts=[]
attach={'C1':('U3','4'),'C2':('U3','5'),'C3':('U4','5'),'R1':('U4','6'),'C4':('U5','6'),'C5':('U5','6'),'R2':('U5','1')}
for mid,title,core,per in modules:
    members=['cmp-'+r for r in [core]+per]
    ir['modules'].append(dict(id=mid,name=title,coreComponents=['cmp-'+core],peripheralComponents=['cmp-'+r for r in per],internalNets=[],ports=[]))
    used={c['netId'] for c in connections if c['componentId'] in members}
    policies={n:('local_ground' if n=='GND' else 'local_power' if n in ['3V3','SYS_SW'] else 'module_port') for n in used}
    layouts.append(dict(id=mid,title=title,coreComponentId='cmp-'+core,netPolicies=policies,peripherals=[dict(componentId='cmp-'+r,pinNumber='1',attachTo=dict(componentId='cmp-'+attach[r][0],pinNumber=attach[r][1])) for r in per]))
geom=read('sheet-geometry.json')['result']
data=dict(schemaVersion=1,connectivity=ir,sheet=geom['sheet']['bbox'],keepouts=[k['bbox'] for k in geom['keepouts']],measurements=measurements,layoutModules=layouts,maxCandidates=100000)
(ROOT/'audio-ldo-layout-input.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'{len(parts)} parts, {len(connections)} mapped pins; remaining pins explicitly unfinished')
