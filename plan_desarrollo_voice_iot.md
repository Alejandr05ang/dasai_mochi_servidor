# Plan de desarrollo: Voice IoT Monitor

## Objetivo
Construir un sistema de reconocimiento de voz para IoT con tres capas bien separadas:

- ESP32 captura audio desde el micrófono.
- Servidor recibe, agrupa, procesa y transcribe.
- Web muestra eventos, transcripciones e intents en tiempo real.

El orden recomendado es construir primero el servidor con datos mock, luego la web, y recién después conectar el ESP32 real.

## Estado actual

### Hecho

- Se creó la base del servidor en `server/`.
- Se añadió `POST /audio` para recibir chunks de audio.
- Se añadió `GET /ws` para conexiones en tiempo real.
- Se implementó un broadcaster mock que envía eventos cada 3 segundos.
- Se creó `requirements.txt` con las dependencias base.
- Se creó la base visual de la web en `web/`.
- La web ya se conecta por WebSocket y muestra eventos en vivo.
- La interfaz incluye estado de conexión, métricas y limpieza de eventos.
- Se agregó un buffer de audio por `device_id` + `session_id`.
- La ruta `/audio` ya acumula chunks y puede cerrar una sesión cuando llega `end=true`.

### Siguiente paso

- Probar el servidor y la web juntos.
- Definir el formato de audio que enviará el ESP32.
- Después pasar al envío real de audio desde el ESP32.

---

## Arquitectura general

### Flujo principal

1. El ESP32 captura audio por I2S.
2. El ESP32 envía chunks al servidor por HTTP.
3. El servidor acumula los chunks por `device_id` + `session_id`.
4. Cuando llega `end=true`, el servidor procesa el audio.
5. El motor STT transcribe el audio.
6. El parser de intents interpreta el texto.
7. El servidor notifica a la web por WebSocket.

### Separación de responsabilidades

- ESP32: captura y envío de audio.
- Servidor: recepción, buffer, transcripción, intents y broadcast.
- Web: visualización de eventos y estado.

Esta separación facilita depuración, mantenimiento y escalabilidad.

---

## Estructura sugerida del proyecto

```text
voice-iot/
├── server/
│   ├── main.py
│   ├── routes/
│   │   └── audio.py
│   ├── ws/
│   │   └── manager.py
│   ├── services/
│   │   ├── buffer.py
│   │   ├── stt.py
│   │   └── intents.py
│   └── requirements.txt
├── web/
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── esp32/
    └── firmware.ino
```

---

## Stack recomendado

### Servidor

- FastAPI
- Uvicorn
- WebSockets
- Vosk para STT en fase posterior

### Web

- HTML
- CSS
- JavaScript puro

### ESP32

- Arduino IDE o ESP-IDF
- I2S para el micrófono
- HTTPClient para envío de audio

---

## Fase 1: Esqueleto del servidor

### Meta
Tener un servidor funcional que acepte audio y WebSocket, aunque todavía no procese nada real.

### Tareas

1. Crear la estructura de carpetas del servidor.
2. Instalar dependencias base.
3. Implementar el administrador de conexiones WebSocket.
4. Crear la ruta HTTP `/audio`.
5. Crear el `main.py` con WebSocket y eventos mock.
6. Verificar que el servidor arranca y responde.

### Dependencias base

```txt
fastapi
uvicorn
websockets
```

### Endpoint HTTP esperado

- `POST /audio`

Debe recibir:

- `device-id`
- `session-id`
- `end`

Y devolver una respuesta simple tipo `200 OK`.

### WebSocket esperado

- `GET /ws`

Debe aceptar clientes y enviar eventos de prueba cada pocos segundos.

### Resultado esperado

- El servidor responde.
- La web puede conectarse.
- Los mensajes mock llegan por WebSocket.
- La base para las siguientes fases ya existe.

---

## Fase 2: Web conectada al mock

### Meta
Construir la interfaz antes de integrar el audio real, para separar errores de UI y de backend.

### Tareas

1. Crear un dashboard simple.
2. Conectar la web al WebSocket del servidor.
3. Mostrar logs en tiempo real.
4. Mostrar estados como:
   - conectado
   - recibiendo audio
   - procesando
   - transcripción
   - intent
5. Agregar reconexión automática.
6. Validar diseño responsive básico.

### Componentes mínimos de la web

- Panel de estado de conexión.
- Lista de eventos en vivo.
- Tarjeta con última transcripción.
- Tarjeta con último intent.

