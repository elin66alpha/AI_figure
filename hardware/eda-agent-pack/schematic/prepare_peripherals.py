import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8-sig'))

library = {}
for filename in ['core-library.json', 'peripheral-library.json', 'resistor-candidates.json']:
    for part in read(filename)['result']['components']:
        library[part['lcsc']] = part

# Initial measured instances. Final module geometry is computed separately.
parts = [
    ('C1','C15850','ldo_input'), ('C2','C15850','ldo_output'),
    ('C3','C1591','microphone_decoupling'), ('R1','C25803','microphone_sd_pulldown'),
    ('C4','C89188','amplifier_decoupling'), ('C5','C49233126','amplifier_reservoir'),
    ('R2','C25803','amplifier_ctrl_pulldown'),
]
steps=[]
source=[]
for index,(ref,lcsc,role) in enumerate(parts):
    part=library[lcsc]
    x=300+index*100
    y=80
    source.append(dict(ref=ref,lcsc=lcsc,role=role,x=x,y=y))
    steps.append(dict(id='place-'+ref,run='sch place',flags=dict(
        lib=part['libraryUuid'],uuid=part['uuid'],designator=ref,x=x,y=y)))
steps.append(dict(id='save-peripherals',run='sch save'))
plan=dict(version=1,meta=dict(name='AI_figure audio and LDO peripherals',
    project='8c5d0d86032348a0a6c85102fe97607e',doc='98cfe13509bc1f5c'),steps=steps)
for name,data in [('peripheral-placement-source.json',source),('peripheral-placement.playbook.json',plan)]:
    (ROOT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
