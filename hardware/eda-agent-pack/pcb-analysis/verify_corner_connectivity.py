"""Independent copper-contact connectivity, including sampled signed-sweep arcs and DSN pad shapes."""
import json,re,math,collections,sys
from pathlib import Path
root=Path(__file__).parent
load=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
b=load(root/(sys.argv[1] if len(sys.argv)>1 else 'after-rounded-branches.json'));old=load(root/'before-angle-fix.json')
dsn=Path(load(root/(sys.argv[2] if len(sys.argv)>2 else 'dsn-corner-verified.json'))['result']['artifactPath']).read_text(encoding='utf-8-sig')
tokens=re.findall(r'"(?:\\.|[^"\\])*"|[^\s()]+|[()]',dsn);stack=[];tree=[]
for token in tokens:
    if token=='(':n=[];(stack[-1] if stack else tree).append(n);stack.append(n)
    elif token==')':stack.pop()
    else:stack[-1].append(token[1:-1] if token.startswith('"') else token)
assert not stack
def children(n,k):return[x for x in n if isinstance(x,list) and x[0]==k]
def child(n,k):return next(iter(children(n,k)))
tree=tree[0];lib=child(tree,'library');network=child(tree,'network');image=child(lib,'image')
stacks={p[1]:p for p in children(lib,'padstack')};nets={}
for n in children(network,'net'):
    for name in child(n,'pins')[1:]:nets[name.removeprefix('u1-').removeprefix('u1.')]=n[1]
def dot(a,c):return a[0]*c[0]+a[1]*c[1]
def pointseg(p,a,c):
    dx,dy=c[0]-a[0],c[1]-a[1];d=dx*dx+dy*dy;t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/d)) if d else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
def cross(a,c,p):return(c[0]-a[0])*(p[1]-a[1])-(c[1]-a[1])*(p[0]-a[0])
def segdist(a,c,d,e):
    if cross(a,c,d)*cross(a,c,e)<=0 and cross(d,e,a)*cross(d,e,c)<=0 and max(min(a[0],c[0]),min(d[0],e[0]))<=min(max(a[0],c[0]),max(d[0],e[0])) and max(min(a[1],c[1]),min(d[1],e[1]))<=min(max(a[1],c[1]),max(d[1],e[1])):return 0
    return min(pointseg(a,d,e),pointseg(c,d,e),pointseg(d,a,c),pointseg(e,a,c))
def inside(p,poly):
    result=False
    for a,c in zip(poly,poly[1:]+poly[:1]):
        if ((a[1]>p[1])!=(c[1]>p[1])) and p[0]<(c[0]-a[0])*(p[1]-a[1])/(c[1]-a[1])+a[0]:result=not result
    return result
def edges(poly):return list(zip(poly,poly[1:]+poly[:1]))
objects=[];padnodes={};via_nodes={}
actual_pad_names={p['primitiveId'].replace('e','',1) for c in b['components'] for p in c['pads']}
def add(obj):
    pts=obj['points'];r=obj.get('radius',0);obj['box']=(min(p[0] for p in pts)-r,min(p[1] for p in pts)-r,max(p[0] for p in pts)+r,max(p[1] for p in pts)+r);objects.append(obj);return len(objects)-1
for pin in children(image,'pin'):
    _,ps,name,x,y=pin;x,y=float(x),float(y)-1968.5
    if name not in actual_pad_names:continue # DSN via aliases may persist at obsolete coordinates; only native component pad identities are pads.
    net=nets.get(name,'');padnodes[name]=[]
    for shape in children(stacks[ps],'shape'):
        s=shape[1];layer={'TopLayer':1,'BottomLayer':2}.get(s[1])
        if layer is None:continue
        if s[0]=='circle':
            off=[float(v) for v in s[3:5]];cx,cy=(x+off[0],y+off[1]) if off else(x,y)
            idx=add({'kind':'circle','points':[(cx,cy)],'radius':float(s[2])/2,'layer':layer,'net':net,'id':name})
        elif s[0]=='polygon':
            coords=[float(v) for v in s[3:]];poly=[(x+dx,y+dy) for dx,dy in zip(coords[::2],coords[1::2])]
            idx=add({'kind':'polygon','points':poly,'radius':float(s[2])/2,'layer':layer,'net':net,'id':name})
        else:raise ValueError(('Unsupported exported pad shape',s[0],name))
        padnodes[name].append(idx)
