"""Exploratory 2D quasi-static odd-mode estimate, not fabrication certification.

Finite-volume Laplace equation; odd symmetry is a zero-potential boundary at x=0.
Uniform mesh, harmonic dielectric interfaces, grounded coplanar copper and back
plane. Q/V is found from conductor face flux. Zdiff = 2/(c sqrt(Codd Codd_air)).
Reports grid/model assumptions explicitly. Does not alter the PCB.
"""
import numpy as np,math,json,sys,time
from pathlib import Path
eps0=8.8541878128e-12;c0=299792458
quick='quick' in sys.argv
def solve(width,spacing,gap,er,dx=1.,mask=True,coplanar=True):
    h=60.;t=1.6;domainx=120 if quick else 240;airheight=60 if quick else 100
    xs=np.arange(0,domainx+dx/2,dx);ys=np.arange(-h,airheight+dx/2,dx);X,Y=np.meshgrid(xs,ys)
    eps=np.where(Y<0,er,1.)
    if mask and er!=1:eps=np.where((Y>=0)&(Y<=2.2),3.8,eps)
    left=spacing/2; taper=.7*np.clip(Y/t,0,1)
    metal=(Y>=0)&(Y<=t)&(X>=left+taper/2)&(X<=left+width-taper/2)
    ground=(Y>=0)&(Y<=t)&(X>=left+width+gap) if coplanar else np.zeros_like(metal)
    fixed=metal|ground;fixed[:,0]=True;fixed[:,-1]=True;fixed[0,:]=True;fixed[-1,:]=True
    free=~fixed[1:-1,1:-1];v=np.zeros_like(X);v[metal]=.5
    def harmonic(a,b):return 2*a*b/(a+b)
    ex=harmonic(eps[:,1:],eps[:,:-1]);ey=harmonic(eps[1:,:],eps[:-1,:]);E=ex[1:-1,1:];W=ex[1:-1,:-1];N=ey[1:,1:-1];S=ey[:-1,1:-1];diag=E+W+N+S
    jj,ii=np.indices(free.shape);red=free&((jj+ii)%2==0);black=free&((jj+ii)%2==1);interior=v[1:-1,1:-1];omega=1.92
    def charge_flux():
        flux=0.
        for a,b,coef,ma,mb in [(v[:,1:],v[:,:-1],ex,metal[:,1:],metal[:,:-1]),(v[1:,:],v[:-1,:],ey,metal[1:,:],metal[:-1,:])]:
            flux+=np.sum(coef*(a-b)*(ma.astype(float)-mb.astype(float)))
        return float(flux)
    previous_flux=None;stable=0
    for iteration in range(16000):
        maxupdate=0.
        for subset in [red,black]:
            target=(E*v[1:-1,2:]+W*v[1:-1,:-2]+N*v[2:,1:-1]+S*v[:-2,1:-1])/diag
            delta=omega*(target-interior);maxupdate=max(maxupdate,float(np.max(np.abs(delta[subset]))));interior[subset]+=delta[subset]
        if iteration%200==0 and maxupdate<2e-9:break
        if quick and iteration%100==0:
            flux=charge_flux();relative_change=float('inf') if previous_flux is None else abs(flux-previous_flux)/abs(flux)
            stable=stable+1 if relative_change<2e-7 else 0;previous_flux=flux
            if iteration>=1000 and stable>=5:break
    # Discrete outward conductor charge: epsilon (Vmetal - Vneighbour).
    flux=charge_flux()
    return float(eps0*flux/.5),iteration,maxupdate
root=Path(__file__).parent;dx=float(sys.argv[1]) if len(sys.argv)>1 else 1.;results=[]
gap_arg=next((float(x.split('=',1)[1]) for x in sys.argv if x.startswith('gap=')),6.02)
for w,s,g in ([(10.,6.2,gap_arg)] if quick else [(10.,6.2,gap_arg),(12.,4.2,gap_arg),(12.18,4.02,gap_arg)]):
    air,n0,e0=solve(w,s,g,1.,dx);cap,n,e=solve(w,s,g,4.5,dx);z=2/(c0*math.sqrt(cap*air));row=dict(widthMil=w,spacingMil=s,groundGapMil=g,zDiffOhm=z,oddCapacitancePFm=cap*1e12,airOddCapacitancePFm=air*1e12,iterations=[n0,n],residualUpdates=[e0,e]);results.append(row);print(json.dumps(row),flush=True)
report=dict(scope='exploratory quasi-static uniform cross-section; not measured board or fabrication-controlled impedance',gridMil=dx,dielectricHeightMil=60.,dielectricEr=4.5,copperMil=1.6,maskEr=3.8,maskMaxHeightMil=2.2,traceTopNarrowingMil=.7,domainXMil=120 if quick else 240,domainAirHeightMil=60 if quick else 100,chargeConvergenceRelative=2e-7 if quick else None,results=results)
(root/f'impedance-estimate-{dx:g}mil{ "-quick" if quick else ""}{ "-gap"+str(gap_arg) if gap_arg!=6.02 else ""}.json').write_text(json.dumps(report,indent=2))
