from pydantic import BaseModel, Field, ConfigDict, AliasChoices, field_validator

# 1. Token Claims (Data extracted directly from the decoded JWT)
# Using AliasChoices to support standard .NET Identity claims, sub, and PascalCase/camelCase.
class TokenClaims(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    
    user_id: str = Field(validation_alias=AliasChoices("Id", "id", "sub", "nameid", "userId", "uid"))
    role: str = Field(default="Student", validation_alias=AliasChoices("Role", "role", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"))
    company_id: str = Field(default="default", validation_alias=AliasChoices("CompanyId", "companyId", "company_id", "tenant_id", "TenantId", "tenant", "Tenant", "company", "Company"))
    department_id: str | None = Field(default=None, validation_alias=AliasChoices("DepartmentId", "departmentId", "department_id"))

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, v: str | list[str]) -> str:
        if isinstance(v, list):
            return v[0] if v else "Student"
        return str(v)

    @property
    def sub(self) -> str:
        return self.user_id

# 2. Nested Module Permissions (Level & Type Filters)
# Maps to the .NET LMS internal API JSON response
class AccessibleModule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    module_id: str = Field(alias="moduleId")
    level_filters: list[str] = Field(default_factory=list, alias="levelFilters")
    type_filters: list[str] = Field(default_factory=list, alias="typeFilters")

# 3. User Permissions (Aggregated LMS Permissions)
# YAGNI: Excluded Standalone & Playlist lists as they are resolved via the Admin role currently.
class UserPermissions(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId")
    accessible_modules: list[AccessibleModule] = Field(default_factory=list, alias="accessibleModules")
    accessible_unit_ids: list[str] = Field(default_factory=list, alias="accessibleUnitIds")
    accessible_lesson_ids: list[str] = Field(default_factory=list, alias="accessibleLessonIds")

# 4. The Final User Context 
# Passed around within FastAPI requests after Auth completes
class UserContext(BaseModel):
    claims: TokenClaims
    permissions: UserPermissions | None = None
    user_entities: list[str] = Field(default_factory=list)

    @property
    def user_id(self) -> str:
        return self.claims.user_id

    @property
    def company_id(self) -> str:
        return self.claims.company_id

    @property
    def tenant_id(self) -> str:
        """Alias for company_id to support multi-tenant conventions uniformly."""
        return self.claims.company_id

    @property
    def role(self) -> str:
        return self.claims.role


# 5. Full Lesson Context (Returned by LMS internal API)
# Uses AliasChoices to seamlessly support both camelCase and PascalCase from .NET serialization.
class LessonFullContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    lesson_id: str = Field(default="", validation_alias=AliasChoices("lessonId", "LessonId"))
    video_url: str | None = Field(default=None, validation_alias=AliasChoices("videoUrl", "VideoUrl"))
    tenant_ids: list[str] = Field(default_factory=list, validation_alias=AliasChoices("tenantIds", "TenantIds"))
    module_id: str = Field(default="", validation_alias=AliasChoices("moduleId", "ModuleId"))
    unit_id: str = Field(default="", validation_alias=AliasChoices("unitId", "UnitId"))
    level_id: str = Field(default="", validation_alias=AliasChoices("levelId", "LevelId"))
    type_id: str = Field(default="", validation_alias=AliasChoices("typeId", "TypeId"))
    target_roles: list[str] = Field(default_factory=list, validation_alias=AliasChoices("targetRoles", "TargetRoles"))

    def __getitem__(self, item: str):
        mapping = {
            "lessonId": self.lesson_id,
            "LessonId": self.lesson_id,
            "lesson_id": self.lesson_id,
            "videoUrl": self.video_url,
            "VideoUrl": self.video_url,
            "video_url": self.video_url,
            "tenantIds": self.tenant_ids,
            "TenantIds": self.tenant_ids,
            "tenant_ids": self.tenant_ids,
            "moduleId": self.module_id,
            "ModuleId": self.module_id,
            "module_id": self.module_id,
            "unitId": self.unit_id,
            "UnitId": self.unit_id,
            "unit_id": self.unit_id,
            "levelId": self.level_id,
            "LevelId": self.level_id,
            "level_id": self.level_id,
            "typeId": self.type_id,
            "TypeId": self.type_id,
            "type_id": self.type_id,
            "targetRoles": self.target_roles,
            "TargetRoles": self.target_roles,
            "target_roles": self.target_roles,
        }
        if item in mapping:
            return mapping[item]
        raise KeyError(item)

    def get(self, item: str, default=None):
        try:
            return self[item]
        except KeyError:
            return default
