// Node 模拟的玩偶:照着 C 源码独立写的设备端,不复用小程序的任何代码。
// 加密全用 node:crypto(X25519 + 'aes-256-ctr'),和小程序那套自写实现互相印证。
//
// 对照的源码(见 README「协议」一节):
//   ESP-IDF protocomm/src/security/security1.c   —— 握手、单条 CTR 流
//   network_provisioning src/network_config.c     —— Get/Set/Apply,resp.msg = req.msg + 1
//   network_provisioning src/network_ctrl.c       —— WiFi reset
//   network_provisioning src/manager.c            —— prov_state:>= CRED_RECV(含 FAIL)拒绝 Apply
//
// 失败(C 里 handler 返回非 ESP_OK)这里用 throw 表示,对应 BLE 上的 ATT 错误。

const crypto = require('node:crypto')

// ---- 自带的极简 protobuf(和 utils/pb.js 故意不同写法)----
function readMsg(buf) {
  const f = {}
  let p = 0
  function vint() {
    let v = 0n, s = 0n
    for (;;) {
      const b = buf[p++]
      if (b === undefined) throw new Error('mock: 截断')
      v |= BigInt(b & 0x7f) << s
      if (!(b & 0x80)) return Number(v)
      s += 7n
    }
  }
  while (p < buf.length) {
    const key = vint()
    if ((key & 7) === 0) f[key >> 3] = vint()
    else if ((key & 7) === 2) { const n = vint(); f[key >> 3] = buf.subarray(p, p + n); p += n }
    else throw new Error('mock: 不支持的线型')
  }
  return f
}
function vbytes(n) { const o = []; do { let b = n & 0x7f; n >>>= 7; if (n) b |= 0x80; o.push(b) } while (n); return Buffer.from(o) }
const V = (no, n) => Buffer.concat([vbytes(no << 3), vbytes(n)])
const L = (no, b) => Buffer.concat([vbytes((no << 3) | 2), vbytes(b.length), Buffer.from(b)])

// ---- X25519 原始 32 字节公钥 <-> KeyObject ----
const rawPub = (k) => Buffer.from(k.export({ format: 'jwk' }).x, 'base64url')
const pubFromRaw = (raw) => crypto.createPublicKey({ key: { kty: 'OKP', crv: 'X25519', x: Buffer.from(raw).toString('base64url') }, format: 'jwk' })

// Status 枚举
const OK = 0, INTERNAL_ERROR = 5, INVALID_ARG = 4

class MockDevice {
  // opts.join(ssid, pass) -> { result: 'ok'|'auth'|'notfound'|'hang', polls: 连接中要被查几次, ip }
  // opts.tamper: 把设备证明改坏,测试客户端能不能发现
  constructor(opts) {
    this.opts = opts || {}
    this.sess = 0              // 0=等 Cmd0, 1=等 Cmd1, 2=会话建立
    this.prov = 'started'      // started | cred_recv | fail | success
    this.wifi = { state: 'connecting' }   // calloc 出来的 wifi_state=0 就是 CONNECTING
    this.cfg = null
    this.counts = { ctrlReset: 0, apply: 0, getStatus: 0 }
    this.received = []         // 收到的 SetConfig 明文 {ssid, pass}
  }

  // 一次 BLE 写 + 读
  handle(ep, data) {
    if (!data.length) throw new Error('mock: 空写(真设备会忽略并返回旧数据)')
    switch (ep) {
      case 'proto-ver': return Buffer.from(JSON.stringify({ prov: { ver: 'netprov-v1.2', sec_ver: 1, cap: ['no_pop', 'wifi_prov', 'wifi_scan'] } }, null, 2))
      case 'prov-session': return this.session(data)
      case 'prov-config': return this.secured(data, (req) => this.config(req))
      case 'prov-ctrl': return this.secured(data, (req) => this.ctrl(req))
    }
    throw new Error('mock: 没有端点 ' + ep)
  }

