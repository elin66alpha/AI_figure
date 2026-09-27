// 加密原语对标准向量:node miniprogram/test/crypto.test.js
const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const { scalarMult, scalarMultBase } = require('../lib/x25519')
const { AesCtr, encryptBlock, expandKey } = require('../lib/aes_ctr')

const hex = (s) => Uint8Array.from(Buffer.from(s.replace(/\s+/g, ''), 'hex'))
const toHex = (u8) => Buffer.from(u8).toString('hex')

test('X25519:RFC 7748 §6.1 Alice/Bob', () => {
  const aPriv = hex('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a')
  const bPriv = hex('5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb')
  const aPub = scalarMultBase(aPriv), bPub = scalarMultBase(bPriv)
  assert.equal(toHex(aPub), '8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a')
  assert.equal(toHex(bPub), 'de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f')
  const k = '4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742'
  assert.equal(toHex(scalarMult(aPriv, bPub)), k)
  assert.equal(toHex(scalarMult(bPriv, aPub)), k)
})

test('X25519:RFC 7748 §5.2 向量 1(u 最高位要忽略)', () => {
  const out = scalarMult(hex('a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4'),
    hex('e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c'))
  assert.equal(toHex(out), 'c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552')
})

test('X25519:和 node:crypto 随机互验', () => {
  for (let i = 0; i < 20; i++) {
    const priv = crypto.randomBytes(32)
    const { publicKey, privateKey } = crypto.generateKeyPairSync('x25519')
    const nodePub = Buffer.from(publicKey.export({ format: 'jwk' }).x, 'base64url')
    const ours = scalarMult(priv, nodePub)
    const myPub = Buffer.from(scalarMultBase(priv))
    const theirs = crypto.diffieHellman({ privateKey, publicKey: crypto.createPublicKey({ key: { kty: 'OKP', crv: 'X25519', x: myPub.toString('base64url') }, format: 'jwk' }) })
    assert.equal(toHex(ours), theirs.toString('hex'))
  }
})

test('AES-256:FIPS-197 附录 C.3 单块', () => {
  const out = new Uint8Array(16)
  encryptBlock(expandKey(hex('000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f')),
    hex('00112233445566778899aabbccddeeff'), out)
  assert.equal(toHex(out), '8ea2b7ca516745bfeafc49904b496089')
})

const F55 = {
  key: '603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4',
  iv: 'f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff',
  pt: `6bc1bee22e409f96e93d7e117393172a ae2d8a571e03ac9c9eb76fac45af8e51
       30c81c46a35ce411e5fbc1191a0a52ef f69f2445df4f9b17ad2b417be66c3710`,
  ct: `601ec313775789a5b7a7f504bbf3d228 f443e3ca4d62b59aca84e990cacaf5c5
       2b0930daa23de94ce87017ba2d84988d dfc9c58db67aada613c2dd08457941a6`,
}

test('AES-256-CTR:NIST SP 800-38A F.5.5', () => {
  const c = new AesCtr(hex(F55.key), hex(F55.iv))
  assert.equal(toHex(c.update(hex(F55.pt))), F55.ct.replace(/\s+/g, ''))
  // F.5.6 解密 = 同一操作
  const d = new AesCtr(hex(F55.key), hex(F55.iv))
  assert.equal(toHex(d.update(hex(F55.ct))), F55.pt.replace(/\s+/g, ''))
})

test('AES-256-CTR:任意切块 = 一次处理(偏移跨调用保留),计数器 128 bit 进位对得上 node', () => {
  const key = crypto.randomBytes(32)
  const iv = hex('00ffffffffffffffffffffffffffffff')   // 很快就要跨 15 个字节进位
  const data = crypto.randomBytes(1000)
  const whole = new AesCtr(key, iv).update(data)
  const ref = crypto.createCipheriv('aes-256-ctr', key, iv).update(data)
  assert.equal(toHex(whole), ref.toString('hex'))

  const c = new AesCtr(key, iv)
  const parts = []
  let p = 0
  for (const n of [0, 1, 31, 32, 5, 16, 17, 3, 200, 695]) { parts.push(c.update(data.subarray(p, p + n))); p += n }
  assert.equal(p, 1000)
  assert.equal(Buffer.concat(parts).toString('hex'), ref.toString('hex'))
})