for t in b['copper']['lines']:
    add({'kind':'stroke','points':[(t['startX'],t['startY']),(t['endX'],t['endY'])],'radius':t['lineWidth']/2,'layer':t['layer'],'net':t['net'],'id':t['primitiveId']})
for t in b['copper']['arcs']:
    a,c=(t['startX'],t['startY']),(t['endX'],t['endY']);theta=math.radians(t['arcAngle']);dx,dy=c[0]-a[0],c[1]-a[1];f=1/(2*math.tan(theta/2));center=((a[0]+c[0])/2-dy*f,(a[1]+c[1])/2+dx*f);angle=math.atan2(a[1]-center[1],a[0]-center[0]);radius=math.dist(a,center);samples=max(2,math.ceil(abs(t['arcAngle'])))
    points=[(center[0]+radius*math.cos(angle+theta*i/samples),center[1]+radius*math.sin(angle+theta*i/samples)) for i in range(samples+1)];points[0]=a;points[-1]=c
    add({'kind':'stroke','points':points,'radius':t['lineWidth']/2,'layer':t['layer'],'net':t['net'],'id':t['primitiveId']})
for v in b['copper']['vias']:
    via_nodes[v['primitiveId']]=[add({'kind':'circle','points':[(v['x'],v['y'])],'radius':v['diameter']/2,'layer':layer,'net':v['net'],'id':v['primitiveId'],'via':True}) for layer in [1,2]]
def distance(a,c):
    ap,cp=a['points'],c['points'];ak,ck=a['kind'],c['kind']
    if ak=='circle' and ck=='circle':return math.dist(ap[0],cp[0])
    if ak=='circle':
        if ck=='polygon' and inside(ap[0],cp):return 0
        return min(pointseg(ap[0],x,y) for x,y in (edges(cp) if ck=='polygon' else zip(cp,cp[1:])))
    if ck=='circle':return distance(c,a)
    if ak=='polygon' and any(inside(p,ap) for p in cp):return 0
    if ck=='polygon' and any(inside(p,cp) for p in ap):return 0
    ae=edges(ap) if ak=='polygon' else list(zip(ap,ap[1:]));ce=edges(cp) if ck=='polygon' else list(zip(cp,cp[1:]))
    return min(segdist(x,y,d,e) for x,y in ae for d,e in ce)
adj=[set() for o in objects]
for i,a in enumerate(objects):
    for j,c in enumerate(objects[:i]):
        if not a['net'] or a['net']!=c['net'] or a['layer']!=c['layer']:continue
        ba,bc=a['box'],c['box']
        if ba[0]>bc[2]+.03 or bc[0]>ba[2]+.03 or ba[1]>bc[3]+.03 or bc[1]>ba[3]+.03:continue
        if distance(a,c)<=a['radius']+c['radius']+.03:adj[i].add(j);adj[j].add(i)
for group in list(via_nodes.values())+list(padnodes.values()):
    for i in group:
        for j in group:
            if i!=j:adj[i].add(j)
def pad(ref):
    designator,number=ref.split('.');component=next(c for c in b['components'] if c['designator']==designator);p=next(p for p in component['pads'] if p['padNumber']==number);name=p['primitiveId'].replace('e','',1)
    assert name in padnodes,(ref,name)
    return padnodes[name]
def reachable(starts):
    seen=set(starts);todo=list(starts)
    while todo:
        i=todo.pop()
        for j in adj[i]-seen:seen.add(j);todo.append(j)
    return seen
groups=[['U3.5','C16.2','C2.1','C3.1','U1.3'],['U7.5','C4.2','C5.1','U5.6'],['C7.1','L1.2','U2.7'],['J1.A6','J1.B6','D1.1','R6.1'],['J1.A7','J1.B7','D2.1','R7.1'],['R6.2','U1.27'],['R7.2','U1.26']]
checks=[]
for refs in groups:
    seen=reachable(pad(refs[0]));checks.append({'pads':refs,'connected':all(bool(seen.intersection(pad(ref))) for ref in refs)})
