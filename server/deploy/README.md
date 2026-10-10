# 部署到公网 VPS

规格背景见 `../../SERVER.md` §7。这一页只写操作。

```
设备 ──wss://<域名>:443 (TLS 1.2, 纯 PSK)──> stunnel ──明文──> 127.0.0.1:8765 Python
```

两件事必须同时成立,少一件就连不上:

1. **VPS 上**:Python 跑在 127.0.0.1:8765,stunnel 在 443 用 PSK 终结 TLS
2. **设备上**:`secrets.h` 里的 `PSK_IDENTITY`/`PSK_KEY_HEX` 和 VPS 的 `psk.secrets` 对得上

---

## 0. 先备一份密钥(在开发机上做)

```bash
python -c "import secrets;print(secrets.token_hex(32))"
```

64 位 hex。这一把要同时填进两个地方:

| 填哪里 | 字段 |
|---|---|
| VPS `/etc/stunnel/psk.secrets` | `c3-01:<hex>` |
| 固件 `firmware/ESP32C3_AI_Voice/secrets.h` | `PSK_IDENTITY "c3-01"` / `PSK_KEY_HEX "<hex>"` |

`psk.secrets` 已进 `.gitignore`。`secrets.h` 本来就在。

---

## 1. VPS:装服务本体

```bash
sudo adduser --system --group --home /opt/esp32_server esp32
sudo mkdir -p /opt/esp32_server
# 把 esp32_server/ 的内容传上来(见下面"同步代码")
sudo chown -R esp32:esp32 /opt/esp32_server

sudo -u esp32 python3 -m venv /opt/esp32_server/.venv
sudo -u esp32 /opt/esp32_server/.venv/bin/pip install -r /opt/esp32_server/requirements.txt

sudo cp /opt/esp32_server/deploy/esp32-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now esp32-server
systemctl status esp32-server --no-pager
```

先不急着接 stunnel,本地自测一把:

```bash
sudo -u esp32 /opt/esp32_server/.venv/bin/python /opt/esp32_server/tools/smoke_echo.py
```

这一步通了说明服务器逻辑是好的。不通就别往下做 —— 后面全是网络层,
逻辑锅和网络锅混在一起最难查(这是 AGENT.md §9.2 排查表的第一把刀)。

## 2. VPS:装 stunnel

```bash
sudo apt update && sudo apt install -y stunnel4

sudo cp /opt/esp32_server/deploy/stunnel-esp32.conf    /etc/stunnel/esp32.conf
sudo cp /opt/esp32_server/deploy/stunnel-esp32.service /etc/systemd/system/

# psk.secrets 自己按 §0 写,不要从仓库里拷
sudo install -o stunnel4 -g stunnel4 -m 600 /dev/stdin /etc/stunnel/psk.secrets <<'PSK'
c3-01:在这里填64位hex
PSK

sudo systemctl daemon-reload
sudo systemctl enable --now stunnel-esp32
systemctl status stunnel-esp32 --no-pager
```

这里用的是仓库自带的 unit,**不是** Debian 打包的 `stunnel4` 服务 ——
后者的 `Type` 和 `/etc/default/stunnel4` 里的 `ENABLED` 开关在各版本间不一致,
和配置里的 `foreground = yes` 容易打架。两个都启用的话会抢 443
(Debian 默认 `ENABLED=0`,一般撞不上;真撞上就 `systemctl disable --now stunnel4`)。

`ExecStart` 写的是 `/usr/bin/stunnel4`。非 Debian 系通常只有 `/usr/bin/stunnel`,
那就改 unit 里那一行。

确认 443 在听、8765 **没有**对外听:

```bash
sudo ss -lntp | grep -E ':443|:8765'
```

期望看到 `0.0.0.0:443` 是 stunnel,`127.0.0.1:8765` 是 python。
要是 8765 显示成 `0.0.0.0:8765`,立刻停下来查 `ESP32_SERVER_HOST` —— 那个端口零鉴权。

## 3. VPS:放行 443

**远程开防火墙有把自己锁在外面的风险。先挂一个自动回滚:**

```bash
sudo systemd-run --on-active=300 --unit=ufw-rollback /usr/sbin/ufw --force disable
```

规则写错的话,5 分钟后 ufw 自动关掉,不用开工单找 VNC。验证通过之后再
`sudo systemctl stop ufw-rollback.timer` 取消它。

