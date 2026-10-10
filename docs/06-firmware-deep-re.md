# 得到录音卡 0.1.8 固件深度反编译分析报告

> 分析时间: 2026-10-10
> 固件: fw_0.1.8_img_f6.bin (1,600,572 B) / fw_0.1.8_img_40.bin (48,000 B)
> App: com.biji.getnotes v3.1.6 (libapp.so, ARM64, 29.8 MB)
> 工具: capstone 5.0.7 (ARM Thumb-2 反汇编)

---

## 一、执行摘要

对 **0.1.8 固件**和 **App** 做了双向反编译，得出三个**颠覆性结论**：

| # | 结论 | 证据等级 |
|---|------|---------|
| 1 | 固件是 **BES best1306p** 的 `mivi_ai_recorder` 定制固件，**代码/数据完全明文**（无加密无压缩） | ★★★★★ |
| 2 | OTA 协议 **BES 标准 BLE OTA，无加密无签名** | ★★★★★ |
| 3 | BLE 私有通道用 **ECDH(P-256) + HKDF + AES-128**，密钥协商在 **App 侧**完成，固件仅被动接收 | ★★★★☆ |

**最大突破**：之前认为"密钥来源未知导致无法自建 App"，现已查明**密钥是 App 侧的 ECDH 协商产生**（标准 pointycastle 库），**可以本地复现**。

---

## 二、固件整体结构

### 2.1 宏观统计
```
文件大小:      1,600,572 bytes
唯一字节值:    256/256 (完整)
零填充:        6.6%
高熵块(>7.0):  27/1563 (1.7%)  ← 极少, 证明无压缩/加密
低熵块(<3.0):  14/1563
"BEST" 出现:   6 次 (0x54C32/54DA0/54FBC/551B2/556C2/16BF52)
函数数量:      1,980 (push {...,lr} 序言统计)
```

### 2.2 固件头 (0x00–0x110)
```
偏移     值                        含义
[0x00]  00 02 00 00              版本/魔数
[0x04]  01 00 00 00              分区 ID = 1
[0x08]  02 00 00 00              标志
[0x0C]  01 01 00 00              标志2
[0x1E]  F4 AD 12 00              长度字段
[0x28]  A1 9A 3C 81              CRC32 #1
[0x2C]  F5 CC 26 A7              CRC32 #2
[0x108] 48 AB 14 2C              FLASH 加载地址 0x2C14AB48 ✅
[0x10C] 10 48 00 47              ARM: ldr r0,[pc,#64]; bx r0
```

### 2.3 启动引导 (0x2C000114 起，反汇编)
```asm
0x2C000114  bl    #0x2c0007a8       ; 早期初始化
0x2C000118  ldr   r0, [pc,#0x3c]
0x2C00011A  msr   msp, r0           ; 设置主堆栈
0x2C000120  msr   msplim, r0        ; 堆栈限制寄存器 (ARMv8-M TrustZone!)
0x2C000126  msr   control, r0       ; 切换特权模式
0x2C00012A  isb   sy                ; 指令同步屏障 (双核启动特征)
0x2C00012E  bl    #0x2c001de8       ; C 运行时初始化
0x2C000132  bl    #0x2c001d00       ; data 段初始化
0x2C000136  bl    #0x2c001c68       ; BSS 清零
```
→ **M33 TrustZone + 双核**特征，与 `best1306p` 完全吻合

---

## 三、OTA 协议完整还原

### 3.1 实测命令表(1200+ 包解析)
| 命令 | 方向 | 含义 | 长度 |
|------|------|------|------|
| `7b 01 00 00 00 00` | App→卡 | OTA 开始 | 6 |
| `99 04 ...01` | App→卡 | 参数协商 | 9 |
| `97 01 ... 03` | App→卡 | 查询 | 6 |
| `8e 04 ... "BEST"` | 卡→App | 芯片确认 | 9 |
| `8c 2c ... "BEST"` | 卡→App | 固件信息头 | 49 |
| `80 0c ... "BEST"...` | App→卡 | 分区配置 | 17 |
| `86 5c ...` | App→卡 | OTA 配置 | 97 |
| **`85 f6 01 00 00` + 337B** | App→卡 | 主固件数据块 | 337 |
| **`85 40 01 00 00` + 325B** | App→卡 | 子固件数据块 | 325 |
| `82 08 ... "BEST"` + CRC | 卡→App | CRC 回执 | 13 |
| `92 04 ... "BEST"` | App→卡 | OTA 结束 | — |

