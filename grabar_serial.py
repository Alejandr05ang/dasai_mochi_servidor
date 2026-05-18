#!/usr/bin/env python3
"""
Script para grabar audio del ESP32 por puerto Serial

Uso:
    python grabar_serial.py COM4 sumar 5

Parámetros:
    PORT: Puerto COM (COM4, COM3, etc.)
    LABEL: Etiqueta de la grabación (sumar, restar, etc.)
    DURATION: Duración máxima en segundos (si sale 0 en log, presiona botón)
"""

import serial
import wave
import sys
import time
import json
import urllib.request
import urllib.error

# --- CONFIGURACIÓN ---
PORT = "COM4"  # Cambia esto al puerto correcto
SAMPLE_RATE = 16000
BAUD = 500000
DEFAULT_SERVER_URL = "http://192.168.18.171:8000/audio/pcm16"
LABEL = "recording"



def upload_to_server(server_url: str, device_id: str, session_id: str, pcm16_bytes: bytes) -> dict:
    request = urllib.request.Request(
        server_url,
        data=pcm16_bytes,
        method="POST",
        headers={
            "device-id": device_id,
            "session-id": session_id,
            "end": "true",
            "Content-Type": "application/octet-stream",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="ignore")
        print(f"\n⬆️  Subido al servidor: HTTP {response.status}")
        print(body)
        try:
            return json.loads(body)
        except Exception:
            return {}


def wait_for_stop_signal(ser: serial.Serial, timeout_seconds: float = 15.0) -> bool:
    """Wait until the ESP32 reports that recording stopped.

    This keeps the transcription text from being sent while the board is still
    streaming binary audio on the same serial link.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"[ESP32] {line}")
            if "GRABACIÓN DETENIDA" in line:
                return True
        time.sleep(0.02)
    return False

def main():
    if len(sys.argv) < 2:
        print("Uso: python grabar_serial.py <puerto> [label] [segundos] [server_url]")
        print("Ejemplo: python grabar_serial.py COM4 sumar 5")
        sys.exit(1)
    
    port = sys.argv[1]
    label = sys.argv[2] if len(sys.argv) > 2 else "recording"
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    server_url = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_SERVER_URL
    device_id = "esp32_serial"
    session_id = f"{label}_{int(time.time())}"
    
    print(f"Conectando a {port} a {BAUD} baud...")
    
    try:
        ser = serial.Serial(port, BAUD, timeout=1)
        time.sleep(2)  # Esperar a que el ESP32 se reinicie
    except Exception as e:
        print(f"❌ Error: No se pudo abrir {port}")
        print(f"   {e}")
        sys.exit(1)
    
    # Limpiar buffer
    ser.reset_input_buffer()
    
    print("\n" + "="*50)
    print(f"GRABANDO: {label.upper()}")
    print("="*50)
    print("📍 Presiona botón G4 en el ESP32 para iniciar")
    print("📍 Suelta para detener")
    print()
    
    # Leer logs del ESP32 hasta que vea "GRABACIÓN INICIADA"
    grabando = False
    while not grabando:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"[ESP32] {line}")
            if "GRABACIÓN INICIADA" in line:
                grabando = True
    
    print("\n🔴 Grabando...\n")
    
    # Buffer para almacenar muestras de audio
    audio_data = bytearray()
    start_time = time.time()
    detener = False
    
    try:
        while not detener and (time.time() - start_time) < duration:
            # Leer audio crudo en bloques para no mezclarlo con logs de texto.
            # Durante la grabación solo consumimos binario; los logs del ESP32
            # compiten con el audio en el mismo puerto y pueden vaciar el buffer.
            chunk = ser.read(1024)

            if chunk:
                audio_data.extend(chunk)

            # Pequeña pausa para dejar respirar al puerto y evitar busy-wait.
            time.sleep(0.01)
    
    except KeyboardInterrupt:
        print("\n⚠️  Grabación cancelada por usuario")
        detener = True

    print("\n⏳ Esperando confirmación de que el ESP32 dejó de grabar...")
    stop_seen = wait_for_stop_signal(ser)
    if not stop_seen:
        print("⚠️  No se recibió el mensaje de fin de grabación; continuaré de todas formas.")
    
    print(f"\n✅ Grabación completada: {len(audio_data)} bytes")
    print(f"   Muestras: {len(audio_data) // 2}")
    print(f"   Duración: {(len(audio_data) / 2) / SAMPLE_RATE:.2f} segundos")
    
    # Guardar WAV
    filename = f"{label}.wav"
    try:
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)           # Mono
            wf.setsampwidth(2)           # 16 bits (2 bytes)
            wf.setframerate(SAMPLE_RATE) # 16000 Hz
            wf.writeframes(bytes(audio_data))
        
        print(f"\n💾 Guardado como: {filename}")
    except Exception as e:
        print(f"❌ Error guardando WAV: {e}")
        sys.exit(1)

    try:
        response = upload_to_server(server_url, device_id, session_id, bytes(audio_data))

        transcription = response.get("transcription") if isinstance(response, dict) else None
        text = ""
        if isinstance(transcription, dict):
            text = (transcription.get("text") or "").strip()
        elif isinstance(response, dict):
            text = (response.get("text") or "").strip()

        if text:
            print(f"\n📝 Transcripción automática: {text}")
            try:
                ser.write(f"T:{text}\n".encode("utf-8"))
                ser.flush()
                print("📺 Enviada a la OLED por Serial")
            except Exception as e:
                print(f"⚠️  No se pudo reenviar la transcripción al ESP32: {e}")
    except urllib.error.URLError as e:
        print(f"❌ Error subiendo al servidor: {e}")
        sys.exit(1)
    
    ser.close()

if __name__ == "__main__":
    main()
