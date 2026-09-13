from pydantic import BaseModel, Field, ConfigDict

# 1. Token Claims (Data extracted directly from the decoded JWT)
# Using aliases to map .NET PascalCase token claims to Python's snake_case.
class TokenClaims(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    user_id: str = Field(alias="Id")
    role: str = Field(alias="Role")
    company_id: str = Field(alias="CompanyId")
    department_id: str | None = Field(default=None, alias="DepartmentId")

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
    def role(self) -> str:
        return self.claims.role
