// 微信 BLE API 的薄封装:开适配器、扫玩偶、连接、按端点收发、关闭。
//
// protocomm 的 BLE 传输很朴素:一次请求 = 往端点特征值**写一次**整条消息(Write Request),
// 再**读一次**同一个特征值拿响应,没有 notify、没有分片。所以:
//   - 每条消息必须一次 ATT 写完 —— 安卓要手动 setBLEMTU 调大,iOS 自己协商
//   - 空写会被忽略,读回来是上一次的旧响应 —— 绝不发 0 字节
//   - 同一时刻只能有一个请求在路上(prov.js 已经串行化,这里只留一个 pending)

const SERVICE = '10624C9A-F2AA-4CA8-8594-9CD3CC78DB3F'
const NAME_PREFIX = 'AIFIG_'
// 端点名 -> 16 bit id;特征值 UUID = 服务 UUID 第一段的第 5~8 个十六进制字符换成它
const ENDPOINTS = {
  'prov-ctrl': 'FF4F', 'prov-scan': 'FF50', 'prov-session': 'FF51', 'prov-config': 'FF52', 'proto-ver': 'FF53',
}
const charUuid = (id) => '1062' + id + SERVICE.slice(8)
const XFER_TIMEOUT_MS = 8000

// wx.xxx({... success, fail}) -> Promise
function call(api, opt) {
  return new Promise((resolve, reject) => {
    wx[api](Object.assign({}, opt, { success: resolve, fail: reject }))
  })
}

const platform = () => (wx.getDeviceInfo ? wx.getDeviceInfo() : wx.getSystemInfoSync()).platform

// 把 wx 的错误翻成用户看得懂的话。自己抛的 Error 原样返回 message
function errText(e) {
  if (!e) return '未知错误'
  const msg = e.errMsg || e.message || String(e)
  if (/location/i.test(msg) || e.errCode === 10016)
    return '安卓手机扫描蓝牙需要打开系统「定位」开关,并允许微信使用位置信息'
  if (/auth|permission|denied/i.test(msg))
    return '微信没有蓝牙权限:请在系统设置里允许微信使用蓝牙,并在小程序右上角「···→设置」里打开蓝牙'
  switch (e.errCode) {
    case 10001: return '手机蓝牙没打开,请打开蓝牙后重试'
    case 10003: return '连接玩偶失败,请靠近一点再试'
    case 10012: return '连接超时,请靠近玩偶再试'
    case 10004:
    case 10005: return '这个设备上找不到配网服务:是不是没进配网模式,或固件太旧?'
    case 10006: return '蓝牙连接已断开'
    case 10009: return '手机系统版本太低,不支持低功耗蓝牙'
  }
  return e.errCode ? msg + '(' + e.errCode + ')' : msg
}

function toBuf(u8) { return u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.length) }

// ---- 适配器 + 扫描 ----

async function openAdapter() {
  if (platform() === 'android' && wx.getSystemSetting) {
    // 提前查,比等扫描莫名其妙扫不到强
    const s = wx.getSystemSetting()
    if (s.bluetoothEnabled === false) throw { errCode: 10001 }
    if (s.locationEnabled === false) throw { errCode: 10016 }
  }
  await call('openBluetoothAdapter', { mode: 'central' })
}

const isDoll = (d) =>
  (d.advertisServiceUUIDs || []).some((u) => u.toUpperCase() === SERVICE) ||
  (d.name || d.localName || '').startsWith(NAME_PREFIX)

let foundCb = null

// onFound({deviceId, name, RSSI}) 每发现/更新一台玩偶调一次
function startScan(onFound) {
  stopScanListener()
  foundCb = (res) => {
    for (const d of res.devices) {
      if (isDoll(d)) onFound({ deviceId: d.deviceId, name: d.name || d.localName || d.deviceId, RSSI: d.RSSI })
    }
  }
  wx.onBluetoothDeviceFound(foundCb)
  // 不按服务过滤:名字前缀也算,万一哪台手机拿不到广播里的 128 bit UUID
  return call('startBluetoothDevicesDiscovery', { allowDuplicatesKey: true, interval: 500 })
}

function stopScanListener() {
  if (foundCb && wx.offBluetoothDeviceFound) wx.offBluetoothDeviceFound(foundCb)
  foundCb = null
}

function stopScan() {
  stopScanListener()
  return call('stopBluetoothDevicesDiscovery', {}).catch(() => {})
}

