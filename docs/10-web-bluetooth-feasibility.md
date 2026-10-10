# Get 笔记「录音卡」BLE 深挖 + 网页连接方案可行性评估

- 日期：2026-10-10
- 前置：`ANALYSIS-REPORT.md`（App 侧）、`FIRMWARE-ANALYSIS.md`（固件侧）
- 本次目标：继续反编译固件与 App，评估"仿照飞书录音豆网页、做一个连所有 Get 笔记设备的网页"的可行性

---

## 一、继续反编译的成果

### 1.1 实测发现：设备广播名与 GATT 暴露

通过 `adb shell dumpsys bluetooth_manager` 拿到实机数据：

```
shim::legacy::record 004  XX:XX:XX:XX:8A:67  BLE  cod:0x000500
                          remote_info:13-01811-00688  name:""
设备列表:  5C:8E:8B:A7:8A:67 [LE]  Get-A78A67     ← 卡片广播名
Profile:   HID_HOST      connection policy = 100  ← 暴露标准 HID
           BATTERY       connection policy = 100  ← 暴露标准 Battery Service
manufacturer_name: 70   ← 0x0046 = BES 恒玄，验证芯片判断
```

**两个关键结论**：
1. 设备广播名规则 = **`Get-` + MAC 后 6 位**（`Get-A78A67`），可据此做 BLE 扫描过滤。
2. 卡片**暴露了标准 GATT 服务（HID + Battery）**——意味着部分服务是公开可发现的，不是完全私有。

### 1.2 App 侧 BLE 使用的插件与类

```
BmReadCharacteristicRequest / BmWriteCharacteristicRequest   ← 统一 BLE 请求封装
BluetoothService / BluetoothCharacteristic / BluetoothDescriptor
AdvertisementData{advName: ...}
ScanResult{device: ...}
_startScan / _scanResults / deviceId / serviceUuid / serviceUuids
primaryServiceUuid / characteristicUuid / authenticatedSignedWrites
```

App 用 Dart 侧的 BLE 抽象层（`BluetoothLowEnergy` 风格的插件），有完整的 **serviceUuid / characteristicUuid** 操作，并用到 `authenticatedSignedWrites`（签名写入）。

### 1.3 已确认的 UUID

```
00009000-0000-1000-8000-57616C6B697A    ← 主服务（后缀 ASCII "Walkiz"）
00009100-0000-1000-8000-57616C6B697A    ← 第二服务（OTA？）
00002902-0000-1000-8000-00805f9b34fb    ← 标准 CCCD
```

> 注意：`00009000-...-57616C6B697A` 的写法说明供应商用了自定义 128-bit UUID，后缀 `57616C6B697A` = "Walkiz"（可能是方案商名）。

### 1.4 固件侧 BLE 应用函数（设备端）

```
app_ble_ai_app_user_init             AI 应用初始化
app_ble_ai_app_adv_activity_prepare  广播数据准备
app_ble_ai_app_data_sent_done        数据已发
app_ble_ai_app_file_receive_data_done 文件接收完成
app_ble_gatt_server_callback         GATT 服务端
app_ble_set_battery_level_handle     电量
common_exit_sleep_enter_pairing      进入配对
ota_ble_conn_hdl                     OTA 连接处理
```

### 1.5 产品功能（从 App UI 文案还原）

从 `libapp.so` 提取出 **243,169 条**干净中文字符串，官方叫法确认：

| 功能 | 证据文案 |
|---|---|
| 设备名 | "**录音卡**"（不是"卡片"）|
| **账户绑定** | "然后录音卡可以绑定到另一个账户"、"你确定要解除绑定吗"、"无法绑定设备" |
| 同步 | "两端数据将自动同步"、"同步主流程开始"、"发现录音卡中还有正在传输的录音" |
| **Wi-Fi 热点传输** | "开录音卡的热点"、"仅在应用内…" |
| 固件升级 | "为使录音卡的固件顺利更新"、"准备发送固件数据包"、"固件已经同步到录音卡中" |
| 录音 | "休眠后仍然可以一键立即开始录音"、"会议录音"、"上传录音" |
| 麦克风回退 | "回退到麦克风录音"、"已经切换到手机麦克风录音"、"自动切换麦克风" |
| 电量/存储 | "录音卡电量不足"、"电量已满" |

