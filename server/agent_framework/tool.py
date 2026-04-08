"""
FunctionTool & @function_tool decorator.

Automatically generates OpenAI-format JSON Schema from a function's
type hints, docstring, and optional ``Annotated[..., Field(...)]`` metadata.
"""

from __future__ import annotations

import inspect
import json
import re
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, get_args, get_origin, get_type_hints

from .context import RunContext

# ── FunctionTool ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FunctionTool:
    """A tool that wraps an async callable and exposes its schema to the LLM."""

    name: str
    description: str
    parameters_schema: dict          # OpenAI-format "parameters" object
    fn: Callable[..., Awaitable[Any]]
    status_message: str = ""         # human-readable text shown while running

    # Pre-built definition dict (cached at creation time)
    _definition: dict = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._definition is None:
            defn = {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameters_schema,
                },
            }
            # frozen dataclass — use object.__setattr__
            object.__setattr__(self, "_definition", defn)

    @property
    def definition(self) -> dict:
        """OpenAI-format tool definition ready for ``tools=[...]``."""
        return self._definition

    async def __call__(self, **kwargs: Any) -> Any:
        return await self.fn(**kwargs)


# ── Schema generation helpers ─────────────────────────────────────────────────

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _type_to_json_schema(tp: Any) -> dict:
    """Convert a Python type hint to a JSON Schema fragment."""
    # Literal["on", "off", "toggle"] → enum
    origin = get_origin(tp)
    if origin is Literal:
        args = get_args(tp)
        return {"type": "string", "enum": list(args)}

    # list[X] → array
    if origin in (list, typing.List):
        item_args = get_args(tp)
        items = _type_to_json_schema(item_args[0]) if item_args else {}
        return {"type": "array", "items": items}

    # Optional[X] is Union[X, None]
    if origin is typing.Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return _type_to_json_schema(args[0])

    # Annotated[X, ...] — unwrap
    if get_origin(tp) is typing.Annotated:
        args = get_args(tp)
        base_schema = _type_to_json_schema(args[0])
        # Pull description from pydantic Field or FieldInfo metadata
        for meta in args[1:]:
            desc = getattr(meta, "description", None)
            if desc:
                base_schema["description"] = desc
        return base_schema

    # Basic scalar types
    if tp in _PY_TO_JSON:
        return {"type": _PY_TO_JSON[tp]}

    # Fallback
    return {"type": "string"}


def _parse_docstring_params(docstring: str | None) -> tuple[str, dict[str, str]]:
    """Extract the summary line and per-parameter descriptions from a docstring.

    Supports both Google-style and Sphinx-style:
        Args:
            city: City name e.g. "北京"
        :param city: City name
    """
    if not docstring:
        return "", {}

    lines = inspect.cleandoc(docstring).splitlines()
    summary_parts: list[str] = []
    params: dict[str, str] = {}

    in_args_section = False
    current_param: str | None = None

    for line in lines:
        stripped = line.strip()

        # Google-style "Args:" header
        if stripped.lower() in ("args:", "arguments:", "parameters:", "params:"):
            in_args_section = True
            continue

        # Sphinx-style ":param name: description"
        m = re.match(r":param\s+(\w+):\s*(.*)", stripped)
        if m:
            current_param = m.group(1)
            params[current_param] = m.group(2).strip()
            in_args_section = True
            continue

        if in_args_section:
            # Google-style "  name: description" or "  name (type): description"
            m = re.match(r"(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)", stripped)
            if m:
                current_param = m.group(1)
                params[current_param] = m.group(2).strip()
                continue

            # Continuation line for current param
            if current_param and stripped and line.startswith(("  ", "\t")):
                params[current_param] += " " + stripped
                continue

            # End of args section (blank line or new section header)
            if not stripped or stripped.endswith(":"):
                in_args_section = False
                current_param = None
                continue
        else:
            if not stripped:
                continue
            if not params and not in_args_section:
                summary_parts.append(stripped)

    summary = " ".join(summary_parts)
    return summary, params


def _build_parameters_schema(
    fn: Callable,
    hints: dict[str, Any],
    param_docs: dict[str, str],
) -> dict:
    """Build the ``parameters`` JSON Schema object from a function signature."""
    sig = inspect.signature(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        # Skip RunContext injection parameter
        hint = hints.get(pname)
        if hint is RunContext or pname == "context":
            continue
        if pname in ("self", "cls"):
            continue

        prop = _type_to_json_schema(hint) if hint else {"type": "string"}

        # Merge docstring-level descriptions (lower priority than Annotated)
        if "description" not in prop and pname in param_docs:
            prop["description"] = param_docs[pname]

        properties[pname] = prop

        if param.default is inspect.Parameter.empty:
            required.append(pname)

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# ── @function_tool decorator ──────────────────────────────────────────────────

def function_tool(
    fn: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    status_message: str = "",
) -> FunctionTool | Callable[[Callable], FunctionTool]:
    """Decorator that converts an async function into a :class:`FunctionTool`.

    Usage::

        @function_tool
        async def get_weather(city: str) -> dict:
            \"\"\"获取指定城市的天气。\"\"\"
            ...

        @function_tool(name="search", status_message="正在搜索...")
        async def web_search(query: str) -> dict:
            ...
    """

    def _wrap(f: Callable) -> FunctionTool:
        hints = get_type_hints(f, include_extras=True)
        doc_summary, doc_params = _parse_docstring_params(f.__doc__)

        tool_name = name or f.__name__
        tool_desc = description or doc_summary or f"{tool_name} tool"
        params_schema = _build_parameters_schema(f, hints, doc_params)

        return FunctionTool(
            name=tool_name,
            description=tool_desc,
            parameters_schema=params_schema,
            fn=f,
            status_message=status_message,
        )

    if fn is not None:
        # @function_tool   (no parentheses)
        return _wrap(fn)
    # @function_tool(...)  (with arguments)
    return _wrap
