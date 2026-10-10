#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcribe.py — 把录音卡的 Ogg 录音转成文字（可选生成摘要）

浏览器/蓝牙链路与本脚本解耦：先用 getcard.py 把 .ogg 拉到本地，再用本脚本调
硅基流动（FunAudioLLM/SenseVoiceSmall 转写 + Qwen/Qwen3-8B 摘要）。

Key 来源（按优先级）：
  1. --key 参数
  2. 环境变量 SILICONFLOW_API_KEY

依赖：仅 Python 标准库（urllib），无需安装第三方包。

用法:
  python transcribe.py 录音.ogg
  python transcribe.py 录音.ogg --summarize meeting
  python transcribe.py 录音.ogg --summarize custom --prompt "提炼成3条待办"
  python transcribe.py *.ogg --json          # shell 展开后逐个输出 JSON

模板: meeting=会议纪要  memo=闪念笔记  interview=访谈整理  custom=自定义  none=只转写
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

BASE = "https://api.siliconflow.cn/v1"
ASR_MODEL = "FunAudioLLM/SenseVoiceSmall"
LLM_MODEL = "Qwen/Qwen3-8B"
PROMPTS = {
    "meeting": "请生成结构化会议纪要，依次给出：一句话摘要、关键要点、明确结论、待办事项"
               "（负责人和截止时间仅在原文明确提及时填写）、待确认问题。不得虚构。",
    "memo": "请把口述内容整理成清晰笔记，依次给出：标题、核心想法、展开要点、下一步行动。"
            "删除口头语但不得增加原文没有的事实。",
    "interview": "请整理访谈内容，依次给出：主题摘要、受访者观点、重要原话、洞察、后续问题。不得虚构。",
}


def http_json(req, timeout=120):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode("utf-8"))
            msg = d.get("message") or (d.get("error") or {}).get("message") or d.get("error")
        except Exception:
            msg = None
        raise RuntimeError("硅基流动 HTTP %d：%s" % (e.code, msg or "请求失败")) from None
    except urllib.error.URLError as e:
        raise RuntimeError("网络错误：%s（检查代理/网络后重试）" % e.reason) from None


def transcribe(key, path, model=ASR_MODEL, timeout=180):
    size = os.path.getsize(path)
    if size > 50 * 1024 * 1024:
        raise RuntimeError("音频超过硅基流动 50 MB 上传限制")
    if size < 2048:
        raise RuntimeError("音频太小（%d B），大概率过短无法转写" % size)
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        audio = f.read()
    fname = os.path.basename(path)
    body = b"".join([
        ('--%s\r\nContent-Disposition: form-data; name="model"\r\n\r\n%s\r\n'
         % (boundary, model)).encode("utf-8"),
        ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
         'Content-Type: audio/ogg\r\n\r\n' % (boundary, fname)).encode("utf-8"),
        audio, b"\r\n",
        ("--%s--\r\n" % boundary).encode("utf-8"),
    ])
    req = urllib.request.Request(
        BASE + "/audio/transcriptions", data=body,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "multipart/form-data; boundary=" + boundary},
        method="POST")
    out = http_json(req, timeout=timeout)
    text = str(out.get("text") or "").strip()
    usage = (out.get("usage") or {}).get("seconds")
    if not text:
        raise RuntimeError("转写结果为空（录音可能过短或接近静音）")
    return {"text": text, "seconds": usage}


def summarize(key, transcript, template="meeting", custom="", model=LLM_MODEL):
    prompt = custom.strip() if (template == "custom" and custom.strip()) else PROMPTS.get(template)
    if not prompt:
        raise RuntimeError("未知模板: %s（可选 %s）" % (template, "/".join(PROMPTS)))
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是严谨的中文录音整理助手。只依据转录文本输出。"},
            {"role": "user", "content": "%s\n\n转录文本：\n%s" % (prompt, transcript)},
        ],
        "stream": False, "temperature": 0.2, "max_tokens": 2048,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/chat/completions", data=payload,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST")
    out = http_json(req)
    text = str(((out.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("摘要结果为空")
    return text


def main():
    ap = argparse.ArgumentParser(description="得到录音卡 · 硅基流动转写/摘要")
    ap.add_argument("files", nargs="+", help=".ogg 录音文件")
    ap.add_argument("--key", default=None, help="硅基流动 API Key（缺省读环境变量 SILICONFLOW_API_KEY）")
    ap.add_argument("--summarize", default="none",
                    choices=["none", "meeting", "memo", "interview", "custom"],
                    help="摘要模板（默认 none=只转写）")
    ap.add_argument("--prompt", default="", help="模板为 custom 时的自定义要求")
    ap.add_argument("--json", action="store_true", help="输出 JSON（便于 agent 解析）")
    args = ap.parse_args()

    key = (args.key or os.environ.get("SILICONFLOW_API_KEY") or "").strip()
    if not key:
        print("错误：缺少 API Key。用 --key 传入或设置环境变量 SILICONFLOW_API_KEY", file=sys.stderr)
        return 2

    results = []
    rc = 0
    for path in args.files:
        if not os.path.exists(path):
            print("错误：文件不存在 %s" % path, file=sys.stderr)
            rc = 1
            continue
        item = {"file": path}
        try:
            t = transcribe(key, path)
            item["transcript"] = t["text"]
            item["seconds"] = t["seconds"]
            if args.summarize != "none":
                item["summary"] = summarize(key, t["text"], args.summarize, args.prompt)
                item["template"] = args.summarize
        except Exception as e:
            item["error"] = str(e)
            rc = 1
        results.append(item)
        if args.json:
            print(json.dumps(item, ensure_ascii=False))
        else:
            if "error" in item:
                print("✗ %s\n  %s" % (path, item["error"]), file=sys.stderr)
                continue
            print("✓ %s" % path)
            print("  转录(%d 字): %s" % (len(item["transcript"]), item["transcript"]))
            if "summary" in item:
                print("  摘要:\n%s" % item["summary"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
