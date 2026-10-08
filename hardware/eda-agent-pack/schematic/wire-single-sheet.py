import json
from pathlib import Path
ROOT=Path(__file__).parent
PAGE='98cfe13509bc1f5c'
PROJECT='8c5d0d86032348a0a6c85102fe97607e'
data=json.loads((ROOT/'single-sheet-positioned.json').read_text(encoding='utf-8-sig'))['result']
parts={c['designator']:c for c in data['components'] if c['componentType']=='part'}
steps=[]
def add(run,**flags):
    steps.append({'id':f's{len(steps)+1}','run':'sch '+run,'flags':dict(flags,doc=PAGE)})
def w(*p):
    pts=[]
    for q in p:
        if not pts or q!=pts[-1]:pts.append(q)
    assert len(pts)>1
    add('wire',points=json.dumps(pts))
def f(net,x,y,rot=0,kind='netport'):
    add('netflag',net=net,x=x,y=y,rotation=rot,kind=kind)
def power(net,x,y):f(net,x,y,0,'power')
def ground(x,y,rot=180):f('GND',x,y,(rot+180)%360,'ground')
def port(net,*p,left=False):
    w(*p);f(net,*p[-1],180 if left else 0)
def emit(name):
    (ROOT/(name+'.json')).write_text(json.dumps({'version':1,'meta':{'name':name,'project':PROJECT},'steps':steps},indent=2),encoding='utf-8');steps.clear()
for ref,x,y in [('R6',2040,950),('D1',2180,1000),('R7',2040,850),('D2',2180,900),('J3',1280,680)]:
    add('modify',id=parts[ref]['primitiveId'],x=x,y=y)
emit('single-sheet-adjust')
# MCU fanout, ordered pin escape channels, wire names supplied only by ports.
nets=['RF_IN','3V3','3V3',None,'SYS_ADC','BOOT_GPIO2','CHIP_EN','REC_KEY','I2S_BCLK','I2S_WS','3V3','MIC_SD','AMP_DIN','LED_GPIO8','BOOT_GPIO9','AMP_CTRL']
for i,n in enumerate(nets):
    if not n:continue
    y=1440-10*i;t=1530-20*i
    lane=385-10*(i if t>=y else 15-i)
    port(n,(405,y),(lane,y),(lane,t),(220,t),left=True)
nets=['3V3','VDD_SPI',None,None,None,None,None,None,'USB_DM','USB_DP','UART_RX','UART_TX','XTAL_N','XTAL_P','3V3','3V3','GND']
for i,n in enumerate(nets):
    if not n:continue
    y=1290+10*i;t=1210+20*i
    lane=575+10*(i if t<y else 16-i)
    port(n,(555,y),(lane,y),(lane,t),(740,t))
for x in [120,220,320,420,520,620]:w((x,1110),(x,1130));w((x,1070),(x,1050))
w((120,1130),(620,1130),(620,1150));power('3V3',620,1150)
w((120,1050),(720,1050));w((620,1050),(620,1030));ground(620,1030)
w((720,1070),(720,1050));w((720,1110),(720,1160));power('VDD_SPI',720,1160)
emit('single-sheet-wire-mcu')
# LDO
w((1055,1510),(1020,1510),(1020,1530),(900,1530),(900,1510),(930,1510))
w((1055,1500),(1020,1500),(1020,1510));w((1020,1530),(1020,1560));power('SYS_SW',1020,1560)
w((970,1510),(990,1510),(990,1470));ground(990,1470)
w((1125,1510),(1160,1510),(1200,1510))
w((1160,1510),(1160,1560));power('3V3',1160,1560)
w((1240,1510),(1290,1510),(1290,1470));ground(1290,1470)
w((1055,1490),(1040,1490),(1040,1450));ground(1040,1450)
# Crystal
w((970,1260),(970,1190),(1070,1190));w((1000,1115),(1000,1190))
port('XTAL_P',(970,1300),(970,1330),(910,1330),left=True)
w((1130,1210),(1200,1210),(1200,1115));port('XTAL_N',(1200,1210),(1260,1210))
w((1070,1210),(1040,1210),(1040,1250));ground(1040,1250,0)
w((1130,1190),(1160,1190),(1160,1160));ground(1160,1160)
for x in [1000,1200]:w((x,1085),(x,1055));ground(x,1055)
emit('single-sheet-wire-ldo-crystal')
# Microphone
port('I2S_WS',(385,880),(365,880),(365,900),(250,900),left=True)
w((385,870),(350,870),(350,810));w((385,860),(350,860));ground(350,810)
w((455,870),(490,870),(490,900),(580,900));w((490,900),(490,940));power('3V3',490,940)
w((620,900),(660,900),(660,870));ground(660,870)
port('I2S_BCLK',(455,860),(480,860),(480,830),(720,830))
w((455,880),(470,880),(470,960),(710,960),(710,800),(620,800))
port('MIC_SD',(710,960),(750,960));w((580,800),(540,800),(540,770));ground(540,770)
# Amplifier
for i,n in enumerate(['AMP_CTRL','I2S_WS','I2S_BCLK','AMP_DIN']):
    port(n,(1005,870-10*i),(985-10*i,870-10*i),(985-10*i,960-20*i),(900,960-20*i),left=True)
for i,n in enumerate(['SPK_N','3V3','GND','SPK_P','GND']):
    port(n,(1095,840+10*i),(1115+10*i,840+10*i),(1115+10*i,800+20*i),(1160,800+20*i))
