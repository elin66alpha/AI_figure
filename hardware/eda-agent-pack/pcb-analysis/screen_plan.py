import json,runpy,contextlib,io,sys,math
from pathlib import Path
root=Path(__file__).parent;args=sys.argv[:];planfile=args[1];boardfile=args[2];dsnfile=args[3] if len(args)>3 else 'dsn-corner-verified.json'
sys.argv=[str(root/'verify_corner_connectivity.py'),boardfile,dsnfile,Path(planfile).stem+'-baseline-connection.json']
with contextlib.redirect_stdout(io.StringIO()):g=runpy.run_path(str(root/'verify_corner_connectivity.py'))
sys.argv=args;p=json.loads((root/planfile).read_text(encoding='utf-8-sig'));deletions=set(p.get('deleteIds',[]));g['objects'][:]=[o for o in g['objects'] if o['id'] not in deletions];objects=g['objects'];add=g['add'];distance=g['distance'];before=len(objects);new=[];issues=[];holes=[]
for m in p.get('componentMoves',[]):
    c=next(c for c in g['b']['components'] if c['primitiveId']==m['primitiveId'])
    assert c['designator']==m['designator'] and (c['designator'].startswith(('R','C')) or c['designator'] in {'D1','D2'})
    angle=math.radians(m.get('rotation',c['rotation'])-c['rotation']);co,si=math.cos(angle),math.sin(angle);ids={q['primitiveId'].replace('e','',1) for q in c['pads']}
    def movept(x,y):
        x,y=x-c['x'],y-c['y'];return(m['x']+co*x-si*y,m['y']+si*x+co*y)
    for i,o in enumerate(objects):
        if o['id'] in ids:
            o['points']=[movept(x,y) for x,y in o['points']];pts=o['points'];rad=o['radius']
            o['box']=(min(x for x,y in pts)-rad,min(y for x,y in pts)-rad,max(x for x,y in pts)+rad,max(y for x,y in pts)+rad)
            new.append(i)
for r in p['routes']:
    for n,(a,c) in enumerate(zip(r['points'],r['points'][1:])):
        if a!=c:new.append(add({'kind':'stroke','points':[a,c],'radius':r['width']/2,'layer':r['layer'],'net':r['net'],'id':f"{r['id']}-{n}",'proposed':True}))
for v in p['vias']:
    for layer in [1,2]:new.append(add({'kind':'circle','points':[(v['x'],v['y'])],'radius':p['viaDiameterMil']/2,'layer':layer,'net':v['net'],'id':v['id'],'via':True,'proposed':True}))
for i in new:
    a=objects[i];box=a['box'];edge=min(box[0],-box[3],1181.1024-box[2],box[1]+1968.5039)
    if edge<11.8-.04:issues.append({'id':a['id'],'kind':'edge','gapMil':round(edge,3)})
    for j,c in enumerate(objects):
        if j==i:continue
        if a['layer']!=c['layer'] or a['id']==c['id']:continue
        ba,bc=a['box'],c['box']
        if ba[0]>bc[2]+6.03 or bc[0]>ba[2]+6.03 or ba[1]>bc[3]+6.03 or bc[1]>ba[3]+6.03:continue
        dist=distance(a,c);gap=dist-a['radius']-c['radius']
        if a['net']!=c['net']:
            minimum=4.02 if a['kind']==c['kind']=='stroke' else 5.98
            if gap<minimum-.07:issues.append({'id':a['id'],'other':c['id'],'kind':'clearance','gapMil':round(gap,3),'minimumMil':minimum})
        if a.get('via') and j<before and c['kind'] in ['polygon','circle'] and not c.get('via') and a['net']==c['net'] and c['id'] in g['padnodes'] and len(g['padnodes'][c['id']])==1:
            holegap=dist-c['radius']-p['viaDrillMil']/2
            if holegap<-.04:holes.append({'via':a['id'],'pad':c['id'],'holeGapMil':round(holegap,3)})
report={'plan':planfile,'board':boardfile,'tracks':sum(len(r['points'])-1 for r in p['routes']),'vias':len(p['vias']),'clearanceCandidates':issues,'holeInSMDCandidates':holes,'passed':not issues and not holes}
(root/(Path(planfile).stem+'-screen.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
