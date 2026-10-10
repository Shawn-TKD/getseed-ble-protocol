# 得到笔记（Get 笔记）语音卡片 —— APK 与固件逆向分析报告

- 分析日期：2026-10-10
- 分析对象：红米 24094RAD4C（代号 beryl）上的 `com.biji.getnotes`（得到笔记 App）
- 分析目的：定位"Get 卡片"（语音卡片 VoiceCard）的固件与通信协议
- 结论一句话：**固件逆向成功，实际固件包已下载到手**

---

## 一、目标定位

| 项 | 值 |
|---|---|
| App 包名 | `com.biji.getnotes` |
| App 名称 | 得到笔记 / Get 笔记（得到 App 团队出品，罗辑思维·igetget） |
| APK 大小 | 306,108,709 字节（约 292 MB，含双架构原生库） |
| 技术栈 | **Flutter**（`libapp.so` + `libflutter.so`，Dart AOT 编译） |
| APK 导出路径 | `output/getnote-apk-review/getnotes-base.apk` |

**产品定位**：这不是"Plaud 国区"设备，而是得到笔记自营的 **AI 录音卡片（VoiceCard）**，配套 App 内的"语音卡片"功能模块。

---

## 二、核心发现：设备与固件

### 2.1 芯片方案：BES 恒玄 best1306p

固件字符串中明确出现：

```
CHIP=best1306p
CHIP=best2007p
../../platform/drivers/bt/best1306p/bt_1306p_reg_map.h
REV_INFO=9a3463e-dirty:best1306p_ibrt
BTC:1306p t0 work mode patch version:%08x
```

- 主控：**BES 恒玄 best1306p**（BES2700 系列，AI 音频 SoC，带 BLE + Wi-Fi 双模）
- 从核/Wi-Fi 子系统：`best2007p`（`REV_INFO=213ecedcfb-dirty:ohos_best2005`）
- BLE 协议栈：`bes_ble`（`bes_ble_gap_conn_update_param`、`bes_ble_gap_stop_adv_all` 等）
- **客户定制分支**：`<default remote="origin" revision="cust/mivi_ai_recorder"/>` —— `mivi_ai_recorder`（AI 录音器客户版本）

### 2.2 固件包（已下载成功）

| 项 | 值 |
|---|---|
| 下载地址 | `https://overseas.aijiatui.com/image/app/1984064358113656832.bin` |
| 版本号 | **0.0.9** |
| 文件大小 | 2,355,804 字节（2.35 MB） |
| HTTP 状态 | 200，`application/octet-stream` |
| 本地路径 | `output/getnote-apk-review/firmware/getnote-voicecard-fw-0.0.9.bin` |
| 编译日期 | **2025-10-27 / 2025-10-30** |

> 该 URL 硬编码在 Dart 代码里，格式为 `version = 0.0.9  url = https://overseas.aijiatui.com/...`

### 2.3 固件包格式（BES 标准双镜像 OTA 包）

文件头（前 48 字节）：

```
0x00: 0x00000200  Header 长度 = 512 字节
0x04: 0x00000001
0x08: 0x00000002  分区数 = 2
0x0C: 0x00000101
0x10: 0x00000100
0x14: 0x0011BDB4  分区条目1 长度 = 1,162,676 字节
0x18: 0x899EAA82  分区条目1 数据偏移/CRC
0x1C: 0x00000107
0x20: 0x0011BEB4  分区条目2 长度 = 1,162,932 字节
0x24: 0x001233A8  分区条目2 长度 = 1,192,872 字节
0x28: 0x8A1C4E8B  CRC32
0x2C: 0x1A8F6D75  CRC32
0x30: 0xFFFFFFFF ... 尾部填充
```

**双镜像结构**（BES 双核架构典型）：
- 镜像 0 @ `0x200`，约 1.16 MB
- 镜像 1 @ `0x200 + 0x11BDB4`，约 1.19 MB
- 每区尾部带 CRC32 校验

---

## 三、通信协议：自研 BES OTA over BLE

### 3.1 SDK 源码结构（从 Dart 类名还原）

固件 OTA 与音频协议由 **`jiatui_meet`** 包实现（"jiatui" = 加推，为 SDK 供应方）。已还原出完整文件树：

