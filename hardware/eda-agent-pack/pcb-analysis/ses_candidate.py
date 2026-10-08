"""Convert unprotected SES additions into an inspectable typed route plan."""
import json,re,sys,collections
from pathlib import Path
root=Path(__file__).parent
def parse(text):
    tokens=re.findall(r'"(?:\\.|[^"\\])*"|[^\s()]+|[()]',text);stack=[];tree=[]
    for t in tokens:
        if t=='(':n=[]; (stack[-1] if stack else tree).append(n);stack.append(n)
        elif t==')':stack.pop()
        else:stack[-1].append(t[1:-1] if t.startswith('"') else t)
    assert not stack
    return tree[0]
def child(n,key):return next((x for x in n if isinstance(x,list) and x[0]==key),None)
ses=parse((root/sys.argv[1]).read_text());routes=child(ses,'routes');network=child(routes,'network_out')
excluded={'GND','USB_DP','USB_DM','USB_DP_CONN','USB_DM_CONN','$1N181','$1N189','$1N222','3V3_AMP'}
plan={'units':'mil','viaDiameterMil':24.02,'viaDrillMil':12.01,'vias':[],'routes':[]};counts=collections.Counter();i=0
for net in network[1:]:
    if net[0]!='net' or net[1] in excluded:continue
    name=net[1]
    for item in net[2:]:
        if child(item,'type')==['type','protect']:continue
        i+=1
        if item[0]=='wire':
            p=child(item,'path');coords=[float(v)/1000 for v in p[3:]];points=list(zip(coords[::2],coords[1::2]))
            if sum(((a[0]-b[0])**2+(a[1]-b[1])**2)**.5 for a,b in zip(points,points[1:]))<.2:continue
            plan['routes'].append({'id':f'router-{i}','net':name,'layer':{'TopLayer':1,'BottomLayer':2}[p[1]],'width':float(p[2])/1000,'points':[[x,round(y-1968.5,5)] for x,y in points]});counts[name]+=len(points)-1
        elif item[0]=='via':
            plan['vias'].append({'id':f'router-via-{i}','net':name,'x':float(item[2])/1000,'y':round(float(item[3])/1000-1968.5,5)})
out=root/'router-candidate-plan.json';out.write_text(json.dumps(plan,indent=2),encoding='utf-8')
print(json.dumps({'tracksByNet':dict(counts),'vias':len(plan['vias']),'routes':len(plan['routes'])},indent=2))
