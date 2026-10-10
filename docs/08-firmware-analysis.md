# 得到笔记「语音卡片」固件逆向分析报告

- 分析日期：2026-10-10
- 目标固件：`getnote-voicecard-fw-0.0.9.bin`（2,355,804 字节）
- 来源：`https://overseas.aijiatui.com/image/app/1984064358113656832.bin`（App 内硬编码）
- 目的：反编译固件，查明其内容与用途

---

## 一、一句话结论

这是一块 **BES 恒玄 best1306p 双核 AI 录音卡片（AI Recorder）** 的完整固件包，内部包含**两个镜像**：一个是 **BLE 主控/应用固件**，另一个是 **Wi-Fi 子系统固件**。设备本质是一款"**耳机形态的语音记录器**"——通过麦克风录音、Opus 编码存 Ogg、经 BLE 或 Wi-Fi 同步到得到笔记 App。

**项目代号（固件源码泄露）**：`../../multimedia/projects/earphone_recorder/m33_rc06_smf.pb.cpp`
—— 项目名直译为 **`earphone_recorder`（耳机录音器）**，SoC 为 `m33`（Cortex-M33），`rc06` 为版本。

---

## 二、固件包结构

### 2.1 外层包格式

```
偏移        内容
0x000       0x00000200   Header 长度 = 512
0x004       0x00000001
0x008       0x00000002   镜像数量 = 2
0x00C       0x00000101
0x010       0x00000100
0x014       0x0011BDB4   镜像0 长度 = 1,162,676 字节
0x018       0x899EAA82   镜像0 校验/魔数
0x01C       0x00000107
0x020       0x0011BEB4
0x024       0x001233A8   镜像1 长度 = 1,192,872 字节
0x028       0x8A1C4E8B   镜像1 校验
0x02C       0x1A8F6D75
0x030-0x0FF  全 0xFF 填充
0x100       00 00 05 00 | 00 00 00 00 | 08 BC 13 2C（内部头/魔数）
0x200       镜像0 数据起点（ARM Thumb-2 代码）
```

### 2.2 两个镜像

| 项 | 镜像 0 | 镜像 1 |
|---|---|---|
| 本地文件 | `firmware/split/img0.bin` | `firmware/split/img1.bin` |
| 大小 | 1,162,676 B（1.11 MB）| 1,192,616 B（1.14 MB）|
| 架构 | ARM Thumb-2（16/32-bit）| ARM Thumb-2 |
| 芯片标识 | `CHIP=best1306p` | `CHIP=best2007p` |
| 版本串 | `REV_INFO=9a3463e-dirty:best1306p_ibrt` | `REV_INFO=213ecedcfb-dirty:ohos_best2005` |
| 编译日期 | **2025-10-30 23:12:34** | **2025-10-27 17:16:39** |
| 字符串数 | 5,496 | 7,539 |
| **角色** | **BLE 主控 + 应用固件** | **Wi-Fi 子系统固件** |
| 判据 | 191 条 ble、118 条 ota、119 条 led | 356 条 rtw/rwnx/realtek |

> 说明：这是 BES 的**双核架构**——best1306p 内置 KM4 应用核 + 一个独立的 Wi-Fi 协处理器（best2007p）。Wi-Fi 固件单独打包，由应用核通过 RWNX 驱动加载。

---

## 三、镜像 0 详解（BLE 主控 / 应用固件）

### 3.1 内存与 Flash 布局（关键泄露）

```
FLASH_BASE        = 0x2C000000      缓存映射基址（XIP）
FLASH_NC_BASE     = 0x28000000      非缓存映射基址
__ota_boot_info_start = 0x28018000  OTA 引导信息区
__userdata_start      = 0x283FC000  用户数据区
__aud_start           = 0x283FE000  音频资源区
__factory_start       = 0x283FF000  工厂数据区
寄存器 0x40080000                     外设寄存器（读/写验证）
```

### 3.2 应用层模块（从 `app_*` 函数还原）

**音频管理**
```
app_audio_manager_handle_process    音频管理器
app_audio_manager_sendrequest       音频请求
app_audio_open / app_audio_thread   音频线程
app_audio_pcmbuff_mutex / app_audio_queue_mutex
```

**电池/充电**
```
app_battery_charger_handler         充电处理
app_battery_charger_slope_proc      充电曲线
app_battery_handle_process_charging 充电态
app_battery_pluginout_debounce      拔出防抖
```