// ---- 连接 + 收发 ----

let conn = null   // { deviceId, chars: {端点名: 特征值 UUID}, pending, onDisconnect }
let listenersOn = false

function onValue(res) {
  const p = conn && conn.pending
  if (!p || res.deviceId !== conn.deviceId || res.characteristicId.toUpperCase() !== p.uuid.toUpperCase()) return
  conn.pending = null
  clearTimeout(p.timer)
  p.resolve(new Uint8Array(res.value))
}

function onState(res) {
  if (!conn || res.deviceId !== conn.deviceId || res.connected) return
  const c = conn
  conn = null
  if (c.pending) { clearTimeout(c.pending.timer); c.pending.reject({ errCode: 10006 }) }
  if (c.onDisconnect) c.onDisconnect()
}

// 连上并找齐端点。onDisconnect:意外断开时回调(加密会话随之作废)
async function connect(deviceId, onDisconnect) {
  await stopScan()
  if (!listenersOn) {
    wx.onBLECharacteristicValueChange(onValue)
    wx.onBLEConnectionStateChange(onState)
    listenersOn = true
  }
  await call('createBLEConnection', { deviceId, timeout: 10000 })
  conn = { deviceId, chars: {}, pending: null, onDisconnect }
  try {
    if (platform() === 'android') {
      // 默认 23 字节 MTU 装不下一条 SetConfig;失败也继续,短消息还能用
      await call('setBLEMTU', { deviceId, mtu: 256 }).catch((e) => console.warn('setBLEMTU 失败', e))
    }
    // 读写前必须先拿过服务和特征值,微信要求的
    const { services } = await call('getBLEDeviceServices', { deviceId })
    const svc = services.find((s) => s.uuid.toUpperCase() === SERVICE)
    if (!svc) throw { errCode: 10004 }
    conn.serviceId = svc.uuid
    const { characteristics } = await call('getBLEDeviceCharacteristics', { deviceId, serviceId: svc.uuid })
    for (const name in ENDPOINTS) {
      const want = charUuid(ENDPOINTS[name])
      const c = characteristics.find((x) => x.uuid.toUpperCase() === want)
      if (c) conn.chars[name] = c.uuid
    }
    for (const need of ['proto-ver', 'prov-session', 'prov-config', 'prov-ctrl'])
      if (!conn.chars[need]) throw { errCode: 10005 }
  } catch (e) {
    await close()
    throw e
  }
}

// 写整条请求,再读回响应(响应经 onBLECharacteristicValueChange 送到)
async function xfer(ep, bytes) {
  if (!conn) throw { errCode: 10006 }
  if (!bytes.length) throw new Error('不能发空消息')   // 设备会忽略空写,读回旧数据
  const c = conn
  const uuid = c.chars[ep]
  const target = { deviceId: c.deviceId, serviceId: c.serviceId, characteristicId: uuid }
  const resp = new Promise((resolve, reject) => {
    c.pending = { uuid, resolve, reject, timer: setTimeout(() => {
      c.pending = null
      reject(new Error('玩偶没有响应,请靠近后重新连接'))
    }, XFER_TIMEOUT_MS) }
  })
  resp.catch(() => {})   // 写失败后它可能永远没人等,别报"未处理的 rejection"
  try {
    await call('writeBLECharacteristicValue', Object.assign({ value: toBuf(bytes), writeType: 'write' }, target))
    await call('readBLECharacteristicValue', target)
  } catch (e) {
    if (c.pending) { clearTimeout(c.pending.timer); c.pending = null }
    throw e
  }
  return resp
}

// 离开页面 / 结束 / 出错时调。什么状态下调都安全
async function close() {
  await stopScan()
  if (conn) {
    const c = conn
    conn = null
    if (c.pending) { clearTimeout(c.pending.timer); c.pending.reject(new Error('已断开')) }
    await call('closeBLEConnection', { deviceId: c.deviceId }).catch(() => {})
  }
  if (listenersOn) {
    if (wx.offBLECharacteristicValueChange) wx.offBLECharacteristicValueChange(onValue)
    if (wx.offBLEConnectionStateChange) wx.offBLEConnectionStateChange(onState)
    listenersOn = false
  }
  await call('closeBluetoothAdapter', {}).catch(() => {})
}

module.exports = { openAdapter, startScan, stopScan, connect, xfer, close, errText }
