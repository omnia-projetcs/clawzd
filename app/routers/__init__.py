"""
Clawzd — FastAPI Routers module.

API route handlers, split by domain from the legacy gateway.py:
- chat: /chat, /stream — conversation endpoints
- media: /images, /audio, /video — media generation and gallery
- documents: /documents, /presentations — document management
- projects: /projects — Kanban project management
- admin: /settings, /tokens, /models — administration
- tools: /execute, /audit — code execution and security scanning
"""
