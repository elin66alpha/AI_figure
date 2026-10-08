import math,heapq
directions=[(1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1)]
def search(start,layer,targets,objects,distance,width=10,net='GND'):
    goals=sorted((pt for pt in targets if math.dist(start,pt)<400),key=lambda pt:math.dist(pt,start));ob=[o for o in objects if o['layer']==layer and o['net']!=net];cache={}
    def clear(a,c):
        k=(a,c)
        if k in cache:return cache[k]
        if any(not(17<=p[0]<=1164 and -1951<=p[1]<=-239) for p in [a,c]):return False
        box=(min(a[0],c[0])-11,min(a[1],c[1])-11,max(a[0],c[0])+11,max(a[1],c[1])+11);z={'kind':'stroke','points':[a,c],'radius':width/2}
        for o in ob:
            q=o['box']
            if box[0]>q[2] or q[0]>box[2] or box[1]>q[3] or q[1]>box[3]:continue
            if distance(z,o)-o['radius']-width/2<(4.03 if o['kind']=='stroke' else 5.99):cache[k]=False;return False
        cache[k]=True;return True
    def point(x,y):return(round(start[0]+x*5,4),round(start[1]+y*5,4))
    def heuristic(pt):return min(math.dist(pt,t) for t in goals)
    queue=[];cost={};prev={};done=None;end=None;expanded=0
    if not goals:return None
    for h in range(8):key=(0,0,h);cost[key]=0;heapq.heappush(queue,(heuristic(start),0,key))
    while queue and expanded<70000:
        _,old,key=heapq.heappop(queue)
        if old!=cost.get(key):continue
        expanded+=1;x,y,h=key;pt=point(x,y);dx,dy=directions[h]
        for t in goals:
            dist=math.dist(pt,t)
            if dist<12 and (dist<.1 or (dx*(t[0]-pt[0])+dy*(t[1]-pt[1]))/(math.hypot(dx,dy)*dist)>.5) and clear(pt,t):done=key;end=t;break
        if done:break
        for nh in [(h-1)%8,h,(h+1)%8]:
            ux,uy=directions[nh];nx,ny=x+ux,y+uy;npt=point(nx,ny)
            if abs(nx)>85 or abs(ny)>85 or not clear(pt,npt):continue
            nk=(nx,ny,nh);nc=old+math.hypot(ux,uy)*5+(0 if nh==h else 1)
            if nc<cost.get(nk,float('inf')):cost[nk]=nc;prev[nk]=key;heapq.heappush(queue,(nc+heuristic(npt),nc,nk))
    if not done:return None
    pts=[end];k=done
    while k in prev:pts.append(point(k[0],k[1]));k=prev[k]
    pts.append(start);pts=list(reversed(pts));simplified=[]
    for pt in pts:
        if simplified and math.dist(pt,simplified[-1])<.01:continue
        if len(simplified)>=2:
            a,c=simplified[-2:];v=(c[0]-a[0],c[1]-a[1]);w=(pt[0]-c[0],pt[1]-c[1])
            if abs(v[0]*w[1]-v[1]*w[0])<.001 and v[0]*w[0]+v[1]*w[1]>0:simplified.pop()
        simplified.append(pt)

    return simplified,expanded
