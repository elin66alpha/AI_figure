import json
from pathlib import Path
p=Path(__file__).parent
def read(n):return json.loads((p/n).read_text(encoding='utf-8-sig'))
lib={}
for n in ['core-library.json','peripheral-library.json','resistor-candidates.json','power-extra-library.json']:
 lib.update({c['lcsc']:c for c in read(n)['result']['components']})
extra=read('inductor-reuse-device.json')['result']
lib['C41406997']={'uuid':extra['uuid'],'libraryUuid':extra['libraryUuid'],'manufacturerId':'DH0618H-2R2M','value':'2.2uH'}
rows=[('U2','C7436031'),('L1','C41406997'),('C6','C15850'),('C7','C503482'),('C8','C89188'),('R3','C22908'),('J2','C173752'),('SW1','C7431054'),('J1','C165948'),('R4','C23186'),('R5','C23186'),('R6','C23140'),('R7','C23140'),('D1','C42400191'),('D2','C42400191'),('F1','C910830'),('R8','C21189')]
old=read('wired-readback.json')['result']['components']
ids=[c['primitiveId'] for c in old if c.get('designator') in ['U2','J1']]
assert len(ids)==2
meta={'name':'Move unwired charger and USB into dedicated schematic page','project':'8c5d0d86032348a0a6c85102fe97607e','doc':'98cfe13509bc1f5c'}
(p/'power-remove-empty.playbook.json').write_text(json.dumps({'version':1,'meta':meta,'steps':[{'id':'remove-unwired-U2-J1','run':'sch prim-delete','flags':{'ids':','.join(ids)}},{'id':'save','action':'schematic.save','payload':{}}]},indent=2),encoding='utf-8')
meta={'name':'Power and USB measurement placements','project':meta['project'],'doc':'2a0b6c4d73111128'}
steps=[]
for i,(ref,lcsc) in enumerate(rows):
 c=lib[lcsc]
 steps.append({'id':'place-'+ref,'run':'sch place','flags':{'lib':c['libraryUuid'],'uuid':c['uuid'],'designator':ref,'x':100+(i%5)*200,'y':700-(i//5)*140}})
steps.append({'id':'save','action':'schematic.save','payload':{}})
(p/'power-parts.playbook.json').write_text(json.dumps({'version':1,'meta':meta,'steps':steps},indent=2),encoding='utf-8')
(p/'power-parts-source.json').write_text(json.dumps({'rows':rows,'library':lib},indent=2),encoding='utf-8')
print('Prepared',len(rows),'parts; old U2 and J1 are unwired')