### Resultado esperado

- La UI funciona con eventos falsos.
- El flujo en vivo se ve correcto.
- La web ya queda lista para recibir datos reales.

---

## Fase 3: ESP32 enviando audio real

### Meta
Conectar el hardware y verificar que el audio llega al servidor.

### Tareas

1. Configurar I2S en el ESP32.
2. Leer audio desde el micrófono INMP441.
3. Capturar chunks de audio.
4. Enviar chunks por HTTP al endpoint `/audio`.
5. Probar conectividad WiFi.
6. Verificar en el servidor el tamaño y continuidad de los chunks.

### Puntos a definir

- Formato de audio enviado.
- Tamaño de chunk.
- Frecuencia de muestreo.
- Conversión a PCM si hace falta.

### Resultado esperado

- El servidor recibe audio real.
- Se puede ver el flujo de datos sin procesar.

---

## Fase 4: Buffer y cierre de sesión

### Meta
Guardar y agrupar correctamente el audio por dispositivo y sesión.

### Tareas

1. Crear buffer por `device_id` + `session_id`.
2. Ir acumulando chunks en memoria.
3. Detectar `end=true`.
4. Unir el audio completo al cierre.
5. Guardar el audio en disco para pruebas.
6. Verificar que el archivo resultante sea reproducible.

### Riesgos a resolver

- Sesiones huérfanas si el ESP32 se desconecta.
- Limpieza de buffers viejos por timeout.

### Resultado esperado

- El servidor arma correctamente un bloque de audio completo.
- Se confirma que el audio llega íntegro.

---

## Fase 5: Integrar Vosk

### Meta
Transcribir el audio dentro del servidor.

### Tareas

1. Instalar y configurar Vosk.
2. Cargar el modelo una sola vez al iniciar el servidor.
3. Convertir el audio al formato esperado:
   - PCM 16-bit
   - mono
   - 16 kHz idealmente
4. Ejecutar la transcripción.
5. Enviar el texto resultante por WebSocket.
6. Mostrar la transcripción en la web.

### Resultado esperado

- La web muestra el texto reconocido en tiempo real.
- El backend ya hace STT de punta a punta.

---

## Fase 6: Parser de intents

### Meta
Convertir transcripciones en acciones útiles para IoT.

### Tareas

1. Definir un diccionario de intents.
2. Normalizar texto:
   - minúsculas
   - sin tildes
   - sin caracteres especiales
3. Mapear frases a intents.
4. Retornar el intent en la respuesta HTTP.
5. Enviar el intent a la web por WebSocket.

### Ejemplo

- `enciende la luz` → `LUZ_ON`
- `apaga la luz` → `LUZ_OFF`

### Resultado esperado

- El sistema no solo transcribe, también interpreta comandos.

---

## Fase 7: Robustez

### Meta
Endurecer el sistema para uso real.

### Tareas

1. Agregar timeout para sesiones abandonadas.
2. Limpiar clientes WebSocket desconectados.
3. Manejar audio corrupto o incompleto.
4. Agregar logs estructurados.
5. Revisar manejo de errores en cada capa.

### Resultado esperado

- El sistema soporta desconexiones y fallos parciales sin romperse.

---

## Orden recomendado de trabajo

```text
1. Servidor mock
2. Web conectada al mock
3. ESP32 enviando audio real
4. Buffer y cierre de sesión
5. Vosk / STT
6. Parser de intents
7. Robustez
```

Este orden evita mezclar bugs de hardware, backend y frontend al mismo tiempo.

---

## Checklist práctico de arranque

### Servidor

- [ ] Crear carpeta `server/`
- [ ] Instalar FastAPI y Uvicorn
- [ ] Implementar `/audio`
- [ ] Implementar `/ws`
- [ ] Enviar eventos mock
- [ ] Probar con `curl`

### Web

- [ ] Crear `index.html`
- [ ] Conectar al WebSocket
- [ ] Mostrar eventos mock
- [ ] Mostrar última transcripción
- [ ] Mostrar último intent

### ESP32

- [ ] Configurar I2S
- [ ] Leer micrófono
- [ ] Enviar chunks por HTTP
- [ ] Confirmar recepción en servidor

---

## Próximo paso recomendado

Empezar por la Fase 1 con el servidor mínimo:

- crear la estructura,
- levantar FastAPI,
- abrir WebSocket,
- y emitir eventos mock.

Cuando eso funcione, la web puede construirse encima de ese contrato sin adivinar nada.
