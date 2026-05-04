from __future__ import annotations

import ast
import json
from typing import Any


def parse_structured_text(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(stripped)
    except (SyntaxError, ValueError):
        return stripped


def normalize_mcp_content(result: Any) -> Any:
    if hasattr(result, "contents"):
        values = []
        for content in result.contents:
            text = getattr(content, "text", None)
            if text is not None:
                values.append(parse_structured_text(text))
        return values[0] if len(values) == 1 else values

    if hasattr(result, "content"):
        values = []
        for content in result.content:
            text = getattr(content, "text", None)
            if text is not None:
                values.append(parse_structured_text(text))
        if len(values) == 1:
            return values[0]
        return values

    return result
