from pydantic import BaseModel, Field

class AudioTranscriptionRequest(BaseModel):
    file_path: str = Field(..., description="المسار المحلي لملف الصوت")

class AudioTranscriptionResponse(BaseModel):
    text: str = Field(..., description="النص المفرغ")
    duration: float = Field(..., description="مدة الملف بالثواني")

class RAGQueryRequest(BaseModel):
    query: str = Field(..., description="سؤال المستخدم للـ RAG")
    limit: int = Field(5, description="عدد النتائج المسترجعة")

class RAGQueryResponse(BaseModel):
    answer: str = Field(..., description="الإجابة المعززة بالـ AI")
    sources: list[str] = Field(..., description="المصادر المستخدمة")