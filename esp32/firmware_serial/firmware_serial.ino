/*
  Voice IoT Monitor - ESP32 firmware
  Transmite audio crudo del micrófono por Serial a 500000 baud
  
  Presiona botón G4 para iniciar/detener grabación
  El audio se envía como PCM16 en tiempo real por el puerto Serial
*/

#include <driver/i2s.h>
// OLED display via I2C using Adafruit GFX + SH110X driver
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

// --- Pines del micrófono (INMP441) ---
#define I2S_WS 17   // Pin L/R (Word Select)
#define I2S_SCK 18  // Pin BCLK (Reloj)
#define I2S_SD 16   // Pin DIN (Datos)
#define I2S_PORT I2S_NUM_0

// --- Pines y periféricos ---
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT  64
#define SDA_PIN        21
#define SCL_PIN        22
#define TOUCH_PIN      15
#define BUZZER_PIN     19
#define MODE_BTN_PIN   4

// --- Botón en pin G4 (alias) ---
#define BUTTON_PIN MODE_BTN_PIN
int lastStableButtonState = HIGH;
unsigned long lastDebounce = 0;
const unsigned long debounceDelay = 50;
int currentButtonReading = HIGH;

bool recording = false;

// --- OLED object ---
Adafruit_SH1106G display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1, 400000, 100000);

// Helper: draw text with simple wrapping, show last N lines
void displayText(const String &text) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  const int charWidth = 6; // approx width in pixels for textSize=1
  const int charHeight = 8;
  int charsPerLine = SCREEN_WIDTH / charWidth;
  int maxLines = SCREEN_HEIGHT / charHeight;

  String lines[8];
  int lineCount = 0;

  String remaining = text;
  while (remaining.length() > 0 && lineCount < 8) {
    if (remaining.length() <= (size_t)charsPerLine) {
      lines[lineCount++] = remaining;
      break;
    }

    int cut = charsPerLine;
    for (int i = charsPerLine - 1; i > 0; --i) {
      if (remaining[i] == ' ') {
        cut = i;
        break;
      }
    }

    lines[lineCount++] = remaining.substring(0, cut);
    if ((int)remaining.length() > cut) {
      remaining = remaining.substring(cut + (remaining[cut] == ' ' ? 1 : 0));
    } else {
      remaining = "";
    }
  }

  // Keep only last maxLines
  int startLine = max(0, lineCount - maxLines);
  int y = 0;
  display.setCursor(0, 0);
  for (int i = startLine; i < lineCount; ++i) {
    display.setCursor(0, y);
    display.print(lines[i]);
    y += charHeight;
  }
  display.display();
}

void setup() {
  Serial.begin(500000); // Velocidad extrema para audio en tiempo real
  delay(1000);
  
  Serial.println("\n\n=== Voice IoT Monitor ===");
  Serial.println("Inicializando I2S...");

  // Iniciar I2C para pantalla OLED
  Wire.begin(SDA_PIN, SCL_PIN);
  if (!display.begin(0x3C)) {
    Serial.println("ERROR: Fallo inicialización SH110X");
  } else {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SH110X_WHITE);
    display.setCursor(0,0);
    display.println("Voice IoT Monitor");
    display.display();
  }
  
  if (!initI2S()) {
    Serial.println("ERROR: Fallo inicialización I2S");
    while(1) delay(100);
  }
  
  Serial.println("I2S inicializado correctamente");
  Serial.println("Presiona botón (G4) para grabar");
  Serial.println("============================\n");
  
  pinMode(BUTTON_PIN, INPUT_PULLUP);
}

bool initI2S() {
  const i2s_config_t i2s_config = {
    .mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = i2s_comm_format_t(I2S_COMM_FORMAT_STAND_I2S),
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 512,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  const i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = -1,
    .data_in_num = I2S_SD
  };

  esp_err_t err = i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  if (err != ESP_OK) return false;
  
  err = i2s_set_pin(I2S_PORT, &pin_config);
  if (err != ESP_OK) return false;
  
  return true;
}

void loop() {
  // ===== DETECCIÓN DE BOTÓN (siempre activa) =====
  int reading = digitalRead(BUTTON_PIN);
  
  if (reading != currentButtonReading) {
    lastDebounce = millis();
    currentButtonReading = reading;
  }
  
  if ((millis() - lastDebounce) > debounceDelay && reading != lastStableButtonState) {
    int previousState = lastStableButtonState;
    lastStableButtonState = reading;
    
    // Presionar (HIGH → LOW)
    if (previousState == HIGH && reading == LOW) {
      recording = true;
      Serial.println("\n### GRABACIÓN INICIADA ###");
      display.clearDisplay();
      display.setTextSize(1);
      display.setTextColor(SH110X_WHITE);
      display.setCursor(0,0);
      display.println("Iniciando grabacion...");
      display.display();
    }
    // Soltar (LOW → HIGH)
    else if (previousState == LOW && reading == HIGH) {
      recording = false;
      Serial.println("### GRABACIÓN DETENIDA ###\n");
    }
  }
  
  // ===== TRANSMISIÓN DE AUDIO =====
  if (recording) {
    int32_t sample32 = 0;
    size_t bytes_read = 0;
    
    // Leer con timeout pequeño para permitir botón responsivo
    esp_err_t result = i2s_read(I2S_PORT, &sample32, sizeof(sample32), &bytes_read, 10);
    
    if (result == ESP_OK && bytes_read > 0) {
      // Convertir 32-bit a 16-bit: extrae los 16 bits superiores y amplifica
      int16_t sample16 = (sample32 >> 14) * 8;
      
      // Enviar 2 bytes por Serial
      Serial.write((uint8_t*)&sample16, 2);
    }
  } else {
    delay(10);
  }

  // Leer por Serial líneas de texto solo cuando no estamos enviando audio.
  if (!recording && Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      // Si la línea viene marcada, p. ej. "T: texto..." o sólo texto, la mostramos
      if (line.startsWith("T:") || line.startsWith("TRANS:") ) {
        // quitar prefijo
        int p = line.indexOf(':');
        String txt = (p >= 0) ? line.substring(p+1) : line;
        txt.trim();
        displayText(txt);
      } else {
        // mostrar la línea tal cual
        displayText(line);
      }
    }
  }
}