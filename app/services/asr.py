"""Doubao streaming ASR adapter."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import wave
from pathlib import Path

import websockets

from app.config import CFG

logger = logging.getLogger(__name__)


def _pcm_payload(audio_bytes: bytes, filename: str | None) -> bytes:
    if (Path(filename or "").suffix or ".wav").lower() in {".wav", ".wave"}:
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as source:
                if (
                    source.getnchannels() != CFG.voice_channels
                    or source.getsampwidth() != CFG.voice_bits // 8
                    or source.getframerate() != CFG.voice_sample_rate
                ):
                    raise ValueError("audio must be 16kHz 16-bit mono PCM")
                return source.readframes(source.getnframes())
        except (wave.Error, EOFError, ValueError) as exc:
            raise ValueError("invalid WAV audio or unsupported audio format") from exc
    return audio_bytes


async def transcribe(audio_bytes: bytes, filename: str | None = None) -> str:
    if not audio_bytes or not CFG.volc_api_key or not CFG.volc_cluster:
        return ""
    try:
        pcm = _pcm_payload(audio_bytes, filename)
        headers = {"Authorization": f"Bearer {CFG.volc_api_key}"}
        async with websockets.connect(
            CFG.asr_ws_url,
            additional_headers=headers,
            open_timeout=CFG.voice_timeout_sec,
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "app": {"token": CFG.volc_api_key, "cluster": CFG.volc_cluster},
                        "user": {"uid": "persion-ast"},
                        "audio": {
                            "rate": CFG.voice_sample_rate,
                            "bits": CFG.voice_bits,
                            "channel": CFG.voice_channels,
                        },
                        "request": {"enable_itn": True, "enable_punc": True},
                    }
                )
            )
            chunk_bytes = CFG.voice_sample_rate // 5 * (CFG.voice_bits // 8) * CFG.voice_channels
            for index in range(0, len(pcm), chunk_bytes):
                await socket.send(
                    json.dumps(
                        {
                            "app": {},
                            "user": {},
                            "audio": {"data": base64.b64encode(pcm[index : index + chunk_bytes]).decode()},
                        }
                    )
                )
            partial = ""
            while True:
                message = await asyncio.wait_for(socket.recv(), CFG.voice_timeout_sec)
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                result = json.loads(message).get("result", {})
                text = result.get("text", "")
                if text:
                    partial = text
                if result.get("is_final"):
                    return partial.strip()
    except Exception:
        logger.warning("Doubao ASR request failed", exc_info=True)
        return ""
