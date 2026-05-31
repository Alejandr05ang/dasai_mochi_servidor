/*
  Voice IoT Monitor - ESP32 firmware (example)

  Objetivo:
  - Capturar audio por I2S (INMP441 u otro) y enviar chunks al servidor
    mediante HTTP POST a /audio con cabeceras: device-id, session-id, end

  Requisitos/Notas:
  - Ajusta `WIFI_SSID`, `WIFI_PASS` y `SERVER_URL`.
  - Este sketch es un punto de partida. Dependiendo de tu core de ESP32 y
    de la librería I2S disponible en tu instalación de Arduino IDE, puede
    necesitar pequeños ajustes en las llamadas a I2S.
  - INMP441 entrega I2S en 32 bits; aquí simplemente leemos el buffer
    y lo enviamos tal cual. En la Fase 5 del servidor convertiremos a
    PCM16/16kHz si hace falta. Si quieres, puedes convertir/filtrar aquí.
  - Para probar rápidamente, el sketch inicia sesión y envía chunks
    continuamente; puedes cambiar la lógica para grabar solo cuando
    detectes voz o al pulsar un botón.

  Cómo usar:
  1. Abrir en Arduino IDE.
  2. Ajustar WiFi y SERVER_URL.
  3. Seleccionar placa "ESP32 Dev Module" (u otra compatible).
  4. Compilar y subir.

*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <driver/i2s.h>
#include <esp_err.h>

// OLED SH1106 (use U8g2 library)
#include <Wire.h>
#include <U8g2lib.h>

// I2C pins for OLED (por defecto en esta placa)
#define OLED_SDA 6
#define OLED_SCL 7

// U8g2 constructor for SH1106 128x64 hardware I2C
U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0);

// Display/state variables
bool wifi_connected = false;
char ip_string[32] = "-";
bool i2s_ok = false;
int last_http_status = 0;
bool http_ever_sent = false;   // false until first finalSendTask completes
unsigned long total_bytes_sent = 0;

// --- CONFIGURA AQUI ---
const char* WIFI_SSID = "MARCO_1";
const char* WIFI_PASS = "dante0507";
const char* SERVER_URL = "https://crzs1qs4-5321.use.devtunnels.ms/audio/pcm16"; // Dev tunnel — no cambiar IP
const char* DEVICE_ID = "esp32_01"; // Identificador del dispositivo
// -----------------------

// --- Pines del micrófono (INMP441) — ajusta si los tuyos son distintos ---
#define I2S_SCK 4 // Pin BCLK (Reloj)
#define I2S_WS 1  // Pin L/R (Word Select)
#define I2S_SD 3  // Pin DIN (Datos)
#define I2S_PORT I2S_NUM_0
// -------------------------------------------------------------------------

// I2S configuration (ajusta según tu micrófono y placa)
// INMP441 suele trabajar con 32-bit I2S, 48kHz o 44.1kHz.
const int SAMPLE_RATE = 8000; // 8 kHz — tasa confirmada para el INMP441
const int I2S_BITS = 32; // bits per sample (ajusta a 32 si usas INMP441)

// Tamaño del chunk de lectura I2S (bytes de 32-bit).
// 4096 bytes = 1024 muestras = 64 ms @16 kHz — menos fragmentación HTTP.
const size_t CHUNK_SIZE = 4096;

// Modo de prueba: arrancar sesión automáticamente y mostrar muestras por Serial
#define AUTO_START_RECORDING false
#define DEBUG_PRINT_SAMPLES true
// Modo micrófono puro: no envía HTTP, solo imprime y muestra nivel
// Cambiar a false para permitir envíos HTTP al servidor
#define MIC_ONLY_MODE false

String sessionId;
bool recording = false;
// Touch TTP223 en GPIO2 (activo en HIGH por defecto)
#define BUTTON_PIN 2
const bool BUTTON_ACTIVE_HIGH = true;
int lastStableButtonState = LOW;
unsigned long lastDebounce = 0;
const unsigned long debounceDelay = 50;
int currentButtonReading = LOW;

// track session start time — SOLO para el guard del botón (>= 1500 ms), NO resetear con envíos
unsigned long sessionStart = 0;
// último envío intermedio exitoso — para el timer de seguridad (se puede resetear con envíos)

// GAIN_SHIFT confirmado por sketch de prueba: >>14 da rango ±8000–30000 sin clipar.
#define GAIN_SHIFT 14

// Duración máxima de la sesión en segundos de AUDIO REAL.
// 3 s es suficiente para "apaga la luz" / "enciende la luz".
// 3 × 8000 Hz × 2 bytes = 48 000 bytes — < 10 % del SRAM del ESP32-C6.
#define AUTO_SESSION_DURATION_S  5
#define AUTO_SESSION_AUDIO_BYTES ((unsigned long)AUTO_SESSION_DURATION_S * SAMPLE_RATE * 2)

// Buffer único que acumula TODA la sesión sin envíos intermedios.
// Sin HTTP bloqueante en el loop → ojos/buzzer/UI del Dasai Mochi nunca se interrumpen.
static uint8_t acc_buffer[AUTO_SESSION_AUDIO_BYTES]; // 48 000 bytes
size_t acc_offset = 0;
unsigned long sessionAudioBytes = 0;
String lastTranscription = "";

// Warmup: con alpha=1/64 (τ=8ms), 100ms cubre 12τ → 99.9% convergencia.
#define WARMUP_DURATION_MS 100
bool warmup_complete = false;
size_t warmup_samples = 0;

// --- Envío asíncrono: copia de la sesión completa para enviar en background ---
static uint8_t  _fs_buf[AUTO_SESSION_AUDIO_BYTES];
static size_t   _fs_len    = 0;
static String   _fs_sid    = "";
static volatile bool _fs_done   = false;
static volatile int  _fs_status = 0;
static TaskHandle_t  _fs_task   = NULL;

void finalSendTask(void*) {
  Serial.print("finalSend: _fs_len="); Serial.print(_fs_len);
  Serial.print(" heap="); Serial.println(ESP.getFreeHeap());
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClientSecure tls;
    tls.setInsecure(); // dev tunnel: omitir verificación de cert
    HTTPClient http;
    http.begin(tls, SERVER_URL);
    http.setTimeout(15000);
    http.addHeader("device-id", DEVICE_ID);
    http.addHeader("session-id", _fs_sid.c_str());
    http.addHeader("end", "true");
    http.addHeader("Content-Type", "application/octet-stream");
    _fs_status = http.sendRequest("POST", _fs_buf, _fs_len);
    if (_fs_status <= 0) {
      Serial.printf("finalSend HTTP error %d: %s\n", _fs_status, http.errorToString(_fs_status).c_str());
    }
    String payload = http.getString();
    if (_fs_status >= 200 && _fs_status < 300) {
      lastTranscription = parseTranscriptionText(payload);
      setMood(parseMoodId(payload));
    }
    http.end();
  } else {
    _fs_status = -4;
    Serial.println("finalSend: WiFi no conectado");
  }
  _fs_done = true;
  _fs_task = NULL;
  vTaskDelete(NULL);
}
// ---------------------------------------------------------------

// Función para convertir 32-bit I2S a 16-bit PCM
// Input: buffer de 32-bit samples (CHUNK_SIZE bytes)
// Output: buffer de 16-bit samples (CHUNK_SIZE/2 bytes)
size_t convert_i2s32_to_pcm16(const uint8_t* input, size_t input_len, uint8_t* output) {
  const int32_t* samples32 = (const int32_t*)input;
  int16_t* samples16 = (int16_t*)output;
  size_t num_samples = input_len / 4;  // 4 bytes por muestra 32-bit

  if (num_samples == 0) return 0;

  // EMA para DC removal — alpha = 1/64 → τ ≈ 8 ms @8 kHz, corte ~20 Hz.
  // Misma velocidad que el sketch de prueba validado; no afecta voz (>80 Hz).
  static int64_t dc_ema = 0;

  double sum_sq = 0.0;
  int32_t max_abs = 0;
  for (size_t i = 0; i < num_samples; i++) {
    int64_t s = (int64_t)samples32[i];
    dc_ema = ((dc_ema * 63) + s) >> 6;            // actualizar EMA de DC (alpha=1/64)
    int32_t centered = (int32_t)(s - dc_ema);    // restar DC suavemente
    int32_t absv = centered < 0 ? -centered : centered;
    if (absv > max_abs) max_abs = absv;
    sum_sq += (double)centered * centered;
    int32_t v = centered >> GAIN_SHIFT;
    if (v > 32767) v = 32767;
    if (v < -32768) v = -32768;
    samples16[i] = (int16_t)v;
  }

  // Mostrar info del chunk para diagnóstico de amplitud
#if defined(DEBUG_PRINT_SAMPLES)
  float rms = 0.0;
  if (num_samples > 0) rms = sqrt((double)sum_sq / (double)num_samples) / (1<<GAIN_SHIFT);
  Serial.print("chunk_peak_raw="); Serial.print(max_abs);
  Serial.print(" chunk_rms=" ); Serial.println(rms);
#endif

  return num_samples * 2;  // Retornar bytes de 16-bit
}

// Extrae el valor de "text" del JSON de respuesta del servidor.
String parseTranscriptionText(const String& json) {
  int idx = json.indexOf("\"text\":\"");
  if (idx < 0) return "";
  int start = idx + 8;
  int end = json.indexOf("\"", start);
  if (end <= start) return "";
  return json.substring(start, end);
}

// Extrae "mood_id" del JSON. Devuelve -1 si no está presente.
int parseMoodId(const String& json) {
  int idx = json.indexOf("\"mood_id\":");
  if (idx < 0) return -1;
  int start = idx + 10;
  int end = start;
  while (end < (int)json.length() && (isdigit(json[end]) || json[end] == '-')) end++;
  if (end == start) return -1;
  return json.substring(start, end).toInt();
}

// Aplica el mood recibido del servidor.
// mood_id coincide con MOOD_IDS del servidor (0=NORMAL, 1=HAPPY, ..., 9=DIZZY).
void setMood(int mood_id) {
  if (mood_id < 0) return;
  Serial.print("setMood: "); Serial.println(mood_id);
  // TODO: llamar animación de ojos/LEDs según mood_id
  // Ejemplo: eyes.play(mood_id);
}

// Muestra el texto de transcripción en el OLED con word-wrap automático.
void display_transcription(const String& text) {
  if (text.length() == 0) return;
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_5x7_tr); // ~21 chars por línea, 7 líneas en 64 px

  int y = 7;   // baseline inicial
  int pos = 0;
  int n = (int)text.length();

  while (pos < n && y <= 63) {
    // Añadir palabras hasta que no quepan en la línea
    int lineEnd = pos;
    int candidate = pos;
    while (candidate < n) {
      int wordEnd = candidate;
      while (wordEnd < n && text[wordEnd] != ' ') wordEnd++;
      String trial = text.substring(pos, wordEnd);
      if (u8g2.getStrWidth(trial.c_str()) > 126 && candidate > pos) break;
      lineEnd = wordEnd;
      candidate = wordEnd + 1;
      if (wordEnd >= n) break;
    }
    // Si ni una palabra entra (palabra muy larga), cortar por caracteres
    if (lineEnd == pos) {
      lineEnd = pos;
      while (lineEnd < n) {
        lineEnd++;
        if (u8g2.getStrWidth(text.substring(pos, lineEnd).c_str()) > 126) { lineEnd--; break; }
      }
      if (lineEnd == pos) lineEnd = pos + 1;
    }
    u8g2.drawStr(0, y, text.substring(pos, lineEnd).c_str());
    y += 9;
    pos = lineEnd;
    while (pos < n && text[pos] == ' ') pos++;
  }
  u8g2.sendBuffer();
}

void connectWiFi() {
  Serial.print("Conectando a WiFi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 40) {
    delay(500);
    Serial.print('.');
    tries++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi conectado!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
    wifi_connected = true;
    snprintf(ip_string, sizeof(ip_string), "%s", WiFi.localIP().toString().c_str());
    update_display();
  } else {
    Serial.println("\nNo se pudo conectar a WiFi");
  }
}

void update_display() {
  u8g2.clearBuffer();

  // ── Fila 1: WiFi + I2S ───────────────────────
  u8g2.setFont(u8g2_font_5x7_tr);
  char buf[48];
  snprintf(buf, sizeof(buf), "WiFi:%-2s  I2S:%-2s",
           wifi_connected ? "OK" : "NO",
           i2s_ok         ? "OK" : "NO");
  u8g2.drawStr(0, 7, buf);

  // ── Fila 2: IP ───────────────────────────────
  u8g2.drawStr(0, 15, ip_string);

  // ── Separador ────────────────────────────────
  u8g2.drawHLine(0, 17, 128);

  // ── Bloque de estado (y=19..39) ──────────────
  const char* stateLabel;
  bool invertBox = false;    // GRABANDO → caja rellena (máximo contraste)
  bool roundBox  = false;    // ENVIANDO → caja redondeada

  if (_fs_task != NULL) {
    stateLabel = "ENVIANDO...";
    roundBox   = true;
  } else if (!recording) {
    stateLabel = wifi_connected ? "LISTO" : "SIN WIFI";
  } else if (!warmup_complete) {
    stateLabel = "INICIANDO";
  } else {
    stateLabel = "GRABANDO";
    invertBox  = true;
  }

  const int BOX_Y = 19, BOX_H = 21;
  u8g2.setFont(u8g2_font_ncenB08_tr);
  int lw = u8g2.getStrWidth(stateLabel);
  int lx = (128 - lw) / 2;

  if (invertBox) {
    u8g2.drawBox(0, BOX_Y, 128, BOX_H);
    u8g2.setDrawColor(0);
    u8g2.drawStr(lx, BOX_Y + 14, stateLabel);
    u8g2.setDrawColor(1);
  } else if (roundBox) {
    u8g2.drawRFrame(0, BOX_Y, 128, BOX_H, 4);
    u8g2.drawStr(lx, BOX_Y + 14, stateLabel);
  } else {
    u8g2.drawFrame(0, BOX_Y, 128, BOX_H);
    u8g2.drawStr(lx, BOX_Y + 14, stateLabel);
  }

  // ── Separador ────────────────────────────────
  u8g2.drawHLine(0, 41, 128);

  // ── Hint contextual (centrado) ────────────────
  u8g2.setFont(u8g2_font_5x7_tr);
  const char* hint;
  if (_fs_task != NULL)         hint = "procesando audio...";
  else if (!recording)          hint = "toca para grabar";
  else if (!warmup_complete)    hint = "calibrando mic...";
  else                          hint = "suelta para enviar";

  int hw = u8g2.getStrWidth(hint);
  u8g2.drawStr((128 - hw) / 2, 51, hint);

  // ── HTTP ─────────────────────────────────────
  if (http_ever_sent)
    snprintf(buf, sizeof(buf), "HTTP:%d", last_http_status);
  else
    snprintf(buf, sizeof(buf), "HTTP:---");
  u8g2.drawStr(0, 63, buf);

  u8g2.sendBuffer();
}

void startSession() {
  acc_offset = 0;
  sessionAudioBytes = 0;
  warmup_complete = false;
  warmup_samples = 0;
  sessionId = String(millis());
  recording = true;
  sessionStart = millis();
  Serial.print("Nueva session: ");
  Serial.println(sessionId);
  update_display();
}

void stopSession() {
  recording = false;
  if (!MIC_ONLY_MODE && _fs_task == NULL) {
    memcpy(_fs_buf, acc_buffer, acc_offset);
    _fs_len    = acc_offset;
    _fs_sid    = sessionId;
    _fs_done   = false;
    _fs_status = 0;
    lastTranscription = "";
    xTaskCreatePinnedToCore(finalSendTask, "fSend", 8192, NULL, 1, &_fs_task, 0);
  }
  acc_offset = 0;
  update_display();
}

bool initI2S() {
  // Configuración que ya te funcionó con el INMP441.
  i2s_config_t default_cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    // 16 × 256 muestras × 4 bytes = 16 384 bytes ≈ 512 ms @8 kHz.
    // Evita que el DMA desborde mientras el HTTP está bloqueando.
    .dma_buf_count = 16,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };
  i2s_pin_config_t default_pins = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };
  esp_err_t err = i2s_driver_install(I2S_PORT, &default_cfg, 0, NULL);
  if (err == ESP_OK) {
    if (i2s_set_pin(I2S_PORT, &default_pins) == ESP_OK) {
      i2s_zero_dma_buffer(I2S_PORT);
      Serial.println("I2S driver instalado con config funcional ONLY_LEFT");
      i2s_ok = true;
      update_display();
      return true;
    }
  }

  Serial.println("I2S init falló completamente");
  i2s_ok = false;
  update_display();
  return false;
}

// Envía un chunk binario al servidor con las cabeceras requeridas
bool sendChunk(const uint8_t* data, size_t len, bool endFlag) {
  if (MIC_ONLY_MODE) {
    return true;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi no conectado, omitiendo envío");
    return false;
  }

  Serial.print("freeHeap before send: ");
  Serial.println(ESP.getFreeHeap());

  WiFiClientSecure tls;
  tls.setInsecure(); // dev tunnel: omitir verificación de cert
  HTTPClient http;
  http.begin(tls, SERVER_URL);
  http.setTimeout(5000);            // Intermedios: máx 5 s para no bloquear el loop
  if (endFlag) http.setTimeout(30000); // Final: espera a Vosk
  http.addHeader("device-id", DEVICE_ID);
  http.addHeader("session-id", sessionId.c_str());
  http.addHeader("end", endFlag ? "true" : "false");
  http.addHeader("Content-Type", "application/octet-stream");

  int statusCode = http.sendRequest("POST", (uint8_t*)data, len);
  if (statusCode <= 0) {
    Serial.printf("sendChunk HTTP error %d: %s\n", statusCode, http.errorToString(statusCode).c_str());
  }
  String payload = http.getString();
  Serial.print("HTTP ");
  Serial.print(statusCode);
  Serial.print(" -> ");
  Serial.println(payload);

  // Si es el último POST, extraer la transcripción de la respuesta JSON
  if (endFlag && statusCode >= 200 && statusCode < 300) {
    lastTranscription = parseTranscriptionText(payload);
    Serial.print("Transcripcion: ");
    Serial.println(lastTranscription);
  }

  http.end();
  Serial.print("freeHeap after send: ");
  Serial.println(ESP.getFreeHeap());
  yield();
  last_http_status = statusCode;
  if (len > 0) total_bytes_sent += len;
  update_display();
  return (statusCode >= 200 && statusCode < 300);
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  // Inicializar I2C y pantalla
  Wire.begin(OLED_SDA, OLED_SCL);
  u8g2.begin();
  update_display();

  if (!MIC_ONLY_MODE) {
    connectWiFi();
  } else {
    Serial.println("MIC_ONLY_MODE enabled: skipping WiFi and HTTP");
  }

  if (!initI2S()) {
    Serial.println("Fallo inicialización I2S. Continua sin micrófono para pruebas.");
    // Nota: si no tienes I2S listo, puedes simular envíos comentando el init.
  }

  // Configurar TTP223 como entrada digital normal
  pinMode(BUTTON_PIN, INPUT);
  currentButtonReading = digitalRead(BUTTON_PIN);
  lastStableButtonState = currentButtonReading;
  Serial.print("Touch inicial: ");
  Serial.println(currentButtonReading);
  update_display();

  // Para demo, arrancamos sesión automáticamente
  //startSession();
  if (AUTO_START_RECORDING) {
    Serial.println("AUTO_START_RECORDING enabled -> starting session");
    startSession();
  }
}

void loop() {
  // ===== RESULTADO DEL ENVÍO FINAL (tarea en background) =====
  if (_fs_done) {
    _fs_done = false;
    last_http_status = _fs_status;
    http_ever_sent = true;
    update_display();
    if (_fs_status >= 200 && _fs_status < 300) {
      // Éxito: mostrar transcripción si la hay
      if (lastTranscription.length() > 0) {
        display_transcription(lastTranscription);
        lastTranscription = "";
      }
    } else {
      // Fallo del envío final: log sin bloquear el reinicio
      Serial.print("Envio final fallido, HTTP: ");
      Serial.println(_fs_status);
    }
  }

  // ===== DETECCIÓN DE BOTÓN (siempre activa) =====
  int reading = digitalRead(BUTTON_PIN);
  if (reading != currentButtonReading) {
    Serial.print("Touch cambio -> ");
    Serial.println(reading);
  }
  
  // Debounce: si el pin cambió, registra el tiempo
  if (reading != currentButtonReading) {
    lastDebounce = millis();
    currentButtonReading = reading;
  }
  
  // Si pasó el tiempo de debounce Y el estado es estable
  if ((millis() - lastDebounce) > debounceDelay && reading != lastStableButtonState) {
    int previousState = lastStableButtonState;
    lastStableButtonState = reading;
    
    // PTT: mantener presionado = grabar; soltar = enviar
    if (BUTTON_ACTIVE_HIGH) {
      if (previousState == LOW && reading == HIGH) {
        // Presión: iniciar grabación
        if (!recording && _fs_task == NULL) {
          Serial.println("PTT: inicio grabacion");
          startSession();
        } else if (_fs_task != NULL) {
          Serial.println("PTT: aun enviando, ignorado");
        }
      } else if (previousState == HIGH && reading == LOW) {
        // Soltar: detener y enviar
        if (recording) {
          Serial.println("PTT: fin grabacion");
          stopSession();
        }
      }
    } else {
      // Sensor activo LOW
      if (previousState == HIGH && reading == LOW) {
        if (!recording && _fs_task == NULL) {
          Serial.println("PTT: inicio grabacion (activo LOW)");
          startSession();
        }
      } else if (previousState == LOW && reading == HIGH) {
        if (recording) {
          Serial.println("PTT: fin grabacion (activo LOW)");
          stopSession();
        }
      }
    }
  }
  
  // ===== GRABACIÓN =====
  if (!recording) {
    delay(50);
    yield();
    return;
  }

  // Buffer temporal para lectura I2S (igual que en el sketch funcional)
  static int32_t sampleBuffer[CHUNK_SIZE / 4];
  // Buffer temporal para audio convertido a 16-bit
  static uint8_t buffer_pcm16[CHUNK_SIZE / 2];

  // Intentamos leer datos desde I2S usando el driver nativo
  size_t bytesRead = 0;
  // Timeout de 1 s para no bloquear el watchdog si I2S no tiene datos.
  esp_err_t r = i2s_read(I2S_PORT, sampleBuffer, sizeof(sampleBuffer), &bytesRead, pdMS_TO_TICKS(1000));
  Serial.print("i2s_read result: "); Serial.println((int)r);
  if (r == ESP_OK && bytesRead > 0) {
    // Dump primeros bytes para depuración
#if defined(DEBUG_PRINT_SAMPLES)
    Serial.print("bytesRead="); Serial.println(bytesRead);
    Serial.print("raw32[0..7]: ");
    int samplesRead = bytesRead / 4;
    for (int si = 0; si < min(8, samplesRead); si++) {
      Serial.print(sampleBuffer[si]); Serial.print(' ');
    }
    Serial.println();
#endif
    // Convertir 32-bit a 16-bit
    size_t pcm16_len = convert_i2s32_to_pcm16((const uint8_t*)sampleBuffer, bytesRead, buffer_pcm16);
#if defined(DEBUG_PRINT_SAMPLES)
    // Mostrar primeros 8 muestras PCM16
    Serial.print("pcm16[0..7]: ");
    int16_t* pcm16_view = (int16_t*)buffer_pcm16;
    size_t pcm_samples = pcm16_len / 2;
    for (size_t si = 0; si < min((size_t)8, pcm_samples); si++) {
      Serial.print(pcm16_view[si]); Serial.print(' ');
    }
    Serial.println();
#endif
    
    if (!MIC_ONLY_MODE && pcm16_len > 0) {
      // Warmup: descartar los primeros ~200ms para dejar que EMA de DC converja
      if (!warmup_complete) {
        size_t warmup_bytes_needed = (SAMPLE_RATE * WARMUP_DURATION_MS / 1000) * 2;  // 2 bytes per sample
        warmup_samples += pcm16_len;
        Serial.print("Warmup: "); Serial.print(warmup_samples); Serial.print(" / "); Serial.println(warmup_bytes_needed);
        if (warmup_samples >= warmup_bytes_needed) {
          warmup_complete = true;
          Serial.println("Warmup complete, audio grabación iniciada");
          update_display();
        }
        return;  // descartar este chunk
      }

      // Acumular en el buffer único de sesión (sin envíos intermedios bloqueantes).
      // El loop nunca hace HTTP aquí → ojos/buzzer/UI continúan sin interrupción.
      size_t space = sizeof(acc_buffer) - acc_offset;
      size_t to_copy = pcm16_len < space ? pcm16_len : space;
      memcpy(acc_buffer + acc_offset, buffer_pcm16, to_copy);
      acc_offset += to_copy;
      sessionAudioBytes += to_copy;
      Serial.print("audioBytes="); Serial.println(sessionAudioBytes);
    }
  } else {
    delay(10);
    yield();
  }

  // Auto-stop: buffer lleno = AUTO_SESSION_DURATION_S segundos de audio capturados.
  if (recording && warmup_complete && sessionAudioBytes >= AUTO_SESSION_AUDIO_BYTES) {
    Serial.print("Auto-stop: ");
    Serial.print(AUTO_SESSION_DURATION_S);
    Serial.println("s de audio capturados");
    stopSession();
  }

  // Timeout de seguridad: si la sesión no termina en 60 s de reloj, forzar cierre.
  if (sessionStart == 0) sessionStart = millis();
  if (recording && millis() - sessionStart > 60000) {
    Serial.println("Sesion finalizada por timeout de seguridad");
    stopSession();
  }
}

// (declaración movida arriba)