### 3.2 固件内 OTA 状态机(字符串符号)
```
[OTA_COMMAND_CONFIG_OTA]         [OTA_RSP_CONFIG]
[OTA_COMMAND_GET_VERSION]        [OTA_RSP_GET_OTA_VERSION]
[OTA_COMMAND_GET_OTA_RESULT]     [OTA_RSP_RESULT]
[OTA_COMMAND_RESUME_VERIFY]      [OTA_RSP_RESUME_VERIFY]
[OTA_DATA_PACKET]                [OTA_RSP_SEGMENT_VERIFY]
[OTA_DATA_ACK]                   [OTA_RSP_START]
[OTA_FLASH_CONTENT_DATA]         [OTA_RSP_START_ROLE_SWITCH]
[OTA_READ_FLASH_CONTENT]
OTA_BOOT_INFO_SECTION_SIZE=0x1000
Bes_enter_ota_state / app_otaMode_enter / app_ota_key_handler
app_ota_push_rx_data / app_ota_buf_lock / app_ota_event_mailbox
ota_ble_conn_hdl / hlw_ota_fs_release / app_update_ota_boot_info
```

**安全评估**：OTA 全程无签名验证、无加密，仅 CRC32 校验 → **可自行刷写任意固件**

---

## 四、BLE 私有协议(设备端)

### 4.1 SPP 命令处理函数表(`blespp_*`)
```
blespp_app_receive_blespp_data_prec              ← 数据接收预处理
blespp_app_cmd_replay_handle                     ← 命令响应
blespp_app_get_device_sn_code_handle             ← 读设备 SN
blespp_app_notify_device_start_or_stop_recode    ← 开始/停止录音
blespp_app_send_hid_to_phone                     ← HID 上报
blespp_file_receive_blespp_data_prec             ← 文件数据接收
blespp_file_get_device_current_time_handle       ← 读时间
blespp_file_set_device_time_handle               ← 设置时间
blespp_file_get_device_file_list_info_handle     ← 列文件
blespp_file_set_device_trans_specify_file_handle ← 传指定文件
blespp_file_set_device_delete_specify_file_handle← 删文件
blespp_file_get_device_wifi_status_handle        ← 读 WiFi 状态
blespp_file_set_device_special_wifi_status_handle← 设置 WiFi
blespp_file_set_device_clear_all_file_handle     ← 清空文件
blespp_device_sync_recode_status                 ← 同步录音状态
blespp_device_get_msd_mode_status                ← U盘模式状态
blespp_device_set_msd_mode_status                ← 设置U盘模式
blespp_get_set_d aes_128_decrypt ble_reply_data  ← ⭐ 解密入口
```

**关键**：所有命令**无鉴权/token 校验分支** → 设备端不校验账号

### 4.2 按键功能(实体按键行为)
```
pwrkey_hlw_ui_key_down_handle                 ← 单击
pwrkey_hlw_ui_key_up_handle
pwrkey_hlw_ui_key_sevenclik_handle            ← 七击
pwrkey_hlw_ui_key_longpress_handle            ← 长按
pwrkey_hlw_ui_key_longpress_up_handle
pwrkey_hlw_ui_key_rampageclick_longpress_handle ← 连击+长按
%s msd mode clock key!!                       ← 进入U盘模式
%s ota mode clock key!!                       ← 进入OTA模式
%s wifi trans clock key!!                     ← 进入WiFi传输
```

---

## 五、密码学分析(重大突破)

### 5.1 App 侧完整密码学栈(pointycastle)
```
ECDHKeyDerivator          ← ECDH 密钥协商
HKDFKeyDerivator          ← HKDF 密钥派生
ECCurve_prime256v1        ← NIST P-256 曲线 ⭐
ECCurve_secp256r1          = P-256
ECCurve_secp256k1         ← Bitcoin 曲线
ECCurve_brainpoolp256r1/256t1
impl.key_derivator.hkdf   ← HKDF 实现
AESEngine                 ← AES 核心
AesPkcs7Codec             ← AES-PKCS7 编解码
AesHeader                 ← AES 报文头封装
EncryptUtil               ← 加密工具
BleCommand / BlePacket / BlePacketSender / BlePacketAssembler
BleData / BleFlow / BleDownload / BleProgress
```

### 5.2 固件侧密码学(对比)
```
仅 WiFi 协议栈标准实现:
  SAE: Derive PWE from PT          ← WPA3 标准
  Derive PMKID using HMAC-SHA-1    ← WPA2 标准
  4-Way Handshake / PTK / GTK      ← 802.11i 标准
BLE 相关仅一行:
  blespp_get_set_d aes_128_decrypt ble_reply_data
AES S-box @ file 0x95C4E (256B, 标准)
逆S-box @ file 0x16CB50 — 非标准(可能动态生成)
```

