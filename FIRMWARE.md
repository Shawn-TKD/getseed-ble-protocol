# 得到 AI 录音卡 固件解析

> 对象：0.1.8 版固件（通过 BLE OTA 抓包完整还原）。芯片：恒玄 BES **best1306p**。
> 配套过程报告见 [docs/06](docs/06-firmware-deep-re.md)、[docs/07](docs/07-firmware-ota-capture.md)、[docs/08](docs/08-firmware-analysis.md)。

---

## 1. 固件是怎么拿到的

设备固件**不提供下载**，但 BLE OTA 是明文协议 —— 于是在 App 升级时用 HCI snoop
抓了完整升级流量（5,136 包）并重建出两个镜像：

| 镜像 | OTA 命令 | 包数 | 重建大小 |
|---|---|---|---|
| 主固件 | `85 f6` | 4,821 | **1,600,572 B (1.53 MB)** |
| 子固件 | `85 40` | 150 | **48,000 B (47 KB)** |

每包 = `85 f6 01 00 00` + **337 B** 数据（子固件 325 B）。CRC32 校验、无签名、无加密。

---

## 2. 宏观结论：固件未加密、未压缩

对主镜像做分块香农熵分析：

```
高熵块 (>7.0):   27 / 1563  (1.7%)   ← 极少 ⇒ 无整体压缩/加密
低熵块 (<3.0):   14 / 1563
函数数量:        1,980（push {...,lr} 序言统计）
```

⇒ 可以直接做字符串提取与线性反汇编，无需脱壳。

## 3. 启动引导（0x2C000114）

```
0x2C000114  bl    #0x2c0007a8       ; 早期初始化
...
0x2C000120  msr   msplim, r0        ; ★ 堆栈限制寄存器 → ARMv8-M TrustZone
```

`msplim` 的存在证明这是 **Cortex-M33 + TrustZone**；配合 `isb/sy` 指令可见双核（CM33 + DSP）结构，
与 BES best1306p（BLE + WiFi SoC）一致。

---

## 4. BLE 私有协议的设备端命令表（`blespp_*`）

固件字符串直接暴露了全部处理器函数 —— **所有命令均无鉴权 / token 校验分支**：

```
blespp_app_receive_blespp_data_prec                数据接收预处理
blespp_app_cmd_replay_handle                       命令响应
blespp_app_get_device_sn_code_handle               读设备 SN
blespp_app_notify_device_start_or_stop_recode      远程开始/停止录音
blespp_app_send_hid_to_phone                       HID 上报
blespp_file_receive_blespp_data_prec               文件数据接收
blespp_file_get_device_current_time_handle         读时间
blespp_file_set_device_time_handle                 设置时间
blespp_file_get_device_file_list_info_handle       列文件
blespp_file_set_device_trans_specify_file_handle   传输指定文件
blespp_file_set_device_delete_specify_file_handle  删除指定文件   ← 实测 cmd 0x0044
blespp_file_get_device_wifi_status_handle          读 WiFi 状态
blespp_file_set_device_special_wifi_status_handle  设置 WiFi
blespp_file_set_device_clear_all_file_handle       清空全部文件
blespp_device_sync_recode_status                   同步录音状态
blespp_device_get_msd_mode_status                  U盘(MSD)模式状态
blespp_device_set_msd_mode_status                  设置 U盘模式
blespp_get_set_d aes_128_decrypt ble_reply_data    ⭐ 数据通道解密入口
```

与 BLE 抓包对齐后的命令码表见 [PROTOCOL.md](PROTOCOL.md)。

### 实体按键（固件符号）

```
pwrkey_hlw_ui_key_down_handle                    单击
pwrkey_hlw_ui_key_sevenclik_handle               七击（关机组合）
pwrkey_hlw_ui_key_longpress_handle               长按（开机）
"%s msd mode clock key!!"                        进入 U盘模式
"%s ota mode clock key!!"                        进入 OTA 模式
"%s wifi trans clock key!!"                      进入 WiFi 传输
```

---

## 5. OTA 协议（还原）

| 命令 | 方向 | 含义 | 载荷 |
|---|---|---|---|
| `7b 01` | App→卡 | 开始升级 | — |
| `99 04` | App→卡 | 协议版本 | — |
| `97` | App→卡 | 开始传输 | — |
| `8e 04` | 卡→App | 芯片确认 | **`BEST`**（magic 即"证书"）|
| `8c 2c` | 卡→App | 固件信息头 | `BEST` + 元数据 (49 B) |
| `80 0c` | App→卡 | 分区配置 | `BEST 58 67 25 00 50 65 bc a9` |
| **`85 f6`** | App→卡 | **主固件数据块** | 337 B |
| **`85 40`** | App→卡 | **子固件数据块** | 325 B |
| `82 08` | 卡→App | CRC 校验回执 | `BEST` + CRC32 (13 B) |
| `92 04` | App→卡 | 结束 | `BEST` |
| `86 5c` / `82 08` / `92 04` / `8c 2c` / `80 0c` | — | 断点续传 / 回执 / 结束 | — |

要点：

1. **芯片确认只看 `BEST` magic**（`42 45 53 54`）—— 无设备证书、无挑战响应
2. 仅 CRC32 完整性校验，**无签名** ⇒ 理论上可推送任意自制镜像
3. `8c 2c` 固件信息头里含分区表与版本元数据

> 同一 `BEST` magic 也出现在安克 D3200（同为 BES 方案）的 OTA 里，见
> [docs/09](docs/09-comparison-anker-d3200.md) —— 两家共用 BES 参考设计。

---

## 6. 密码学现状

| 位置 | 内容 |
|---|---|
| 固件 | 仅 WiFi WPA 标准密码学（wpa_supplicant）；BLE 数据通道有 `aes_128_decrypt` 入口 |
| App（libapp.so） | pointycastle：`ECDHKeyDerivator`(P-256)、`HKDFKeyDerivator`、`CBCBlockCipher`、`AesHeader`、`AesPkcs7Codec`、`EncryptUtil`、字段 `secretKey` |
| 数据通道（0xA102/A105） | 16 B 块，仅 4+5 种且**跨会话逐字节相同** ⇒ 静态密钥 + 确定性模式 |
| 控制通道 / 录音 | **完全明文** |

⇒ 录音数据的机密性依赖的加密通道**并不承载数据**；录音本身零加密。

---

## 7. 其他能力（固件支持、尚未全部实测）

| 能力 | 状态 |
|---|---|
| U盘（MSD）模式 | 固件支持 `get/set_msd_mode_status`；默认关闭，需 BLE 命令或按键组合切入 |
| WiFi 快传 | `*_wifi_status_handle` 一族；录音传输时经 BLE 通知 App WiFi 信息 |
| 远程录音 | `notify_device_start_or_stop_recode`（命令码未定位）|
| 删除 / 清空 | 已实测（`0x0044` / `0x0041`）|
| HID | `send_hid_to_phone`（用途未查明）|
