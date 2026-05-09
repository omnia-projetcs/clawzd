"""
Clawzd — Token counting utilities.
"""
import tiktoken
import logging

logger = logging.getLogger("clawzd.tokens")

_encodings = {}

def get_encoding(model: str = "gpt-4o"):
    if model not in _encodings:
        try:
            _encodings[model] = tiktoken.encoding_for_model(model)
        except KeyError:
            _encodings[model] = tiktoken.get_encoding("cl100k_base")
    return _encodings[model]

def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Return the number of tokens in a text string."""
    if not text:
        return 0
    try:
        enc = get_encoding(model)
        return len(enc.encode(text, disallowed_special=()))
    except Exception as e:
        logger.warning("Failed to count tokens: %s", e)
        return max(1, len(text) // 4)

def count_message_tokens(messages: list[dict], model: str = "gpt-4o") -> int:
    """Return the number of tokens used by a list of messages."""
    if not messages:
        return 0
    try:
        enc = get_encoding(model)
        num_tokens = 0
        for message in messages:
            num_tokens += 3  # every message follows <|start|>{role/name}\n{content}<|end|>\n
            for key, value in message.items():
                num_tokens += len(enc.encode(str(value), disallowed_special=()))
        num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
        return num_tokens
    except Exception as e:
        logger.warning("Failed to count message tokens: %s", e)
        return sum(max(1, len(str(m.get("content", ""))) // 4) for m in messages)
