import pytest
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def post(text: str) -> dict:
    r = client.post("/transcribe", json={"text": text})
    assert r.status_code == 200
    return r.json()


def test_mood_sleepy_returns_correct_id():
    r = post("duerme un rato")
    assert r["intent"] == "MOOD_SLEEPY"
    assert r["mood_id"] == 3
    assert r["text"] == "duerme un rato"


def test_query_hora_mood_id_minus_one():
    r = post("qué hora es")
    assert r["intent"] == "QUERY_HORA"
    assert r["mood_id"] == -1


def test_pomodoro_start():
    r = post("inicia pomodoro")
    assert r["intent"] == "POMODORO_START"
    assert r["mood_id"] == -1


def test_unknown_intent():
    r = post("hola mundo")
    assert r["intent"] == "UNKNOWN"
    assert r["mood_id"] == -1


def test_normalisation_with_accents():
    r = post("estás bien hoy")
    assert r["intent"] == "MOOD_HAPPY"


def test_empty_text():
    r = post("")
    assert r["intent"] == "UNKNOWN"
