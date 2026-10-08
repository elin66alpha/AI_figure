import json,sys
from pathlib import Path
root=Path(__file__).parent;p=json.loads((root/sys.argv[1]).read_text(encoding='utf-8-sig'));steps=[]
if p.get('deleteIds'):
    steps.append({'id':'replace-measured-old-routing','action':'pcb.route.delete','payload':{'primitiveIds':p['deleteIds']},'assert':{'$.count':'exists'}})
for m in p.get('componentMoves',[]):
    assert m['designator'].startswith(('R','C')) or m['designator'] in {'D1','D2'}
    steps.append({'id':'move-'+m['designator'],'action':'pcb.component.modify','payload':{'primitiveId':m['primitiveId'],'patch':{k:m[k] for k in ['x','y','rotation'] if k in m}},'assert':{'$.verified':'true'}})
for v in p['vias']:
    steps.append({'id':v['id'],'action':'pcb.via.create','payload':{'x':v['x'],'y':v['y'],'net':v['net'],'holeDiameter':p['viaDrillMil'],'diameter':p['viaDiameterMil']},'assert':{'$.primitiveId':'exists'},'capture':{v['id'].replace('-','_'):'$.primitiveId'}})
for r in p['routes']:
    for n,(a,c) in enumerate(zip(r['points'],r['points'][1:])):
        if a==c:continue
        rid=f"{r['id']}-{n+1}";steps.append({'id':rid,'action':'pcb.line.create','payload':{'startX':a[0],'startY':a[1],'endX':c[0],'endY':c[1],'lineWidth':r['width'],'layer':r['layer'],'net':r['net']},'assert':{'$.primitiveId':'exists'}})
steps.append({'id':'save','action':'pcb.save','assert':{'$.saved':'true'}})
out=root/(Path(sys.argv[1]).stem+'.apply.json');out.write_text(json.dumps({'version':1,'meta':{'name':Path(sys.argv[1]).stem,'project':'8c5d0d86032348a0a6c85102fe97607e','doc':'f39f5125c569691f'},'steps':steps},indent=2));print(f'{len(steps)} typed steps -> {out.name}')
