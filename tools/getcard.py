#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
getcard — 得到笔记卡片 · 电脑端直连工具

绕过官方 App，直接通过蓝牙读取卡片上的录音文件。
协议来自固件/抓包逆向：控制通道 0xA202/0xA205 为明文 fcfcfcfc 帧。

用法:
  python getcard.py scan                 扫描并列出附近卡片
  python getcard.py info                 设备信息(固件版本/SN/公钥)
  python getcard.py list                 列出卡片上的录音
  python getcard.py pull <文件名>         下载指定录音
  python getcard.py pull --all           下载全部录音
  python getcard.py pull --all --delete-after   下载后删除卡片原文件
  python getcard.py sync                 只下载新录音(增量)
  python getcard.py delete <文件名> --yes  ★删除卡片上的录音(不可恢复)
  python getcard.py delete --all --yes    ★逐个删除全部录音(危险)
  python getcard.py purge --yes           ☠️ 清理已传输文件(cmd 0x0041, App 每次连接都会发)
  python getcard.py watch                轮询等待新录音并自动下载

选项:
  --out DIR     保存目录 (默认 ~/GetCard)
  --wav         同时转成 WAV
  --json        输出 JSON (便于 agent 解析)
  --addr MAC    指定设备地址 (默认自动扫描 Get-*)
  --yes         delete/purge 时确认执行
  --delete-after  pull/sync 成功下载后删除卡片原文件

⚠️ 重要提示(实测结论)
  * 0x0044 delete  : body=文件名 → 永久删除该文件(设备回 01)
  * 0x0041 purge   : 无 body → 永久删除【所有已传输/已下载】的文件(设备回 01)
                     App 每次连上卡片第一件事就是发 0x0041，所以"被 App 同步过"的
                     录音会从卡片上消失 —— 这是官方设计，不是故障。
  * 列表为空(0x0043 len=0)是正常状态；App 自己也常常拿到空列表。
  * 判断文件是否还在：发 0x0145 下载 —— 不存在时设备回 0x0545 + 0x5a。
