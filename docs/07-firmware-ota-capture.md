# 得到录音卡 (VoiceCard) 固件 0.1.8 抓取与逆向分析报告

> 抓取时间: 2026-10-10 12:56:10 ~ 13:04:30
> 抓取方式: BLE OTA 传输过程 logcat 明文记录 + 软件重建
> 设备: Get-A78A67 (MAC 5C:8E:8B:A7:8A:67), 手机: Redmi Note 14 5G
> App: com.biji.getnotes v3.1.6 (versionCode 20260915)
> 升级前固件: 0.1.4 → 升级后固件: **0.1.8**

---

## 一、成功验证:固件抓取成功

本次通过监听 App 的 Flutter 日志,完整记录了 BLE OTA 升级的全过程。**每一条固件数据包都以明文 hex 打印在日志中**,因此无需任何解密即可完整重建固件。

| 指标 | 数值 |
|------|------|
| OTA 数据包总数 | 5,136 |
| 主固件包 (85 f6) | 4,821 包 |
| 子固件包 (85 40) | 150 包 |
| 控制/握手包 | 165 包 |
| **主固件重建大小** | **1,600,572 字节 (1.53 MB)** |
| **子固件重建大小** | **48,000 字节 (47 KB)** |
| 原始日志流 | 1,675,698 字节 |

产物文件:
- `fw_0.1.8_img_f6.bin` — 主固件 (BLE/BT 主控)
- `fw_0.1.8_img_40.bin` — 子固件
- `ota_raw_stream.bin` — 含包头的原始流
- `ota_payload.bin` — 纯 payload
- `fw_0.1.8_img_f6.bin.strings.txt` — 19,807 条字符串
- `fw_0.1.8_img_40.bin.strings.txt` — 556 条字符串

---

## 二、BLE OTA 协议完整逆向

### 2.1 数据包格式

```
[85] [f6] [01] [00] [00] [payload ...]
 │    │    └────┬────┘   └─── 固件数据 (337 或 325 字节)
 │    │         └── 固定标志 01 00 00
 │    └── 子命令: f6 = 主固件分区, 40 = 子固件分区
 └── 命令码: 0x85 = OTA 数据包
```

### 2.2 控制命令表(从日志实测)

| 命令 | 方向 | 名称 | 载荷 |
|------|------|------|------|
| `7b 01` | App→卡 | OTA 开始 | — |
| `99 04` | App→卡 | 参数协商 | `00 00 00 00 01` |
| `97 01` | App→卡 | 查询 | `00 03` |
| `8e 04` | 卡→App | 芯片确认 | **`BEST`** |
| `8c 2c` | 卡→App | 固件信息头 | `BEST` + 元数据 (49B) |
| `80 0c` | App→卡 | 分区配置 | `BEST 58 67 25 00 50 65 bc a9` |
| `86 5c` | App→卡 | OTA 配置 | `58 ...` (97B) |
| **`85 f6`** | App→卡 | **主固件数据块** | 337B |
| **`85 40`** | App→卡 | **子固件数据块** | 325B |
| `82 08` | 卡→App | **CRC 校验回执** | `BEST` + CRC32 (13B) ×150 |
| `92 04` | App→卡 | OTA 结束 | `BEST` |

### 2.3 固件内 OTA 状态机(字符串符号提取)

```
[OTA_COMMAND_CONFIG_OTA]        [OTA_RSP_CONFIG]
[OTA_COMMAND_GET_VERSION]       [OTA_RSP_GET_OTA_VERSION]
[OTA_COMMAND_GET_OTA_RESULT]    [OTA_RSP_RESULT]
[OTA_COMMAND_RESUME_VERIFY]     [OTA_RSP_RESUME_VERIFY]
[OTA_DATA_PACKET]               [OTA_RSP_SEGMENT_VERIFY]
[OTA_DATA_ACK]                  [OTA_RSP_START]
[OTA_FLASH_CONTENT_DATA]        [OTA_RSP_START_ROLE_SWITCH]
[OTA_READ_FLASH_CONTENT]
Bes_enter_ota_state / app_otaMode_enter / app_ota_key_handler
app_ota_push_rx_data / app_ota_buf_lock / app_ota_event_mailbox
app_ota_get_conidx / ota_ble_conn_hdl
OTA_BOOT_INFO_SECTION_SIZE=0x1000
```

