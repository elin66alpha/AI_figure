// 端到端:utils/prov.js 对 Node 模拟设备跑完整配网。node miniprogram/test/prov.test.js
const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const { createProv } = require('../utils/prov')
const pb = require('../utils/pb')
const { MockDevice, xferOf } = require('./mock_device')

const FAST = { intervalMs: 0 }

async function connected(dev) {
  const prov = createProv(xferOf(dev))
  const info = await prov.protoVer()
  assert.ok(info.prov.cap.includes('no_pop'))
  await prov.handshake(crypto.randomBytes(32))
  return prov
}

test('握手 -> Set -> Apply -> 连接中 x3 -> 已连接(拿到 IP)', async () => {
  const dev = new MockDevice({ join: () => ({ result: 'ok', polls: 3, ip: '192.168.31.77' }) })
  const prov = await connected(dev)
  const steps = []
  const r = await prov.provision(pb.utf8('家里的WiFi'), pb.utf8('pass word 123'), { intervalMs: 0, onStep: (s) => steps.push(s) })
  assert.deepEqual(r, { state: 'connected', ip: '192.168.31.77' })
  assert.deepEqual(dev.received, [{ ssid: '家里的WiFi', pass: 'pass word 123' }])
  assert.equal(dev.counts.getStatus, 4)      // 3 次"连接中" + 1 次"已连接"
  assert.equal(dev.counts.ctrlReset, 0)
  assert.deepEqual(steps, ['发送 WiFi 信息…', '玩偶正在连 WiFi…'])
})

test('密码错 -> 同一会话 ctrl reset -> 改密码重试成功', async () => {
  const dev = new MockDevice({ join: (ssid, pass) => ({ result: pass === 'right-pass' ? 'ok' : 'auth', polls: 1, ip: '10.0.0.8' }) })
  const prov = await connected(dev)
  assert.deepEqual(await prov.provision(pb.utf8('AP'), pb.utf8('wrong-pass'), FAST), { state: 'failed', reason: 'auth' })
  assert.deepEqual(await prov.provision(pb.utf8('AP'), pb.utf8('right-pass'), FAST), { state: 'connected', ip: '10.0.0.8' })
  assert.equal(dev.counts.ctrlReset, 1)
  assert.equal(dev.counts.apply, 2)
})

test('找不到 WiFi 的原因能区分;不 reset 直接 Apply 会被拒,但会话不坏', async () => {
  const dev = new MockDevice({ join: (ssid) => ({ result: ssid === 'Home' ? 'ok' : 'notfound', polls: 0, ip: '1.2.3.4' }) })
  const prov = await connected(dev)
  assert.deepEqual(await prov.provision(pb.utf8('Home-5G'), pb.utf8(''), FAST), { state: 'failed', reason: 'notfound' })

  // 绕过 provision 的自动 reset:设备回 InternalError(正常响应,流还对得上)
  await prov.setWifi(pb.utf8('Home'), pb.utf8(''))
  await assert.rejects(prov.apply(), /应用 WiFi 配置被玩偶拒绝:设备内部错误/)
  // 之后 reset + 重来照样能用 —— 证明两端密钥流没错位
  await prov.ctrlReset()
  await prov.setWifi(pb.utf8('Home'), pb.utf8(''))
  await prov.apply()
  assert.deepEqual(await prov.getStatus(), { state: 'connected', ip: '1.2.3.4' })
})

test('不在失败状态时 ctrl reset 被拒(设备 InternalError)', async () => {
  const prov = await connected(new MockDevice())
  await assert.rejects(prov.ctrlReset(), /重置 WiFi 状态被玩偶拒绝/)
  // 仍然同步
  assert.deepEqual(await prov.getStatus(), { state: 'connecting' })
})

test('一直连接中 -> 超时', async () => {
  const dev = new MockDevice({ join: () => ({ result: 'hang' }) })
  const prov = await connected(dev)
  assert.deepEqual(await prov.provision(pb.utf8('AP'), pb.utf8('12345678'), { timeoutMs: 30, intervalMs: 5 }), { state: 'timeout' })
})

test('设备证明不对 -> 握手失败,之后的请求都拒绝', async () => {
  const prov = createProv(xferOf(new MockDevice({ tamper: true })))
  await assert.rejects(prov.handshake(crypto.randomBytes(32)), /玩偶身份校验失败/)
  await assert.rejects(prov.getStatus(), /加密会话已失效/)
})

test('传输出错 -> 会话作废', async () => {
  const dev = new MockDevice()
  let fail = false
  const xfer = xferOf(dev)
  const prov = createProv((ep, b) => (fail ? Promise.reject(new Error('ATT 错误')) : xfer(ep, b)))
  await prov.handshake(crypto.randomBytes(32))
  fail = true
  await assert.rejects(prov.getStatus(), /ATT 错误/)
  fail = false
  await assert.rejects(prov.getStatus(), /加密会话已失效/)
})

test('并发调用也按顺序串行,不会把密钥流搅乱', async () => {
  const dev = new MockDevice({ join: () => ({ result: 'ok', polls: 2, ip: '192.168.0.2' }) })
  const xfer = xferOf(dev)
  let inFlight = 0
  const prov = createProv(async (ep, b) => {
    assert.equal(++inFlight, 1)
    await new Promise((r) => setTimeout(r, 2))
    try { return await xfer(ep, b) } finally { inFlight-- }
  })
  await prov.handshake(crypto.randomBytes(32))
  const [, , a, b, c] = await Promise.all([
    prov.setWifi(pb.utf8('AP'), pb.utf8('12345678')), prov.apply(), prov.getStatus(), prov.getStatus(), prov.getStatus(),
  ])
  assert.deepEqual([a.state, b.state, c.state], ['connecting', 'connecting', 'connected'])
})

test('SSID 超长时设备回 InvalidArgument', async () => {
  const prov = await connected(new MockDevice())
  await assert.rejects(prov.setWifi(new Uint8Array(33).fill(65), pb.utf8('')), /参数错误/)
})