"""
import asyncio, argparse, json, os, struct, sys, time, zlib, wave
from datetime import datetime

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("缺少 bleak: pip install bleak", file=sys.stderr); sys.exit(1)

# ---- 协议常量 (逆向自抓包) ----
CH_CTL_W = "00009101-0000-1000-8000-57616c6b697a"
CH_CTL_N = "00009102-0000-1000-8000-57616c6b697a"
SVC_CTL  = "00009100-0000-1000-8000-57616c6b697a"
SVC_CMD  = "66666666-6666-6666-6666-666666666666"
SVC_DAT  = "00009000-0000-1000-8000-57616c6b697a"

C_TIME_SYNC = 0x0146
C_QUERY     = 0x0050
C_LIST      = 0x0043
C_DELETE    = 0x0044   # ★ 实测确认: body=文件名字符串 → 删除该文件, 设备回 01
C_PURGE     = 0x0041   # ☠️ 实测确认: 无 body → 清掉所有"已传输"文件, 设备回 01
C_STORAGE   = 0x0042   # 存储信息: 4B + 可用空间KB(0x03A47880≈58.3GB) + 4B
C_DEV_TIME  = 0x0046   # 设备当前时间 (14B ASCII, 形如 20261010161909)
C_MTU_RPT   = 0x0047   # MTU 上报: 00 01 00 <mtu:2B LE>  (0x01ef = 495)
C_DEV_UP    = 0x0140   # 设备上线通知(设备→主机)
C_DOWNLOAD  = 0x0145
C_FILE_INFO = 0x0245   # 4B 文件大小; 文件不存在时为 0
C_DATA      = 0x0345
C_DONE      = 0x0445   # 4B = 文件大小
C_ERR       = 0x0545   # 1B 错误码: 0x5a = 文件不存在 (本次新发现)
C_PROGRESS  = 0x0150
C_MTU       = 0x0147

ERR_NOT_FOUND = 0x5A


def ctrl_frame(cmd: int, body: bytes = b"") -> bytes:
    pkt = b"\xfc\xfc\xfc\xfc" + struct.pack("<H", cmd) + struct.pack("<H", len(body)) + body
    return pkt + struct.pack("<I", zlib.crc32(pkt) & 0xFFFFFFFF)


def parse_ctrl(v: bytes):
    if len(v) < 8 or v[:4] != b"\xfc\xfc\xfc\xfc":
        return None
    ln = struct.unpack("<H", v[6:8])[0]
    if len(v) < 8 + ln:
        return None
    return struct.unpack("<H", v[4:6])[0], v[8:8 + ln]


class CardSession:
    """一次与卡片的会话"""

    def __init__(self, addr=None, verbose=True):
        self.addr = addr
        self.verbose = verbose
        self.client = None
        self.device = None
        self.list_buf = None
        self.dl = None
        self.mtu = None
        self.notify_sizes = []
        self.other = []
        self.del_ack = None
        self.purge_ack = None
        self.dev_time = None
        self.storage = None
        self.err = None

    def _log(self, *a):
        if self.verbose:
            print(*a, file=sys.stderr, flush=True)

    # ---------- 连接 ----------
    async def connect(self, retries=4):
        if self.addr:
            dev = await BleakScanner.find_device_by_address(self.addr, timeout=20.0)
        else:
            dev = await BleakScanner.find_device_by_filter(
                lambda d, ad: (d.name or ad.local_name or "").startswith("Get-"), timeout=20.0)
        if not dev:
            raise RuntimeError("未找到卡片。请确认卡片已开机、且未被手机 App 占用。")
        self.device = dev
        self._log("[连接] %s (%s)" % (dev.name, dev.address))

        last = None
        for i in range(retries):
            try:
                cli = BleakClient(dev, timeout=40.0)
                await cli.connect()
                self.client = cli
                break
            except Exception as e:
                last = e
                self._log("[重试 %d] %s" % (i + 1, e))
                await asyncio.sleep(2.0)
        else:
            raise RuntimeError("连接失败: %s" % last)

        self._log("[连接] 成功 mtu=%d" % self.client.mtu_size)
        await self.client.start_notify(CH_CTL_N, self._on_notify)
        await asyncio.sleep(0.4)
        return self

    async def close(self):
        if self.client:
            try:
                await self.client.stop_notify(CH_CTL_N)
            except Exception:
                pass
            try:
                await self.client.disconnect()
            except Exception:
                pass

    # ---------- 收包 ----------
    def _on_notify(self, _s, data):
        v = bytes(data)
        self.notify_sizes.append(len(v))
        p = parse_ctrl(v)
        if not p:
            return
        cmd, body = p
        if cmd == C_LIST:
            self.list_buf = body.decode("utf-8", "replace")
        elif cmd == C_DATA and self.dl is not None:
            if len(body) >= 4:
                off = struct.unpack("<I", body[0:4])[0]
                self.dl["chunks"].append((off, body[4:]))
                self.dl["got"] = max(self.dl["got"], off)
                self.dl["n"] += 1
                if self.dl["n"] % 20 == 0:
                    self._log("    ... 已接收 %d / %d B" % (self.dl["got"], self.dl.get("size", 0)))
        elif cmd == C_FILE_INFO and self.dl is not None and len(body) >= 4:
            self.dl["size"] = struct.unpack("<I", body[0:4])[0]
            self._log("    文件大小: %d B" % self.dl["size"])
        elif cmd == C_DONE and self.dl is not None:
            self.dl["done"] = True
            if len(body) >= 4:
                self.dl["done_size"] = struct.unpack("<I", body[0:4])[0]
        elif cmd == C_ERR:
            self.err = body[:1]
            if body[:1] and body[0] == ERR_NOT_FOUND:
                self._log("    !! 设备返回错误: 文件不存在 (0x5a)")
        elif cmd == C_MTU and len(body) >= 5:
            self.mtu = struct.unpack("<H", body[3:5])[0]
            self._log("    设备上报 MTU = %d" % self.mtu)
        elif cmd == C_MTU_RPT and len(body) >= 5:
            self.mtu = struct.unpack("<H", body[3:5])[0]
            self._log("    设备上报 MTU = %d (0x0047)" % self.mtu)
        elif cmd == C_DEV_TIME:
            self.dev_time = body.decode("utf-8", "replace")
            self._log("    设备当前时间 = %s" % self.dev_time)
        elif cmd == C_STORAGE and len(body) >= 8:
            self.storage = {"raw": body.hex(),
                            "free_kb": struct.unpack("<I", body[4:8])[0]}
            self._log("    可用空间 ≈ %.2f GB" % (self.storage["free_kb"] / 1024 / 1024))
        elif cmd == C_DELETE:
            self.del_ack = body[:1]
        elif cmd == C_PURGE:
            self.purge_ack = body[:1]
        elif cmd in (C_TIME_SYNC, C_QUERY, C_PROGRESS, 0x0040):
            pass
        else:
            self.other.append((cmd, body))

    async def _send(self, cmd, body=b""):
        await self.client.write_gatt_char(CH_CTL_W, ctrl_frame(cmd, body), response=False)

    # ---------- 操作 ----------
    async def time_sync(self):
        ts = datetime.now().strftime("%Y%m%d%H%M%S").encode()
        await self._send(C_TIME_SYNC, ts)
        await asyncio.sleep(0.4)

    async def get_list(self, timeout=4.0):
        self.list_buf = None
        await self._send(C_QUERY, b"")
        await asyncio.sleep(0.3)
        await self._send(C_LIST, bytes.fromhex("0100000005000000"))
        t0 = time.time()
        while self.list_buf is None and time.time() - t0 < timeout:
            await asyncio.sleep(0.1)
        return self.parse_list(self.list_buf or "")

    @staticmethod
    def parse_list(txt):
        files = []
        for seg in (txt or "").split(";"):
            seg = seg.strip()
            if not seg:
                continue
            p = seg.split(",")
            if len(p) < 4:
                continue
            files.append({"index": p[0], "name": p[1], "time": p[2],
                          "size": int(p[3]) if p[3].isdigit() else 0})
        return files

    async def download(self, name, timeout_s=120):
        self.dl = {"chunks": [], "got": 0, "n": 0, "size": 0, "done": False}
        self.err = None
        nb = name.encode()
        await self._send(C_DOWNLOAD, b"\x00\x00\x00\x00" + nb)
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            await asyncio.sleep(0.15)
            d = self.dl
            if self.err is not None and not d["n"]:
                break                       # 设备明确报错且无数据 → 立即退出
            if d["done"]:
                break
            if d["size"] and d["got"] >= d["size"]:
                break
        await asyncio.sleep(0.5)
        d = self.dl
        if self.err == ERR_NOT_FOUND or (d["n"] == 0 and not d["size"]):
            raise RuntimeError("文件不存在 (设备回 0x0545/0x5a)：%s" % name)
        total = d["size"] or d["got"]
        if total <= 0:
            raise RuntimeError("未收到数据")
        buf = bytearray(total)
        for off, seg in d["chunks"]:
            st = max(0, off - len(seg))
            e = min(total, st + len(seg))
            buf[st:e] = seg[:e - st]
        return bytes(buf)

    async def delete(self, name, wait=3.0):
        """★ 删除卡片上的指定文件 (cmd 0x0044, 实测有效, 不可恢复)"""
        self.del_ack = None
        await self._send(C_DELETE, name.encode())
        t0 = time.time()
        while time.time() - t0 < wait and self.del_ack is None:
            await asyncio.sleep(0.1)
        return self.del_ack == b"\x01"

    async def purge(self, wait=3.0):
        """☠️ 清理已传输文件 (cmd 0x0041, 无 body)。

        实测：发送后列表立刻从 1 → 0，且再按文件名下载会返回
        0x0545/0x5a(文件不存在) —— 即【永久删除所有已下载过的文件】。
        App 每次连上卡片都会先发这条，所以被 App 同步过的录音会消失。
        """
        self.purge_ack = None
        await self._send(C_PURGE, b"")
        t0 = time.time()
        while time.time() - t0 < wait and self.purge_ack is None:
            await asyncio.sleep(0.1)
        return self.purge_ack == b"\x01"

    async def device_status(self, wait=2.5):
        """读取设备时间(0x0046) / MTU(0x0047) / 存储(0x0042)"""
        self.dev_time = None
        self.storage = None
        self.mtu = None
        for cmd, tag in ((C_DEV_TIME, "time"), (C_MTU_RPT, "mtu"), (C_STORAGE, "storage")):
            await self._send(cmd, b"")
            await asyncio.sleep(0.6)
        await asyncio.sleep(wait * 0.2)
        return {"device_time": self.dev_time, "mtu": self.mtu,
                "storage": self.storage}

    async def device_info(self):
        """从 0x8D/0x8F 拿固件版本与公钥 (需订阅另一条通道, 这里只做尽力采集)"""
        info = {"mtu": self.mtu}
        return info


# ---------- 工具 ----------
def ensure_dir(d):
    os.makedirs(d, exist_ok=True)
    return d


def load_state(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return {"downloaded": {}}


def save_state(path, st):
    json.dump(st, open(path, "w"), indent=1, ensure_ascii=False)


def ogg_to_wav(raw: bytes, out: str) -> bool:
    try:
        import av
    except ImportError:
        return False
    tmp = out + ".tmp.ogg"
    open(tmp, "wb").write(raw)
    try:
        inp = av.open(tmp)
        o = av.open(out, mode="w")
        ost = o.add_stream("pcm_s16le", rate=16000)
        ost.layout = "mono"
        res = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for fr in inp.decode(audio=0):
            for rf in res.resample(fr):
                for pk in ost.encode(rf):
                    o.mux(pk)
        for pk in ost.encode(None):
            o.mux(pk)
        o.close(); inp.close()
        return True
    except Exception as e:
        print("  ! WAV 转换失败: %s" % e, file=sys.stderr)
        return False
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def ogg_duration(raw: bytes):
    """从最后一个 Ogg 页的 granule 估算时长(Opus 48kHz)"""
    try:
        i, gp = 0, 0
        while i + 27 <= len(raw) and raw[i:i+4] == b"OggS":
            gp = struct.unpack("<q", raw[i+6:i+14])[0]
            nseg = raw[i+26]
            blen = sum(raw[i+27:i+27+nseg])
            i += 27 + nseg + blen
        return gp / 48000.0
    except Exception:
        return 0.0


# ---------- 子命令 ----------
async def cmd_scan(args):
    print("扫描中 (8s)...", file=sys.stderr)
    devs = await BleakScanner.discover(timeout=8.0, return_adv=True)
    rows = []
    for addr, (d, adv) in devs.items():
        n = d.name or adv.local_name or ""
        if n.startswith("Get-") or (args.addr and addr.upper() == args.addr.upper()):
            rows.append((addr, n, adv.rssi))
    if args.json:
        print(json.dumps([{"addr": a, "name": n, "rssi": r} for a, n, r in rows],
                         ensure_ascii=False, indent=1))
    else:
        if not rows:
            print("未发现 Get-* 卡片")
        for a, n, r in rows:
            print("  %-20s %-16s rssi=%d" % (a, n, r))
    return 0


async def cmd_info(args):
    s = await CardSession(args.addr).connect()
    try:
        await s.time_sync()
        st = await s.device_status()
        files = await s.get_list()
        out = {"addr": s.device.address, "name": s.device.name,
               "mtu": s.mtu or s.client.mtu_size,
               "client_mtu": s.client.mtu_size,
               "notify_max": max(s.notify_sizes) if s.notify_sizes else 0,
               "device_time": st.get("device_time"),
               "free_gb": round(st["storage"]["free_kb"] / 1024 / 1024, 2) if st.get("storage") else None,
               "files": len(files)}
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=1))
        else:
            lines = [
                "设备        : %s (%s)" % (out["name"], out["addr"]),
                "客户端 MTU  : %d" % out["client_mtu"],
                "设备上报 MTU: %s" % (out["mtu"] if out["mtu"] else "(无)"),
                "通知最大长度: %d B" % out["notify_max"],
                "设备时间    : %s" % (out["device_time"] or "(无)"),
                "可用空间    : %s" % (("%.2f GB" % out["free_gb"]) if out["free_gb"] else "(无)"),
                "录音数      : %d" % out["files"],
            ]
            print("\n".join(lines))
    finally:
        await s.close()
    return 0


async def do_list(s):
    await s.time_sync()
    return await s.get_list()


async def cmd_list(args):
    s = await CardSession(args.addr).connect()
    try:
        files = await do_list(s)
        if args.json:
            print(json.dumps(files, ensure_ascii=False, indent=1))
        else:
            if not files:
                print("卡片上没有待下载的录音。")
                print("  (列表为空是正常状态 —— App 每次连接会先发 0x0041 清掉已传输的文件)")
            for f in files:
                print("  %-34s  %s  %8d B" % (f["name"], f["time"], f["size"]))
        return 0
    finally:
        await s.close()


async def cmd_purge(args):
    if not args.yes:
        print("", file=sys.stderr)
        print("☠️  purge 会【永久删除卡片上所有已传输/已下载的录音】！", file=sys.stderr)
        print("    这是 App 每次连接卡片时自动执行的动作(cmd 0x0041)。", file=sys.stderr)
        print("    不可恢复，也没有回收站。确认请加 --yes", file=sys.stderr)
        return 2
    s = await CardSession(args.addr).connect()
    try:
        before = await do_list(s)
        print("清理前: %d 个文件" % len(before), file=sys.stderr)
        for f in before:
            print("   - %s (%d B)" % (f["name"], f["size"]), file=sys.stderr)
        ok = await s.purge()
        after = await do_list(s)
        print("设备回应: %s" % ("01 成功" if ok else "无/失败"), file=sys.stderr)
        print("清理后: %d 个文件" % len(after), file=sys.stderr)
        if args.json:
            print(json.dumps({"before": before, "after": after, "ack": bool(ok)},
                             ensure_ascii=False, indent=1))
        return 0
    finally:
        await s.close()


async def cmd_pull(args):
    outdir = ensure_dir(args.out)
    s = await CardSession(args.addr).connect()
    try:
        files = await do_list(s)
        if not files:
            print("卡片上没有录音"); return 0
        targets = files if args.all else [f for f in files if f["name"] == args.name]
        if not targets:
            print("未找到: %s" % args.name, file=sys.stderr); return 1
        if args.delete_after:
            print("[警告] 已启用 --delete-after：下载成功后会删除卡片上的原文件", file=sys.stderr)
        else:
            print("[只读] 仅下载，不会删除卡片上的任何文件", file=sys.stderr)
        results = []
        for f in targets:
            print("[下载] %s (%d B)" % (f["name"], f["size"]), file=sys.stderr)
            raw = await s.download(f["name"])
            ok = raw[:4] == b"OggS"
            fp = os.path.join(outdir, f["name"])
            open(fp, "wb").write(raw)
            dur = ogg_duration(raw)
            line = {"name": f["name"], "time": f["time"], "path": fp,
                    "bytes": len(raw), "ogg": ok, "duration": round(dur, 2)}
            if args.wav:
                wpath = os.path.join(outdir, os.path.splitext(f["name"])[0] + ".wav")
                line["wav"] = ogg_to_wav(raw, wpath) and wpath or None
            results.append(line)
            print("  -> %s  %dB  %.1fs  Ogg=%s" % (fp, len(raw), dur, ok), file=sys.stderr)
            if args.delete_after and ok:
                d = await s.delete(f["name"])
                print("  %s 卡片原文件" % ("✓ 已删除" if d else "✗ 删除失败"), file=sys.stderr)
                line["deleted_on_card"] = d
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0
    finally:
        await s.close()


async def cmd_sync(args):
    outdir = ensure_dir(args.out)
    stpath = os.path.join(outdir, ".getcard_state.json")
    st = load_state(stpath)
    s = await CardSession(args.addr).connect()
    try:
        files = await do_list(s)
        new = [f for f in files if f["name"] not in st["downloaded"]]
        if not new:
            print("没有新录音"); return 0
        print("发现 %d 个新录音" % len(new), file=sys.stderr)
        out = []
        for f in new:
            raw = await s.download(f["name"])
            fp = os.path.join(outdir, f["name"])
            open(fp, "wb").write(raw)
            if args.wav:
                ogg_to_wav(raw, os.path.join(outdir, os.path.splitext(f["name"])[0] + ".wav"))
            st["downloaded"][f["name"]] = {"time": f["time"], "bytes": len(raw),
                                           "at": datetime.now().isoformat(timespec="seconds")}
            out.append({"name": f["name"], "path": fp, "bytes": len(raw),
                        "duration": round(ogg_duration(raw), 2)})
            print("  -> %s" % f["name"], file=sys.stderr)
            if args.delete_after:
                d = await s.delete(f["name"])
                out[-1]["deleted_on_card"] = d
                print("  %s 卡片原文件" % ("✓ 已删除" if d else "✗ 删除失败"), file=sys.stderr)
        save_state(stpath, st)
        print(json.dumps(out, ensure_ascii=False, indent=1) if args.json
              else "已下载 %d 个文件到 %s" % (len(out), outdir))
        return 0
    finally:
        await s.close()


async def cmd_delete(args):
    if not args.yes:
        print("⚠️  删除不可恢复！确认请加 --yes", file=sys.stderr)
        return 2
    s = await CardSession(args.addr).connect()
    try:
        files = await do_list(s)
        if not files:
            print("卡片上没有录音"); return 0
        targets = files if args.all else [f for f in files if f["name"] == args.name]
        if not targets:
            print("未找到: %s" % args.name, file=sys.stderr); return 1
        out = []
        for f in targets:
            ok = await s.delete(f["name"])
            out.append({"name": f["name"], "deleted": ok})
            print("  %s  %s" % ("✓ 已删除" if ok else "✗ 失败", f["name"]), file=sys.stderr)
            await asyncio.sleep(0.4)
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        await s.close()


async def cmd_watch(args):
    print("轮询模式：每 %d 秒检查一次新录音 (Ctrl+C 退出)" % args.interval, file=sys.stderr)
    while True:
        try:
            rc = await cmd_sync(args)
        except Exception as e:
            print("  [%s] %s" % (datetime.now().strftime("%H:%M:%S"), e), file=sys.stderr)
        await asyncio.sleep(args.interval)


def main():
    ap = argparse.ArgumentParser(description="得到笔记卡片 · 电脑端直连工具",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("command", choices=["scan", "info", "list", "pull", "sync", "delete", "purge", "watch"])
    ap.add_argument("name", nargs="?", help="pull/delete 时的文件名")
    ap.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "GetCard"))
    ap.add_argument("--wav", action="store_true", help="同时转 WAV")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--addr", default=None, help="指定 MAC")
    ap.add_argument("--all", action="store_true", help="对全部文件操作")
    ap.add_argument("--interval", type=int, default=30, help="watch 轮询间隔秒")
    ap.add_argument("--yes", action="store_true", help="delete 时确认执行")
    ap.add_argument("--delete-after", action="store_true",
                    help="pull/sync 成功下载后删除卡片上的原文件")
    args = ap.parse_args()

    fn = {"scan": cmd_scan, "info": cmd_info, "list": cmd_list,
          "pull": cmd_pull, "sync": cmd_sync, "delete": cmd_delete,
          "purge": cmd_purge, "watch": cmd_watch}[args.command]
    try:
        rc = asyncio.run(fn(args))
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        print("错误: %s" % e, file=sys.stderr)
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
