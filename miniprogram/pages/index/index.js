// 唯一的页面:填 WiFi -> 扫描并点选玩偶 -> 连接 + 握手 + 配网 -> 结果。
// 连接成功后握手一次;失败(密码错 / 找不到 WiFi)就在同一个连接、同一个加密会话里重试。

const ble = require('../../utils/ble')
const pb = require('../../utils/pb')
const { createProv } = require('../../utils/prov')

const RESULT_TEXT = {
  auth: '密码错误,改一下再试',
  notfound: '找不到这个 WiFi —— 是不是 5G,或者名字填错了?',
  timeout: '30 秒还没连上:可能信号太弱,或路由器只开了 WPA3。请按住玩偶的按键重新上电(保持 3 秒)进配网模式,再试一次',
}

function random(n) {
  return new Promise((resolve, reject) => wx.getRandomValues({
    length: n,
    success: (r) => resolve(new Uint8Array(r.randomValues)),
    fail: reject,
  }))
}

// 设备端限制:SSID ≤ 32 字节、密码 ≤ 63 字节(UTF-8,一个汉字 3 字节)
function checkInput(ssid, pass) {
  if (!ssid.length) return '请填写 WiFi 名称'
  if (ssid.length > 32) return 'WiFi 名称太长(最多 32 字节,一个汉字算 3 个)'
  if (pass.length > 63) return '密码太长(最多 63 个字符)'
  if (pass.length && pass.length < 8) return 'WiFi 密码至少 8 位'
  return ''
}

Page({
  data: {
    ssid: '', password: '', showPwd: false, wifiHint: '',
    phase: 'scan',        // scan | busy | ok | fail
    devices: [], scanErr: '',
    step: '', msg: '', ip: '', canRetry: false,
  },

  prov: null,

  onLoad() {
    if (!wx.getRandomValues) {
      this.setData({ scanErr: '微信版本太旧,请升级微信后再用' })
      return
    }
    this.prefillSsid()
    this.startScan()
  },

  onUnload() {
    this.prov = null
    ble.close()
  },

  // 预填手机当前连着的 WiFi。拿不到(没权限、没连 WiFi)就算了,让用户自己填
  prefillSsid() {
    wx.startWifi({
      success: () => wx.getConnectedWifi({
        success: ({ wifi }) => {
          if (!wifi || !wifi.SSID || this.data.ssid) return
          // frequency 只有安卓给
          const hint = wifi.frequency > 4900 ? '手机现在连的是 5G WiFi,玩偶连不上 5G,请换成 2.4G 的那个' : ''
          this.setData({ ssid: wifi.SSID, wifiHint: hint })
        },
      }),
    })
  },

  onSsid(e) { this.setData({ ssid: e.detail.value, wifiHint: '' }) },
  onPwd(e) { this.setData({ password: e.detail.value }) },
  togglePwd() { this.setData({ showPwd: !this.data.showPwd }) },

  async startScan() {
    this.prov = null
    this.devMap = {}
    this.setData({ phase: 'scan', devices: [], scanErr: '', msg: '' })
    try {
      await ble.close()   // 从失败页回来时先把旧连接/适配器清干净
      await ble.openAdapter()
      await ble.startScan((d) => {
        this.devMap[d.deviceId] = d
        const devices = Object.values(this.devMap).sort((a, b) => b.RSSI - a.RSSI)
        this.setData({ devices })
      })
    } catch (e) {
      this.setData({ scanErr: ble.errText(e) })
    }
  },

  // 读输入并校验,不合法就提示并返回 null
  input() {
    const ssid = pb.utf8(this.data.ssid), pass = pb.utf8(this.data.password)
    const err = checkInput(ssid, pass)
    if (err) {
      wx.showToast({ title: err, icon: 'none', duration: 2500 })
      return null
    }
    return { ssid, pass }
  },

  async onPick(e) {
    const inp = this.input()
    if (!inp) return
    this.setData({ phase: 'busy', step: '连接玩偶…' })
    try {
      await ble.connect(e.currentTarget.dataset.id, () => this.onDisconnect())
      const prov = createProv(ble.xfer)
      this.prov = prov
      this.setData({ step: '检查固件版本…' })
      await prov.protoVer()
      this.setData({ step: '建立加密通道…' })
      await prov.handshake(await random(32))
      await this.run(inp)
    } catch (err) {
      this.fail(ble.errText(err), false)
    }
  },

  async onRetry() {
    const inp = this.input()
    if (!inp) return
    this.setData({ phase: 'busy', step: '' })
    try {
      await this.run(inp)
    } catch (err) {
      this.fail(ble.errText(err), false)
    }
  },

  async run({ ssid, pass }) {
    const r = await this.prov.provision(ssid, pass, { onStep: (step) => this.setData({ step }) })
    if (r.state === 'connected') {
      this.prov = null
      this.setData({ phase: 'ok', ip: r.ip })
      ble.close()   // 玩偶收到"已连接"查询后会自己停配网、重启
    } else {
      // 只有设备明确回了失败原因,才能在同一连接里 reset 后重试;超时就只能重来
      this.fail(RESULT_TEXT[r.reason || r.state], r.state === 'failed')
    }
  },

  fail(msg, canRetry) {
    this.setData({ phase: 'fail', msg, canRetry })
    if (!canRetry) {
      this.prov = null
      ble.close()
    }
  },

  onDisconnect() {
    if (this.data.phase === 'ok') return
    this.fail('蓝牙连接断开了,请重新连接玩偶', false)
  },
})
