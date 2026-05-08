"""
Clawzd Plugin — Context Enrichment.

Automatically enriches the system prompt with:
- Current date/time (so the LLM knows "today")
- Active artifact context (so "update the previous code" works)
- Token budget awareness
"""
from app.core.plugin_system import ClawzdPlugin


class ContextEnrichmentPlugin(ClawzdPlugin):
    name = "context_enrichment"
    description = "Auto-inject date/time and artifact context into prompts"
    version = "1.0.0"

    def before_prompt_build(self, context: dict) -> dict:
        """Inject temporal awareness and artifact context."""
        import datetime

        additions = []

        # 1. Current date/time (models don't know "today" otherwise)
        now = datetime.datetime.now()
        additions.append(
            f"Current date: {now.strftime('%A %d %B %Y, %H:%M')}."
        )

        # 2. Recent artifacts for this session (enables "update the chart")
        session_id = context.get("session_id")
        if session_id:
            try:
                from app.core.artifacts import list_artifacts
                recent = list_artifacts(session_id=session_id, limit=3)
                if recent:
                    artifact_hints = []
                    for a in recent:
                        lang_tag = f" ({a['language']})" if a.get("language") else ""
                        artifact_hints.append(
                            f"- [{a['id']}] {a['title']}{lang_tag} v{a['version']}"
                        )
                    additions.append(
                        "Recent artifacts in this session:\n"
                        + "\n".join(artifact_hints)
                        + "\nYou can reference these by ID to update them."
                    )
            except Exception:
                pass  # Non-critical

        if additions:
            extra = "\n".join(additions)
            context["system_prompt"] = (
                context.get("system_prompt", "") + "\n\n" + extra
            )

        return context


# Module-level plugin instance (auto-discovered by plugin system)
plugin = ContextEnrichmentPlugin()
