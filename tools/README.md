# getcard.py — 得到 AI 录音卡 · 电脑端直连工具

绕过官方 App，通过蓝牙直接列出 / 下载 / 管理卡片上的录音。
协议见仓库根目录 [PROTOCOL.md](../PROTOCOL.md)。

```bash
pip install bleak
```

## 命令

| 命令 | 作用 |
|---|---|
| `scan` | 扫描附近的 `Get-*` 卡片 |
| `info` | 设备信息：名称 / MTU / 设备时间 / 可用空间 / 录音数 |
| `list` | 列出录音（`--json` 便于程序解析）|
| `pull <名>` | 下载指定录音 |
| `pull --all` | 下载全部（默认**只读**，不删卡片文件）|
| `pull --all --wav` | 同时转 WAV（需要 `pip install av`）|
| `pull --all --delete-after` | 下载成功后删除卡片原件（⚠️ 不可恢复）|
| `sync` | 增量下载新录音（状态存 `--out` 目录）|
| `watch` | 每 N 秒轮询，发现新录音自动下载 |
| `delete <名> --yes` | ☠️ 删除指定录音 |
| `purge --yes` | ☠️ 清理所有"已传输"的录音（即官方 App 连接时自动做的事）|

## Agent 集成

```bash
python getcard.py sync --json          # 输出 JSON，供自动化解析
python getcard.py list --json
```

## 安全默认值

- `pull` / `sync` **只读**：不会删除卡片上的任何文件
- `delete` / `purge` 必须显式 `--yes`
- 不要在自动化流程里调用 `purge` —— 它等于官方 App 的"同步后清空"

## 示例：录音 → 转文字

```bash
python getcard.py pull --all --wav --out ~/GetCard
# 然后把 ~/GetCard/*.ogg 交给任意语音转写服务
```
