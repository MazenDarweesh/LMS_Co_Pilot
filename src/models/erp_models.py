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


ErpIntent = Literal["question", "navigate", "action", "unknown"]


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
    intent: ErpIntent = Field(
        default="unknown",
        description="نية المستخدم كما حددها الذكاء الاصطناعي: سؤال معرفي / تنقل / إجراء إدخال بيانات"
    )
    source: Literal["ai", "memory", "lexical"] = Field(
        default="ai",
        description="مصدر القرار: الذكاء الاصطناعي، ذاكرة القرارات المؤكدة، أو المطابقة المعجمية الاحتياطية"
    )
    decision_id: str | None = Field(
        default=None,
        description="معرف سجل القرار لإرسال التغذية الراجعة (applied/rejected) لاحقاً"
    )


class ControlIn(BaseModel):
    """زر أو عنصر تحكم ظاهر في شاشة الـ ERP"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(..., description="معرف العنصر الفريد داخل الصفحة")
    label: str = Field(..., min_length=1, max_length=120, description="النص الظاهر على الزر")


class ControlRolesRequest(BaseModel):
    """طلب تحديد أدوار الأزرار (إضافة سطر / مستند جديد) في شاشة محددة"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    screen_id: str = Field(..., min_length=1, max_length=128, description="كود الشاشة النشطة")
    controls: list[ControlIn] = Field(..., min_length=1, max_length=80, description="الأزرار الظاهرة في الشاشة")


class ControlRolesResponse(BaseModel):
    """أدوار الأزرار كما حددها الذكاء الاصطناعي (معرفات من المدخلات فقط)"""
    roles: dict[str, str] = Field(
        default_factory=dict,
        description="خريطة الدور إلى معرف الزر: add_row / new_form"
    )
    source: Literal["ai", "memory"] = Field(default="ai")


class NavFeedbackRequest(BaseModel):
    """تغذية راجعة على قرار ملاحة لتأكيده (applied) أو إلغائه (rejected)"""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    decision_id: str = Field(..., min_length=8, max_length=64)
    outcome: Literal["applied", "rejected"]


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