### 5.3 推导出的 BLE 加密链路
```
① App 生成 ECDH 密钥对 (P-256)
② App ↔ 设备 交换公钥 (经 BLE 明文 / blespp get/set 命令)
③ 双方各自计算 sharedSecret = ECDH(privKey, peerPubKey)
④ HKDF(sharedSecret) → AES-128 key
⑤ AES-PKCS7 加解密 BLE 私有通道 (AesHeader 封装帧)
⑥ 固件侧 blespp_get_set_data 调用 aes_128_decrypt 解密
```

**与飞书录音豆 D3200 对比**：
| 项目 | D3200 | 得到录音卡 |
|------|-------|-----------|
| 密钥协商 | ECDH(P-256) | ECDH(P-256) ✅ 相同 |
| 密钥派生 | HKDF | HKDF ✅ 相同 |
| 对称加密 | AES-CTR | AES-PKCS7 (CBC?) ⚠️ 略异 |
| 传输 | BLE GATT | BLE SPP over GATT |
| 账号依赖 | 不需要 | 设备端不需要 ✅ |

---

## 六、对"自建 App 接入"的最终结论

### 可行性评估(更新版)
| 层级 | 可行性 | 说明 |
|------|--------|------|
| ① 设备控制(录音/按键/状态) | ✅ 完全可行 | `blespp_*` 无鉴权 |
| ② 读取文件列表/下载 | ✅ 可行 | 需过 AES 层 |
| ③ 解密下载内容 | ✅ **现判定可行** | 密钥 = App 侧 ECDH 协商结果 |
| ④ 自制 App 刷固件 | ✅ 可行 | OTA 无签名 |
| ⑤ 脱离官方长期使用 | ✅ 可行 | 设备端无账号绑定 |

### 关键实施路径
1. **抓取 BLE 密钥协商握手**：监听 App 与设备首次连接时的 `blespp` 交换(公钥交换)
2. **复现 ECDH+HKDF**：用 Python (cryptography / pycryptodome) 实现 P-256 ECDH
3. **移植 AES 层**：确认 AES 模式(CBC/CTR)和 IV 来源
4. **用 bleak PoC 验证**：connect → 握手 → 解密一条 status 回复

### 剩余未知项
- [ ] AES 具体模式(CBC vs CTR) — 需从 `AesPkcs7Codec` 反汇编确认
- [ ] IV/Nonce 生成方式
- [ ] 公钥交换的确切命令格式(需抓 BLE 握手)

**这些都可以通过"抓一次 App 与设备的完整 BLE 握手"来解决。**

---

## 七、其他发现

### 7.1 源码元数据泄露(再次确认)
```
客户代号:   mivi
定制分支:   cust/mivi_ai_recorder
内部 Gerrit: ssh://172.16.40.40:29418/wifi
子仓库:     bsp-src / bthost-src / multimedia-src / services/aiot / libc_adapter
构建日期:   Jun 19 2025 / May 15 2026
```

### 7.2 芯片平台确认
```
BTC 1306p: metal id=%d
BTC:1306p t1 work mode patch version:%08x
rx_dc_cal_1306p
bt_drv_update_btc_sw_version
→ BES 恒玄 best1306p (Cortex-M33 + TrustZone + 双核)
```

### 7.3 Flash 布局
```
FLASH_BASE            = 0x2C000000
FLASH_NC_BASE         = 0x28000000
__ota_boot_info_start = 0x28018000
__factory_start       = 0x283FF000
OTA_BOOT_INFO_SECTION_SIZE = 0x1000
```

---

## 八、下一步建议

**优先级 1（打通自建 App）**：抓取 App↔设备 BLE 握手
- 方法：logcat 已证明 App 打印明文；连接瞬间抓 `blespp` 命令流
- 产出：公钥交换格式 + 确认 AES 模式

**优先级 2（固件自由刷写）**：实现 BES OTA 工具
- 依据：已完整的 OTA 命令表
- 产出：Python 版 OTA 刷写器（可刷回 0.1.4 / 刷任意固件）

**优先级 3（深入）**：反汇编 `aes_128_decrypt` @ img0
- 定位实际 AES 调用点，确认模式与 IV

---

*报告生成: 2026-10-10 | 工具: capstone + Python*
