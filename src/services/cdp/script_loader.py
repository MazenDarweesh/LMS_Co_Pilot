"""
CDP Script Loader Utility.
Loads and caches isolated JavaScript scripts from the `scripts/` directory in memory,
enabling syntax highlighting, linting, and parameter templating without file I/O overhead.
"""

from functools import lru_cache
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent / "scripts"


@lru_cache(maxsize=32)
def _read_raw_script(script_name: str) -> str:
    """قراءة ملف الجافاسكريبت وتخزينه في الذاكرة لتجنب القراءة المتكررة من القرص"""
    file_path = SCRIPTS_DIR / script_name
    if not file_path.exists():
        raise FileNotFoundError(f"CDP Script file not found: {file_path}")
    return file_path.read_text(encoding="utf-8")


def get_script(script_name: str, **replacements: str | int | float) -> str:
    """
    جلب محتوى السكربت واستبدال المتغيرات المؤطرة بـ __KEY__ بقيمها الممررة.
    مثال: get_script("click_ripple.js", X=150, Y=300) -> يستبدل __X__ و __Y__
    """
    content = _read_raw_script(script_name)
    for key, val in replacements.items():
        content = content.replace(f"__{key}__", str(val))
    return content
