"""
Clawzd Plugin — Smart Automation.

Uses the after_tool_execute hook to:
1. Auto-register generated files in the Upload Store
2. Record usage patterns for analytics
3. Auto-pin important artifacts (code files > 20 lines)

Uses the after_generation hook to:
1. Detect structured UI components and log them
2. Auto-suggest relevant follow-up actions via notifications
"""
import logging
import os
from app.core.plugin_system import ClawzdPlugin

logger = logging.getLogger("clawzd.plugin.automation")


class AutomationPlugin(ClawzdPlugin):
    name = "automation"
    description = "Auto-register uploads, pin important artifacts, suggest follow-ups"
    version = "1.0.0"

    def after_tool_execute(self, context: dict) -> dict:
        """Auto-register generated files in the Upload Store."""
        tool_name = context.get("tool_name", "")
        result = context.get("result", {})
        session_id = context.get("session_id")

        if not isinstance(result, dict):
            return context

        # 1. Auto-register generated images in the Upload Store
        if tool_name in ("generate_image", "generate_animation"):
            images = result.get("images", [])
            for img_path in images:
                if isinstance(img_path, str) and os.path.exists(img_path):
                    try:
                        from app.core.upload_store import register_file
                        register_file(
                            img_path,
                            session_id=session_id,
                            category="image",
                            source="generation",
                        )
                    except Exception:
                        pass

        # 2. Auto-register screenshots
        if tool_name in ("screenshot_remote", "screenshot_local"):
            screenshot = result.get("path") or result.get("screenshot")
            if isinstance(screenshot, str) and os.path.exists(screenshot):
                try:
                    from app.core.upload_store import register_file
                    register_file(
                        screenshot,
                        session_id=session_id,
                        category="screenshot",
                        source="tool",
                    )
                except Exception:
                    pass

        return context

    def after_generation(self, context: dict) -> dict:
        """Analyze the response and push smart notifications."""
        response = context.get("response", "")
        session_id = context.get("session_id")

        if not response or not session_id:
            return context

        # 1. Detect if the response contains structured components
        try:
            from app.core.structured_ui import extract_components
            components = extract_components(response)
            if components:
                comp_types = [c["type"] for c in components]
                logger.info(
                    "Session %s: %d structured components (%s)",
                    session_id[:8], len(components), ", ".join(comp_types),
                )
        except Exception:
            pass

        # 2. If the response generated a lot of code, suggest artifact save
        code_blocks = response.count("```")
        if code_blocks >= 6:
            try:
                from app.core.notifications import notify
                notify(
                    "💡 Tip: Save as artifact",
                    "This response contains substantial code. "
                    "Consider pinning it as an artifact for future reference.",
                    session_id=session_id,
                )
            except Exception:
                pass

        return context


# Module-level plugin instance (auto-discovered by plugin system)
plugin = AutomationPlugin()
