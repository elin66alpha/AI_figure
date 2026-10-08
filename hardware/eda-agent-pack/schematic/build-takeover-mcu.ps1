$ErrorActionPreference = 'Stop'
$base = $PSScriptRoot
$raw = Get-Content -Raw -LiteralPath "$base\takeover-mcu-staged-readback.json" | ConvertFrom-Json
$dg = Get-Content -Raw -LiteralPath "$base\takeover-mcu-staged-designators.json" | ConvertFrom-Json
$old = Get-Content -Raw -LiteralPath "$base\audio-ldo-layout-input.json" | ConvertFrom-Json
$parts = @($raw.result.components | Where-Object { $_.designator })
$nets = @{}
$connections = @()
$components = @()
$measurements = @()
$intent = @{
 U1=@{'2'='3V3';'3'='3V3';'5'='SYS_ADC';'6'='BOOT_GPIO2';'7'='CHIP_EN';'8'='REC_KEY';'11'='3V3';'14'='LED_GPIO8';'15'='BOOT_GPIO9';'17'='3V3';'18'='VDD_SPI';'25'='USB_DM_MCU';'26'='USB_DP_MCU';'27'='UART_RX';'28'='UART_TX';'29'='XTAL_N';'30'='XTAL_P';'31'='3V3';'32'='3V3';'33'='GND'}
 C9=@{'1'='3V3';'2'='GND'}; C10=@{'1'='3V3';'2'='GND'}; C11=@{'1'='3V3';'2'='GND'}
 C12=@{'1'='3V3';'2'='GND'}; C13=@{'1'='3V3';'2'='GND'}; C14=@{'1'='VDD_SPI';'2'='GND'}
 C15=@{'1'='CHIP_EN';'2'='GND'}; C16=@{'1'='3V3';'2'='GND'}
 C17=@{'1'='XTAL_P';'2'='GND'}; C18=@{'1'='XTAL_N';'2'='GND'}
 R9=@{'1'='CHIP_EN';'2'='3V3'};R10=@{'1'='BOOT_GPIO2';'2'='3V3'}
 R11=@{'1'='LED_GPIO8';'2'='3V3'};R12=@{'1'='BOOT_GPIO9';'2'='3V3'}
 R13=@{'1'='LED_ANODE';'2'='3V3'};D3=@{'1'='LED_ANODE';'2'='LED_GPIO8'}
 SW2=@{'1'='CHIP_EN';'2'='GND'};SW3=@{'1'='BOOT_GPIO9';'2'='GND'};SW4=@{'1'='REC_KEY';'2'='GND'}
 Y1=@{'1'='XTAL_P';'3'='XTAL_N';'2'='GND';'4'='GND'}
}
foreach ($p in $parts) {
 if ($p.deviceIdentityError -or $p.device.uuid.Length -ne 32) { throw "Missing exact library identity $($p.designator)" }
 $pins=@(); $mpins=@()
 foreach($pin in $p.pins) {
  $net=$pin.net; $nc=$pin.noConnected
  if($intent.ContainsKey($p.designator) -and $intent[$p.designator].ContainsKey($pin.pinNumber)) { $net=$intent[$p.designator][$pin.pinNumber]; $nc=$false }
  if($p.designator -eq 'U1' -and $pin.pinNumber -in @('4','19','20','21','22','23','24')) { $nc=$true }
  $cp=@{number=$pin.pinNumber;name=$pin.pinName}
  if($nc) {$cp.noConnected=$true} elseif($net) {
   $nets[$net]=@{id=$net;name=$net;scope='global';role=$(if($net -eq 'GND'){'ground'}elseif($net -in @('3V3','VDD_SPI','SYS_SW')){'power'}else{'signal'})}
   $connections+=@{componentId=('cmp-'+$p.designator);pinNumber=$pin.pinNumber;netId=$net;kind='netlist'}
  }else {$cp.connectionState='unconnected'}
  $pins+=$cp
  $mpins+=@{number=$pin.pinNumber;name=$pin.pinName;net=$net;x=$pin.x;y=$pin.y;rotation=$pin.rotation}
 }
 $components+=@{id=('cmp-'+$p.designator);ref=$p.designator;device=@{libraryUuid=$p.device.libraryUuid;deviceUuid=$p.device.uuid;name=$p.device.name};pins=$pins}
 $attr=@($dg.designators | Where-Object parentId -eq $p.primitiveId)
 if($attr.Count -ne 1){throw "Missing measured designator $($p.designator)"}
 $measurements+=@{designator=$p.designator;value=$(if($p.otherProperty.Value){$p.otherProperty.Value}else{$p.otherProperty.Description});x=$p.x;y=$p.y;rotation=$p.rotation;mirror=$p.mirror;bbox=$p.bbox;pins=$mpins;textBboxes=@($attr[0].bbox)}
}
$owner = @{
 C9=@('1','U1','2');C10=@('1','U1','11');C11=@('1','U1','17');C12=@('1','U1','31');C13=@('1','U1','32');C14=@('1','U1','18');C15=@('1','U1','7');C16=@('1','U1','2');
 R9=@('1','U1','7');R10=@('1','U1','6');R11=@('1','U1','14');R12=@('1','U1','15');SW2=@('1','U1','7');SW3=@('1','U1','15');SW4=@('1','U1','8');D3=@('2','U1','14');R13=@('1','D3','1');Y1=@('1','U1','30');C17=@('1','Y1','1');C18=@('1','Y1','3')
}
$pol=@{};foreach($name in $nets.Keys){$pol[$name]=$(if($name -eq 'GND'){'local_ground'}elseif($name -in @('3V3','VDD_SPI','SYS_SW')){'local_power'}else{'module_port'})}
foreach($name in @('CHIP_EN','BOOT_GPIO2','LED_GPIO8','BOOT_GPIO9','LED_ANODE','REC_KEY','XTAL_P','XTAL_N')){$pol[$name]='direct'}
$per=@();foreach($ref in $owner.Keys){$a=$owner[$ref];$per+=@{componentId=('cmp-'+$ref);pinNumber=$a[0];attachTo=@{componentId=('cmp-'+$a[1]);pinNumber=$a[2]}}}
$modules=@(@{id='mcu';title='ESP32-C3 minimum system';coreComponentId='cmp-U1';netPolicies=$pol;peripherals=$per})
foreach($m in $old.layoutModules){if($m.id -in @('ldo','microphone','amplifier')){$modules+=$m}}
$canonicalModules=@()
foreach($m in $modules){
 $members=@($m.coreComponentId)+@($m.peripherals.componentId)
 $used=@($connections | Where-Object {$_.componentId -in $members} | Select-Object -ExpandProperty netId -Unique)
 $filtered=@{}
 foreach($name in $used){if($m.netPolicies -is [hashtable]){$filtered[$name]=$m.netPolicies[$name]}else{$filtered[$name]=$m.netPolicies.$name}}
 if($m -is [hashtable]){$m.netPolicies=$filtered}else{$m.netPolicies=[pscustomobject]$filtered}
 $canonicalModules+=@{id=$m.id;name=$m.title;coreComponents=@($m.coreComponentId);peripheralComponents=@($m.peripherals.componentId);internalNets=@();ports=@()}
}
@{schemaVersion=1;connectivity=@{schemaVersion='1.4';projectId='8c5d0d86032348a0a6c85102fe97607e';documentId='98cfe13509bc1f5c';components=$components;nets=@($nets.Values);connections=$connections;modules=$canonicalModules};sheet=$old.sheet;keepouts=$old.keepouts;measurements=$measurements;layoutModules=$modules;maxCandidates=1000000} | ConvertTo-Json -Depth 30 | Set-Content -Encoding utf8 -LiteralPath "$base\takeover-mcu-layout-input.json"