```
package:jiatui_meet/jiatui_meet.dart              主入口
package:jiatui_meet/jiatui_meet.dart
package:jiatui_meet/BlePermission.dart             蓝牙权限
package:jiatui_meet/unit.dart
package:jiatui_meet/opus_decoder_util.dart         Opus 音频解码
package:jiatui_meet/audio_sync_cmd_parser.dart     音频同步命令解析
package:jiatui_meet/cmd/aes_pkcs7_codec.dart       AES-PKCS7 编解码
package:jiatui_meet/cmd/audio_download_cmd_parser.dart
package:jiatui_meet/cmd/ble_command.dart           BLE 命令定义
package:jiatui_meet/cmd/ble_packet.dart            BLE 包结构
package:jiatui_meet/cmd/ble_packet_assembler.dart  包重组
package:jiatui_meet/cmd/ble_packet_sender.dart     包发送
package:jiatui_meet/cmd/packet_assembly.dart
package:jiatui_meet/cmd/tran_protocol_decoder.dart 传输协议解码
package:jiatui_meet/ota/sdk/bes_ota_cmd.dart       ★ BES OTA 命令
package:jiatui_meet/ota/sdk/ota_manager.dart       ★ OTA 管理器
package:jiatui_meet/ota/sdk/data_util.dart
package:jiatui_meet/ota/sdk/list_hex_conversion.dart
package:jiatui_meet/ota/ota_upgrade_screen.dart
package:jiatui_meet/ota/ota_upgrade_sheet.dart
package:jiatui_meet/ota/circle_progress.dart
```

### 3.2 关键类名（Dart 运行时符号）

- `BesOtaCMD` / `besOtaCMD` / `besOtaProgress` —— BES OTA 命令与进度
- `BlePacket` / `BlePacketAssembler` / `BlePacketSender` —— BLE 分包与重组
- `OTAManager` / `_otaManager` —— OTA 流程管理
- `VoiceCardDeviceAdapter` / `AiXiaobuVoiceCardEngineFactoryDelegate` —— 设备适配层

### 3.3 BLE 通信加密

固件侧证据：
```
%s aes_128_decrypt ble_reply_data:
%s token is NULL
AES-128-CMAC
```

**BLE 通信数据使用 AES-128 加密**（`aes_128_decrypt ble_reply_data`）+ AES-128-CMAC 完整性校验。这与 App 侧 `cmd/aes_pkcs7_codec.dart` 对应。

### 3.4 固件侧 OTA 状态机

```
Bes_enter_ota_state / Bes_exit_ota_state        进入/退出 OTA
OTA config pass / OTA config failed             配置校验
OTA can resume. Resuming from the breakpoint at: 0x%x    断点续传
OTA can't resume because the randomCode is inconsistent  randomCode 一致性校验
[OTA_COMMAND_RESUME_VERIFY] / [OTA_RSP_RESUME_VERIFY]   续传校验命令
__ota_boot_info_start=0x28018000                 OTA boot info 地址
OTA_BOOT_INFO_SECTION_SIZE=0x1000
```

> **重要安全特性**：BES OTA 支持**断点续传**，但用 `randomCode` 校验会话一致性 —— 中断重连后 randomCode 不一致就拒绝续传，必须重传。

---

## 四、设备功能（从固件字符串还原）

| 模块 | 证据 |
|---|---|
| 存储 | **eMMC**（`emmc_full`、`format_emmc`、`emmc cache`、`emmc_free`）|
| USB | USB Mass Storage（`MBED.ORGMBED USB DISK 1.0`、`/usb/recode`、`/usb/ota.bin`）|
| 录音 | `emmc will full,stop recode`，录音文件存 `/usb/recode/`，索引 `fileInfo.txt` |
| Wi-Fi | SoftAP + Station 双模（`####wifi ap have station connect`、`wifi device got ip`、`ssid:%s, passwd:%s, hidden:%d`）|
| BLE | `bes_ble` 栈 + `ble_spp_uart_event`（SPP 透传）+ 自定义 OTA 服务 |
| 电池 | `batttery_volt %d charge:%d`、`ble_spp_uart_event %d battery_level:%d` |
| 音频 | Opus 解码（`opus_decoder_util.dart`）、`change speech mic channel` |
| 复位 | `factory_reset:%d msd_mode:%d need_scan:%d`、`factory reset format emmc` |
| LED | `emmc full led dont need set` |

---

## 五、云端接口（App 侧 API）

### 5.1 设备管理接口

