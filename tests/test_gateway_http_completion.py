"""Gateway HTTP completion must follow its own SSE, even with reordered raw logs."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
import app as web

ASYNC_CLIENT = httpx.AsyncClient


def chunk(text=None, finish=None):
    delta = {"content": text} if text is not None else {}
    return {"choices": [{"delta": delta, "finish_reason": finish}]}


def frame(payload):
    return ("data: " + (payload if isinstance(payload, str) else json.dumps(payload)) + "\n\n").encode()


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    for name, value in {
        "ENV_FILE": tmp_path / ".env", "SESSIONS_DIR": tmp_path / "sessions",
        "OPENCLAW_SESSIONS_DIR": tmp_path / "oc", "OUTPUTS_DIR": tmp_path / "outputs",
        "DEBUG_DIR": tmp_path / "debug", "SHARED_RAW_STREAM": tmp_path / "raw.jsonl",
        "_session_locks": {}, "_RUNNING_CHAT": {}, "_STOPPED_CHAT": set(), "_BG_TASKS": set(),
        "GatewayClient": None,
    }.items():
        monkeypatch.setattr(web, name, value)
    web.ENV_FILE.write_text("", encoding="utf-8")
    web.SHARED_RAW_STREAM.write_text("", encoding="utf-8")
    monkeypatch.setattr(web, "_chat_backend", lambda _: "openclaw")
    monkeypatch.setattr(web, "_harness_settings", lambda: {"runtime": "openclaw"})
    monkeypatch.setattr(web, "_chat_message", lambda req: req.message)
    monkeypatch.setattr(web, "_resolve_transport", lambda _: "http")
    monkeypatch.setattr(web, "_heal_openclaw_session", lambda _: None)
    monkeypatch.setattr(web, "_agent_thinking_level", lambda: "off")
    monkeypatch.setattr(web, "openclaw_base_cmd", lambda: ["must-not-spawn"])
    monkeypatch.setattr(web, "chat_completions_url", lambda: "http://localhost:50288/v1/chat/completions")
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, headers={"Origin": local}) as client:
        yield client


@pytest.mark.parametrize("finish,done,error,reordered,clean,note", [
    ("stop", True, False, True, True, ""),
    ("stop", True, False, False, True, ""),
    ("length", True, False, False, False, "被截断"),
    ("tool_use", True, False, False, False, "下一步操作时中断"),
    ("stop", False, False, False, False, "可能没写完"),
    (None, True, False, False, False, "可能没写完"),
    (None, False, False, False, False, "可能没写完"),
    ("stop", True, True, False, False, "可能没写完"),
])
def test_gateway_stream_end_and_recovery(gateway, monkeypatch, finish, done, error, reordered, clean, note):
    consumed = threading.Event()
    original = web._raw_event_for_run

    def observe(line, run_id):
        event = original(line, run_id)
        if event and event["event"] == ("assistant_text_stream" if reordered else "assistant_message_end"):
            consumed.set()
        return event

    monkeypatch.setattr(web, "_raw_event_for_run", observe)

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield frame(chunk("完整回答"))
            raw = [{"runId": "test-run", "event": "assistant_message_end"}]
            if reordered:
                raw.append({"runId": "test-run", "event": "assistant_text_stream",
                            "evtType": "text_delta", "delta": "完整回答"})
            web.SHARED_RAW_STREAM.write_text("".join(json.dumps(e) + "\n" for e in raw), encoding="utf-8")
            assert await asyncio.to_thread(consumed.wait, 2), "raw reader did not observe test events"
            if finish:
                yield frame(chunk(finish=finish))
            if error:
                yield frame({"error": {"message": "upstream interrupted"}})
            if done:
                yield frame("[DONE]")

    def respond(request):
        assert request.headers["x-openclaw-session-key"] == "agent:main:completion"
        return httpx.Response(200, stream=Stream())

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:
                        ASYNC_CLIENT(transport=httpx.MockTransport(respond), **kw))
    response = gateway.post("/api/chat/stream", json={
        "message": "probe", "sessionId": "completion", "turnId": "completion-turn",
    })
    assert response.status_code == 200 and "event: done" in response.text
    last = gateway.get("/api/chat/last/completion", params={"turn_id": "completion-turn"}).json()
    assert last["status"] == "done" and last["clean_end"] is clean
    assert last["stop_reason"] == finish
    assert last["text"].count("完整回答") == 1
    if clean:
        assert last["text"] == "完整回答" and "⚠️" not in response.text
    else:
        assert note in last["text"]
    assert ("event: error" in response.text) is error
    debug = json.loads((web.DEBUG_DIR / "chat-stream.jsonl").read_text().splitlines()[-1])
    assert debug["clean_end"] is clean
    assert debug["last_ev"] == ("assistant_text_stream" if reordered else "assistant_message_end")
    replay = gateway.get("/api/chat/jobs/completion-turn/stream").text
    assert ("event: error" if error else "event: done") in replay
