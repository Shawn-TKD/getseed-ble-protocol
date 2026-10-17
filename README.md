# 得到 AI 录音卡（GetSeed）BLE 协议逆向

> 型号 **GSC10** · 恒玄 BES best1306p · 固件 0.1.8（`a622fb2-best1306p_ibrt`）
>
> 对得到笔记的 AI 录音卡做了完整协议逆向：**无需官方 App、无需账号、无需任何密钥**，
> 即可用电脑（或浏览器）直接连接卡片、列出并下载全部录音。

[![protocol](https://img.shields.io/badge/protocol-BLE%20GATT-blue)](PROTOCOL.md)
[![chip](https://img.shields.io/badge/SoC-BES%20best1306p-orange)](FIRMWARE.md)
[![audio](https://img.shields.io/badge/audio-Ogg%20Opus%2016kHz-green)](PROTOCOL.md)

---

## 最小可用示例

```bash
pip install bleak
python tools/getcard.py scan                 # 扫描卡片
python tools/getcard.py list                 # 列出录音
python tools/getcard.py pull --all --wav     # 全部下载并转 WAV
python tools/getcard.py pull --all --delete-after   # 下载后删卡片原件（"移动"）
python tools/getcard.py info                 # 设备时间 / MTU / 可用空间
```

完整命令见 [tools/README](tools/) 与 `getcard.py --help`。

一条网页版路线（Chrome/Edge，免装 Python）也已实现，见
[docs/10-web-bluetooth-feasibility.md](docs/10-web-bluetooth-feasibility.md)。

---

## 🧩 WorkBuddy / Agent 技能包（`skills/getcard/`）

把"Agent 直读录音卡"封装成了标准 Skill，可直接安装到 WorkBuddy（或任何支持
SKILL.md 约定的 Agent）：

```
skills/getcard/
├── SKILL.md                  ← 触发条件 + 操作流程 + 安全规则 + 故障速查
├── scripts/getcard.py        ← 蓝牙操作（同 tools/）
├── scripts/transcribe.py     ← 硅基流动转写 + 摘要（纯标准库）
└── references/protocol.md    ← 协议参考（按需加载）
```

安装：把 `skills/getcard/` 复制到 `~/.workbuddy/skills/getcard/`（用户级）。
之后对 Agent 说"**把录音卡上的录音拉下来转写成文字**"即可自动执行。

安全默认值写进了 SKILL.md：**只读优先**，`delete`/`purge` 必须用户当次明确要求。

---

## 核心结论（TL;DR）

| # | 结论 |
|---|---|
| 1 | **录音文件完全明文**（Ogg Opus，16 kHz 单声道），走 BLE 控制通道 `0x9101/0x9102` |
| 2 | **免配对、免绑定、免账号**：固件 `blespp_*` 命令表里没有任何 bind/unbind 处理器，广播也无 bind 位 |
| 3 | 官方宣称「非本人不可取、硬件级防护、严禁外设导出」—— **实测不成立** |
| 4 | 加密只存在于短命令通道（`0xA102/A105`），且**不承载录音数据**；密文跨会话恒定 ⇒ 静态密钥 |
| 5 | 控制通道 CRC32 已破解（`zlib.crc32`），帧可 100% 伪造 |
| 6 | 官方 App 每次连接先发 `0x0041` 清掉上次已同步的录音 —— **「同步后卡片清空」是设计行为** |
| 7 | 固件未加密未压缩（熵分析 1.7% 高熵块），OTA 无签名，芯片确认只看 `BEST` magic |

---

## 文档导航

| 文档 | 内容 |
|---|---|
| **[PROTOCOL.md](PROTOCOL.md)** | ⭐ 协议总集：广播、GATT、帧格式、完整命令表、下载流程、设备信息通道 |
| **[FIRMWARE.md](FIRMWARE.md)** | ⭐ 固件解析：OTA 抓包重建、熵分析、启动引导、`blespp_*` 命令表、密码学现状 |
| [PRIVACY.md](PRIVACY.md) | 安全与隐私评估（明文 + 零鉴权意味着什么）|
| [tools/getcard.py](tools/getcard.py) | 电脑端直连工具（scan / info / list / pull / sync / delete / purge / watch）|

### 过程报告（按时间线）

| # | 报告 | 里程碑 |
|---|---|---|
| 12 | [apk-analysis-report](docs/12-apk-analysis-report.md) | APK 结构与 Flutter 产物 |
| 01 | [ble-handshake-capture](docs/01-ble-handshake-capture.md) | btsnoop 抓包方法（bugreport 提取 HCI log）|
| 02 | [ble-protocol-full](docs/02-ble-protocol-full.md) | 三通道划分 + 控制通道 CRC32 破解 |
| 03 | [audio-transfer-cracked](docs/03-audio-transfer-cracked.md) | 录音下载协议 + Ogg 重建 + offset 语义 |
| 04 | [protocol-firmware-conclusions](docs/04-protocol-firmware-conclusions.md) | 密钥使用判定 + 固件能力清单 |
| 05 | [protocol-update-v2](docs/05-protocol-update-v2.md) | `0x0041` 之谜 + 命令表 v2 + `0x0545/0x5A` 错误码 |
| 06 | [firmware-deep-re](docs/06-firmware-deep-re.md) | 固件深度反编译（熵、启动、命令表、密码学）|
| 07 | [firmware-ota-capture](docs/07-firmware-ota-capture.md) | OTA 抓包与镜像重建（1.53 MB 主固件）|
| 08 | [firmware-analysis](docs/08-firmware-analysis.md) | 固件结构补充分析 |
| 09 | [comparison-anker-d3200](docs/09-comparison-anker-d3200.md) | 与安克 D3200（同为 BES）对比 |
| 10 | [web-bluetooth-feasibility](docs/10-web-bluetooth-feasibility.md) | 纯网页版可行性（Web Bluetooth）|
| 11 | [self-app-integration](docs/11-self-app-integration.md) | 自建 App 接入路径 |
| 13 | [wifi-transfer-analysis](docs/13-wifi-transfer-analysis.md) | **WiFi 快传链路**：MCU2WIFI SPI 桥 + SoftAP + wifi_iot 握手还原 |

---

## 设备信息

| 项 | 值 |
|---|---|
| 产品 | 得到 AI 录音卡 GetSeed |
| 型号 | GSC10 |
| SoC | 恒玄 BES best1306p（Cortex-M33 + TrustZone，BLE + WiFi）|
| 存储 | 64 GB（实测可用 ≈ 58.28 GB）|
| 录音格式 | Ogg Opus，单声道 16 kHz，设备端 FFmpeg（Lavf）编码 |
| 续航 | 连续录音 35 h / 待机 60 天（官方）|

## 环境要求

- Python 3.10+ 与 [`bleak`](https://github.com/hbldh/bleak)（Windows/macOS/Linux 均可）
- 浏览器方案：Chrome / Edge（**iOS 不支持** Web Bluetooth）
- 卡片需处于**可连接状态**：BLE 一次只能被一个主机占用，先让手机 App 断开（关手机蓝牙即可，**无需解绑**）

## 免责声明

本项目仅用于对**自己拥有或获授权管理的设备**做互操作性研究、数据自主导出与安全评估。
请遵守当地法律，不要用于读取他人设备。固件与 App 的知识产权归原厂所有，本仓库只包含
分析结论与自研工具，**不含**固件镜像、APK、录音样本或任何凭据。
