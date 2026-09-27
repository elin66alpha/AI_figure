// X25519(RFC 7748)—— 只留配网要用的 scalarMult / scalarMultBase。
//
// 取自 TweetNaCl-js 的 crypto_scalarmult,乘法用的是它早期版本的简单双循环写法
// (没展开,慢一点,但一次握手只算两次,手机上几毫秒)。
//
// TweetNaCl-js by Dmitry Chestnykh and Devi Mandiri, based on TweetNaCl by
// Daniel J. Bernstein, Bernard van Gastel, Wesley Janssen, Tanja Lange,
// Peter Schwabe, Sjaak Smetsers. Public domain (The Unlicense).
// https://github.com/dchest/tweetnacl-js

// 域元素 = 16 个 16 bit 肢,用 Float64Array 存(乘积累加不超过 2^53,不会丢精度)
function gf(init) {
  const r = new Float64Array(16)
  if (init) for (let i = 0; i < init.length; i++) r[i] = init[i]
  return r
}

const _121665 = gf([0xdb41, 1])
const _9 = new Uint8Array(32); _9[0] = 9

function car25519(o) {
  let c = 1
  for (let i = 0; i < 16; i++) {
    const v = o[i] + c + 65535
    c = Math.floor(v / 65536)
    o[i] = v - c * 65536
  }
  o[0] += c - 1 + 37 * (c - 1)
}

// 常数时间条件交换:b=1 交换 p/q
function sel25519(p, q, b) {
  const c = ~(b - 1)
  for (let i = 0; i < 16; i++) {
    const t = c & (p[i] ^ q[i])
    p[i] ^= t
    q[i] ^= t
  }
}

function pack25519(o, n) {
  const m = gf(), t = gf()
  for (let i = 0; i < 16; i++) t[i] = n[i]
  car25519(t); car25519(t); car25519(t)
  for (let j = 0; j < 2; j++) {
    m[0] = t[0] - 0xffed
    for (let i = 1; i < 15; i++) {
      m[i] = t[i] - 0xffff - ((m[i - 1] >> 16) & 1)
      m[i - 1] &= 0xffff
    }
    m[15] = t[15] - 0x7fff - ((m[14] >> 16) & 1)
    const b = (m[15] >> 16) & 1
    m[14] &= 0xffff
    sel25519(t, m, 1 - b)
  }
  for (let i = 0; i < 16; i++) {
    o[2 * i] = t[i] & 0xff
    o[2 * i + 1] = t[i] >> 8
  }
}

function unpack25519(o, n) {
  for (let i = 0; i < 16; i++) o[i] = n[2 * i] + (n[2 * i + 1] << 8)
  o[15] &= 0x7fff  // RFC 7748:u 坐标最高位忽略
}

function A(o, a, b) { for (let i = 0; i < 16; i++) o[i] = a[i] + b[i] }
function Z(o, a, b) { for (let i = 0; i < 16; i++) o[i] = a[i] - b[i] }

function M(o, a, b) {
  const t = new Float64Array(31)
  for (let i = 0; i < 16; i++) for (let j = 0; j < 16; j++) t[i + j] += a[i] * b[j]
  for (let i = 0; i < 15; i++) t[i] += 38 * t[i + 16]  // 2^256 ≡ 38 (mod p)
  for (let i = 0; i < 16; i++) o[i] = t[i]
  car25519(o); car25519(o)
}

function S(o, a) { M(o, a, a) }

// 求逆 = a^(p-2)
function inv25519(o, i) {
  const c = gf()
  for (let a = 0; a < 16; a++) c[a] = i[a]
  for (let a = 253; a >= 0; a--) {
    S(c, c)
    if (a !== 2 && a !== 4) M(c, c, i)
  }
  for (let a = 0; a < 16; a++) o[a] = c[a]
}

// 标量 n(32 字节,内部做 clamp)乘点 p(32 字节 u 坐标,小端),返回 32 字节
function scalarMult(n, p) {
  const z = new Uint8Array(32)
  for (let i = 0; i < 31; i++) z[i] = n[i]
  z[31] = (n[31] & 127) | 64
  z[0] &= 248

  const x = gf(), a = gf(), b = gf(), c = gf(), d = gf(), e = gf(), f = gf()
  unpack25519(x, p)
  for (let i = 0; i < 16; i++) b[i] = x[i]
  a[0] = d[0] = 1

  // Montgomery ladder
  for (let i = 254; i >= 0; --i) {
    const r = (z[i >>> 3] >>> (i & 7)) & 1
    sel25519(a, b, r)
    sel25519(c, d, r)
    A(e, a, c)
    Z(a, a, c)
    A(c, b, d)
    Z(b, b, d)
    S(d, e)
    S(f, a)
    M(a, c, a)
    M(c, b, e)
    A(e, a, c)
    Z(a, a, c)
    S(b, a)
    Z(c, d, f)
    M(a, c, _121665)
    A(a, a, d)
    M(c, c, a)
    M(a, d, f)
    M(d, b, x)
    S(b, e)
    sel25519(a, b, r)
    sel25519(c, d, r)
  }
  inv25519(c, c)
  M(a, a, c)
  const q = new Uint8Array(32)
  pack25519(q, a)
  return q
}

function scalarMultBase(n) { return scalarMult(n, _9) }

module.exports = { scalarMult, scalarMultBase }
