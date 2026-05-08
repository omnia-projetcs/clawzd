"""
Clawzd — Plugin System (OpenClaw OS-inspired).

Lightweight plugin architecture that allows extending Clawzd without
modifying the monolithic gateway.py. Plugins register via hooks that
fire at key points in the request lifecycle.

Hook Points:
    before_prompt_build  — Modify system prompt, inject context
    after_skill_detect   — Filter/augment detected skills
    before_tool_execute  — Intercept tool calls, add guards
    after_tool_execute   — Post-process tool results
    after_generation     — Post-process full response
    on_session_create    — React to new sessions
    register_routes      — Add custom HTTP endpoints

Usage:
    from app.core.plugin_system import ClawzdPlugin, register_plugin

    class MyPlugin(ClawzdPlugin):
        name = "my_plugin"

        def before_prompt_build(self, context):
            context["system_prompt"] += "\\nCustom instruction"
            return context

    register_plugin(MyPlugin())
"""
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("clawzd.plugins")


# ---------------------------------------------------------------------------
# Base Plugin class
# ---------------------------------------------------------------------------

class ClawzdPlugin:
    """Base class for all Clawzd plugins.

    Override hook methods to extend functionality.
    All hooks receive a context dict and should return it (possibly modified).
    """
    name: str = "unnamed_plugin"
    description: str = ""
    version: str = "1.0.0"
    enabled: bool = True

    def before_prompt_build(self, context: dict) -> dict:
        """Called before the system prompt is finalized.

        Context keys:
            system_prompt (str): Current system prompt content
            user_message (str): The user's message
            session_id (str): Current session ID
            provider (str): LLM provider name
            model (str): Model name
            detected_skills (list): Skills detected for this request
        """
        return context

    def after_skill_detect(self, context: dict) -> dict:
        """Called after skills are detected, before injection.

        Context keys:
            detected_skills (list[dict]): Detected skills with confidence
            user_message (str): The user's message
        """
        return context

    def before_tool_execute(self, context: dict) -> dict:
        """Called before a tool is executed.

        Context keys:
            tool_name (str): Resolved tool name
            params (dict): Tool parameters
            session_id (str): Current session ID
            skip (bool): Set to True to skip execution
        """
        return context

    def after_tool_execute(self, context: dict) -> dict:
        """Called after a tool finishes execution.

        Context keys:
            tool_name (str): Tool that was executed
            params (dict): Tool parameters
            result (dict): Tool result
            session_id (str): Current session ID
        """
        return context

    def after_generation(self, context: dict) -> dict:
        """Called after the full response is generated.

        Context keys:
            response (str): Full generated text
            session_id (str): Current session ID
            provider (str): Provider used
            model (str): Model used
        """
        return context

    def on_session_create(self, context: dict) -> dict:
        """Called when a new chat session is created.

        Context keys:
            session_id (str): New session ID
            provider (str): Provider
            model (str): Model
        """
        return context

    def register_routes(self, app) -> None:
        """Called during startup to register custom HTTP routes.

        Args:
            app: The FastAPI application instance.
        """
        pass


# ---------------------------------------------------------------------------
# Plugin Registry
# ---------------------------------------------------------------------------

_plugins: list[ClawzdPlugin] = []


def register_plugin(plugin: ClawzdPlugin) -> None:
    """Register a plugin instance."""
    if not isinstance(plugin, ClawzdPlugin):
        raise TypeError(f"Expected ClawzdPlugin, got {type(plugin).__name__}")

    # Prevent duplicate registration
    for existing in _plugins:
        if existing.name == plugin.name:
            logger.warning("Plugin '%s' already registered — skipping", plugin.name)
            return

    _plugins.append(plugin)
    logger.info("Registered plugin: %s v%s", plugin.name, plugin.version)


def unregister_plugin(name: str) -> bool:
    """Unregister a plugin by name. Returns True if found."""
    global _plugins
    before = len(_plugins)
    _plugins = [p for p in _plugins if p.name != name]
    removed = len(_plugins) < before
    if removed:
        logger.info("Unregistered plugin: %s", name)
    return removed


def list_plugins() -> list[dict]:
    """List all registered plugins."""
    return [
        {
            "name": p.name,
            "description": p.description,
            "version": p.version,
            "enabled": p.enabled,
        }
        for p in _plugins
    ]


def get_plugin(name: str) -> Optional[ClawzdPlugin]:
    """Get a plugin by name."""
    for p in _plugins:
        if p.name == name:
            return p
    return None


# ---------------------------------------------------------------------------
# Hook dispatcher
# ---------------------------------------------------------------------------

def run_hook(hook_name: str, context: dict) -> dict:
    """Run all enabled plugins for a given hook.

    Each plugin's hook method receives the context and returns it
    (potentially modified). Plugins run in registration order.
    Errors in individual plugins are caught and logged — never fatal.
    """
    for plugin in _plugins:
        if not plugin.enabled:
            continue

        hook_fn = getattr(plugin, hook_name, None)
        if hook_fn is None:
            continue

        # Skip if the method is not overridden (default base implementation)
        if hook_fn.__func__ is getattr(ClawzdPlugin, hook_name, None):
            continue

        try:
            result = hook_fn(context)
            if result is not None:
                context = result
        except Exception as exc:
            logger.error(
                "Plugin '%s' hook '%s' failed: %s",
                plugin.name, hook_name, exc,
            )

    return context


def run_hook_register_routes(app) -> None:
    """Special hook: let plugins register their HTTP routes."""
    for plugin in _plugins:
        if not plugin.enabled:
            continue
        try:
            plugin.register_routes(app)
        except Exception as exc:
            logger.error(
                "Plugin '%s' register_routes failed: %s",
                plugin.name, exc,
            )


# ---------------------------------------------------------------------------
# Auto-discovery: load plugins from app/plugins/ directory
# ---------------------------------------------------------------------------

def discover_plugins(plugins_dir: str = "app/plugins") -> int:
    """Auto-discover and register plugins from the plugins directory.

    Each .py file in the directory should have a `plugin` module-level
    variable that is a ClawzdPlugin instance.

    Returns the number of plugins loaded.
    """
    import importlib
    import os
    import sys

    if not os.path.isdir(plugins_dir):
        return 0

    loaded = 0
    for fname in sorted(os.listdir(plugins_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue

        module_name = f"app.plugins.{fname[:-3]}"
        try:
            if module_name in sys.modules:
                mod = importlib.reload(sys.modules[module_name])
            else:
                mod = importlib.import_module(module_name)

            plugin = getattr(mod, "plugin", None)
            if plugin and isinstance(plugin, ClawzdPlugin):
                register_plugin(plugin)
                loaded += 1
            else:
                logger.debug("No 'plugin' variable in %s", fname)
        except Exception as exc:
            logger.error("Failed to load plugin %s: %s", fname, exc)

    if loaded:
        logger.info("Auto-discovered %d plugin(s) from %s", loaded, plugins_dir)

    return loaded