**BLE AI 应用（核心业务）**
```
app_ble_ai_app_user_init            AI 应用初始化
app_ble_ai_app_adv_activity_prepare 广播准备
app_ble_ai_app_data_sent_done       数据发送完成
app_ble_ai_app_file_receive_data_done 文件接收完成
app_ble_gatt_server_callback        GATT 服务端回调
app_ble_gatt_client_callback        GATT 客户端回调
app_ble_set_battery_level_handle    电量上报
app_ble_update_conn_param_mode      连接参数调整
```

**按键/蓝牙**
```
app_bt_key / app_bt_key_shutdown         按键与关机
app_bt_key_enter_testmode / _nosignal_mode
app_bluetooth_application_init
```

### 3.3 录音功能（业务核心）

```
%s change_recode:%d recode_mode:%d recode:%d
%s recode:%d change_mode:%d ble_send_start:%d wifi_send_start:%d
%s emmc will full,stop recode !!          录音中存储将满则停止
%s recode timeout stop recode !!          录音超时自动停
%s recodeBuffer full dont write!!         录音缓冲满
%s sleep dont recode!! / %s recode dont need sleep!!
%s,fflush recodeBuffer fail
```

**音频编码链（第三方库）**
```
../../multimedia/smf/plugin/opus/AudioEncoderOpus.cpp    Opus 编码器
../../multimedia/smf/plugin/ogg/AudioMuxerOgg.cpp        Ogg 封装器
../../multimedia/projects/earphone_recorder/m33_rc06_smf.pb.cpp
```

**音频格式标记**：`,RIFFWAVEg722pcm`、`,opuspcm`、`only support 16bit sample`
**音频参数**：`sample_rate`、`frame_size`、`_channels`、`codec_tune_resample_rate`
**MIC 通道切换**：`change normol mic channel` / `change speech mic channel`（普通/语音双通道切换）

### 3.4 存储（eMMC）

```
emmc_full / emmc will full / format_emmc / emmc cache / emmc_free
录音文件路径: /usb/recode
文件索引:     /usb/recode/fileInfo.txt, fileInfo_1.txt
```

### 3.5 OTA 升级

```
Bes_enter_ota_state / Bes_exit_ota_state         OTA 状态机
OTA config pass / failed                        镜像校验
OTA can resume. Resuming from breakpoint at 0x%x 断点续传
OTA can't resume because randomCode inconsistent randomCode 一致性保护
[OTA_COMMAND_RESUME_VERIFY] / [OTA_RSP_RESUME_VERIFY]
OTA_BOOT_INFO_SECTION_SIZE=0x1000
```

### 3.6 LED 与电源

```
recover_led / full_led / lowbat_led             恢复/满存/低电 LED
poweroff_count %d con:%d record:%d service_con:%d
```

---

## 四、镜像 1 详解（Wi-Fi 子系统固件）

### 4.1 协议栈

```
RWNX + LwIP driver                RWNX 驱动 + LwIP 轻量 TCP/IP
RWNX driver init succeed
RWNX-CTRL: Change MAC config failed
RWNX-CTRL: Coex cmd (%d) failed   BLE/WiFi 共存调度 (coex)
```

### 4.2 源码路径泄露（作者：xiaodongjin）

```
/home/xiaodongjin/fw/fw2/rwnx_fw/patch/src/wifi_hook.c
/home/xiaodongjin/fw/fw2/rwnx_fw/patch/src/wifi_patch2.c
/home/xiaodongjin/fw/fw2/rwnx_fw/patch/src/coex/patch_coex_chan.c
/home/xiaodongjin/fw/fw2/rwnx_fw/patch/src/coex/patch_coex_sched.c
```

### 4.3 Wi-Fi 功能函数

```
rwnx_connect / rwnx_add_key / rwnx_add_station
rwnx_abort_scan / rwnx_cancel_remain_on_channel
rwnx_change_beacon / rwnx_config_mac_rx_da
rwnx_dbac_cali / rwnx_dbac_calculate_chan   射频校准
```

### 4.4 配网能力

```
####wifi ap have station connect      SoftAP 模式接入了客户端
####wifi ap have station disconnect
####wifi connect connected            Station 模式连上路由器
####wifi device got ip                DHCP 拿到 IP
%s ssid:%s, passwd:%s, hidden:%d     配网参数
```

**结论**：卡片支持 **SoftAP + Station 双模配网**，可由 App 下发 Wi-Fi SSID/密码后直连路由器，实现**录音文件高速上传**（免手机中转）。

---

## 五、这是一块什么设备？

综合所有证据：

