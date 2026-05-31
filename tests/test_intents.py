import pytest
from server.services.intents import detect_intent, build_response, MOOD_IDS


# ---------------------------------------------------------------------------
# detect_intent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    # Expresiones — palabra clave directa
    ("estoy feliz",              "MOOD_HAPPY"),
    ("qué contento estoy",       "MOOD_HAPPY"),
    ("wow increíble",            "MOOD_SURPRISED"),
    ("duerme un rato",           "MOOD_SLEEPY"),
    ("estoy cansado",            "MOOD_SLEEPY"),
    ("enójate ya",               "MOOD_ANGRY"),
    ("estoy triste",             "MOOD_SAD"),
    ("qué genial",               "MOOD_EXCITED"),
    ("te amo mucho",             "MOOD_LOVE"),
    ("qué raro esto",            "MOOD_SUSPICIOUS"),
    ("estoy mareado",            "MOOD_DIZZY"),
    ("regresa a normal",         "MOOD_NORMAL"),
    # Con tildes (normalización)
    ("estás bien hoy",           "MOOD_HAPPY"),
    ("detén pomodoro",           "POMODORO_STOP"),
    # Reloj
    ("qué hora es",              "QUERY_HORA"),
    ("hora es ya",               "QUERY_HORA"),
    # Pomodoro
    ("empieza pomodoro ahora",   "POMODORO_START"),
    ("inicia pomodoro",          "POMODORO_START"),
    ("para pomodoro",            "POMODORO_STOP"),
    ("cuánto falta",             "POMODORO_QUERY"),
    # Sin match
    ("enciende la luz",          "UNKNOWN"),
    ("hola mundo",               "UNKNOWN"),
    ("",                         "UNKNOWN"),
])
def test_detect_intent(text, expected):
    assert detect_intent(text) == expected


# ---------------------------------------------------------------------------
# Variantes fonéticas de pomodoro (Vosk limitado)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("empieza comodoro",      "POMODORO_START"),
    ("inicia comodoro",       "POMODORO_START"),
    ("empieza pomo adoro",    "POMODORO_START"),
    ("inicia pom adoro",      "POMODORO_START"),
    ("empieza como adoro",    "POMODORO_START"),
    ("para comodoro",         "POMODORO_STOP"),
    ("deten comodoro",        "POMODORO_STOP"),
    ("para pomo adoro",       "POMODORO_STOP"),
    ("para como adoro",       "POMODORO_STOP"),
])
def test_pomodoro_aliases(text, expected):
    assert detect_intent(text) == expected


# ---------------------------------------------------------------------------
# build_response
# ---------------------------------------------------------------------------

def test_build_response_mood_fields():
    r = build_response("MOOD_SLEEPY", "duerme")
    assert r["intent"] == "MOOD_SLEEPY"
    assert r["mood_id"] == MOOD_IDS["MOOD_SLEEPY"]
    assert r["text"] == "duerme"


def test_build_response_non_mood_has_minus_one():
    r = build_response("QUERY_HORA", "qué hora es")
    assert r["mood_id"] == -1


def test_build_response_unknown_has_minus_one():
    r = build_response("UNKNOWN", "hola")
    assert r["mood_id"] == -1


def test_mood_ids_all_unique():
    values = list(MOOD_IDS.values())
    assert len(values) == len(set(values)), "IDs de mood duplicados"


def test_mood_ids_range():
    for name, mid in MOOD_IDS.items():
        assert 0 <= mid <= 9, f"{name} tiene id fuera de rango: {mid}"
