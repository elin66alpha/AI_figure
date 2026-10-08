// 最小 protobuf 编解码 —— 配网只用到 varint(0) 和 length-delimited(2)两种线型。
//
// 编码:消息写成 [[字段号, 值], ...]
//   值是 number     -> varint;等于 0 时不写(proto3 默认值不上线)
//   值是 Uint8Array -> bytes,原样写(空也写,无害)
//   值是数组        -> 嵌套消息,**总是写**,哪怕是空消息 —— oneof 成员靠它"在场"
// 解码:返回 { 字段号: 值 },varint 为 number,length-delimited 为 Uint8Array
//   (嵌套消息自己再 decode 一次)。缺的字段就是 undefined,调用方按 proto3 当 0。

function pushVarint(out, n) {
  while (n > 0x7f) {
    out.push((n & 0x7f) | 0x80)
    n = Math.floor(n / 128)
  }
  out.push(n)
}

function encodeTo(out, fields) {
  for (const [no, v] of fields) {
    if (typeof v === 'number') {
      if (v === 0) continue
      pushVarint(out, no * 8)
      pushVarint(out, v)
    } else {
      const body = v instanceof Uint8Array ? v : encode(v)
      pushVarint(out, no * 8 + 2)
      pushVarint(out, body.length)
      for (let i = 0; i < body.length; i++) out.push(body[i])
    }
  }
  return out
}

function encode(fields) { return Uint8Array.from(encodeTo([], fields)) }

function decode(buf) {
  const msg = {}
  let i = 0
  const varint = () => {
    let n = 0, mul = 1, b
    do {
      if (i >= buf.length) throw new Error('protobuf 截断')
      b = buf[i++]
      n += (b & 0x7f) * mul
      mul *= 128
    } while (b & 0x80)
    return n
  }
  while (i < buf.length) {
    const tag = varint()
    const no = Math.floor(tag / 8), type = tag & 7
    if (type === 0) msg[no] = varint()
    else if (type === 2) {
      const len = varint()
      if (i + len > buf.length) throw new Error('protobuf 截断')
      msg[no] = buf.subarray(i, i + len)
      i += len
    } else if (type === 1) i += 8      // 用不到的定长类型,跳过
    else if (type === 5) i += 4
    else throw new Error('protobuf 线型不支持: ' + type)
  }
  return msg
}

// UTF-8 编码(SSID 可能有中文;小程序里没有 TextEncoder)
function utf8(str) {
  const out = []
  for (const ch of str) {
    const c = ch.codePointAt(0)
    if (c < 0x80) out.push(c)
    else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63))
    else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63))
    else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63))
  }
  return Uint8Array.from(out)
}

// 设备回来的字符串(proto-ver 的 JSON、IP)都是 ASCII,不用完整 UTF-8 解码
function ascii(bytes) {
  let s = ''
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i])
  return s
}

module.exports = { encode, decode, utf8, ascii }