  session(data) {
    const req = readMsg(data)
    if (req[2] !== 1) throw new Error('mock: sec_ver 不是 1')
    if (!req[11]) throw new Error('mock: 没有 sec1')
    const s1 = readMsg(req[11])
    const msg = s1[1] || 0
    if (msg === 0) {                       // Session_Command0
      this.sess = 0                        // C 里:不在 CMD0 状态就重开会话
      const sc0 = s1[20] && readMsg(s1[20])
      if (!sc0 || !sc0[1] || sc0[1].length !== 32) throw new Error('mock: 客户端公钥不对')
      const { publicKey, privateKey } = crypto.generateKeyPairSync('x25519')
      this.devPub = rawPub(publicKey)
      this.cliPub = Buffer.from(sc0[1])
      const key = crypto.diffieHellman({ privateKey, publicKey: pubFromRaw(this.cliPub) })   // 无 PoP,不异或
      const rand = crypto.randomBytes(16)
      this.stream = crypto.createCipheriv('aes-256-ctr', key, rand)   // 整个会话就这一条
      this.sess = 1
      // SessionData{sec_ver=1, sec1{msg=Response0(1), sr0{status 缺省, device_pubkey, device_random}}}
      return Buffer.concat([V(2, 1), L(11, Buffer.concat([V(1, 1), L(21, Buffer.concat([L(2, this.devPub), L(3, rand)]))]))])
    }
    if (msg === 2) {                       // Session_Command1
      if (this.sess !== 1) throw new Error('mock: 会话状态不对')
      const sc1 = s1[22] && readMsg(s1[22])
      if (!sc1 || !sc1[2] || sc1[2].length !== 32) throw new Error('mock: 客户端证明不对')
      const check = this.stream.update(sc1[2])
      if (!check.equals(this.devPub)) throw new Error('mock: Key mismatch')
      const proof = this.stream.update(this.cliPub)
      if (this.opts.tamper) proof[0] ^= 1
      this.sess = 2
      return Buffer.concat([V(2, 1), L(11, Buffer.concat([V(1, 3), L(23, L(3, proof))]))])
    }
    throw new Error('mock: 未知 sec1 msg ' + msg)
  }

  // protocomm:会话建立后,端点数据先整段解密给 handler,handler 的回复再整段加密
  secured(data, handler) {
    if (this.sess !== 2) throw new Error('mock: 加密会话没建立')
    const resp = handler(readMsg(this.stream.update(data)))
    return this.stream.update(resp)
  }

  config(req) {
    const msg = req[1] || 0
    let body
    if (msg === 0) {                       // GetWifiStatus
      if (!req[10]) throw new Error('mock: GetStatus 缺 cmd_get_wifi_status(真设备不查,但空消息会变成空写)')
      this.counts.getStatus++
      this.tick()
      const w = this.wifi
      if (w.state === 'connecting') body = V(2, 1)              // oneof 指针为 NULL,不上线
      else if (w.state === 'connected') body = L(11, Buffer.concat([L(1, Buffer.from(w.ip)), V(5, 6)]))
      else body = Buffer.concat([V(2, 3), Buffer.from([10 << 3, w.reason])])  // oneof 里的标量是 0 也上线
    } else if (msg === 2) {                // SetWifiConfig
      if (!req[12]) throw new Error('mock: cmd_set_wifi_config 为 NULL,C 里会解引用崩')
      const c = readMsg(req[12])
      const ssid = Buffer.from(c[1] || []), pass = Buffer.from(c[2] || [])
      if (ssid.length >= 33 || pass.length >= 64) body = V(1, INVALID_ARG)
      else { this.cfg = { ssid, pass }; this.received.push({ ssid: ssid.toString(), pass: pass.toString() }); body = Buffer.alloc(0) }
    } else if (msg === 4) {                // ApplyWifiConfig
      this.counts.apply++
      const cfg = this.cfg
      this.cfg = null                      // handlers.c:不管成败都 free
      if (!cfg || this.prov !== 'started') body = V(1, INTERNAL_ERROR)
      else {
        this.prov = 'cred_recv'
        const j = (this.opts.join || (() => ({ result: 'ok', polls: 1, ip: '192.168.1.50' })))(cfg.ssid.toString(), cfg.pass.toString())
        this.wifi = { state: 'connecting', left: j.polls, result: j.result, ip: j.ip || '0.0.0.0' }
        body = Buffer.alloc(0)
      }
    } else throw new Error('mock: 未知 config msg ' + msg)
    return Buffer.concat([V(1, msg + 1), L(11 + msg, body)])
  }

  // 模拟连 WiFi 的进展:每被查一次状态走一步
  tick() {
    const w = this.wifi
    if (w.state !== 'connecting' || w.result === undefined || w.result === 'hang') return
    if (w.left-- > 0) return
    if (w.result === 'ok') { w.state = 'connected'; this.prov = 'success' }
    else { w.state = 'disconnected'; w.reason = w.result === 'auth' ? 0 : 1; this.prov = 'fail' }
  }

  ctrl(req) {
    if (req[1] !== 1) throw new Error('mock: 只模拟了 CmdCtrlWifiReset')
    this.counts.ctrlReset++
    let st = INTERNAL_ERROR                // manager.c:不在 FAIL 状态就拒绝
    if (this.prov === 'fail') { this.prov = 'started'; st = OK }
    return Buffer.concat([V(1, 2), st ? V(2, st) : Buffer.alloc(0), L(12, [])])
  }
}

// 给 createProv 用的 xfer
const xferOf = (dev) => async (ep, bytes) => new Uint8Array(dev.handle(ep, Buffer.from(bytes)))

module.exports = { MockDevice, xferOf }
