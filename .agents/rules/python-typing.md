# Rule: Python Typing Standards

This rule is **always active**. Enforce it automatically in every code edit.

## Required

- Use `dict | None` instead of `Optional[dict]`
- Use `list[str]` instead of `List[str]`
- Use `str | None` instead of `Optional[str]`
- Use `X | Y` union syntax throughout — never import `Optional`, `Union`, `List`, `Dict`, `Tuple` from `typing` for these cases
- When using `# type: ignore`, **always** add a comment explaining WHY on the same line
  - ✅ `scores = model.predict(pairs).tolist()  # type: ignore — sentence-transformers PairInput overload mismatch`
  - ❌ `scores = model.predict(pairs).tolist()  # type: ignore`

## Forbidden Patterns

```python
# ❌ FORBIDDEN — do not write these:
from typing import Optional, List, Dict, Union
def foo(x: Optional[str]) -> List[int]: ...
def bar(x: Union[str, int]) -> Dict[str, Any]: ...

# ✅ CORRECT — use these instead:
def foo(x: str | None) -> list[int]: ...
def bar(x: str | int) -> dict[str, Any]: ...
```

## Exceptions

- `TypeVar`, `Generic`, `Protocol`, `Callable`, `Any`, `TYPE_CHECKING` — still import from `typing`
- Third-party library stubs that require legacy syntax — use `# type: ignore` with explanation
