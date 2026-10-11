from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class NavCandidateIn(BaseModel):
    """مرشح شاشة في نظام الـ ERP"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(..., description="معرف الشاشة أو العنصر الفريد")
    label: str = Field(..., min_length=1, description="اسم الشاشة المعروض للمستخدم")
    path: list[str] = Field(default_factory=list, description="المسار الهرمي في القوائم")


class NavRequest(BaseModel):
    """طلب تحديد وجهة الملاحة في الـ ERP"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    user_message: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="رسالة أو طلب المستخدم للتنقل"
    )
    candidates: list[NavCandidateIn] = Field(
        ...,
        min_length=1,
        max_length=60,
        description="قائمة الشاشات المرشحة المعروضة حالياً"
    )
    current_path: list[str] = Field(
        default_factory=list,
        description="المسار الحالي الذي يقف عليه المستخدم"
    )


class NavScored(BaseModel):
    """مرشح شاشة بعد تقييم ملاءمته ونسبة الثقة"""
    id: str = Field(..., description="معرف الشاشة")
    confidence: float = Field(..., ge=0.0, le=1.0, description="درجة الملاءمة بين 0 و 1")
    reason: str = Field(..., description="سبب اختيار أو ترجيح هذه الشاشة")


class NavResolution(BaseModel):
    """قرار الملاحة النهائي"""
    decision: Literal["go", "ask", "clarify"] = Field(
        ...,
        description="قرار الملاحة: go للانتقال المباشر، ask للتخيير، clarify لطلب توضيح"
    )
    candidates: list[NavScored] = Field(
        default_factory=list,
        description="أعلى المرشحين (بحد أقصى 3) مرتبين تنازلياً"
    )


class FieldSignatureIn(BaseModel):
    """توصيف حقل ظهر حديثاً في شاشة الـ ERP"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    key: str = Field(..., description="المفتاح التقني للحقل")
    label: str = Field(..., description="الاسم المعروض للحقل بالعربية أو الإنجليزية")
    kind: str = Field(default="text", description="نوع الحقل (text, ng-select, number, date, checkbox)")
    disabled: bool = Field(default=False, description="هل الحقل معطل للقراءة فقط")
    options: list[str] | None = Field(default=None, description="الخيارات المتاحة إذا كان الحقل قائمة اختيار")


class LeftoverRequest(BaseModel):
    """طلب تعبئة الحقول الجديدة التي ظهرت ديناميكياً"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    user_message: str = Field(default="", max_length=500, description="رسالة المستخدم الأصلية")
    extracted_data: dict[str, Any] = Field(
        default_factory=dict,
        description="البيانات المستخرجة من الذكاء الاصطناعي سابقاً"
    )
    filled: dict[str, Any] = Field(
        default_factory=dict,
        description="الحقول التي تمت تعبئتها بالفعل في الشاشة"
    )
    new_fields: list[FieldSignatureIn] = Field(
        ...,
        max_length=40,
        description="قائمة الحقول الجديدة المطلوب ملؤها"
    )


class LeftoverResponse(BaseModel):
    """استجابة تعبئة الحقول المتبقية"""
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="الحقول التي تم استنتاج وتأكيد قيمها"
    )
    ask_user: list[str] = Field(
        default_factory=list,
        description="الحقول التي تحتاج سؤال وتأكيد المستخدم لعدم وضوح قيمتها أو عدم مطابقة الخيارات"
    )
