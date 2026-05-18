def detect_intent(text: str) -> str:
    """Placeholder de parser de intents para la siguiente fase."""
    normalized = text.strip().lower()
    if "enciende la luz" in normalized:
        return "LUZ_ON"
    if "apaga la luz" in normalized:
        return "LUZ_OFF"
    return "UNKNOWN"
