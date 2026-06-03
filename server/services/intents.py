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
    "como doro",
    "como adoro",
    "pomo doro",
    "pomo adoro",
    "pom adoro",
    "pomó doro",
    "pomo loro",
    "como loro",
    "pomodor",
]

def _normalizar_pomodoro(texto: str) -> str:
    for alias in _POMODORO_ALIASES:
        texto = texto.replace(alias, "pomodoro")
    return texto


# Verbos de inicio/parada — se buscan como substrings tras normalizar
_VERBOS_INICIO = [
    "empieza", "empezar", "empeza",
    "inicia", "iniciar",
    "comienza", "comenzar",
    "arranca", "arrancar",
    "activa", "activar",
    "pon", "poner",
    "arranca", "lanza", "lanzar",
    "start",
]
_VERBOS_PARADA = [
    "para", "parar",
    "deten", "detener",
    "cancela", "cancelar",
    "termina", "terminar",
    "acaba", "acabar",
    "frena", "frenar",
    "stop",
]


def _detect_pomodoro(text: str) -> str | None:
    if "pomodoro" not in text:
        return None
    if any(v in text for v in _VERBOS_INICIO):
        return "POMODORO_START"
    if any(v in text for v in _VERBOS_PARADA):
        return "POMODORO_STOP"
    return None


INTENT_MAP = [
    # Expresiones
    (["feliz", "contento", "bien", "como estas",
      "alegra", "alegrarte", "alegrate"],           "MOOD_HAPPY"),
    (["sorpresa", "sorprendete", "sorprenderte",
      "wow", "increible"],                          "MOOD_SURPRISED"),
    (["duerme", "dormir", "descansa", "descansar",
      "cansado", "cansada"],                        "MOOD_SLEEPY"),
    (["enojate", "enojarte", "enojas", "enojado",
      "molesto", "furioso", "enoja"],               "MOOD_ANGRY"),
    (["triste", "llora", "llorar", "mal",
      "tristeza", "deprimido"],                     "MOOD_SAD"),
    (["emocionado", "genial", "excelente",
      "emocionarte", "emocionate"],                 "MOOD_EXCITED"),
    (["amor", "te amo", "corazon",
      "amoroso", "enamorado"],                      "MOOD_LOVE"),
    (["sospechoso", "mmm", "raro",
      "sospecha", "sospechar", "desconfiado"],      "MOOD_SUSPICIOUS"),
    (["mareado", "confundido",
      "mareo", "marearte", "confundir"],            "MOOD_DIZZY"),
    (["normal", "neutral", "resetea",
      "resetear", "reinicia", "reiniciar"],         "MOOD_NORMAL"),
    # Reloj básico
    (["que hora", "hora es"],                       "QUERY_HORA"),
    # Pomodoro — fallback si _detect_pomodoro no captura
    (["empieza pomodoro", "inicia pomodoro",
      "iniciar pomodoro", "empezar pomodoro"],      "POMODORO_START"),
    (["para pomodoro", "deten pomodoro",
      "parar pomodoro", "detener pomodoro"],        "POMODORO_STOP"),
    (["cuanto falta", "tiempo falta",
      "tiempo queda", "cuanto queda"],              "POMODORO_QUERY"),
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
    pomodoro = _detect_pomodoro(text)
    if pomodoro:
        return pomodoro
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
