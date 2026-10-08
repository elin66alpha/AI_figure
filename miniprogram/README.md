# AI 玩偶配网小程序

用微信小程序通过 BLE 把家里 WiFi 的名称和密码发给 ESP32-C3 玩偶。协议就是乐鑫自带的
protocomm / network_provisioning(固件用 Arduino 核心的 `WiFiProv`),**Security 1、没有 PoP**:
X25519 密钥交换 + AES-256-CTR,WiFi 密码在空中是加密的。

纯 JavaScript,没有 npm、没有构建步骤、没有 UI 框架。加密库是本目录里自带的两个小文件。

## 用法(用户视角)

1. 玩偶进配网模式:按住按键再上电、保持 3 秒;从没配过网的玩偶开机自己进。
2. 打开小程序,WiFi 名称会自动填成手机当前连的那个(拿不到就手填),输入密码。
3. 列表里点 `AIFIG_xxxxxx`,等 10 秒左右。
4. 成功:显示玩偶 IP,玩偶自己重启并播"已连接"提示音。
   失败:提示「密码错误」或「找不到这个 WiFi(是不是 5G / 名字填错)」,改完直接点「重试」,
   不用重新连蓝牙。

## 开发者:打开和真机调试

1. 没有 AppID 就先申请**测试号**:<https://developers.weixin.qq.com/sandbox>,微信扫码即得一个测试 AppID。
2. 微信开发者工具 → 导入项目 → 目录选本目录 `miniprogram/`,AppID 填测试号
   (`project.config.json` 里是占位的 `touristappid`,导入时改掉即可)。
3. **BLE 只能真机调试**:模拟器没有蓝牙。工具栏点「真机调试」,手机扫码。
   - 安卓:手机要开蓝牙 + 系统「定位」开关,并允许微信使用位置信息(安卓扫 BLE 的系统要求)。
   - iOS:第一次会弹蓝牙授权。
4. 基础库:需要 `wx.getRandomValues`(基础库 2.15.0 起);`setBLEMTU`、`getSystemSetting` 等是更早/可选的。
   `project.config.json` 里 `libVersion` 设的是 3.0.0,只影响开发者工具调试用的基础库。

## 文件

```
app.js / app.json / app.wxss / sitemap.json / project.config.json   小程序壳
pages/index/          唯一的页面:填 WiFi → 扫描点选 → 进度 → 结果
utils/ble.js          微信 BLE API 封装:扫描、连接、setBLEMTU、按端点"写一次再读一次"、关闭、错误翻译
utils/prov.js         协议本体(与传输无关):proto-ver、Sec1 握手、Set/Apply/GetStatus、ctrl reset、轮询
utils/pb.js           最小 protobuf 编解码 + UTF-8
lib/x25519.js         X25519,取自 TweetNaCl-js(public domain)
lib/aes_ctr.js        AES-256 加密 + 连续 CTR 流,按 FIPS-197 直写
test/                 Node 测试 + 独立实现的模拟设备(node:crypto)
```

## 协议要点

对照的源码:ESP-IDF v5.5 `components/protocomm/src/security/security1.c`、`protocomm/proto/*.proto`、
`protocomm/src/transports/protocomm_nimble.c`;network_provisioning 1.0.2 的
`proto/network_{config,ctrl,constants}.proto`、`src/network_config.c`、`src/network_ctrl.c`、`src/manager.c`;
乐鑫 Python 客户端 `esp_prov`(`security/security1.py`、`transport/transport_ble.py`)。

**BLE**

- 服务 UUID `10624c9a-f2aa-4ca8-8594-9cd3cc78db3f`,在广播包里;名字 `AIFIG_` + MAC 后 3 字节,在扫描响应里。
- 每个端点一个特征值,UUID = 服务 UUID 第一段第 5~8 位换成端点 id:
  `prov-ctrl` FF4F、`prov-scan` FF50、`prov-session` FF51、`prov-config` FF52、`proto-ver` FF53。
  微信给的 UUID 是大写,一律忽略大小写比较。
- 一次请求 = **一次 Write Request 写整条消息**,再 **Read 同一特征值** 拿响应。没有 notify,没有应用层分片。
  空写会被设备忽略、读回旧数据,所以绝不发 0 字节(这就是 GetStatus 为什么要带一个空的子消息 `52 00`)。
- 加密会话 = 这条 BLE 连接。断开即作废,重连要重新握手。

**Security 1(无 PoP)**

