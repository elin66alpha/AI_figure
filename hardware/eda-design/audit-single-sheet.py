import json,sys
from pathlib import Path
from collections import defaultdict
r=Path(__file__).parent
source=r/(sys.argv[1] if len(sys.argv)>1 else 'single-sheet-final-read.json')
d=json.loads(source.read_text(encoding='utf-8-sig'))
assert d['ok'],d
parts=[c for c in d['result']['components'] if c['componentType']=='part']
expected=json.loads((r/'single-sheet-expected-before.json').read_text())
expected['R1']={'1':'GND','2':'MIC_SD'} # Symmetric resistor, layout reversed.
expected['U1']['1']='RF_IN'
expected.update({'L3':{'1':'RF_IN','2':'RF_OUT'},'C20':{'1':'RF_IN','2':'GND'},'C21':{'1':'RF_OUT','2':'GND'},'J4':{'1':'GND','2':'RF_OUT','3':'GND'}})
for i,n in enumerate(['UART_RX','UART_TX','GND','CHIP_EN','BOOT_GPIO9','3V3']):expected[f'TP{i+1}']={'1':n}
internal={'CHG_SW','CHG_ISET','VBUS_FUSED','XTAL_P_CRYSTAL','LED_ANODE','RF_OUT'}
actual={}; groups=defaultdict(set); intended=defaultdict(set);errors=[]
assert len({c['designator'] for c in parts})==len(parts),'duplicate designator'
for c in parts:
    ref=c['designator']
    if not c.get('netlistAvailable'):errors.append(f'{ref}: netlist unavailable')
    for p in c['pins']:
        key=(ref,p['pinNumber']);actual[key]=p
        if p.get('net'):groups[p['net']].add(key)
for ref,pins in expected.items():
    for pin,net in pins.items():
        key=(ref,pin)
        if key not in actual:errors.append(f'missing {key}');continue
        a=actual[key]
        if net: intended[net].add(key)
        if net in internal:continue
        if net and a.get('net')!=net:errors.append(f'{key}: {a.get("net")} != {net}')
        if not net and not a.get('noConnected'):errors.append(f'{key}: expected NC')
for net in internal:
    keys=intended[net]; actual_names={actual[k].get('net') for k in keys}
    if len(actual_names)!=1 or not next(iter(actual_names),None):errors.append(f'{net}: split internal net {actual_names}');continue
    name=next(iter(actual_names))
    if groups[name]!=keys:errors.append(f'{net}: unexpected connected pins {groups[name]^keys}')
report={'snapshot':source.name,'parts':len(parts),'pins':len(actual),'expectedParts':len(expected),'passed':not errors,'errors':errors,'internalNetAliases':{n:actual[next(iter(intended[n]))].get('net') for n in internal}}
(r/'single-sheet-pin-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False,indent=2))
sys.exit(bool(errors))
