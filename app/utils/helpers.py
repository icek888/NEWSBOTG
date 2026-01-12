"""Helper functions module"""

def format_text(text: str) -> str:
    return text.strip()

def truncate_text(text: str, max_length: int) -> str:
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text
