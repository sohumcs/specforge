"""Versioned prompt templates.

Templates live in `app/llm/templates/<name>.v<N>.md`. Bumping PROMPT_VERSION
switches every template and changes the generation cache key, so old cached
blueprints are never served for new prompts.
"""

import re
from functools import cache
from pathlib import Path

PROMPT_VERSION = "v1"
_DIR = Path(__file__).parent / "templates"
_VAR = re.compile(r"\{\{(\w+)\}\}")


@cache
def load(name: str, version: str = PROMPT_VERSION) -> str:
    return (_DIR / f"{name}.{version}.md").read_text(encoding="utf-8")


def render(name: str, **values: object) -> str:
    """Render the current-version template `name`."""
    return render_version(name, PROMPT_VERSION, **values)


def render_version(name: str, version: str, **values: object) -> str:
    """Replace {{var}} placeholders. A missing value is a programming error."""
    template = load(name, version)
    missing = {m for m in _VAR.findall(template) if m not in values}
    if missing:
        raise KeyError(f"prompt {name}.{version} missing values: {sorted(missing)}")
    return _VAR.sub(lambda m: str(values[m.group(1)]), template)