for y in [920,750]:
    w((1180,y),(1150,y),(1150,y+30));power('3V3',1150,y+30)
    w((1220,y),(1270,y),(1270,y-30));ground(1270,y-30)
port('AMP_CTRL',(930,760),(860,760),left=True);w((970,760),(1000,760),(1000,730));ground(1000,730)
port('SPK_P',(1260,685),(1240,685),(1240,705),(1180,705),left=True)
port('SPK_N',(1260,675),(1240,675),(1240,655),(1180,655),left=True)
emit('single-sheet-wire-audio')
# Reset, boot and user interface
w((220,530),(220,510),(350,510),(350,490),(390,490));w((320,490),(320,510));port('CHIP_EN',(220,510),(160,510),left=True)
w((220,570),(220,600));power('3V3',220,600)
w((320,450),(320,430));ground(320,430);w((450,490),(480,490),(480,450));ground(480,450)
w((620,530),(620,470),(750,470));port('BOOT_GPIO9',(620,500),(560,500),left=True)
w((620,570),(620,600));power('3V3',620,600);w((810,470),(840,470),(840,440));ground(840,440)
port('BOOT_GPIO2',(940,530),(940,500),(880,500),left=True)
port('LED_GPIO8',(1100,530),(1100,500),(1160,500))
for x in [940,1100]:w((x,570),(x,600));power('3V3',x,600)
w((1040,380),(1120,380));w((1160,380),(1200,380),(1200,410));power('3V3',1200,410)
port('LED_GPIO8',(1000,380),(960,380),left=True)
port('REC_KEY',(610,360),(550,360),left=True);w((650,360),(700,360),(700,330));ground(700,330)
# RF
port('RF_IN',(380,230),(200,230),left=True);w((200,230),(200,150),(240,150))
w((280,150),(310,150),(310,110));ground(310,110)
w((420,230),(570,230),(570,190),(670,190),(670,200))
w((470,230),(470,150),(500,150));w((540,150),(570,150),(570,110));ground(570,110)
w((620,230),(600,230),(600,280));ground(600,280,0)
w((720,230),(750,230),(750,160));ground(750,160)
emit('single-sheet-wire-control-rf')
# Charger and system switching
w((1735,1420),(1660,1420),(1660,1520),(1760,1520))
w((1800,1520),(1930,1520),(1930,1410),(1825,1410));w((1930,1410),(1930,1370),(2020,1370))
w((2060,1370),(2120,1370),(2120,1340));ground(2120,1340)
w((1930,1520),(1930,1560));power('SYS',1930,1560)
port('VBUS_CHG',(1825,1420),(1855,1420),(1855,1470),(1900,1470))
w((2020,1430),(1990,1430),(1990,1470));power('VBUS_CHG',1990,1470)
w((2060,1430),(2090,1430),(2090,1400));ground(2090,1400)
w((1825,1400),(1870,1400),(1870,1310),(2020,1310));w((1950,1310),(1950,1340));power('VBAT',1950,1340)
w((2060,1310),(2090,1310),(2090,1280));ground(2090,1280)
w((1825,1390),(1845,1390),(1845,1220),(1880,1220));w((1920,1220),(1960,1220),(1960,1180));ground(1960,1180)
w((1735,1410),(1710,1410),(1710,1350));w((1735,1400),(1710,1400));ground(1710,1350)
w((1825,1430),(1840,1430),(1840,1450));ground(1840,1450,0)
w((2170,1495),(2140,1495),(2140,1530));power('VBAT',2140,1530)
w((2170,1485),(2150,1485),(2150,1450));ground(2150,1450)
port('SYS',(2190,1236),(2190,1200),(2240,1200))
port('SYS_SW',(2180,1236),(2180,1220),(2120,1220),left=True)
add('no-connect',designator='U2',pin='4');add('no-connect',designator='SW1',pin='3')
emit('single-sheet-wire-charger')
# USB connector fanout and ESD
nets=['GND','VBUS_USB',None,'USB_CC1','USB_DM_CONN','USB_DP_CONN','USB_DM_CONN','USB_DP_CONN',None,'USB_CC2','VBUS_USB','GND']
for i,n in enumerate(nets):
    if not n:continue
    y=925-10*i;t=985-20*i;lane=1735-10*(i if t>=y else 11-i)
    port(n,(1755,y),(lane,y),(lane,t),(1550,t),left=True)
for y in [845,835,825,815]:w((1825,y),(1850,y))
w((1850,845),(1850,785));ground(1850,785)
for x,n in [(1570,'USB_CC1'),(1790,'USB_CC2')]:
    port(n,(x-20,700),(x-60,700),left=True);w((x+20,700),(x+60,700),(x+60,670));ground(x+60,670)
for y,n in [(950,'USB_DP'),(850,'USB_DM')]:
    w((2020,y),(1980,y),(1980,y+50),(2150,y+50));port(n+'_CONN',(1980,y+50),(1940,y+50),left=True)
    port(n,(2060,y),(2130,y));w((2210,y+50),(2250,y+50),(2250,y+20));ground(2250,y+20)
port('VBUS_USB',(1580,610),(1510,610),left=True);w((1620,610),(1760,610));port('VBUS_CHG',(1800,610),(1900,610))
add('no-connect',designator='J1',pin='A8,B8')
# Battery measurement
w((1020,290),(1020,320));power('SYS_SW',1020,320)
w((1020,250),(1020,170));w((1020,210),(1200,210),(1200,170));port('SYS_ADC',(1200,210),(1280,210))
w((1020,130),(1020,100),(1200,100),(1200,130));ground(1020,100)
emit('single-sheet-wire-usb-adc')
