"""
Clawzd — Core infrastructure module.

Contains foundational services shared across the application:
- cache: In-memory and file-based caching
- compression: Response and data compression
- database: SQLite database access layer
- llm_provider: Unified LLM provider abstraction (Ollama, OpenAI, etc.)
- memory: Conversation memory management
- metrics: Performance and usage metrics collection
- output_compressor: LLM output size optimization
- settings: Application settings management
- preprompts: System prompt templates and management
"""
