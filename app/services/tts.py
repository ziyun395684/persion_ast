"""Doubao streaming TTS adapter."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import wave

import websockets

from app.config import CFG

logger = logging.getLogger(__name__)


def _audio_payload(message: bytes) -> bytes:
    if not message or message[:1] in {b"{", b"["}:
        return b""
    header_size = (message[0] & 0x0F) * 4
    return message[header_size:] if header_size <= len(message) else b""


def _wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(CFG.voice_channels)
        target.setsampwidth(CFG.voice_bits // 8)
        target.setframerate(CFG.voice_sample_rate)
        target.writeframes(pcm)
    return output.getvalue()


async def synthesize(text: str) -> bytes:
    text = (text or "").strip()
    if not text or not CFG.volc_api_key or not CFG.volc_cluster or not CFG.volc_voice:
        return b""
    try:
        headers = {"Authorization": f"Bearer {CFG.volc_api_key}"}
        async with websockets.connect(
            CFG.tts_ws_url,
            additional_headers=headers,
            open_timeout=CFG.voice_timeout_sec,
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "appid": "",
                        "cluster": CFG.volc_cluster,
                        "token": CFG.volc_api_key,
                        "namespace": "TTS",
                        "request": {
                            "req_type": "stream",
                            "text": "",
                            "voice_type": CFG.volc_voice,
                            "audio_type": "pcm",
                            "speed": 1.0,
                        },
                    }
                )
            )
            await socket.send(
                json.dumps(
                    {
                        "cluster": CFG.volc_cluster,
                        "token": CFG.volc_api_key,
                        "namespace": "TTS",
                        "request": {"req_type": "stream", "text": text[: CFG.tts_max_chars]},
                    }
                )
            )
            await socket.send(
                json.dumps(
                    {
                        "cluster": CFG.volc_cluster,
                        "token": CFG.volc_api_key,
                        "namespace": "TTS",
                        "request": {"req_type": "finish"},
                    }
                )
            )
            chunks = []
            while True:
                try:
                    message = await asyncio.wait_for(socket.recv(), CFG.voice_timeout_sec)
                except asyncio.TimeoutError:
                    break
                except websockets.exceptions.ConnectionClosed:
                    break
                if isinstance(message, bytes):
                    payload = _audio_payload(message)
                    if payload:
                        chunks.append(payload)
                elif isinstance(message, str):
                    try:
                        data = json.loads(message)
                        if data.get("code", 0) not in (0, None):
                            raise RuntimeError("Doubao TTS returned an error")
                    except json.JSONDecodeError:
                        continue
            return _wav(b"".join(chunks)) if chunks else b""
    except Exception:
        logger.warning("Doubao TTS request failed", exc_info=True)
        return b""