---

## 二、参照物：飞书录音豆 D3200 的网页为何能做

项目里已有 `recording-bean-web/`（在线体验 `recording-bean-web.pages.dev`），其成功的关键在于：

| 维度 | D3200（能做网页） |
|---|---|
| 识别设备 | 直接按 **Service UUID 精确过滤**，不依赖广播名 |
| 加密 | **ECDH(P-256) + HKDF-SHA256 + AES-CTR**，浏览器 `crypto.subtle` 原生支持 |
| 密钥协商 | **每次连接现场协商**，不依赖账号、不依赖云端 |
| 账号 | **完全不需要**（"无需账号，也不需要后端服务器"）|
| 协议 | 明文结构清晰（`protocol.js`、`crypto.js` 全部还原）|

> 核心：D3200 的安全模型是**纯本地点对点密码学**，浏览器完全有能力复现，所以纯网页方案成立。

---

## 三、Get 笔记录音卡 vs D3200：关键差异

| 维度 | D3200 录音豆 | **Get 笔记录音卡** | 对网页方案的影响 |
|---|---|---|---|
| BLE 服务 UUID | 公开，可过滤 | `00009000-...Walkiz` / `00009100` 已知 | ✅ 可过滤 |
| 加密算法 | ECDH+HKDF+AES-CTR | **AES-128**（`aes_128_decrypt ble_reply_data`）| ⚠️ 算法简单，但… |
| 密钥来源 | **现场 ECDH 协商** | **疑似与账号绑定相关**（`secretID`/`secretKey`/`session`）| ❌ 关键障碍 |
| 账号绑定 | 不需要 | **强绑定**（`/devices/bind`、`bind/pre-check`、绑定手机号）| ❌ 关键障碍 |
| 设备归属 | 无 | "录音卡可以绑定到另一个账户" | ❌ |
| 传输方式 | BLE 直传 | **BLE + Wi-Fi 热点**双通道 | ⚠️ Wi-Fi 热点浏览器无法直连 |
| 协议实现 | 已完整还原 | 部分还原，AES 密钥未定位 | ⚠️ 需继续逆向 |

### 3.1 核心障碍一：账户绑定与云端依赖

设备要能用，必须先走 `POST /voicenotes/mind/app/v1/devices/bind`（带 `bind/pre-check` 预检）。UI 文案明确显示设备**绑定到账户**，且支持"绑定到另一个账户"（即换账号需解绑）。

**这意味着**：设备与得到账号之间存在服务端强关联。即使浏览器能连上 BLE，设备端也可能要求一个只有登录后才能拿到的**绑定凭证/会话密钥**才会正常应答音频数据。

### 3.2 核心障碍二：AES 密钥来源未知

固件的 `aes_128_decrypt ble_reply_data` 需要一个 128-bit 密钥。目前**尚未定位密钥是**：
- (a) 固定的硬编码 key（那么任何客户端都能解密 → 网页可行）
- (b) 由云端绑定时下发的 session key（那么需登录 → 网页不可行）
- (c) 基于设备 MAC/SN 派生（折中）

**这一条是决定性的，必须进一步逆向才能下定论。**

### 3.3 核心障碍三：Wi-Fi 热点传输浏览器无能为力

产品支持"开录音卡的热点"高速传输录音。浏览器**无法主动连接设备创建的 Wi-Fi 热点**（Web 平台无此 API）。所以大批量录音上传这条路径，纯网页做不到，只能走 BLE（慢）。

---

## 四、结论：能否做一个"连所有 Get 笔记设备"的网页？

### 4.1 分能力给出结论

