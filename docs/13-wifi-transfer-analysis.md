# WiFi 快传链路分析（固件符号 + App 反编译）

> 状态：**静态分析完成，未空口抓包验证**。本文所有结论来自两处证据：
> ① 固件镜像 `fw_0.1.8_img_f6.bin` 的字符串表（见 `FIRMWARE.md` 第 1 节如何获得）；
> ② 官方 App（Flutter，`libapp.so`）的 Dart 符号与资源字符串（见 [docs/12](12-apk-analysis-report.md)）。
> 文末给出把剩余未知补齐（空口抓包）的具体方法。

---

## 1. 一句话架构

```
┌─────────────── 卡片（BES best1306p）───────────────┐
│   MCU 核（CM33，跑 blespp_* BLE 协议栈）           │
│        │  spi_bridge（FIFO，"MCU2WIFI"）           │
│   WiFi 核（rwnx_fw：softAP / STA / wpa_supplicant）│
└──────────────────┬──────────────────────────────┘
                   │  Wi-Fi SoftAP（卡片开热点）
                   ▼
┌─────────────── 手机 App（Flutter）─────────────────┐
│  wifi_iot 插件：连热点 → forceWifiUsage 强制走WiFi │
│  _runWifiDownload / downloadFileWifi：拉录音       │
└────────────────────────────────────────────────────┘
```

卡片内部不是一颗核包办一切：主固件（MCU 核）通过 **SPI bridge + FIFO**（字符串
`spi_bridge_master_* / spi_bridge_slave_send / spi_bridge_wifi_ready`、`MCU2WIFI`、
`the fifo will full, spi send stop, datalen = %d, free_size = %d`）与 WiFi 子系统
（驱动路径 `rwnx_fw/patch/src/wifi_hook.c`、`wifi_patch.c`）交互。BLE 命令在 MCU 核
处理，音频文件由 MCU 核经 SPI 桥推给 WiFi 核对外发送。

## 2. 触发与握手流程（按字符串还原）

### 卡片侧（固件字符串）

| 证据 | 含义 |
|---|---|
| `%s wifi trans clock key!!` | **实体按键组合**可进入 WiFi 传输模式（与 MSD/OTA 模式同一套按键框架）|
| `blespp_file_get_device_wifi_status_handle` | BLE 命令：**读 WiFi 状态** |
| `blespp_file_set_device_special_wifi_status_handle` | BLE 命令：**设置 WiFi 开关/模式** |
| `blespp_file_device_notify_app_wifi_stait:%d` | 卡片**主动经 BLE 把 WiFi 状态通知给 App** |
| `bwifi_softap_start fail` / `wifi_hal_softap_peer_query` / `wifi_hal_softap_disconnect_sta` | 卡片以 **SoftAP（热点）模式**工作，并管理接入的站点（STA）|
| `start wifi quick connect` / `start wifi scan` / `start wifi connect` | 同时具备 STA（连路由器）能力，快传场景用的是 SoftAP |
| `%s close wifi,stop spi send!!` | 关 WiFi 时停止 SPI 桥发送（印证音频经 SPI→WiFi 的通路）|
| `%s recode dont wifi trans!!` | **录音进行中不允许 WiFi 传输**（状态互斥）|
| `connect app close wifi dont need set led!!` | App 断开后关 WiFi 的 LED 逻辑 |

### 手机侧（App 反编译）

| 证据 | 含义 |
|---|---|
| `package:wifi_iot/wifi_iot.dart`（WifiForIoTPlugin）| App 用 **wifi_iot 插件连卡片热点** |
| `forceWifiUsage` / `--she--forceWifiUsage-----` | 连上热点后**强制数据走 WiFi**（否则 Android 会因热点无互联网回落到蜂窝）|
| `getWifiIP` / `getWifiName` / `wifiActive=` | 确认已连上卡片的网络 |
| `com.biji.getNotes/wifi_lock`（MethodChannelWifiLock）| 传输期间持 WiFiLock 防止休眠断流 |
| UI 资源 `ic_wifi_state_open_hotspot / connect_hotspot / connected_hotspot` | 三态 UI：开热点 → 连接中 → 已连接 |
| `WifiQuickTransferSheet` / `WifiTransmissionSheet` | 两个传输入口页（快传 / 普通传输）|
| `startWifiTransfer` / `cancelWifiTransfer` | 传输启停控制 |
| `_runWifiDownload` / `downloadFileWifi` / `_onWifiProgress` | **下载式**拉取录音（手机是客户端，卡片是服务端）|