1. 客户端 32 字节随机数当 X25519 私钥,算公钥,`prov-session` 发 Cmd0(`10 01 5a 25 a2 01 22 0a 20 <公钥>`)。
2. Resp0 带设备公钥和 16 字节 `device_random`。
3. AES 密钥 = X25519 共享密钥**原样**(有 PoP 时才会异或 SHA256(PoP),我们没有);
   AES-256-CTR,初始计数器 = `device_random`,128 bit 大端整体 +1。
4. **整个会话只有一条 CTR 密钥流**,两个方向、所有端点、所有消息共用,字节偏移跨消息延续(不按块对齐):
   密钥流[0,32) 加密设备公钥作为 Cmd1 的 `client_verify_data`;[32,64) 解开 Resp1 里的设备证明,应等于我方公钥;
   之后每个请求的加密、每个响应的解密,都严格按发生顺序继续消耗这条流。
   所以请求必须严格串行(`prov.js` 里用一条 Promise 链保证),任何传输层出错都意味着两端错位 → 断开重来。
5. 握手之后,`prov-config` / `prov-ctrl` / `prov-scan` 的数据整段加解密,没有 MAC、没有额外封装。

**配网**

- Set:`NetworkConfigPayload{msg=2, cmd_set_wifi_config(12){ssid, passphrase}}`,字段 12 必须在场
  (设备 C 代码直接解引用)。SSID ≤ 32 字节、密码 ≤ 63 字节。
- Apply:`{msg=4, cmd_apply_wifi_config(14){}}`。设备 1 秒后才真正开始连。
- GetStatus:每秒查一次,最多 30 秒。`wifi_sta_state` 为 Connected(0) 时在线上是**缺省**的,
  IP 在 `wifi_connected.ip4_addr`;ConnectionFailed(3) 时 `wifi_fail_reason` 0=密码错、1=找不到 AP。
  设备在回完"已连接"之后自己停止配网、存凭据、重启。
- **失败后重试**:设备进入 FAIL 状态后会拒绝再次 Apply(回 InternalError),
  要先在 `prov-ctrl` 发 `NetworkCtrlPayload{msg=CmdCtrlWifiReset(1), cmd_ctrl_wifi_reset(11){}}`,
  再 Set + Apply。同一连接、同一加密会话里完成。
- 一直"连接中"到超时:说明设备在按非密码类原因不停重连,此时 reset 会被拒,只能让玩偶重新上电。

## 测试

需要 Node(装的是 v24),无依赖。在仓库根目录:

```
node --test "miniprogram/test/*.test.js"
```

或单个跑:`node miniprogram/test/prov.test.js`。

- `crypto.test.js`:X25519 对 RFC 7748 §5.2/§6.1 向量并和 node:crypto 随机互验;
  AES-256 对 FIPS-197 C.3;AES-256-CTR 对 NIST SP 800-38A F.5.5;任意切块 = 一次处理(含 128 bit 进位)。
- `pb.test.js`:Cmd0/Cmd1/SetConfig/GetStatus/Apply/CtrlReset 的编码逐字节对照。
- `prov.test.js`:`prov.js` 对 `mock_device.js` 跑端到端 —— 握手、Set、Apply、连接中→已连接、
  密码错→reset→重试、找不到 AP、超时、设备证明被篡改、传输出错后会话作废、并发调用被串行化。
  模拟设备是照 C 源码另写的(自己的 protobuf、node:crypto 的一条 `aes-256-ctr` 流),不复用小程序代码。

## 还没在真机上验证的点

- **写长度**:SetConfig 最长约 105 字节。安卓上 `setBLEMTU(256)`;就算失败,安卓对带响应的写
  超过 MTU 时一般会自动走 Prepare/Execute 长写。iOS 自己协商 MTU(通常 ≥185)。
  微信文档对 iOS 单次写入过长有"可能没有回调"的警告 —— 要在 iPhone 上用长 SSID + 长密码实测。
- `writeType: 'write'` 参数是较新基础库才有的(具体起始版本没查实);老版本会忽略它,按平台默认方式写。
- 部分安卓机 `createBLEConnection` 之后立刻 `getBLEDeviceServices` 会失败,如遇到可在中间加几百毫秒延时。
- 5 GHz 提示依赖 `getConnectedWifi` 返回的 `frequency`,只有安卓给。
- 成功后设备会断开 BLE 并重启,小程序这边直接关连接,不会把这次断开当成错误。
