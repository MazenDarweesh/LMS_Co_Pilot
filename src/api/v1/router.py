from fastapi import APIRouter
from src.models.schemas import (
    AudioTranscriptionRequest, AudioTranscriptionResponse,
    RAGQueryRequest, RAGQueryResponse
)
from src.services.audio_service import audio_service
from src.services.rag_service import rag_service

router = APIRouter(prefix="/v1", tags=["V1 API"])

@router.post("/transcribe", response_model=AudioTranscriptionResponse)
async def transcribe(request: AudioTranscriptionRequest):
    return await audio_service.transcribe_audio(request.file_path)

@router.post("/query-rag", response_model=RAGQueryResponse)
async def query_rag(request: RAGQueryRequest):
    return await rag_service.query_rag(request.query, request.limit)

        