```bash
# 顺序不能反:先放行,再改默认策略,最后才 enable
sudo ufw allow 22/tcp  comment "SSH"
sudo ufw allow 443/tcp comment "wss (stunnel TLS-PSK -> esp32 voice)"
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw --force enable
```

**验证要开一条全新的 SSH 连接**,不能只看当前这条 —— ufw 的 `before.rules` 里有
`ESTABLISHED,RELATED -j ACCEPT`,已经建立的连接即使规则写错也不会断,
"当前连接还活着"完全证明不了 22 是通的。

```bash
# 三件事都要验:22 能新连、443 能握手、8765 从外网不可达
ssh <vps> 'echo ok'
openssl s_client -connect <域名>:443 -psk_identity <ident> -psk <hex> -tls1_2 \
  -cipher PSK-AES128-GCM-SHA256 </dev/null 2>&1 | grep '^New'
nc -z -w5 <域名> 8765 && echo "!! 8765 暴露了" || echo "8765 不可达,对"
```

RHEL 系换成:

```bash
sudo firewall-cmd --permanent --add-port=443/tcp && sudo firewall-cmd --reload
```

`ufw status` 显示 `inactive` 就说明根本没开防火墙,那这一步可以跳过 ——
很多独立服务器商(ColoCrossing、Hetzner 这类)交付的就是裸机,没有任何过滤。

⚠️ **有些厂商还有第二道墙:控制台里的安全组 / 网络 ACL**,和系统防火墙互相独立。
阿里云、腾讯云、AWS、GCP 都有,要单独放行 443;传统独服商一般没有。
判断办法很简单:做完 §4 之后从**外网**连一次,VPS 上 `ss` 显示在听但外面连不上,
那就是被上游的墙挡了。

## 4. 验证 TLS-PSK 握手(不用烧 ESP32)

在 VPS 上:

```bash
openssl s_client -connect 127.0.0.1:443 \
  -psk_identity c3-01 -psk <64位hex> \
  -tls1_2 -cipher PSK-AES128-GCM-SHA256 </dev/null
```

看到 `Cipher is PSK-AES128-GCM-SHA256` 就对了。
报 `no ciphers available` / `psk identity not found` 就是 `psk.secrets` 没对上。

再从**开发机**上跑一遍同样的命令(把 `127.0.0.1` 换成域名),验证公网路径通。

## 5. 全链路自测(不用烧 ESP32)

`smoke_echo.py` 不会说 PSK(Python 的 `set_psk_client_callback` 要 3.13)。
不用为此升 Python —— 开个 SSH 隧道直接打明文口就行:

```bash
ssh -N -L 8765:127.0.0.1:8765 <user>@<域名>     # 一个终端挂着
python tools/smoke_echo.py                       # 另一个终端
```

这样测的是服务器逻辑;TLS 那一段已经在 §4 单独验过了。

## 6. 设备侧

`firmware/ESP32C3_AI_Voice/secrets.h` 填域名 + 443 + PSK,重新编译烧录。
串口应该依次出现:

```
[WIFI] 已连接  IP=...
[WS] 连接 wss://<域名>:443/ws  (TLS-PSK, ident=c3-01)
[WS] TLS 握手成功 ... 
[WS] 握手成功
```

卡在哪一行就查哪一段,对照 `../../SERVER.md` §7.5 的排查表。

---

## 同步代码

开发机上(Windows / Git Bash。注意 Git Bash **自带 `scp` 但不带 `rsync`**):

```bash
cd "D:/DATA/重要项目/AI_figure"
scp -r esp32_server root@172.245.226.201:/tmp/
ssh root@172.245.226.201 '
  rm -rf /tmp/esp32_server/__pycache__ /tmp/esp32_server/tools/__pycache__
  cp -a /tmp/esp32_server/. /opt/esp32_server/
  chown -R esp32:esp32 /opt/esp32_server
  systemctl restart esp32-server'
```

⚠️ `cp -a /tmp/esp32_server/.` 是**覆盖**不是**同步** —— 删掉的文件不会跟着消失。
真要干净同步就先 `rm -rf /opt/esp32_server/{*.py,tools}` 再拷,但别碰 `.venv`。

装了 `rsync` 的话更省事(`apt install rsync`,两边都要):

```bash
rsync -av --delete --exclude '__pycache__' --exclude '.venv' \
  esp32_server/ root@172.245.226.201:/opt/esp32_server/
```

Stage 8 之后改一行 prompt 就走这条路重启,**不用重烧固件** ——
这正是加服务器那一层的收益之一。