---

## 三、固件身份确认

### 3.1 芯片平台
| 证据 | 内容 |
|------|------|
| 字符串 | **`BTC 1306p: metal id=%d`** |
| 字符串 | `BTC:1306p t1 work mode patch version` |
| 字符串 | `rx_dc_cal_1306p` |
| 字符串 | `bt_drv_update_btc_sw_version` |
| 结论 | **芯片 = BES 恒玄 best1306p** (Cortex-M33 蓝牙主控) |

### 3.2 固件头结构 (0x00)
```
00 02              → 版本字段 (0x0200)
00 00 01 00        → 分区 ID
00 00 01 01        → 标志
00 00 f4 ac 12 00  → 长度字段 0x12ACF4
a1 9a 3c 81        → CRC32 #1
f5 cc 26 a7        → CRC32 #2
48 ab 14 2c        → FLASH 加载地址 0x2C14AB48
10 48 00 47        → ARM Thumb: ldr r0,[pc,#64]; bx r0  ← 启动跳转
```

### 3.3 Flash 内存布局(固件内符号)
```
FLASH_BASE            = 0x2C000000
FLASH_NC_BASE         = 0x28000000
__ota_boot_info_start = 0x28018000
__factory_start       = 0x283FF000
OTA_BOOT_INFO_SECTION_SIZE = 0x1000
```

### 3.4 源码仓库信息(固件内 build 元数据泄露)
```
remote "wifi"   fetch="../../wifi"  review="ssh://172.16.40.40:29418/wifi"
project bsp-src         upstream="cust/mivi_ai_recorder"
project bthost-src      upstream="cust/mivi_ai_recorder"
project multimedia-src  upstream="cust/mivi_ai_recorder"
project services/aiot   upstream="cust/mivi_ai_recorder"
project libc_adapter    upstream="cust/mivi_ai_recorder"
```
→ 客户代号 **mivi**,分支 `cust/mivi_ai_recorder`(= mivi AI 录音器定制分支)
→ 内部 Gerrit 服务器 `172.16.40.40:29418`

构建日期: `Jun 19 2025` / `May 15 2026`

---

## 四、0.1.8 版本更新内容(官方弹窗 + 固件证据)

官方弹窗宣称:
1. **蓝牙免配对** — 取消系统蓝牙配对弹窗,打开 App 即直连,多设备切换无需解绑
2. **快传优化** — WiFi 快传稳定性提升,传输时手机可用 4G/5G

固件侧佐证字符串:
- `%s ota mode clock key!!` / `app_otaMode_enter` — OTA 模式
- `ble_send:%d wifi_status:%d ota:%d` — BLE/WiFi 双通道状态
- `%s poweroff_count %d con:%d record:%d service_con:%d` — 连接/录音状态机
- Opus + Ogg 音频编码链路 (`enc,enc,buf1,keys`, `omax=`, `fmt-pcm`)

---

## 五、安全发现(对二次开发的意义)

1. **BLE OTA 全程无加密** — 固件数据以明文 BLE 传输,仅靠 `82 08` CRC 校验,无签名校验或加密
2. **OTA 协议为 BES 标准 OTA** — 可直接参照 BES SDK 文档复现
3. **芯片确认靠 "BEST" magic** — `8e 04` 回 `BEST` 即通过,无设备证书
4. **无账号绑定校验** — 与之前 App 侧分析一致,可脱离官方 App 独立刷写
5. 固件内含 **`OTA_RSP_START_ROLE_SWITCH`** —— 支持双镜像 A/B 分区角色切换

---

## 六、待深入

- [ ] 定位并反汇编 `common_set_current_software_version`,提取完整版本号
- [ ] 对比 0.0.9 与 0.1.8 的 diff,确认具体改动
- [ ] 用 BES SDK 工具链解析 `__ota_boot_info` 区
- [ ] 提取 Opus 编码参数,实现自制 App 音频解码

---

*报告生成: 2026-10-10*
