import numpy as np
import struct
from io import BytesIO

SAMPLE_RATE = 16000

def convert_i2s32_to_pcm16_wav(audio_bytes: bytes) -> bytes:
    """
    Convierte audio I2S de 32-bit a PCM16 WAV.
    El I2S de 32-bit viene left-aligned, así que extrae los 16 bits superiores.
    
    Args:
        audio_bytes: Buffer con datos I2S 32-bit little-endian
    
    Returns:
        Buffer WAV completo con encabezado
    """
    if len(audio_bytes) == 0:
        return b''
    
    # Convertir bytes a array de int32 (little-endian)
    samples_int32 = np.frombuffer(audio_bytes, dtype=np.int32)
    
    # Para I2S de 32-bit left-aligned: desplaza 16 bits a la derecha
    # para obtener los 16 bits más significativos (mantiene la amplitud)
    samples_int16 = (samples_int32 >> 16).astype(np.int16)
    
    # Convertir a bytes WAV
    wav_buffer = BytesIO()
    
    # Encabezado RIFF
    num_samples = len(samples_int16)
    byte_rate = SAMPLE_RATE * 2  # 2 bytes por muestra (16-bit)
    data_size = num_samples * 2
    
    # RIFF header
    wav_buffer.write(b'RIFF')
    wav_buffer.write(struct.pack('<I', 36 + data_size))  # Tamaño archivo - 8
    wav_buffer.write(b'WAVE')
    
    # fmt subchunk
    wav_buffer.write(b'fmt ')
    wav_buffer.write(struct.pack('<I', 16))  # Tamaño de fmt chunk
    wav_buffer.write(struct.pack('<H', 1))   # Audio format (1 = PCM)
    wav_buffer.write(struct.pack('<H', 1))   # Num channels (mono)
    wav_buffer.write(struct.pack('<I', SAMPLE_RATE))  # Sample rate
    wav_buffer.write(struct.pack('<I', byte_rate))    # Byte rate
    wav_buffer.write(struct.pack('<H', 2))   # Block align (2 bytes)
    wav_buffer.write(struct.pack('<H', 16))  # Bits per sample
    
    # data subchunk
    wav_buffer.write(b'data')
    wav_buffer.write(struct.pack('<I', data_size))
    wav_buffer.write(samples_int16.tobytes())
    
    return wav_buffer.getvalue()
