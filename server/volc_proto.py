# -*- coding: utf-8 -*-
"""火山(豆包语音)二进制帧的编解码。ASR/TTS 共用。规格见 ../SERVER.md §4。

帧布局:

    [0] version(4b)=1 | header_size(4b)=1 (x4 字节)      -> 0x11
    [1] msg_type(4b)  | flags(4b)
    [2] serialization(4b) | compression(4b)
    [3] reserved
    -- 以下按 flags / msg_type 可选 --
    [int32 sequence]          flags 低 2 位为 0b01 / 0b11 时
      或 [uint32 error_code]  msg_type = ERROR 时(二者互斥)
    [uint32 event]            flags 含 0b0100 时
    [uint32 id_len][id]       有 event 且不是连接级上行事件(1/2)时:
                              session_id(会话级)或 connect_id(50/51/52)
    [uint32 payload_len][payload]

全大端。压缩一律用 NONE(§4.1:服务端跟随客户端的压缩方式)。
"""
import json
import struct
import uuid
from dataclasses import dataclass

import config

# msg_type
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_REQUEST = 0b0010
FULL_SERVER_RESPONSE = 0b1001
AUDIO_ONLY_RESPONSE = 0b1011
ERROR_INFORMATION = 0b1111

# flags
FLAG_NONE = 0b0000
FLAG_POS_SEQ = 0b0001
FLAG_LAST_NO_SEQ = 0b0010      # ASR 负包(最后一包),不带 sequence
FLAG_NEG_SEQ = 0b0011
FLAG_EVENT = 0b0100

# serialization / compression
SER_RAW = 0b0000
SER_JSON = 0b0001
COMP_NONE = 0b0000
COMP_GZIP = 0b0001

# events(TTS 用到的那些)
EV_START_CONNECTION = 1
EV_FINISH_CONNECTION = 2
EV_CONNECTION_STARTED = 50
EV_CONNECTION_FAILED = 51
EV_CONNECTION_FINISHED = 52
EV_SESSION_FINISHED = 152
EV_TTS_SENTENCE_START = 350
EV_TTS_SENTENCE_END = 351
EV_TTS_RESPONSE = 352

# 上行里不带 id 的连接级事件
_NO_ID_EVENTS = (EV_START_CONNECTION, EV_FINISH_CONNECTION)


def encode(msg_type: int, payload: bytes, *, flags: int = FLAG_NONE,
           serialization: int = SER_JSON, sequence: int = None,
           event: int = None, sid: str = None) -> bytes:
    """编一帧。只支持无压缩。"""
    out = bytearray((0x11, (msg_type << 4) | flags, (serialization << 4) | COMP_NONE, 0))
    if flags & 0b0011 in (FLAG_POS_SEQ, FLAG_NEG_SEQ):
        out += struct.pack(">i", sequence)
    if flags & FLAG_EVENT:
        out += struct.pack(">I", event)
        if event not in _NO_ID_EVENTS:
            b = (sid or "").encode()
            out += struct.pack(">I", len(b)) + b
    out += struct.pack(">I", len(payload)) + payload
    return bytes(out)


def encode_json(msg_type: int, obj, **kw) -> bytes:
    return encode(msg_type, json.dumps(obj, ensure_ascii=False).encode(), **kw)


@dataclass
class Frame:
    msg_type: int
    flags: int
    serialization: int
    sequence: int = None
    event: int = None
    sid: str = None
    error_code: int = None
    payload: bytes = b""

    @property
    def is_error(self) -> bool:
        return self.msg_type == ERROR_INFORMATION

    @property
    def is_last(self) -> bool:
        """ASR 的最后一个响应(负包)。"""
        return self.flags & 0b0011 in (FLAG_LAST_NO_SEQ, FLAG_NEG_SEQ)

    def json(self):
        if not self.payload:
            return None
        try:
            return json.loads(self.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    def __repr__(self):
        body = self.json()
        if body is None:
            body = "<%d B>" % len(self.payload)
        return "Frame(type=%s flags=%s ev=%s seq=%s err=%s %s)" % (
            bin(self.msg_type), bin(self.flags), self.event, self.sequence,
            self.error_code, body)


def decode(data: bytes) -> Frame:
    if len(data) < 4:
        raise ValueError("帧太短: %d B" % len(data))
    hsize = (data[0] & 0x0F) * 4
    msg_type, flags = data[1] >> 4, data[1] & 0x0F
    ser, comp = data[2] >> 4, data[2] & 0x0F
    if comp != COMP_NONE:
        # 我们从不开 gzip,服务端跟随客户端。真收到了说明请求头写错了。
        raise ValueError("收到压缩帧(compression=%d),请求里是不是开了 gzip" % comp)

    f = Frame(msg_type, flags, ser)
    p = hsize

    def u32():
        nonlocal p
        v = struct.unpack_from(">I", data, p)[0]
        p += 4
        return v

    # 顺序照官方 demo(protocols.py):先 sequence 或 error_code,再 event/id。
    if msg_type == ERROR_INFORMATION:
        f.error_code = u32()
    elif flags & 0b0011 in (FLAG_POS_SEQ, FLAG_NEG_SEQ):
        f.sequence = struct.unpack_from(">i", data, p)[0]
        p += 4
    if flags & FLAG_EVENT:
        f.event = u32()
        if f.event not in _NO_ID_EVENTS:
            n = u32()
            f.sid = data[p:p + n].decode("utf-8", "replace")
            p += n
    n = u32()
    f.payload = bytes(data[p:p + n])
    if len(f.payload) != n:
        raise ValueError("payload 截断: 声明 %d,实有 %d" % (n, len(f.payload)))
    return f


def auth_headers(resource_id: str) -> dict:
    """火山 WS 握手头。ASR 和 TTS 共用,只有 Resource-Id 不同(SERVER.md §4.5)。

    控制台新旧版两种鉴权,填其一:
      新版 VOLC_API_KEY                   -> X-Api-Key
      旧版 VOLC_APP_ID + VOLC_ACCESS_KEY  -> X-Api-App-Id(TTS)/ X-Api-App-Key(ASR)+ X-Api-Access-Key
    """
    rid = str(uuid.uuid4())
    h = {
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": rid,
        "X-Api-Connect-Id": rid,
    }
    if config.VOLC_API_KEY:
        h["X-Api-Key"] = config.VOLC_API_KEY
    elif config.VOLC_APP_ID and config.VOLC_ACCESS_KEY:
        h["X-Api-App-Id"] = config.VOLC_APP_ID        # TTS 文档用这个名字
        h["X-Api-App-Key"] = config.VOLC_APP_ID       # ASR 文档用这个名字
        h["X-Api-Access-Key"] = config.VOLC_ACCESS_KEY
    else:
        raise ValueError("没配火山密钥:设 VOLC_API_KEY,或 VOLC_APP_ID + VOLC_ACCESS_KEY")
    return h
