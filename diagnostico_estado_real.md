# Diagnóstico: Estado real del proyecto Voice IoT

Fecha: 2026-05-19

---

## 1. STT con Vosk — ¿funciona localmente?

**Respuesta corta: el código está listo, pero el modelo no está incluido.**

### Lo que existe y funciona

[server/services/stt.py](server/services/stt.py) tiene integración completa con Vosk:

- Carga el modelo al inicio buscando cualquier carpeta `vosk-model-*` dentro de `server/models/`
- Valida el formato del WAV (mono, 16-bit PCM)
- Hace resampleo si la frecuencia no es 16 kHz
- Ejecuta la transcripción de forma async
- Devuelve JSON con el texto reconocido o un error claro

[server/routes/audio_pcm16.py](server/routes/audio_pcm16.py) hace el resampleo 8 kHz → 16 kHz antes de pasar el audio a Vosk (con scipy si está disponible, con numpy como fallback).

Hay 16 archivos `.wav` grabados en `server/storage/` (hasta 1.9 MB). Esos archivos son el resultado de sesiones reales del ESP32.

### El bloqueo actual

El modelo de Vosk **no está en el repositorio**. Sin él, el servidor arranca pero `stt.py` lanza un error al intentar transcribir.

**Para desbloquearlo:**

```bash
# Descargar el modelo pequeño en español
# https://alphacephei.com/vosk/models
# vosk-model-small-es-0.42 (~40 MB)

mkdir server/models
# Descomprimir el modelo descargado dentro de server/models/
# La carpeta resultante debe llamarse: server/models/vosk-model-small-es-0.42 (o similar)
```

Además, `vosk` no está en [server/requirements.txt](server/requirements.txt). Hay que agregarlo:

```
vosk
```

### Para confirmar que funciona con los .wav grabados

```bash
# Desde el servidor corriendo:
curl "http://localhost:8000/transcribe?file=esp32_01_5038_1779099785.wav"
```

Si el modelo está instalado y el archivo tiene contenido de voz, devuelve texto. Si devuelve `""` (cadena vacía), el audio llegó silencioso o el formato no coincide con lo que Vosk espera.

---

## 2. intents.py — ¿lógica real o placeholder?

**Respuesta corta: placeholder. Solo tiene 2 reglas hardcodeadas.**

Contenido real de [server/services/intents.py](server/services/intents.py):

```python
def detect_intent(text: str) -> str:
    text = text.lower()
    if "enciende la luz" in text:
        return "LUZ_ON"
    if "apaga la luz" in text:
        return "LUZ_OFF"
    return "UNKNOWN"
```

No hay normalización de tildes, no hay sinónimos, no hay fuzzy matching, no hay modelo NLU. Cualquier frase que no sea exactamente esas dos devuelve `UNKNOWN`.

**Lo que falta para que sea funcional:**

- Normalizar el texto (minúsculas + quitar tildes) antes de comparar
- Ampliar el diccionario con variaciones comunes ("prende", "apaga", "ventilador", "temperatura", etc.)
- Opcionalmente: matching por palabras clave en lugar de frases exactas

Esto es trabajo de una tarde. No requiere modelos externos.

---

## 3. ¿El flujo completo cierra?

### Mapa del flujo actual

```
ESP32
  └─ POST /audio  (chunks PCM16, 8 kHz)
        └─ audio_pcm16.py
              ├─ buffer.py         acumula chunks
              ├─ audio_converter   resamplea 8→16 kHz
              ├─ stt.py            transcribe con Vosk  ← BLOQUEADO sin modelo
              ├─ intents.py        detecta intent       ← STUB (solo 2 reglas)
              └─ manager.py        broadcast por WS
                    └─ Web         muestra transcripción e intent
```

### Estado por tramo

| Tramo | Estado | Condición para funcionar |
|---|---|---|
| ESP32 → servidor (chunks) | Funciona | ESP32 configurado y en red |
| Servidor acumula buffer | Funciona | Nada extra |
| Conversión I2S / PCM16 | Funciona | Nada extra |
| Resampleo 8→16 kHz | Funciona | scipy recomendado, numpy como fallback |
| Vosk transcribe | **Bloqueado** | Falta modelo + `vosk` en requirements |
| intents.py clasifica | Funcional mínimo | Solo "enciende/apaga la luz" |
| WebSocket broadcast | Funciona | Nada extra |
| Web muestra resultado | No verificado | Requiere revisar `web/` |

### Veredicto

El flujo **no cierra todavía** porque el STT está bloqueado por el modelo ausente. Todo lo demás está encadenado correctamente. Una vez instalado el modelo Vosk, el único eslabón débil restante es `intents.py`.

---

## Próximos pasos en orden de prioridad

### 1. Instalar Vosk y el modelo (30 min)

```bash
pip install vosk
# Descargar vosk-model-small-es-0.42 y colocarlo en server/models/
```

Agregar `vosk` a [server/requirements.txt](server/requirements.txt).

### 2. Verificar con los .wav grabados (15 min)

Usar el endpoint `/transcribe` con los archivos que ya están en `server/storage/`. Confirmar que el texto devuelto tiene sentido. Si devuelve cadena vacía, verificar que el audio no esté en silencio o en el formato equivocado.

### 3. Expandir intents.py (1-2 horas)

Agregar normalización básica y al menos 10-15 comandos comunes. No requiere ninguna dependencia nueva.

### 4. Verificar la web (pendiente)

El directorio `web/` no fue examinado en este diagnóstico. Confirmar que el WebSocket client en la web procesa los mensajes de tipo `transcription` y `intent` que emite el servidor.

---

## Resumen ejecutivo

El servidor está en mejor estado del esperado. Las capas de recepción, buffer y broadcast son código de producción, no mocks. Los dos únicos puntos que impiden cerrar el flujo completo son concretos y pequeños: falta el modelo Vosk (descarga de ~40 MB) y `intents.py` es un placeholder de 8 líneas que necesita expansión. Ninguno de los dos requiere rediseño.
