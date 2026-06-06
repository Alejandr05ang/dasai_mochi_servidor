import re
import unicodedata


def normalizar(texto: str) -> str:
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


# Variantes fonéticas que Vosk produce en lugar de "pomodoro"
# IMPORTANTE: usar re.sub con \b — str.replace sin límites de palabra corrompe
# el texto cuando un alias es prefijo de otro (e.g. "pomodor" ⊂ "pomodoro").
_POMODORO_ALIASES = [
    "comodoro",
    "comodor",      # parcial sin 'o' final
    "como doro",
    "como dor",
    "como adoro",
    "pomo doro",
    "pomo dor",
    "pongo doro",
    "pongo dor",
    "pomo adoro",
    "pom adoro",
    "pomó doro",
    "pomo loro",
    "como loro",
    "pomodor",      # parcial sin 'o' final — va al final para no tocar "pomodoro"
]

def _normalizar_pomodoro(texto: str) -> str:
    for alias in _POMODORO_ALIASES:
        texto = re.sub(r"\b" + re.escape(alias) + r"\b", "pomodoro", texto)
    return texto


# Variantes fonéticas que Vosk produce en lugar de "gif"
# (Vosk no tiene "gif" en vocabulario español y lo reemplaza por palabras parecidas)
_GIF_ALIASES = [
    "guia",
    "guie",
    "gui",
    "guif",
    "giff",
    "jif",
    "jiff",
    "gym",      # Vosk confunde "gif" con "gym"
    "gif",
]

def _normalizar_gif(texto: str) -> str:
    for alias in _GIF_ALIASES:
        texto = re.sub(r"\b" + re.escape(alias) + r"\b", "gif", texto)
    return texto


# Variantes fonéticas que Vosk produce en lugar de "canvas"
_CANVAS_ALIASES = [
    "chambas",
    "chamba",   # Vosk produce singular y plural según el contexto
    "camba",
    "cambas",
    "campus",
    "canbas",
    "camvas",
    "can bas",
    "can vas",
    "canba",
    "champa",
    "champas",
]

def _normalizar_canvas(texto: str) -> str:
    for alias in _CANVAS_ALIASES:
        texto = re.sub(r"\b" + re.escape(alias) + r"\b", "canvas", texto)
    return texto


# Infinitivos → imperativos: Vosk suele producir la forma infinitiva cuando el
# hablante dice el imperativo (e.g. "abre" → "abrir", "pon" → "poner").
_VERB_NORM = [
    (r"\babrir\b",   "abre"),
    (r"\bponer\b",   "pon"),
    (r"\bmostrar\b", "muestra"),
    (r"\bvolver\b",  "vuelve"),
    (r"\bparar\b",   "para"),
    (r"\bpausar\b",  "pausa"),
]

def _normalizar_verbos(texto: str) -> str:
    for pattern, replacement in _VERB_NORM:
        texto = re.sub(pattern, replacement, texto)
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
        return "POMODORO_PAUSE"
    return None


