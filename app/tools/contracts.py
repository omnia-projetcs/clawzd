"""
Clawzd — Typed Tool Contracts (OpenClaw OS-inspired Zod-like schemas).

Pydantic models defining the expected inputs/outputs for each tool.
Benefits:
- LLM receives JSON Schema → fewer parameter hallucinations
- Automatic validation before execution
- Auto-generated API documentation
- Type coercion integrated with the repair pipeline

Usage:
    from app.tools.contracts import get_tool_schema, validate_tool_params

    schema = get_tool_schema("execute_python")
    # → {"type": "object", "properties": {"code": {"type": "string", ...}}, ...}

    validated = validate_tool_params("execute_python", {"code": "print(1)"})
    # → {"code": "print(1)", "confirmed": false}  (defaults applied)
"""
import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("clawzd.contracts")


# ---------------------------------------------------------------------------
# Tool Input Models
# ---------------------------------------------------------------------------

class ExecutePythonParams(BaseModel):
    """Parameters for the execute_python tool."""
    code: str = Field(..., description="Python code to execute")
    confirmed: bool = Field(False, description="Set to true to confirm risky operations")


class RunCommandParams(BaseModel):
    """Parameters for the run_command tool."""
    command: str = Field(..., description="Shell command to execute")
    confirmed: bool = Field(False, description="Set to true to confirm risky commands")


class SearchWebParams(BaseModel):
    """Parameters for the search_web tool."""
    query: str = Field(..., description="Search query")
    max_results: int = Field(50, description="Maximum number of results", ge=1, le=100)


class ScreenshotRemoteParams(BaseModel):
    """Parameters for the screenshot_remote tool."""
    url: str = Field(..., description="URL to screenshot")
    full_page: bool = Field(False, description="Capture the full scrollable page")


class GenerateImageParams(BaseModel):
    """Parameters for the generate_image tool."""
    prompt: str = Field(..., description="Image description prompt")
    negative_prompt: str = Field("blurry, low quality, distorted", description="What to avoid")
    format: str = Field("auto", description="Output format: auto, png, svg")
    style: str = Field("none", description="Style preset: none, anime, photo, etc.")


class GenerateAnimationParams(BaseModel):
    """Parameters for the generate_animation tool."""
    prompt: str = Field(..., description="Animation description prompt")
    format: str = Field("gif", description="Output format: gif, mp4, webm")
    duration: float = Field(2.0, description="Duration in seconds", ge=0.5, le=10.0)


class EditFileParams(BaseModel):
    """Parameters for the edit_file tool."""
    file_path: str = Field(..., description="Relative path to the file to edit")
    old_string: str = Field("", description="Text to find and replace (empty = write new file)")
    new_string: str = Field("", description="Replacement text")
    replace_all: bool = Field(False, description="Replace all occurrences vs first only")


class ReadFileParams(BaseModel):
    """Parameters for the read_file tool."""
    file_path: str = Field(..., description="Relative path to the file to read")
    start_line: int = Field(1, description="First line to read (1-indexed)", ge=1)
    end_line: Optional[int] = Field(None, description="Last line to read (inclusive)")


class AuditCodeParams(BaseModel):
    """Parameters for the audit_code tool."""
    mode: str = Field("quick", description="Audit mode: quick (inline code) or full (target path)")
    code: str = Field("", description="Code to audit (quick mode)")
    target: str = Field("", description="Target path to audit (full mode)")


class RagSearchParams(BaseModel):
    """Parameters for the rag_search tool."""
    query: str = Field(..., description="Search query for the knowledge base")
    k: int = Field(3, description="Number of results to return", ge=1, le=10)


class BrowseWebParams(BaseModel):
    """Parameters for the browse_web tool."""
    url: str = Field(..., description="URL to navigate to")
    actions: list = Field(default_factory=list, description="Browser actions to perform")


class CreateDocumentParams(BaseModel):
    """Parameters for the create_document tool."""
    format_type: str = Field("markdown", description="Document format: markdown, html, pdf, docx")
    content: str = Field(..., description="Document content")
    title: str = Field("", description="Document title")


class MemoryParams(BaseModel):
    """Parameters for the memory tool."""
    action: str = Field("read", description="Action: read, write, append")
    file: str = Field("MEMORY.md", description="Memory file to access")
    content: str = Field("", description="Content to write/append")


class SendEmailParams(BaseModel):
    """Parameters for the send_email tool."""
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body (HTML supported)")
    to_email: Optional[str] = Field(None, description="Recipient email (default from config)")


# ---------------------------------------------------------------------------
# Schema Registry
# ---------------------------------------------------------------------------

_TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "execute_python": ExecutePythonParams,
    "run_command": RunCommandParams,
    "search_web": SearchWebParams,
    "screenshot_remote": ScreenshotRemoteParams,
    "generate_image": GenerateImageParams,
    "generate_animation": GenerateAnimationParams,
    "edit_file": EditFileParams,
    "read_file": ReadFileParams,
    "audit_code": AuditCodeParams,
    "rag_search": RagSearchParams,
    "browse_web": BrowseWebParams,
    "create_document": CreateDocumentParams,
    "memory": MemoryParams,
    "send_email": SendEmailParams,
}


def get_tool_schema(tool_name: str) -> Optional[dict]:
    """Return the JSON Schema for a tool's parameters.

    Returns None if no schema is registered for the tool.
    """
    model = _TOOL_SCHEMAS.get(tool_name)
    if not model:
        return None
    return model.model_json_schema()


def get_all_schemas() -> dict[str, dict]:
    """Return all registered tool schemas."""
    return {name: get_tool_schema(name) for name in _TOOL_SCHEMAS}


def get_compact_schemas() -> str:
    """Return a compact text representation of all tool schemas.

    Designed for injection into the LLM context — much more token-efficient
    than raw JSON Schema.
    """
    lines = []
    for name, model_cls in _TOOL_SCHEMAS.items():
        fields = model_cls.model_fields
        params = []
        for fname, finfo in fields.items():
            ftype = finfo.annotation.__name__ if hasattr(finfo.annotation, '__name__') else str(finfo.annotation)
            req = "required" if finfo.is_required() else f"default={finfo.default}"
            params.append(f"{fname}:{ftype} ({req})")
        lines.append(f"- {name}({', '.join(params)})")
    return "\n".join(lines)


def validate_tool_params(tool_name: str, params: dict) -> dict:
    """Validate and normalize tool parameters using the Pydantic model.

    - Applies defaults for missing optional fields
    - Coerces types where possible
    - Returns the validated params dict

    If no schema exists for the tool, returns params unchanged.
    Validation errors are logged but never block execution.
    """
    model_cls = _TOOL_SCHEMAS.get(tool_name)
    if not model_cls:
        return params

    try:
        validated = model_cls.model_validate(params)
        return validated.model_dump()
    except Exception as exc:
        logger.warning(
            "Schema validation failed for %s: %s — using raw params",
            tool_name, exc,
        )
        return params
