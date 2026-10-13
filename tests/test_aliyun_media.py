"""阿里云协议回归：图片编辑、视频尺寸、同步音乐、TTS 和分段字幕。"""
from __future__ import annotations

import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/shared/scripts"))

import ai_image
import ai_music
import ai_video
import aliyun_asr
import voice_clone

BASE = "https://workspace.cn-beijing.maas.aliyuncs.com"


def test_image_model_never_falls_back_to_chat_model(monkeypatch):
    for name in ("IMG_MODEL", "OPENAI_IMAGE_MODEL", "IMAGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "qwen3.7-plus")
    assert ai_image.resolve_config("IMG_MODEL") == ("", None)


def test_aliyun_image_edit_uses_generation_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("IMG_BASE_URL", BASE + "/compatible-mode/v1")
    monkeypatch.setenv("IMG_MODEL", "qwen-image-3.0")
    monkeypatch.setenv("IMG_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(ai_image, "encode_image_data_uri", lambda _: "data:image/png;base64,aA==")
    monkeypatch.setattr(ai_image, "http_post", lambda u, k, p, **kw: calls.append((u, p)) or {})
    monkeypatch.setattr(ai_image, "save_sync_data", lambda *a: [])
    args = ai_image.parse_args(["img2img", "--prompt", "改成蓝色", "--image", "input.png",
                                "-o", str(tmp_path / "out.png")])
    ai_image.cmd_img2img(args)
    assert calls[0][0].endswith("/images/generations")
    assert calls[0][1]["image"].startswith("data:image/png;")
    args.mask = "mask.png"
    with pytest.raises(SystemExit):
        ai_image.cmd_img2img(args)
    assert len(calls) == 1


def test_video_uses_pixels_and_correct_i2v_model(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", BASE + "/api/v1")
    monkeypatch.setenv("DASHSCOPE_VIDEO_MODEL", "wan2.6-t2v")
    monkeypatch.delenv("DASHSCOPE_I2V_MODEL", raising=False)
    assert ai_video.resolve_model("dashscope", image=True) == "wan2.6-i2v"
    calls = []
    monkeypatch.setattr(ai_video, "http_request", lambda u, h, **kw:
                        calls.append((u, kw["payload"])) or {"output": {"task_id": "id"}})
    monkeypatch.setattr(ai_video, "_poll", lambda *a: {"video_url": "https://example.test/video.mp4"})
    monkeypatch.setattr(ai_video, "download_video", lambda u, p: p)
    args = SimpleNamespace(model=None, ratio="9:16", duration=5, prompt="cat", audio=None,
                           poll_interval=1, timeout=10, output=str(tmp_path / "out.mp4"))
    ai_video.generate_dashscope(args, None)
    assert calls[0][0].endswith("/services/aigc/video-generation/video-synthesis")
    assert calls[0][1]["parameters"]["size"] == "720*1280"


def test_fun_music_accepts_sync_audio_response(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", BASE + "/api/v1")
    calls = []
    def post(url, headers, payload, **kwargs):
        calls.append((url, headers, payload))
        return {"output": {"audio": {"url": "https://example.test/music.mp3"}}}
    monkeypatch.setattr(ai_music, "http_post", post)
    monkeypatch.setattr(ai_music, "download_audio", lambda u, p: p)
    args = SimpleNamespace(model="fun-music-v1", prompt="轻快钢琴", lyrics=None, duration=10,
                           instrumental=True, timeout=30, output=str(tmp_path / "music.mp3"))
    ai_music.generate_dashscope(args)
    url, headers, payload = calls[0]
    assert url.endswith("/services/audio/music/generation")
    assert "X-DashScope-Async" not in headers
    assert payload["input"]["is_instrumental"] is True


def test_qwen_music_uses_audio_generator_with_requested_format(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", BASE + "/api/v1")
    calls = []
    monkeypatch.setattr(ai_music, "http_post", lambda u, h, p, **kw:
                        calls.append((u, p)) or {"output": {"audio": {"url": "https://example.test/music.mp3"}}})
    monkeypatch.setattr(ai_music, "download_audio", lambda u, p: p)
    args = SimpleNamespace(model="qwen-audio-3.1-tts-next", prompt="钢琴", lyrics=None, duration=5,
                           instrumental=True, timeout=30, output=str(tmp_path / "music.mp3"))
    ai_music.generate_dashscope(args)
    assert calls[0][0].endswith("/services/audio/tts/SpeechSynthesizer")
    assert calls[0][1]["input"]["format"] == "mp3"
    assert "纯音乐" in calls[0][1]["input"]["text_prompt"]


def test_qwen_tts_uses_preset_voice_and_single_api_prefix(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", BASE + "/api/v1")
    monkeypatch.setenv("DASHSCOPE_TTS_MODEL", "qwen3-tts-flash")
    monkeypatch.setenv("VOICE_NARRATOR_VOICE_ID", "Cherry")
    calls = []
    monkeypatch.setattr(voice_clone, "http_json", lambda u, h, p:
                        calls.append((u, p)) or {"output": {"audio": {"url": "https://example.test/voice.wav"}}})
    monkeypatch.setattr(voice_clone, "download", lambda u, p: p)
    voice_clone.clone_dashscope(SimpleNamespace(model=None, voice_id=None, text="你好", emotion=None),
                               tmp_path / "voice.wav")
    assert calls[0][0] == BASE + "/api/v1/services/aigc/multimodal-generation/generation"
    assert calls[0][1]["input"]["voice"] == "Cherry"


def test_asr_keeps_sentence_offsets_across_chunks(monkeypatch, tmp_path):
    def segment(command, **kwargs):
        for i in range(2):
            with wave.open(command[-1].replace("%05d", f"{i:05d}"), "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * 16000)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(aliyun_asr.subprocess, "run", segment)
    events = [{"output": {"text": "正在识别"}}, {"output": {"text": "你好。", "sentence": {
        "sentence_id": 1, "sentence_end": True, "begin_time": 100, "end_time": 900,
        "text": "你好。", "words": [{"begin_time": 100, "end_time": 900, "text": "你好", "punctuation": "。"}]}}}]
    monkeypatch.setattr(aliyun_asr, "_request", lambda *a: events)
    cues, meta = aliyun_asr.transcribe(tmp_path / "input.wav", {"DASHSCOPE_API_KEY": "test-key"},
                                      SimpleNamespace(model=None, language="zh", max_line_chars=18))
    assert cues == [(0.1, 0.9, "你好。"), (1.1, 1.9, "你好。")]
    assert meta["duration_sec"] == 2.0


def test_aliyun_asr_settings_are_visible_and_saveable(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("aliyun_settings_test", ROOT / "web/app.py")
    web = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = web
    spec.loader.exec_module(web)
    env = tmp_path / ".env"
    env.write_text("ASR_PROVIDER=dashscope\nDASHSCOPE_API_KEY=test-key\n"
                   "DASHSCOPE_ASR_MODEL=qwen-audio-3.0-asr-flash\n"
                   f"DASHSCOPE_BASE_URL={BASE}/api/v1\n")
    monkeypatch.setattr(web, "ENV_FILE", env)
    row = web._model_channels()["channels"]["transcribe"]["rows"][1]
    assert row["name"] == "阿里千问语音识别"
    assert row["role"] == "主"
    import asyncio
    asyncio.run(web.api_settings_models_save(web.ModelSaveRequest(channel="transcribe", rows=[
        web.ModelSaveRow(slot="dashscope", model="fun-asr-flash-2026-06-15", primary=True)])))
    assert "DASHSCOPE_ASR_MODEL=fun-asr-flash-2026-06-15" in env.read_text()
