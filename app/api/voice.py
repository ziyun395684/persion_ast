import base64
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import db
from app.api.chat import ChatRequest, _run_chat, _schedule_retain
from app.models import User
from app.services import asr, tts
from app.services.auth import get_current_user

router = APIRouter(prefix="/voice", tags=["voice"])


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


async def _read_audio(audio: UploadFile) -> bytes:
    if audio.content_type and audio.content_type not in {
        "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/m4a"
    }:
        raise HTTPException(status_code=415, detail="unsupported audio format")
    if Path(audio.filename or "audio.wav").suffix.lower() not in {".wav", ".wave"}:
        raise HTTPException(status_code=415, detail="Doubao ASR currently requires 16kHz WAV audio")
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="没听清，再说一次好不好")
    return data


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    data = await _read_audio(audio)
    text = await asr.transcribe(data, audio.filename)
    if not text:
        raise HTTPException(status_code=400, detail="没听清，再说一次好不好")
    return {"text": text}


@router.post("/synthesize")
async def synthesize(
    request: SynthesizeRequest,
    user: User = Depends(get_current_user),
) -> Response:
    audio = await tts.synthesize(request.text)
    if not audio:
        raise HTTPException(status_code=503, detail="语音服务暂不可用，先看文字回复吧")
    return Response(content=audio, media_type="audio/wav")


@router.post("/chat")
async def voice_chat(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    data = await _read_audio(audio)
    user_text = await asr.transcribe(data, audio.filename)
    if not user_text:
        raise HTTPException(status_code=400, detail="没听清，再说一次好不好")
    request = ChatRequest(message=user_text)
    result = await _run_chat(request, session, user.id)
    _schedule_retain(background_tasks, request, result, user.id)
    reply_text = result.get("reply", "")
    audio_bytes = await tts.synthesize(reply_text)
    return {
        "user_text": user_text,
        "reply_text": reply_text,
        "audio_base64": base64.b64encode(audio_bytes).decode() if audio_bytes else "",
    }
