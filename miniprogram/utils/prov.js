// 乐鑫 protocomm / network_provisioning 客户端,Security 1,无 PoP。
//
// 和传输层无关:只要一个 xfer(端点名, 请求字节) -> Promise<响应字节>。
// 真机上是 BLE 写+读(utils/ble.js),测试里是 Node 模拟设备(test/mock_device.js)。
//
// 协议细节对照的是 ESP-IDF v5.5 protocomm/src/security/security1.c 和
// network_provisioning 1.0.2 的 proto/*.proto、src/network_config.c、src/network_ctrl.c,
// 要点见 README.md。

const pb = require('./pb')
const { scalarMult, scalarMultBase } = require('../lib/x25519')
const { AesCtr } = require('../lib/aes_ctr')

// constants.proto 的 Status
const STATUS_TEXT = ['成功', '安全方案不匹配', '协议错误', '会话太多', '参数错误', '设备内部错误', '加密错误', '会话无效']
const EMPTY = new Uint8Array(0)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function createProv(xfer) {
  let ctr = null          // 整个会话**唯一**一条 CTR 密钥流,两个方向、所有端点共用
  let broken = false      // 传输出过错 = 两端密钥流位置可能已错开,只能断开重来
  let needReset = false   // 上次连 WiFi 失败:设备拒绝再次 Apply,要先发 ctrl reset
  let chain = Promise.resolve()

  // 密钥流按调用顺序消耗,请求绝不能交叠 —— 所有对外操作都排进这一条链
  function serial(fn) {
    const p = chain.then(() => {
      if (broken) throw new Error('加密会话已失效,请重新连接玩偶')
      return fn()
    })
    chain = p.catch(() => {})
    return p
  }

  // 加密请求 -> 发 -> 解密响应。设备回的是正常响应(哪怕 status 非 0),流就还对得上;
  // 只有传输层失败才算错位。
  async function secure(ep, fields) {
    const req = ctr.update(pb.encode(fields))
    try {
      return pb.decode(ctr.update(await xfer(ep, req)))
    } catch (e) {
      broken = true
      throw e
    }
  }

  function checkStatus(st, what) {
    st = st || 0
    if (st !== 0) throw new Error(what + '被玩偶拒绝:' + (STATUS_TEXT[st] || st))
  }

  // NetworkConfigPayload:发 fields,取回响应里 respField 那个子消息
  async function config(fields, respField, what) {
    const body = (await secure('prov-config', fields))[respField]
    if (!body) throw new Error('玩偶回复格式不对(' + what + ')')
    const r = pb.decode(body)
    checkStatus(r[1], what)
    return r
  }

  // SessionData 响应 -> 取出 Sec1Payload 里的 sr0 / sr1
  function sec1Resp(buf, field) {
    const d = pb.decode(buf)
    if (d[2] !== 1) throw new Error('玩偶的安全方案不是 Security 1')
    const r = pb.decode(pb.decode(d[11] || EMPTY)[field] || EMPTY)
    checkStatus(r[1], '加密握手')
    return r
  }

  // proto-ver 明文端点:写任意非空字节,读回 JSON。用来确认固件是 Sec1、不要 PoP。
  function protoVer() {
    return serial(async () => {
      const info = JSON.parse(pb.ascii(await xfer('proto-ver', pb.utf8('---'))))
      const p = info.prov || {}
      if (p.sec_ver !== 1) throw new Error('玩偶固件的安全版本是 ' + p.sec_ver + ',小程序只支持 1')
      return info
    })
  }

  // Security 1 握手。priv = 32 字节随机数(调用方用 wx.getRandomValues 生成)
  function handshake(priv) {
    return serial(async () => {
      try {
        const cliPub = scalarMultBase(priv)
        // Cmd0:SessionData{sec_ver=1, sec1{msg=Command0(0), sc0{client_pubkey}}}
        const r0 = sec1Resp(await xfer('prov-session',
          pb.encode([[2, 1], [11, [[20, [[1, cliPub]]]]]])), 21)
        const devPub = r0[2], devRand = r0[3]
        if (!devPub || devPub.length !== 32 || !devRand || devRand.length !== 16)
          throw new Error('玩偶握手回复格式不对')

        // 无 PoP:AES 密钥就是 X25519 共享密钥本身;初始计数器 = device_random
        ctr = new AesCtr(scalarMult(priv, devPub), devRand)

        // Cmd1:client_verify = 密钥流[0,32) XOR 设备公钥
        const r1 = sec1Resp(await xfer('prov-session',
          pb.encode([[2, 1], [11, [[1, 2], [22, [[2, ctr.update(devPub)]]]]]])), 23)
        // 设备证明 = 密钥流[32,64) XOR 我方公钥
        const check = ctr.update(r1[3] || EMPTY)
        if (check.length !== 32 || check.some((b, i) => b !== cliPub[i]))
          throw new Error('玩偶身份校验失败')
      } catch (e) {
        broken = true
        throw e
      }
    })
  }

  // ssid / pass 都是 UTF-8 字节。字段 12(cmd_set_wifi_config)必须在场,pb.encode 保证这点
  function setWifi(ssid, pass) {
    return serial(() => config([[1, 2], [12, [[1, ssid], [2, pass]]]], 13, '发送 WiFi 信息'))
  }

  function apply() {
    return serial(() => config([[1, 4], [14, []]], 15, '应用 WiFi 配置'))
  }

  // 返回 {state:'connecting'} / {state:'connected', ip} / {state:'failed', reason:'auth'|'notfound'}
  function getStatus() {
    return serial(async () => {
      // msg=GetWifiStatus(0) 不上线,只剩空的 cmd_get_wifi_status —— 请求不能是 0 字节
      const r = await config([[10, []]], 11, '查询状态')
      const state = r[2] || 0                 // Connected=0 在线上是缺省的
      if (state === 1) return { state: 'connecting' }
      if (state === 0) return { state: 'connected', ip: pb.ascii(pb.decode(r[11] || EMPTY)[1] || EMPTY) }
      // 3=ConnectionFailed(2=Disconnected 设备实际不发)。原因缺省按 proto3 当 0=AuthError
      return { state: 'failed', reason: r[10] === 1 ? 'notfound' : 'auth' }
    })
  }

  // NetworkCtrlPayload{msg=CmdCtrlWifiReset(1), cmd_ctrl_wifi_reset{}};status 在外层字段 2
  function ctrlReset() {
    return serial(async () => {
      const r = await secure('prov-ctrl', [[1, 1], [11, []]])
      checkStatus(r[2], '重置 WiFi 状态')
    })
  }

  // 完整一轮:(必要时先 reset)-> Set -> Apply -> 每 intervalMs 查一次状态直到出结果。
  // 结果多一种 {state:'timeout'}:设备还在连,可能在按"非密码类原因"不停重试。
  async function provision(ssid, pass, opt) {
    const { timeoutMs = 30000, intervalMs = 1000, onStep = () => {} } = opt || {}
    if (needReset) {
      onStep('重置玩偶的 WiFi 状态…')
      await ctrlReset()
      needReset = false
    }
    onStep('发送 WiFi 信息…')
    await setWifi(ssid, pass)
    await apply()
    onStep('玩偶正在连 WiFi…')
    const t0 = Date.now()
    for (;;) {
      await sleep(intervalMs)
      const s = await getStatus()
      if (s.state === 'failed') needReset = true
      if (s.state !== 'connecting') return s
      if (Date.now() - t0 >= timeoutMs) return { state: 'timeout' }
    }
  }

  return { protoVer, handshake, setWifi, apply, getStatus, ctrlReset, provision }
}

module.exports = { createProv }