### 还原出的完整时序

```
手机                        BLE                         卡片
 │ ①请求WiFi快传/按卡片按键组合  ──────────────────────▶  进入 WiFi 传输模式
 │ ◀──────────────── ②BLE 通知 wifi_status（含热点信息）  开 SoftAP
 │ ③wifi_iot 连热点，forceWifiUsage                    
 │ ④（经 WiFi 下载录音 downloadFileWifi，协议未抓包）▶
 │ ◀──────────────── ⑤进度/完成（_onWifiProgress）      
 │ ⑥cancel/结束 ──────────────────────────────────────▶  close wifi, stop spi send
```

要点：**BLE 仍是控制信道**（WiFi 状态查询/设置、热点信息下发都走 `blespp_*` 命令表），
WiFi 只是**数据面**。这解释了为什么 BLE 命令表里留有 `get/set wifi_status` 一族处理器。

## 3. 已确认 / 待抓包

| 问题 | 状态 |
|---|---|
| 卡片热点是 SoftAP 模式吗 | ✅ 是（`bwifi_softap_start`、`softap_peer_query/disconnect_sta`）|
| 热点 SSID/密码如何给 App | 🔶 推测经 BLE 命令下发（`set_device_special_wifi_status`/`notify_app_wifi_stait` 载荷），**需抓 BLE 确认字段格式** |
| 应用层传输协议 | ❓ 未抓包。App 侧只有 `downloadFileWifi`，无本地 URL 字符串 ⇒ 端点可能是运行时拼接（IP 由 `getWifiIP` 网段推断，热网关即卡片）；**很可能是 HTTP GET 或裸 TCP** |
| WiFi 链路是否加密 | 🔶 WiFi 本身必然 WPA2（固件带完整 wpa_supplicant + `wifi factory` 数据校验）；应用层未发现新增密符号，**推测沿用"录音明文"的设计** |
| WiFi 传输后卡片会不会清文件 | ❓ 未知（BLE 路径的清理命令是 `0x0041`，WiFi 路径需实测）|

## 4. 如何补齐（空口抓包清单）

1. **抓 BLE 握手段**：手机开 HCI snoop → App 里触发 WiFi 快传 → 在 btsnoop 里看
   `0x____`（WiFi 状态族命令码）的载荷，热点 SSID/密码/信道应在此明文出现。
2. **抓 WiFi 数据段**：电脑直接连卡片热点（SSID/密码取自上一步），先
   `nmap -sV 卡片网关` 扫端口；开放 80/8080 则直接 `curl` 探路径；否则用
   Wireshark 抓 TCP 流还原应用层帧。
3. 对照 App 侧：用 frida/objection hook `downloadFileWifi` 附近的网络调用，
   直接拿到目标 URL/端口（Flutter 的 Dart AOT 也可用 reFlutter 辅助）。

> 一旦拿到端口与帧格式，`tools/getcard.py` 可加 `--wifi` 路径：BLE 握手拿热点凭证
> → WiFi 高速拉取（BLE 25 KB/s → WiFi 预计 >1 MB/s，提升约 40 倍）。

## 5. 安全观察

- WiFi 核的"出厂区"有 magic/版本/CRC 三重校验（`wifi factory magic/version/crc error`），
  但这是**数据完整性**校验，与传输安全无关。
- 整个 WiFi 快传没有发现任何应用层鉴权符号（无 token/挑战响应），与 BLE 通道
  "零鉴权"一脉相承 —— **连上卡片热点即可访问传输服务**（待实测确认）。
  若属实：同一空间内任何知道热点密码的设备都能拉取录音，这是比 BLE 更值得
  关注的暴露面（BLE 至少要物理接近且主动连接，热点则是被动广播）。
