// protobuf 编码对照固件期望的线上字节:node miniprogram/test/pb.test.js
const test = require('node:test')
const assert = require('node:assert/strict')
const pb = require('../utils/pb')

const toHex = (u8) => Buffer.from(u8).toString('hex')
const k32 = Uint8Array.from({ length: 32 }, (_, i) => i + 1)
const k32hex = toHex(k32)

test('Session Cmd0', () => {
  assert.equal(toHex(pb.encode([[2, 1], [11, [[20, [[1, k32]]]]]])), '10015a25a20122' + '0a20' + k32hex)
})

test('Session Cmd1', () => {
  assert.equal(toHex(pb.encode([[2, 1], [11, [[1, 2], [22, [[2, k32]]]]]])), '10015a270802b20122' + '1220' + k32hex)
})

test('SetWifiConfig(含中文 SSID)', () => {
  const ssid = pb.utf8('家WiFi'), pass = pb.utf8('12345678')
  const inner = '0a' + '07' + toHex(ssid) + '12' + '08' + toHex(pass)
  assert.equal(toHex(pb.encode([[1, 2], [12, [[1, ssid], [2, pass]]]])), '0802' + '62' + (inner.length / 2).toString(16).padStart(2, '0') + inner)
})

test('GetStatus / Apply / CtrlReset', () => {
  assert.equal(toHex(pb.encode([[10, []]])), '5200')
  assert.equal(toHex(pb.encode([[1, 4], [14, []]])), '08047200')
  assert.equal(toHex(pb.encode([[1, 1], [11, []]])), '08015a00')
})

test('多字节 varint 和长度', () => {
  const big = new Uint8Array(300)
  const e = pb.encode([[1, 300], [2, big]])
  assert.equal(toHex(e.subarray(0, 6)), '08ac02' + '12ac02')
  const d = pb.decode(e)
  assert.equal(d[1], 300)
  assert.equal(d[2].length, 300)
})

test('decode:缺字段为 undefined,跳过 fixed32/64', () => {
  const d = pb.decode(Uint8Array.from([0x08, 0x03, 0x15, 1, 2, 3, 4, 0x19, 1, 2, 3, 4, 5, 6, 7, 8, 0x5a, 0x02, 0x0a, 0x00]))
  assert.equal(d[1], 3)
  assert.equal(d[2], undefined)
  assert.equal(toHex(d[11]), '0a00')
  assert.throws(() => pb.decode(Uint8Array.from([0x0a, 0x05, 1])), /截断/)
})

test('utf8 与 Buffer 一致', () => {
  for (const s of ['', 'abc', '家里的WiFi', 'é', '😀x']) assert.equal(toHex(pb.utf8(s)), Buffer.from(s, 'utf8').toString('hex'))
})
