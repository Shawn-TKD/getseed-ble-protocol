---
name: getcard
description: Connect to a 得到 AI 录音卡 (GetSeed / GSC10, broadcasts as "Get-XXXXXX") over Bluetooth directly from the computer to list, download, transcribe and manage recordings — without the official app, account, or any keys. This skill should be used when the user asks to 拉取/读取/下载/转写/删除 Get笔记或得到录音卡上的录音, check what is on the card, or set up automatic pull of new recordings. Audio is plain Ogg Opus over a cleartext GATT channel; no pairing, binding, or encryption keys are involved.
agent_created: true
---

# Get 卡片直读（得到 AI 录音卡 GetSeed）

通过蓝牙让 Agent 直接操作得到 AI 录音卡：列出录音 → 下载 → 转写 →（可选）删除。
协议逆向细节见 `references/protocol.md`；本文件只写操作流程。

## 前置条件

1. **Python 3.10+** 与 `bleak`：`pip install bleak`（转 WAV 另需 `pip install av`）
2. **卡片可被连接**：BLE 一次只能被一个主机占用
   - 若 `scan` 找不到卡片 → 让用户**关闭手机蓝牙**（或退出得到笔记 App），再按一下卡片按键唤醒
   - 卡片空闲约 3 小时会自动休眠，同样需要按键唤醒
   - **无需解绑**：解绑是云端账号操作，与蓝牙连接无关
3. 转写需要硅基流动 Key：环境变量 `SILICONFLOW_API_KEY`（或 `--key` 参数）

## 核心工具

- `scripts/getcard.py` — 蓝牙操作（扫描/列表/下载/删除/轮询）
- `scripts/transcribe.py` — 硅基流动转写 + 摘要（仅标准库，无额外依赖）

以下用 `PY` 指代本机 Python 3.10+ 解释器，`SKILL_DIR` 指代本技能目录。

## 工作流

### 1. 确认卡片在线

```bash
"$PY" "$SKILL_DIR/scripts/getcard.py" scan
```

输出 `DC:xx Get-XXXXXX rssi=…` 即在线。**找不到时不要盲目重试**：按"前置条件"第 2 条
排查（手机占用 → 关手机蓝牙；休眠 → 按键唤醒；充电中插拔可唤醒）。

### 2. 列出录音

```bash
"$PY" "$SKILL_DIR/scripts/getcard.py" list --json
```

返回 `[{index, name, time, size}]`。**列表为空是正常状态**：官方 App 每次连接会先发
`0x0041` 清掉已同步文件（App 自己 9 次请求里 7 次也拿到空列表）。向用户说明即可，
不要当作故障反复重试。

### 3. 下载录音（默认只读）

```bash
"$PY" "$SKILL_DIR/scripts/getcard.py" pull --all --wav --out <目录> --json
```

- 输出 JSON 含 `name / time / path / bytes / duration / wav`；`duration` 单位秒
- **默认不删除卡片上的文件**（会打印 `[只读]`）
- 建议下载后校验：`bytes` 与列表 `size` 一致、`ogg` 为 true

### 4. 转写 / 摘要

```bash
SILICONFLOW_API_KEY=sk-xxx "$PY" "$SKILL_DIR/scripts/transcribe.py" <录音.ogg> --json
# 带摘要：--summarize meeting|memo|interview|custom --prompt "自定义要求"
```

- 转写模型 `FunAudioLLM/SenseVoiceSmall`；摘要 `Qwen/Qwen3-8B`
- **<1 秒的录音会返回空文本**（"转写结果为空"）——向用户说明录音太短，不要重试
- Key 无效时报 `Token is invalid.`；让用户检查 Key
- 音频由本机直接上传到 api.siliconflow.cn，不经过任何中转

### 5. 持续同步（可选）

```bash
"$PY" "$SKILL_DIR/scripts/getcard.py" watch --interval 30 --out <目录> --json
```

长任务，用后台方式运行；有新录音即下载。

## 安全规则（必须遵守）

- **只读优先**：默认只用 `scan / info / list / pull / sync / watch`，绝不主动删除
- **`purge` 与 `delete` 是永久删除**（设备无回收站）：仅当用户在**当前对话中明确要求**
  删除某条录音时才执行 `delete <名> --yes`；`purge` 仅当用户明确说"清空/清理卡片"时使用
- `--delete-after` 只在用户要求"下载后删原件/移动"时加
- **不要在用户录音前抢连卡片**：录音动作本身不需要连接；录完再拉取即可
- 手机 App 会"同步后删除"录音 —— 若用户想用 Agent 存档，提醒其先关手机蓝牙

## 故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| scan 找不到卡片 | 被手机 App 占用（不广播）| 关手机蓝牙 / 退出 App |
| scan 找不到卡片 | 卡片休眠或没电 | 按一下按键唤醒；或插电 |
| 连接后立刻断开 | 有其他主机在抢 | 关掉手机蓝牙，重试（工具有 4 次重试）|
| `WinError` 连接失败 | Windows 蓝牙栈缓存 | 等几秒重试（工具自带重试）|
| 列表为空 | 正常状态 / 被 App 清空 | 见上，向用户说明 |
| 下载缺字节 | MTU 或干扰 | 重跑一次 `pull` |
| 转写为空 | 录音 <1 秒 | 告知用户，无需重试 |
| 转写 `Token is invalid.` | Key 错误 | 让用户检查 Key |

## 深入参考

需要理解协议细节（命令码、帧格式、CRC、GATT 服务、固件命令表）时再读
`references/protocol.md`；日常操作不需要加载它。
