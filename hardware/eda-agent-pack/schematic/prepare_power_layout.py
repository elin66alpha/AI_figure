import json
from pathlib import Path
p=Path(__file__).parent
def read(n):return json.loads((p/n).read_text(encoding='utf-8-sig'))
snap=read('power-measured.json');lib=read('power-parts-source.json')['library']
parts=[c for c in snap['result']['components'] if c['componentType']=='part']
des={d['parentId']:d['bbox'] for d in read('power-designators.json')['designators']}
intent={
'U2':{'1':'CHG_SW','2':'GND','3':'GND','4':None,'5':'ISET','6':'BATT','7':'SYS','8':'CHG_IN','9':'GND'},
'L1':{'1':'CHG_SW','2':'SYS'},'C6':{'1':'CHG_IN','2':'GND'},'C7':{'1':'SYS','2':'GND'},'C8':{'1':'BATT','2':'GND'},'R3':{'1':'ISET','2':'GND'},
'J2':{'1':'BATT','2':'GND'},'SW1':{'1':'SYS','2':'SYS_SW','3':None},
'J1':{'A1B12':'GND','A4B9':'VBUS','B8':None,'A5':'CC1','B7':'USB_DM','A6':'USB_DP','A7':'USB_DM','B6':'USB_DP','A8':None,'B5':'CC2','B4A9':'VBUS','B1A12':'GND','1':'GND','2':'GND','3':'GND','4':'GND'},
'R4':{'1':'CC1','2':'GND'},'R5':{'1':'CC2','2':'GND'},'R6':{'1':'USB_DM','2':'MCU_USB_DM'},'R7':{'1':'USB_DP','2':'MCU_USB_DP'},
'D1':{'1':'USB_DM','2':'GND'},'D2':{'1':'USB_DP','2':'GND'},'F1':{'1':'VBUS','2':'VBUS_FUSED'},'R8':{'1':'VBUS_FUSED','2':'CHG_IN'}}
groups=[('charger','Battery charger 400mA','U2',['L1','C6','C7','C8','R3']),('battery','Protected 1S battery','J2',[]),('switch','Load power switch','SW1',[]),('usb','USB-C data and charge input','J1',['R4','R5','R6','R7','D1','D2','F1','R8'])]
attach={'L1':('1','U2','1'),'C6':('1','U2','8'),'C7':('1','U2','7'),'C8':('1','U2','6'),'R3':('1','U2','5'),'R4':('1','J1','A5'),'R5':('1','J1','B5'),'R6':('1','J1','B7'),'R7':('1','J1','A6'),'D1':('1','R6','1'),'D2':('1','R7','1'),'F1':('1','J1','A4B9'),'R8':('1','F1','2')}
components=[];measurements=[];connections=[];nets=set();binding=[]
for c in parts:
 ref=c['designator'];source=lib[c['supplierId']]; pins=[];mp=[]
 for pin in c['pins']:
  num=pin['pinNumber'];assert num in intent[ref],(ref,num)
  n=intent[ref][num];cp={'number':num,'name':pin['pinName']}
  if n is None:cp['noConnected']=True
  else:
   nets.add(n);connections.append({'componentId':'cmp-'+ref,'pinNumber':num,'netId':n,'kind':'netlist'})
  pins.append(cp);mp.append({'number':num,'name':pin['pinName'],'net':n or '',**{k:pin[k] for k in ['x','y','rotation']}})
 components.append({'id':'cmp-'+ref,'ref':ref,'device':{'libraryUuid':source['libraryUuid'],'deviceUuid':source['uuid'],'name':source['manufacturerId']},'pins':pins})
 measurements.append({'designator':ref,'value':source.get('value',source['manufacturerId']),**{k:c[k] for k in ['x','y','rotation','mirror','bbox']},'pins':mp,'textBboxes':[des[c['primitiveId']]]})
 file=p/('power-binding-'+ref+'.json');file.write_text(json.dumps({'otherProperty':{'EasyEDA Agent Component ID':'cmp-'+ref}}),encoding='utf-8')
 binding.append({'id':'bind-'+ref,'run':'sch modify','flags':{'id':c['primitiveId'],'patch-file':str(file.resolve())}})
ir={'schemaVersion':'1.4','projectId':snap['context']['projectUuid'],'documentId':snap['context']['documentUuid'],'components':components,'nets':[{'id':n,'name':n} for n in sorted(nets)],'connections':connections,'modules':[]}
layouts=[]
for mid,title,core,per in groups:
 members=['cmp-'+r for r in [core]+per];used={c['netId'] for c in connections if c['componentId'] in members}
 ir['modules'].append({'id':mid,'name':title,'coreComponents':['cmp-'+core],'peripheralComponents':['cmp-'+r for r in per],'internalNets':[],'ports':[]})
 policies={n:('local_ground' if n=='GND' else 'local_power' if n in ['VBUS','VBUS_FUSED','CHG_IN','SYS','SYS_SW','BATT'] else 'module_port') for n in used}
 layouts.append({'id':mid,'title':title,'coreComponentId':'cmp-'+core,'netPolicies':policies,'peripherals':[{'componentId':'cmp-'+r,'pinNumber':attach[r][0],'attachTo':{'componentId':'cmp-'+attach[r][1],'pinNumber':attach[r][2]}} for r in per]})
geom=read('power-sheet.json')['result']
data={'schemaVersion':1,'connectivity':ir,'sheet':geom['sheet']['bbox'],'keepouts':[k['bbox'] for k in geom['keepouts']],'measurements':measurements,'layoutModules':layouts,'maxCandidates':1000000}
(p/'power-layout-input.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
(p/'power-bind.playbook.json').write_text(json.dumps({'version':1,'meta':{'name':'Bind measured power parts','project':ir['projectId'],'doc':ir['documentId']},'steps':binding},indent=2),encoding='utf-8')
print(len(parts),'parts;',len(connections),'connected pins')
