"""Prepare reviewable DSN parameters; does not mutate the live PCB."""
import json,re,sys
from pathlib import Path
root=Path(__file__).parent
source=Path(json.loads((root/(sys.argv[1] if len(sys.argv)>1 else 'dsn-critical.json')).read_text(encoding='utf-8-sig'))['result']['artifactPath'])
s=source.read_text(encoding='utf-8-sig')
board=json.loads((root/(sys.argv[2] if len(sys.argv)>2 else 'critical-protected.json')).read_text(encoding='utf-8-sig'))
# Export includes routed vias twice: as image pins AND wiring vias. Remove image aliases only.
via_aliases=[]
def remove_via_pin(m):
    name,x,y=m.group(2),float(m.group(3)),float(m.group(4))
    if any(abs(v['x']-x)<.03 and abs(v['y']+1968.5-y)<.03 for v in board['copper']['vias']):
        via_aliases.append(name);return ''
    return m.group(0)
s=re.sub(r'\(pin (\S+) (\S+) ([\d.-]+) ([\d.-]+)\)',remove_via_pin,s)
for name in via_aliases:
    for sep in ['.','-']:
        s=s.replace('u1'+sep+name+' ', '').replace('u1'+sep+name+')',')')
# Single quotes are literal in Specctra; exporter emitted unbound class net names.
s=re.sub(r"(\(class \S+) '([^']+)'",lambda m:m.group(1)+' "'+m.group(2)+'"',s)
# Live antenna coordinates transformed using DSN pin coordinates: y + 1968.5, x unchanged.
s,n=re.subn(r'\(keepout "region_keepout_1" \(polygon signal[^\n]+', '(keepout "region_keepout_1" (polygon signal 0 0 1744.1 0 1968.5 677.2 1968.5 677.2 1744.1 0 1744.1))',s)
assert n==1
widths={'SYS':20,'VBAT':20,'VBUS_USB':20,'VBUS_CHG':20,'3V3':25,'3V3_AMP':16,'SPK_P':16,'SPK_N':16,'$1N181':28,'$1N222':20}
classes=[]
def adjust(m):
    block=m.group(0);net=m.group(1)
    width=widths.get(net,10 if net.startswith('USB_D') else 8)
    block=re.sub(r'\(width [\d.]+\)',f'(width {width})',block)
    # Conservative uniform line clearance also satisfies track-to-pad spacing.
    block=block.replace('(clearance 4.02)','(clearance 6.03)')
    classes.append({'net':net,'widthMil':width,'clearanceMil':6.03})
    return block
s,n=re.subn(r'\(class (\S+) [\s\S]*?\n    \)',adjust,s)
assert n==31
(root/'router-input.dsn').write_text(s,encoding='utf-8')
(root/'router-input-audit.json').write_text(json.dumps({'source':str(source),'removedDuplicateViaPins':via_aliases,'classBindingCorrection':'Specctra double quotes replace literal single quote wrappers','keepoutCorrection':'subtract erroneous injected +5 mil x/y; verified pin transform y+1968.5','outlineLimitation':'native DSN boundary is rectangular approximation; native PCB DRC must check actual rounded outline','existingWiring':'type protect, retained','classes':classes},indent=2),encoding='utf-8')
print(f'{n} classes adjusted, protected input written')
