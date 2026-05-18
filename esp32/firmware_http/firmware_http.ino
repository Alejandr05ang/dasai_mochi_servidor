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
unsigned long total_bytes_sent = 0;

// --- CONFIGURA AQUI ---
const char* WIFI_SSID = "MARCO_1";
const char* WIFI_PASS = "dante0507";
const char* SERVER_URL = "http://192.168.18.171:8000/audio/pcm16"; // Cambia por la IP de tu servidor
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
#define AUTO_START_RECORDING true
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

// track session start time (inicializado cuando comienza la sesión)
unsigned long sessionStart = 0;

// GAIN_SHIFT: cuanto menor, mayor amplitud PCM16.
// >>14 era demasiado silencioso (~4-15 % del fondo de escala).
// >>12 da ~60 % para voz normal, rara vez clipea.
#define GAIN_SHIFT 12

// Acumular N lecturas I2S antes de cada POST HTTP.
// 4 lecturas × 128 ms = 512 ms de audio por envío → menos overhead HTTP.
#define SEND_EVERY_N_CHUNKS 4
uint8_t acc_buffer[SEND_EVERY_N_CHUNKS * (CHUNK_SIZE / 2)]; // 8 192 bytes
size_t acc_offset = 0;
String lastTranscription = ""; // última transcripción recibida del servidor

// Función para convertir 32-bit I2S a 16-bit PCM
// Input: buffer de 32-bit samples (CHUNK_SIZE bytes)
// Output: buffer de 16-bit samples (CHUNK_SIZE/2 bytes)
size_t convert_i2s32_to_pcm16(const uint8_t* input, size_t input_len, uint8_t* output) {
  const int32_t* samples32 = (const int32_t*)input;
  int16_t* samples16 = (int16_t*)output;
  size_t num_samples = input_len / 4;  // 4 bytes por muestra 32-bit

  if (num_samples == 0) return 0;

  // EMA para DC removal — la variable es estática y persiste entre llamadas.
  // Al ser continua entre chunks no crea saltos → elimina el artefacto de "hélice".
  // alpha = 1/512 → τ ≈ 64 ms @8 kHz; solo filtra sub-2.5 Hz (no afecta la voz).
  static int64_t dc_ema = 0;

  int64_t sum_sq = 0;
  int32_t max_abs = 0;
  for (size_t i = 0; i < num_samples; i++) {
    int64_t s = (int64_t)samples32[i];
    dc_ema = ((dc_ema * 511) + s) >> 9;          // actualizar EMA de DC
    int32_t centered = (int32_t)(s - dc_ema);    // restar DC suavemente
    int32_t absv = centered < 0 ? -centered : centered;
    if (absv > max_abs) max_abs = absv;
    sum_sq += (int64_t)centered * centered;
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
  // Initialize Wire and display if not already
  // (u8g2.begin should be called from setup once)
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_ncenB08_tr);
  u8g2.drawStr(0, 10, "Voice IoT");

  // WiFi status
  char buf[64];
  snprintf(buf, sizeof(buf), "WiFi: %s", wifi_connected ? "OK" : "NO");
  u8g2.drawStr(0, 25, buf);

  // IP
  u8g2.drawStr(0, 37, ip_string);

  // I2S / mic
  snprintf(buf, sizeof(buf), "I2S: %s", i2s_ok ? "OK" : "NO");
  u8g2.drawStr(0, 49, buf);

  // Touch / HTTP
  snprintf(buf, sizeof(buf), "Touch:%s HTTP:%d", recording ? "REC" : "WAIT", last_http_status);
  u8g2.drawStr(0, 61, buf);

  u8g2.sendBuffer();
}

void startSession() {
  acc_offset = 0; // limpiar buffer acumulador de la sesión anterior
  sessionId = String(millis());
  recording = true;
  Serial.print("Nueva session: ");
  Serial.println(sessionId);
  sessionStart = millis();
  Serial.print("sessionStart= "); Serial.println(sessionStart);
  update_display();
}

void stopSession() {
  if (!MIC_ONLY_MODE) {
    lastTranscription = "";
    sendChunk(acc_buffer, acc_offset, true); // flush + end=true
    acc_offset = 0;
  }
  recording = false;
  update_display();
  // Mostrar resultado en OLED (sobreescribe el estado de grabación)
  if (lastTranscription.length() > 0) {
    display_transcription(lastTranscription);
  }
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

  HTTPClient http;
  http.begin(SERVER_URL);
  // El POST final espera que Vosk termine → dar hasta 30 s
  if (endFlag) http.setTimeout(30000);
  http.addHeader("device-id", DEVICE_ID);
  http.addHeader("session-id", sessionId.c_str());
  http.addHeader("end", endFlag ? "true" : "false");
  http.addHeader("Content-Type", "application/octet-stream");

  int statusCode = http.sendRequest("POST", (uint8_t*)data, len);
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
    
    // TTP223: transición LOW → HIGH = toque detectado
    if (BUTTON_ACTIVE_HIGH && previousState == LOW && reading == HIGH) {
      if (!recording) {
        Serial.println("Entro a la sesion");
        startSession();
      }
    }
    // TTP223: transición HIGH → LOW = toque liberado
    else if (BUTTON_ACTIVE_HIGH && previousState == HIGH && reading == LOW) {
      if (recording) {
        Serial.println("Sesión finalizada por pulsador");
        stopSession(); // stopSession envía flush + end=true
      }
    }

    // Si el sensor viniera cableado al revés, esta rama ayuda a depurar rápido
    else if (!BUTTON_ACTIVE_HIGH && previousState == HIGH && reading == LOW) {
      if (!recording) {
        Serial.println("Entro a la sesion (activo LOW)");
        startSession();
      }
    } else if (!BUTTON_ACTIVE_HIGH && previousState == LOW && reading == HIGH) {
      if (recording) {
        Serial.println("Sesión finalizada por pulsador (activo LOW)");
        stopSession(); // stopSession envía flush + end=true
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
      // Acumular en el buffer; enviar solo cuando esté lleno (reduce POSTs HTTP)
      memcpy(acc_buffer + acc_offset, buffer_pcm16, pcm16_len);
      acc_offset += pcm16_len;
      Serial.print("acc_offset="); Serial.println(acc_offset);
      if (acc_offset >= sizeof(acc_buffer)) {
        bool ok = sendChunk(acc_buffer, acc_offset, false);
        if (!ok) Serial.println("Envio fallido; continuando...");
        acc_offset = 0;
      }
    }
  } else {
    // Si no hay datos, esperar un poco
    delay(10);
    yield();
  }

  // Ejemplo: cerrar sesión después de cierto tiempo (p.ej. 60s)
  if (sessionStart == 0) sessionStart = millis();
  if (millis() - sessionStart > 20000) {
    Serial.println("Sesión finalizada por timeout");
    stopSession(); // stopSession envía flush + end=true
    // Para demo, recalculamos nueva session tras 5s
    delay(5000);
    yield();
    //startSession();
    sessionStart = millis();
  }
}

// (declaración movida arriba)