> **BES 恒玄 best1306p 方案的 AI 录音卡片（语音记录器）**，产品形态类似"卡片式/挂饰式录音笔"。

| 维度 | 规格 |
|---|---|
| 主控 | BES best1306p（Cortex-M33 应用核 + best2007p Wi-Fi 协处理器）|
| 无线 | **BLE + Wi-Fi 双模**（BLE 用于连接/控制/小文件，Wi-Fi 用于大批量录音上传）|
| 存储 | **eMMC**（本地录音落盘，路径 `/usb/recode`）|
| 音频 | 麦克风阵列 + **Opus 编码 → Ogg 封装**，16-bit PCM，支持普通/语音双通道切换 |
| 交互 | 按键（短按/长按）、LED 指示（录音/满存/低电）、USB 大容量存储 |
| 电源 | 锂电池 + 充电管理（充电曲线、拔出防抖）|
| 升级 | BLE OTA，双镜像、CRC32 校验、断点续传、randomCode 防重放 |

**用途**：用户按下按键录音 → 音频以 Opus/Ogg 存入 eMMC → 通过 **BLE** 同步到手机"得到笔记"App，或经 **Wi-Fi** 高速上传 → 云端做 ASR 转录 + AI 总结，生成笔记。整条链路里，卡片是"**采集端**"，App/云端是"**处理端**"。

---

## 六、与 App 侧协议的对应关系

固件与 App 侧的 `jiatui_meet` SDK 完全对应：

| 固件侧 | App 侧（Dart）|
|---|---|
| `app_ble_ai_app_*` | `VoiceCardDeviceAdapter` |
| `recode` 录音流 | `VoiceCardPcmFrameStore`、`VoiceCardFrameBackfill` |
| Opus 编码 | `opus_decoder_util.dart` |
| AES 加密 BLE 数据（`aes_128_decrypt ble_reply_data`）| `cmd/aes_pkcs7_codec.dart` |
| BLE 分包 | `cmd/ble_packet_assembler.dart` |
| OTA | `ota/sdk/bes_ota_cmd.dart`、`ota_manager.dart` |
| 文件传输协议 | `cmd/tran_protocol_decoder.dart`、`audio_download_cmd_parser.dart` |

固件里明确出现 **`%s aes_128_decrypt ble_reply_data:`** —— BLE 通信内容用 **AES-128** 加密，对应 App 的 AES-PKCS7 编解码。

---

## 七、安全性观察

| 项 | 发现 | 评价 |
|---|---|---|
| 固件下载地址 | App 内**明文硬编码** | 任何人可下载固件，无鉴权 |
| 固件包 | **无签名验证**（仅 CRC32 完整性）| 可被篡改后重打包 |
| OTA 传输 | randomCode 校验会话一致性 | 防重放有效 |
| 源码泄露 | 编译路径含内网 Gerrit `ssh://172.16.40.40:29418/wifi`、开发者名 `xiaodongjin` | 信息泄露 |
| BLE 数据 | AES-128 加密 | 密钥管理是关键，需逆向 App 才有 |

---

## 八、产出文件清单

```
output/getnote-apk-review/
├── ANALYSIS-REPORT.md                        总报告（App 侧）
├── FIRMWARE-ANALYSIS.md                      本报告（固件侧）
├── firmware/
│   ├── getnote-voicecard-fw-0.0.9.bin        原始固件包 (2.35 MB)
│   └── split/
│       ├── img0.bin                          镜像0: BLE主控/应用固件 (1.11 MB)
│       ├── img1.bin                          镜像1: WiFi子系统固件 (1.14 MB)
│       ├── img0_strings.txt                  镜像0 字符串 (5,496)
│       └── img1_strings.txt                  镜像1 字符串 (7,539)
```

## 九、下一步可深挖方向

1. **反汇编主控固件**：用 Ghidra/IDA（ARM Cortex-M33, Thumb-2）载入 `img0.bin`，基址 `0x28000000`，定位 `app_ble_ai_app_*` 函数还原 BLE GATT 服务、UUID 与命令表
2. **提取 BLE 服务 UUID**：结合 App 侧 `00009000/00009100-0000-1000-8000-57616C6B697A`（"Walkiz"）验证
3. **还原 AES 密钥**：从 `img0.bin` 中 `aes_128_decrypt` 调用点找密钥来源（可能是固定 key 或 ECDH）
4. **OTA 协议还原**：定位 `bes_ota_cmd.dart` 对应的固件端命令处理，复现完整 OTA 流程
5. **提取 Ogg 文件格式**：确认录音容器结构，实现离线解析
