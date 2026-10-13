"""阿里云 Flash ASR：本地音频上传、长音频分段和真实字幕时间戳。"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _sentence_cues(sentence: dict, offset: float, max_chars: int) -> list[tuple[float, float, str]]:
    words = sentence.get("words") or []
    if not words:
        text = str(sentence.get("text") or "").strip()
        end = sentence.get("end_time")
        if not text or end is None:
            return []
        return [(offset + sentence.get("begin_time", 0) / 1000, offset + end / 1000, text)]
    cues = []
    text = ""
    start = None
    end = 0.0
    for word in words:
        if word.get("end_time") is None or word.get("begin_time") is None:
            continue
        if start is None:
            start = offset + word["begin_time"] / 1000
        text += str(word.get("text") or "") + str(word.get("punctuation") or "")
        end = offset + word["end_time"] / 1000
        if text.rstrip().endswith(tuple("。！？.!?")) or len(text) >= max_chars * 2:
            if text.strip():
                cues.append((start, end, text.strip()))
            start, text = None, ""
    if start is not None and text.strip():
        cues.append((start, end, text.strip()))
    return cues


def _request(url: str, key: str, payload: dict) -> list[dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json",
                                          "X-DashScope-SSE": "enable"})
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = response.read().decode("utf-8")
            if "text/event-stream" in response.headers.get("Content-Type", ""):
                return [json.loads(line[5:].strip()) for line in raw.splitlines()
                        if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]")]
            return [json.loads(raw)]
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:350]
        raise RuntimeError(f"阿里云转写 HTTP {error.code}：{detail}") from error


def transcribe(audio: Path, env: dict[str, str], args: Any) -> tuple[list, dict]:
    key = env.get("DASHSCOPE_API_KEY") or env.get("DASHSCOPE_KEY") or env.get("ALIYUN_API_KEY")
    if not key:
        raise RuntimeError("阿里云转写需要 DASHSCOPE_API_KEY。")
    base = (env.get("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
    if not base.endswith("/api/v1"):
        base += "/api/v1"
    model = getattr(args, "model", None) or env.get("DASHSCOPE_ASR_MODEL") or "qwen-audio-3.0-asr-flash"
    max_chars = getattr(args, "max_line_chars", 18)
    cues = []
    duration = 0.0
    # 每段四分钟、16k 单声道 WAV，保持在 Flash 的五分钟输入限制内。
    with tempfile.TemporaryDirectory(prefix="easel-aliyun-asr-") as folder:
        import wave
        output = str(Path(folder) / "part-%05d.wav")
        proc = subprocess.run(["ffmpeg", "-y", "-i", str(audio), "-vn", "-ac", "1",
                               "-ar", "16000", "-c:a", "pcm_s16le", "-f", "segment",
                               "-segment_time", "240", "-reset_timestamps", "1", output],
                              capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError("转写音频预处理失败：" + proc.stderr[-250:])
        chunks = sorted(Path(folder).glob("part-*.wav"))
        if not chunks:
            raise RuntimeError("未提取到可转写的音频。")
        for chunk in chunks:
            with wave.open(str(chunk)) as wav:
                chunk_duration = wav.getnframes() / wav.getframerate()
            data = "data:audio/wav;base64," + base64.b64encode(chunk.read_bytes()).decode()
            params: dict = {"format": "wav", "sample_rate": "16000"}
            if getattr(args, "language", "auto") not in (None, "", "auto"):
                params["language_hints"] = [args.language]
            payload = {"model": model, "input": {"messages": [{"role": "user", "content": [
                {"type": "input_audio", "input_audio": {"data": data}}]}]}, "parameters": params}
            sentences = {}
            had_text = False
            for event in _request(base + "/services/aigc/multimodal-generation/generation", key, payload):
                if event.get("code"):
                    raise RuntimeError(f"阿里云转写失败：{event.get('code')} {event.get('message', '')}")
                result = event.get("output") or {}
                had_text = had_text or bool(result.get("text"))
                items = result.get("sentences") or [result.get("sentence") or {}]
                for sentence in items:
                    if sentence.get("sentence_end") and sentence.get("end_time") is not None:
                        sentences[sentence.get("sentence_id", 0)] = sentence
            if had_text and not sentences:
                raise RuntimeError("转写返回文本却缺少字幕时间戳，请使用 Flash ASR 模型。")
            for _, sentence in sorted(sentences.items()):
                cues.extend(_sentence_cues(sentence, duration, max_chars))
            duration += chunk_duration
    return cues, {"source": str(audio), "provider": "dashscope", "model": model,
                  "language": getattr(args, "language", "auto"),
                  "duration_sec": round(duration, 3), "num_segments": len(cues)}
