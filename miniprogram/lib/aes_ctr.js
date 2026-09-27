// AES-256-CTR,只做加密方向(CTR 模式解密 = 加密)。
//
// 按 FIPS-197 直写的字节版,没有查表优化:配网全程只加解密几百字节,快慢无所谓,
// 可读、可对着标准逐步核对更重要。正确性由 test/crypto.test.js 的 NIST 向量兜底。
// 本文件为本项目原创,随本项目许可使用。

// S 盒现算:用生成元 3 遍历 GF(2^8) 的非零元素,同时得到逆元,再做仿射变换
const SBOX = new Uint8Array(256)
;(function () {
  const rotl = (x, s) => ((x << s) | (x >> (8 - s))) & 0xff
  let p = 1, q = 1
  do {
    p = p ^ ((p << 1) & 0xff) ^ (p & 0x80 ? 0x1b : 0)          // p *= 3
    q ^= q << 1; q ^= q << 2; q ^= q << 4; q &= 0xff          // q /= 3
    if (q & 0x80) q ^= 0x09
    SBOX[p] = q ^ rotl(q, 1) ^ rotl(q, 2) ^ rotl(q, 3) ^ rotl(q, 4) ^ 0x63
  } while (p !== 1)
  SBOX[0] = 0x63
})()

const xtime = (a) => ((a << 1) ^ (a & 0x80 ? 0x1b : 0)) & 0xff

// 32 字节密钥 -> 15 轮 × 16 字节轮密钥
function expandKey(key) {
  if (key.length !== 32) throw new Error('AES-256 需要 32 字节密钥')
  const w = new Uint8Array(240)
  w.set(key)
  let rcon = 1
  for (let i = 32; i < 240; i += 4) {
    let t0 = w[i - 4], t1 = w[i - 3], t2 = w[i - 2], t3 = w[i - 1]
    if (i % 32 === 0) {            // RotWord + SubWord + Rcon
      const t = t0
      t0 = SBOX[t1] ^ rcon; t1 = SBOX[t2]; t2 = SBOX[t3]; t3 = SBOX[t]
      rcon = xtime(rcon)
    } else if (i % 32 === 16) {    // AES-256 特有:中间多一次 SubWord
      t0 = SBOX[t0]; t1 = SBOX[t1]; t2 = SBOX[t2]; t3 = SBOX[t3]
    }
    w[i] = w[i - 32] ^ t0
    w[i + 1] = w[i - 31] ^ t1
    w[i + 2] = w[i - 30] ^ t2
    w[i + 3] = w[i - 29] ^ t3
  }
  return w
}

// 加密一个块。state 按列存:s[列*4 + 行]
function encryptBlock(rk, input, out) {
  let s = new Uint8Array(16)
  for (let i = 0; i < 16; i++) s[i] = input[i] ^ rk[i]
  for (let round = 1; round <= 14; round++) {
    const t = new Uint8Array(16)
    for (let c = 0; c < 4; c++)          // SubBytes + ShiftRows(第 r 行左移 r)
      for (let r = 0; r < 4; r++) t[c * 4 + r] = SBOX[s[((c + r) & 3) * 4 + r]]
    if (round < 14) {                    // MixColumns,最后一轮没有
      for (let c = 0; c < 4; c++) {
        const a0 = t[c * 4], a1 = t[c * 4 + 1], a2 = t[c * 4 + 2], a3 = t[c * 4 + 3]
        const x = a0 ^ a1 ^ a2 ^ a3
        t[c * 4] = a0 ^ x ^ xtime(a0 ^ a1)
        t[c * 4 + 1] = a1 ^ x ^ xtime(a1 ^ a2)
        t[c * 4 + 2] = a2 ^ x ^ xtime(a2 ^ a3)
        t[c * 4 + 3] = a3 ^ x ^ xtime(a3 ^ a0)
      }
    }
    for (let i = 0; i < 16; i++) t[i] ^= rk[round * 16 + i]
    s = t
  }
  out.set(s)
}

// 连续的 CTR 密钥流:字节偏移跨调用保留(不按块对齐),计数器 128 bit 大端整体 +1,
// 和 mbedtls_aes_crypt_ctr 的 nc_off / stream_block 行为一致。
function AesCtr(key, iv) {
  const rk = expandKey(key)
  const counter = Uint8Array.from(iv)
  const block = new Uint8Array(16)
  let off = 16
  if (counter.length !== 16) throw new Error('CTR 初始计数器必须 16 字节')

  this.update = function (data) {
    const out = new Uint8Array(data.length)
    for (let i = 0; i < data.length; i++) {
      if (off === 16) {
        encryptBlock(rk, counter, block)
        for (let j = 15; j >= 0; j--) { counter[j]++; if (counter[j] !== 0) break }  // 回绕成 0 才进位
        off = 0
      }
      out[i] = data[i] ^ block[off++]
    }
    return out
  }
}

module.exports = { AesCtr, encryptBlock, expandKey }
