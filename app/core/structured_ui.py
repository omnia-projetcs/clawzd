"""
Clawzd — Structured UI Components (OpenClaw OS-inspired Generative UI).

Instead of the LLM always returning raw Markdown, this system allows it
to emit structured component blocks that the frontend renders as
interactive widgets. Uses the existing __MARKER__ pattern.

Supported components:
    __CHART__{ ... JSON config }__CHART__     → Chart.js interactive chart
    __TABLE__{ ... JSON config }__TABLE__     → Sortable data table
    __PROGRESS__{ ... JSON }__PROGRESS__      → Progress bar / status
    __CARD__{ ... JSON }__CARD__              → Info card with icon
    __ALERT__{ ... JSON }__ALERT__            → Styled alert box
    __ARTIFACT__{ ... JSON }__ARTIFACT__      → Artifact reference card

The LLM injects these markers into its response text, and the frontend
streaming_parser + renderMd convert them into interactive DOM elements.

This module provides:
1. Schema definitions for each component
2. Helper functions for the LLM to emit components
3. Parsing functions for the frontend integration
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger("clawzd.structured_ui")


# ---------------------------------------------------------------------------
# Component schemas (for LLM prompt injection)
# ---------------------------------------------------------------------------

COMPONENT_SCHEMAS = {
    "chart": {
        "description": "Interactive Chart.js chart",
        "format": '__CHART__{"type":"bar|line|pie|doughnut|radar","title":"...","labels":["..."],"datasets":[{"label":"...","data":[...]}]}__CHART__',
        "example": '__CHART__{"type":"bar","title":"Sales Q1","labels":["Jan","Feb","Mar"],"datasets":[{"label":"Revenue","data":[100,200,150]}]}__CHART__',
    },
    "table": {
        "description": "Sortable data table",
        "format": '__TABLE__{"title":"...","headers":["..."],"rows":[["..."]]}__TABLE__',
        "example": '__TABLE__{"title":"Results","headers":["Name","Score"],"rows":[["Alice","95"],["Bob","87"]]}__TABLE__',
    },
    "progress": {
        "description": "Progress indicator",
        "format": '__PROGRESS__{"label":"...","value":75,"max":100,"status":"info|success|warning|error"}__PROGRESS__',
    },
    "card": {
        "description": "Information card",
        "format": '__CARD__{"title":"...","content":"...","icon":"📊","color":"blue|green|red|yellow"}__CARD__',
    },
    "alert": {
        "description": "Alert / callout box",
        "format": '__ALERT__{"type":"info|success|warning|error","title":"...","message":"..."}__ALERT__',
    },
}


def get_component_prompt() -> str:
    """Generate a compact prompt section describing available UI components.

    Injected into the system prompt for cloud providers.
    """
    lines = ["## Structured UI Components",
             "You can emit interactive components using these markers:\n"]

    for name, schema in COMPONENT_SCHEMAS.items():
        lines.append(f"- **{name}**: {schema['description']}")
        lines.append(f"  Format: `{schema['format']}`")
        if "example" in schema:
            lines.append(f"  Example: `{schema['example']}`")
        lines.append("")

    lines.append("Use these instead of raw markdown when the data is structured.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parser (backend-side validation)
# ---------------------------------------------------------------------------

_COMPONENT_RE = re.compile(
    r'__(?:CHART|TABLE|PROGRESS|CARD|ALERT|ARTIFACT)__'
    r'(\{[\s\S]*?\})'
    r'__(?:CHART|TABLE|PROGRESS|CARD|ALERT|ARTIFACT)__'
)


def extract_components(text: str) -> list[dict]:
    """Extract and validate structured components from LLM output.

    Returns list of {"type": "chart", "config": {...}, "raw": "..."} dicts.
    """
    components = []

    patterns = {
        "chart": re.compile(r'__CHART__(\{[\s\S]*?\})__CHART__'),
        "table": re.compile(r'__TABLE__(\{[\s\S]*?\})__TABLE__'),
        "progress": re.compile(r'__PROGRESS__(\{[\s\S]*?\})__PROGRESS__'),
        "card": re.compile(r'__CARD__(\{[\s\S]*?\})__CARD__'),
        "alert": re.compile(r'__ALERT__(\{[\s\S]*?\})__ALERT__'),
        "artifact": re.compile(r'__ARTIFACT__(\{[\s\S]*?\})__ARTIFACT__'),
    }

    for comp_type, pattern in patterns.items():
        for match in pattern.finditer(text):
            try:
                config = json.loads(match.group(1))
                components.append({
                    "type": comp_type,
                    "config": config,
                    "raw": match.group(0),
                })
            except json.JSONDecodeError as e:
                logger.warning(
                    "Invalid %s component JSON: %s",
                    comp_type, str(e)[:80],
                )

    return components


def validate_chart_config(config: dict) -> bool:
    """Validate a chart configuration."""
    required = {"type", "labels", "datasets"}
    if not required.issubset(config.keys()):
        return False
    if config["type"] not in ("bar", "line", "pie", "doughnut", "radar", "scatter"):
        return False
    if not isinstance(config["labels"], list):
        return False
    if not isinstance(config["datasets"], list) or len(config["datasets"]) == 0:
        return False
    return True


def validate_table_config(config: dict) -> bool:
    """Validate a table configuration."""
    if "headers" not in config or "rows" not in config:
        return False
    if not isinstance(config["headers"], list):
        return False
    if not isinstance(config["rows"], list):
        return False
    return True