thermal=[]
for ep,coords in [('U2.9',[(625,-1665),(625,-1725),(805,-1665),(805,-1725)]),('U5.9',[(946.4,-882),(946.4,-940),(1126.4,-882),(1126.4,-940)])]:
    seen=reachable(pad(ep))
    for x,y in coords:
        v=next(v for v in b['copper']['vias'] if math.hypot(v['x']-x,v['y']-y)<.01);nodes=via_nodes[v['primitiveId']]
        thermal.append({'ep':ep,'via':v['primitiveId'],'connectedToEP':all(i in seen for i in nodes),'trackContactBothLayers':all(any(objects[j]['kind']=='stroke' and objects[j]['layer']==objects[i]['layer'] for j in adj[i]) for i in nodes)})
same_parts=old['components']==b['components'];same_regions=old['copper']['regions']==b['copper']['regions']
pose_changes=[];parts_authorized=True
allowed={'C13':(1004.57,-310,180),'R6':(650,-590,90),'R7':(710,-558.6,90),'R2':(375,-631,0),'D1':(618.82,-1049.49,135),'D2':(672.12,-1089.49,45)} # Exact poses authorized by the user; no blanket component exemption.
def equivalent(a,c):
    if isinstance(a,(int,float)) and isinstance(c,(int,float)):return abs(a-c)<.11
    if isinstance(a,dict) and isinstance(c,dict):return a.keys()==c.keys() and all(equivalent(a[k],c[k]) for k in a)
    if isinstance(a,list) and isinstance(c,list):return len(a)==len(c) and all(equivalent(x,y) for x,y in zip(a,c))
    return a==c
assert len(old['components'])==len(b['components'])
for a,c in zip(old['components'],b['components']):
    if a==c:continue
    target=allowed.get(c['designator'])
    if target is None or abs(c['x']-target[0])>.02 or abs(c['y']-target[1])>.02 or c['rotation']!=target[2]:
        parts_authorized=False;continue
    expected=json.loads(json.dumps(a));dx,dy=c['x']-a['x'],c['y']-a['y'];expected['x']=c['x'];expected['y']=c['y'];expected['rotation']=c['rotation']
    da=c['rotation']-a['rotation'];angle=math.radians(da);co,si=math.cos(angle),math.sin(angle)
    def transform(x,y):
        x,y=x-a['x'],y-a['y'];return(c['x']+co*x-si*y,c['y']+si*x+co*y)
    corners=[transform(x,y) for x in [a['bbox']['minX'],a['bbox']['maxX']] for y in [a['bbox']['minY'],a['bbox']['maxY']]]
    expected['bbox']={'minX':min(x for x,y in corners),'minY':min(y for x,y in corners),'maxX':max(x for x,y in corners),'maxY':max(y for x,y in corners)}
    for q in expected['pads']:
        q['x'],q['y']=transform(q['x'],q['y']);q['rotation']=(q['rotation']+da)%360
        actual=next(pad for pad in c['pads'] if pad['primitiveId']==q['primitiveId'])
        if q['rotation']==0 and 'rotation' not in actual:q.pop('rotation') # Native readback omits zero rotation.
        w,h=q['width'],q['height'];q['width']=abs(co)*w+abs(si)*h;q['height']=abs(si)*w+abs(co)*h
    valid=equivalent(expected,c);parts_authorized&=valid
    pose_changes.append({'designator':c['designator'],'dxMil':dx,'dyMil':dy,'otherFieldsPreserved':valid})
result={'geometryScope':'native DSN exact pad polygons/circles; fresh track and via readback; signed-sweep arcs sampled at <=1 degree; 0.03 mil readback rounding tolerance; connectivity only, not ordered paths or routed length','checks':checks,'thermal':thermal,'componentsUnchanged':same_parts,'authorizedPassiveMoves':pose_changes,'componentChangesAuthorized':parts_authorized,'regionsUnchanged':same_regions,'passed':all(c['connected'] for c in checks) and all(c['connectedToEP'] and c['trackContactBothLayers'] for c in thermal) and parts_authorized and same_regions}
(root/(sys.argv[3] if len(sys.argv)>3 else 'corner-connectivity-verification.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));assert result['passed']