| 能力 | 纯网页（Web Bluetooth）可行性 | 说明 |
|---|---|---|
| **扫描/发现** Get 录音卡 | ✅ **可行** | 按 `Get-XXXXXX` 广播名或 `00009000` 服务 UUID 过滤 |
| **读取电量、固件版本** | 🟡 **大概率可行** | Battery Service 是标准服务（实测已暴露），可能无需密钥 |
| **读取录音列表 / 下载录音** | ❓ **存疑** | 取决于 AES 密钥来源；若需账号绑定则不可行 |
| **播放/导出录音** | ✅ 若拿到明文则可行 | 浏览器可做 Opus→Ogg→WAV（D3200 已实现同类） |
| **转录 + AI 总结** | ✅ **完全可行** | 与设备无关，调硅基流动等 API（D3200 网页已实现） |
| **OTA / 解绑 / 恢复出厂** | ❌ 不建议 | 高风险，D3200 网页也明确不提供 |
| **Wi-Fi 热点高速传输** | ❌ **不可行** | 浏览器无法连设备热点 |

### 4.2 总体判断

> **"像 D3200 那样做一个完全绕过官方 App、连所有 Get 录音卡的纯网页，目前不能直接照搬实现——卡在两个点上：① AES 会话密钥来源未知；② 设备强依赖账户绑定。这两点必须先逆向清楚。**

但存在**两条现实可行路径**：

#### 路径 A（推荐，风险低）：网页只做"后处理"，不碰设备
浏览器负责：**上传录音文件 → 转录 → AI 总结 → 导出**。
- 录音文件由用户从官方 App 导出后再拖进网页
- 与设备零耦合，**立刻就能做**，且对所有设备通用
- 这正是 D3200 网页里最实用的那部分能力（转录+总结+ZIP 导出）

#### 路径 B（研究向，风险高）：网页做设备直连
需要先完成：
1. **定位 AES-128 密钥来源**（继续逆向 `img0.bin` 中 `aes_128_decrypt` 调用点 + App 侧 `aes_pkcs7_codec.dart`）
2. **验证设备是否强制要求绑定凭证**（用未绑定账号的浏览器尝试连接，看设备是否拒绝音频通道）
3. **还原完整命令帧格式**（`bes_ota_cmd.dart` + `ble_packet_assembler.dart` + `tran_protocol_decoder.dart`）
4. **判断绑定凭证能否本地复现**（若只是 SN+固定算法，则可；若需云端签发，则不可）

若 1-4 都通过，则可做出类似 D3200 的网页；只要有一步是"云端签发"，纯网页方案即不成立。

### 4.3 与"所有 Get 笔记设备通用"的关系

- Get 录音卡目前**只有一种硬件**（BES best1306p，`mivi_ai_recorder` 分支），所以"连所有设备"在协议上其实是**同一套**，比 D3200 还简单。
- 真正的门槛不是"设备型号多"，而是**账号绑定 + 密钥**。

---

## 五、下一步建议（若要继续推进路径 B）

1. **逆向 AES 密钥**：在 `img0.bin` 中定位调用 `aes_128_decrypt` 的函数，回溯密钥寄存器/内存来源；同时反编译 App 的 `cmd/aes_pkcs7_codec.dart`
2. **抓包验证**：用 nRF Connect 手动连 `00009000` 服务，看无账号时能读到什么（电量/固件通常不加密）
3. **尝试读取**：若电量/固件明文可读 → 网页至少能做"设备状态面板"
4. **判断绑定**：观察绑定后在 BLE 层是否多出一个"会话建立"步骤
5. **工具**：bleak（Python）先做 PoC，验证协议后再移植到 Web Bluetooth

---

## 六、本次新增产出

```
output/getnote-apk-review/
├── ui_strings_zh.txt          从 libapp.so 提取的 243,169 条干净中文 UI 文案
└── WEB-FEASIBILITY.md         本报告
```

（参考项目：`recording-bean-web/` = 飞书录音豆 D3200 的网页直连实现，可作为 Get 录音卡网页版的技术模板）
