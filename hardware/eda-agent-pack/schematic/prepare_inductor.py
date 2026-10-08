import json, hashlib
from pathlib import Path
p=Path(__file__).parent
mm=39.37007874
spec={
 'name':'DH0618H-2R2M_AI_figure','description':'2.2uH shielded power inductor, LCSC C41406997',
 'libraryUUID':'2cb3ad867dfa4740a0fbae81ea348a21','designator':'L',
 'evidence':{'manufacturer':'Deheng','mpn':'DH0618H-2R2M','packageVariant':'DH0618H 7.1x6.6mm H1.8mm',
  'datasheet':{'title':'DH0618H-2R2M specification S200519-003','locator':str((p/'DH0618H-datasheet.pdf').resolve()),'revision':'A/0 2020-05-19','sha256':hashlib.sha256((p/'DH0618H-datasheet.pdf').read_bytes()).hexdigest()},
  'pinoutPages':[3],'packageDrawingPages':[3],'landPattern':{'basis':'datasheet','pages':[3],'note':'G=2.9mm inner gap, H=7.8mm outer span, I=3.5mm height. Pad width=(H-G)/2=2.45mm; centers +/-2.675mm. Nonpolar winding assigned 1 left / 2 right; winding start dot not numerically specified.'}},
 'pinMapping':{'footprintOnly':[],'symbolOnly':[]},
 'symbol':{'name':'DH0618H-2R2M','description':'Nonpolar two-terminal 2.2uH inductor',
  'geometry':{'outline':[-15,-5,15,-5,15,5,-15,5,-15,-5], 'pins':[
   {'number':'1','name':'1','x':-30,'y':0,'rotation':0,'length':15,'pinType':'Passive','shape':'None'},
   {'number':'2','name':'2','x':30,'y':0,'rotation':180,'length':15,'pinType':'Passive','shape':'None'}]}},
 'footprint':{'name':'DH0618H_LAND_7.8x3.5','description':'Manufacturer recommended two 2.45x3.5mm pads, 2.9mm gap, units mil',
  'geometry':{'pads':[{'number':str(i),'layer':1,'x':x*mm,'y':0,'rotation':0,'shape':[1,2.45*mm,3.5*mm]} for i,x in [(1,-2.675),(2,2.675)]],
  'lines':[{'layer':3,'startX':-3.3*mm,'startY':y*mm,'endX':3.3*mm,'endY':y*mm,'width':5} for y in [-3.55,3.55]]}},
 'properties':{'Manufacturer':'Deheng','Manufacturer Part':'DH0618H-2R2M','Supplier':'LCSC','Supplier Part':'C41406997','Value':'2.2uH','Datasheet':'https://atta.szlcsc.com/upload/public/pdf/source/20241112/2B291D1A3B9FC49D176F25E8B1E8EEB3.pdf'}
}
(p/'inductor-device.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