INTENT_MAP = [
    # ── NAVEGACIÓN DE MODOS ─────────────────────────────────────────────
    (["abre mascota", "ir a mascota", "modo mascota",
      "ve a mascota", "mascota",
      "muestra mascota", "pon mascota"],                  "GOTO_MASCOTA"),

    (["abre gif", "ir a gif", "modo gif", "abre gifs",
      "ve a gif", "muestra gif", "pon gif",
      "animacion", "animaciones"],                        "GOTO_GIF"),

    (["abre reloj", "ir a reloj", "modo reloj",
      "que hora es", "que hora son",
      "ver reloj", "muestra reloj", "pon reloj",
      "ver hora"],                                        "GOTO_HORA"),

    (["abre clima", "ir a clima", "modo clima",
      "que tiempo hace", "como esta el clima",
      "ver clima", "muestra clima", "pon clima",
      "como esta el tiempo", "temperatura"],              "GOTO_CLIMA"),

    (["abre pomodoro", "ir a pomodoro", "modo pomodoro",
      "ver pomodoro", "muestra pomodoro", "pon pomodoro",
      "temporizador", "timer"],                           "GOTO_POMODORO"),

    (["abre canvas", "ir a canvas", "modo canvas",
      "ver canvas", "muestra canvas", "pon canvas",
      "pantalla web", "dibujo web"],                      "GOTO_CANVAS"),

    (["abre menu", "ir al menu", "menu principal",
      "ver menu", "muestra menu", "volver al menu",
      "inicio"],                                          "GOTO_MENU"),

    # ── ACCIONES — MODO GIF ─────────────────────────────────────────────
    (["pausa gif", "pausar gif", "detener gif",
      "para gif", "congela gif", "frena gif"],            "GIF_PAUSE"),

    (["reanuda gif", "reanudar gif", "continua gif",
      "continuar gif", "play gif", "reproduce gif"],      "GIF_RESUME"),

    (["siguiente gif", "proximo gif", "otro gif",
      "cambia gif", "cambiar gif", "siguiente animacion",
      "proxima animacion"],                               "GIF_NEXT"),

    # ── ACCIONES — MODO HORA ────────────────────────────────────────────
    (["muestra segundos", "mostrar segundos",
      "ver segundos", "agrega segundos",
      "con segundos"],                                    "HORA_SHOW_SECONDS"),

    (["quita segundos", "quitar segundos",
      "sin segundos", "oculta segundos",
      "ocultar segundos"],                                "HORA_HIDE_SECONDS"),

    (["toggle segundos", "cambia segundos",
      "segundos"],                                        "HORA_TOGGLE_SECONDS"),

    # ── ACCIONES — MODO CLIMA ───────────────────────────────────────────
    (["vista actual", "clima ahora", "temperatura ahora",
      "como esta ahora", "tiempo ahora"],                 "CLIMA_VIEW_NOW"),

    (["vista hoy", "clima hoy", "resumen hoy",
      "como estara hoy", "pronostico hoy"],               "CLIMA_VIEW_TODAY"),

    (["actualiza clima", "actualizar clima",
      "refresca clima", "refrescar clima"],               "CLIMA_REFRESH"),

    # ── ACCIONES — MODO POMODORO ────────────────────────────────────────
    (["empieza pomodoro", "inicia pomodoro",
      "iniciar pomodoro", "empezar pomodoro",
      "arranca pomodoro", "start pomodoro"],              "POMODORO_START"),

    (["pausa pomodoro", "pausar pomodoro",
      "para pomodoro", "deten pomodoro",
      "detener pomodoro", "espera pomodoro"],             "POMODORO_PAUSE"),

    (["reanuda pomodoro", "reanudar pomodoro",
      "continua pomodoro", "continuar pomodoro",
      "sigue pomodoro"],                                  "POMODORO_RESUME"),

    (["reinicia pomodoro", "reiniciar pomodoro",
      "resetea pomodoro", "reset pomodoro",
      "vuelve a empezar"],                                "POMODORO_RESET"),

    (["cuanto falta", "cuanto tiempo falta",
      "tiempo falta", "tiempo queda",
      "cuanto queda", "cuanto le falta"],                 "POMODORO_QUERY"),

    (["agrega tiempo", "agregar tiempo",
      "mas tiempo", "añade tiempo",
      "suma tiempo"],                                     "POMODORO_ADD_TIME"),

    (["quita tiempo", "quitar tiempo",
      "menos tiempo", "reduce tiempo",
      "resta tiempo"],                                    "POMODORO_SUB_TIME"),

    # ── EXPRESIONES / MOOD ──────────────────────────────────────────────
    (["feliz", "contento", "bien", "como estas",
      "alegra", "alegrarte", "alegrate",
      "pon feliz", "ponte feliz"],                        "MOOD_HAPPY"),

    (["sorpresa", "sorprendete", "sorprenderte",
      "wow", "increible", "que sorpresa",
      "pon sorprendido"],                                 "MOOD_SURPRISED"),

    (["duerme", "dormir", "descansa", "descansar",
      "cansado", "cansada", "que sueno",
      "pon dormido", "pon somnoliento"],                  "MOOD_SLEEPY"),

    (["enojate", "enojarte", "enojas", "enojado",
      "molesto", "furioso", "enoja",
      "pon enojado", "ponte furioso"],                    "MOOD_ANGRY"),

    (["triste", "llora", "llorar", "mal",
      "tristeza", "deprimido",
      "pon triste", "ponte triste"],                      "MOOD_SAD"),

    (["emocionado", "genial", "excelente",
      "emocionarte", "emocionate",
      "pon emocionado", "muy bien"],                      "MOOD_EXCITED"),

    (["amor", "te amo", "corazon",
      "amoroso", "enamorado",
      "pon amoroso", "con amor"],                         "MOOD_LOVE"),

    (["sospechoso", "mmm", "raro",
      "sospecha", "sospechar", "desconfiado",
      "pon sospechoso"],                                  "MOOD_SUSPICIOUS"),

    (["mareado", "confundido",
      "mareo", "marearte", "confundir",
      "pon mareado"],                                     "MOOD_DIZZY"),

    (["normal", "neutral", "resetea expresion",
      "resetear expresion", "reinicia expresion",
      "cara normal", "pon normal"],                       "MOOD_NORMAL"),
]

# Intents que el ESP32 reconoce en parseCommand() — referencia para sincronizar servidor ↔ firmware
ESP32_COMMANDS = [
    "GOTO_MENU", "GOTO_MASCOTA", "GOTO_GIF",
    "GOTO_HORA", "GOTO_CLIMA", "GOTO_POMODORO", "GOTO_CANVAS",
    "GIF_PAUSE", "GIF_RESUME", "GIF_NEXT",
    "HORA_SHOW_SECONDS", "HORA_HIDE_SECONDS", "HORA_TOGGLE_SECONDS",
    "CLIMA_VIEW_NOW", "CLIMA_VIEW_TODAY", "CLIMA_REFRESH",
    "POMODORO_START", "POMODORO_PAUSE", "POMODORO_RESUME",
    "POMODORO_RESET", "POMODORO_QUERY", "POMODORO_ADD_TIME", "POMODORO_SUB_TIME",
    "MOOD_NORMAL", "MOOD_HAPPY", "MOOD_SURPRISED", "MOOD_SLEEPY",
    "MOOD_ANGRY", "MOOD_SAD", "MOOD_EXCITED", "MOOD_LOVE",
    "MOOD_SUSPICIOUS", "MOOD_DIZZY",
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
    text = _normalizar_verbos(text)
    text = _normalizar_pomodoro(text)
    text = _normalizar_gif(text)
    text = _normalizar_canvas(text)
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
