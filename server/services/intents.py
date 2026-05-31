import re
import unicodedata


def normalizar(texto: str) -> str:
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


# Variantes fonéticas que Vosk produce en lugar de "pomodoro"
_POMODORO_ALIASES = [
    "comodoro",
    "pomo adoro",
    "pom adoro",
    "como adoro",
    "pomó doro",
    "pomo doro",
    "como doro",
]

def _normalizar_pomodoro(texto: str) -> str:
    for alias in _POMODORO_ALIASES:
        texto = texto.replace(alias, "pomodoro")
    return texto


INTENT_MAP = [
    # Expresiones
    (["feliz", "contento", "bien", "como estas"],  "MOOD_HAPPY"),
    (["sorpresa", "sorprendete", "wow"],            "MOOD_SURPRISED"),
    (["duerme", "descansa", "cansado"],             "MOOD_SLEEPY"),
    (["enojate", "molesto", "furioso"],             "MOOD_ANGRY"),
    (["triste", "llora", "mal"],                    "MOOD_SAD"),
    (["emocionado", "genial", "excelente"],         "MOOD_EXCITED"),
    (["amor", "te amo", "corazon"],                 "MOOD_LOVE"),
    (["sospechoso", "mmm", "raro"],                 "MOOD_SUSPICIOUS"),
    (["mareado", "confundido"],                     "MOOD_DIZZY"),
    (["normal", "neutral", "resetea"],              "MOOD_NORMAL"),
    # Reloj básico
    (["que hora", "hora es"],                       "QUERY_HORA"),
    # Pomodoro básico
    (["empieza pomodoro", "inicia pomodoro"],       "POMODORO_START"),
    (["para pomodoro", "deten pomodoro"],           "POMODORO_STOP"),
    (["cuanto falta"],                              "POMODORO_QUERY"),
]

MOOD_IDS = {
    "MOOD_NORMAL":     0,
    "MOOD_HAPPY":      1,
    "MOOD_SURPRISED":  2,
    "MOOD_SLEEPY":     3,
    "MOOD_ANGRY":      4,
    "MOOD_SAD":        5,
    "MOOD_EXCITED":    6,
    "MOOD_LOVE":       7,
    "MOOD_SUSPICIOUS": 8,
    "MOOD_DIZZY":      9,
}


def detect_intent(text: str) -> str:
    text = normalizar(text)
    text = _normalizar_pomodoro(text)
    for keywords, intent in INTENT_MAP:
        if any(re.search(r"\b" + re.escape(kw) + r"\b", text) for kw in keywords):
            return intent
    return "UNKNOWN"


def build_response(intent: str, text: str) -> dict:
    return {
        "intent":  intent,
        "mood_id": MOOD_IDS.get(intent, -1),
        "text":    text,
    }