```
GET/POST /voicenotes/mind/app/v1/devices                     设备列表
POST     /voicenotes/mind/app/v1/devices/bind                绑定
POST     /voicenotes/mind/app/v1/devices/bind/pre-check      绑定预检查
POST     /voicenotes/mind/app/v1/devices/unbind              解绑
GET      /voicenotes/mind/app/v1/devices/info                设备信息
★        /voicenotes/mind/app/v1/devices/firmware_check      固件版本检查
POST     /voicenotes/mind/app/v1/devices/check_device_equity_claimable
POST     /voicenotes/mind/app/v1/devices/claim_device_equity
POST     /shop/mind/app/v1/hardware/recorder/get_by_sn       按 SN 查硬件
```

### 5.2 域名体系

```
生产/主域:  https://biji.com, https://doc.biji.com
得到系:     https://entree.igetget.com, https://entree.biji.com
设备/云:    https://dmind.didatrip.com, https://dmind.luojilab.com
固件 CDN:   https://overseas.aijiatui.com      ← 固件托管
开发环境:   http://biji.dev.didatrip.com, http://dmind.dev.didatrip.com
```

---

## 六、逆向手法总结（可复现）

1. **ADB 定位**：`adb shell pm list packages | grep -i note` → 命中 `com.biji.getnotes`
2. **APK 拉取**：`adb shell pm path com.biji.getnotes` → `adb pull`
3. **识别框架**：解包见 `libflutter.so`/`libapp.so` → Flutter 应用
4. **字符串提取**：自写 Python 脚本从 `libapp.so` 抓 ASCII 串（6.7 万条），绕过无 `strings` 命令的限制
5. **关键词定位**：搜 `firmware` / `ota` / `bes` → 命中 `BesOtaCMD`、`firmware_check`
6. **挖出硬编码 URL**：`version = 0.0.9 url = https://overseas.aijiatui.com/image/app/1984064358113656832.bin`
7. **直接下载固件**：`curl -sL` → HTTP 200，2.35 MB
8. **固件解析**：识别 BES 双镜像 OTA 包格式（512B Header + 双分区 + CRC32）
9. **芯片指纹**：固件字符串 → `CHIP=best1306p`（BES 恒玄）

---

## 七、关键文件清单

```
output/getnote-apk-review/
├── getnotes-base.apk                      原始 APK (292 MB)
├── ANALYSIS-REPORT.md                     本报告
├── libapp_strings.txt                     libapp.so 提取的字符串 (67,711 条)
├── fw_strings.txt                         固件提取的字符串 (16,155 条)
├── firmware/
│   └── getnote-voicecard-fw-0.0.9.bin     ★ 语音卡片固件 (2.35 MB)
└── extracted/                             APK 完整解包
    ├── lib/arm64-v8a/libapp.so            Flutter Dart AOT 代码
    └── assets/flutter_assets/assets/
        ├── device.zip                     内嵌 H5 设备页 (Vue 打包)
        └── icons/ic_voice_card*.png       语音卡片 UI 资源
```

---

## 八、后续可继续深挖的方向

1. **反编译 Dart**：用 `blutter` 对 `libapp.so` 做 Dart 反编译，还原 `bes_ota_cmd.dart` 的命令枚举值与 randomCode 算法
2. **固件反汇编**：BES1306p 是 ARM Cortex-M（KM4/CM33），提取镜像后用 Ghidra/IDA 分析 OTA 服务 BLE UUID 与 AES 密钥
3. **提取 BLE 服务 UUID**：Dart 常量池中的 `00009000-0000-1000-8000-57616C6B697A`（`Walkiz`？ASCII `Walkiz` = 0x57616C6B697A）等 UUID 高度可疑，需结合 blutter 确认
4. **抓包验证**：用 nRF Connect 或 BLE 抓包，对照固件的 `aes_128_decrypt ble_reply_data` 还原明文协议
5. **SSH 源站**：固件中泄露源码仓库 `<remote name="wifi" ... review="ssh://172.16.40.40:29418/wifi"/>`（内网 Gerrit，不可达，但可用于确认厂商）

---

## 附：一处值得注意的线索

固件中 `00009000-0000-1000-8000-57616C6B697A` 与 `00009100-0000-1000-8000-57616C6B697A` 的 UUID 后缀 `57616C6B697A` 是 ASCII 字符串 **"Walkiz"**（0x57='W', 0x61='a', 0x6C='l', 0x6B='k', 0x69='i', 0x7A='z'）。这两个 UUID 极可能就是语音卡片的 **BLE 主服务 / OTA 服务**，建议优先验证。

`00002902-0000-1000-8000-00805f9b34fb` 是标准的 **CCCD**（客户端特征配置描述符），用于开启 notify。
