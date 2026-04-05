import wave
import struct
import math

filename = 'alert.wav'
sample_rate = 44100
duration = 0.3
freq = 880
num_samples = int(sample_rate * duration)

with wave.open(filename, 'w') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sample_rate)
    for i in range(num_samples):
        val = int(32767 * 0.5 * math.sin(2 * math.pi * freq * i / sample_rate))
        wf.writeframes(struct.pack('<h', val))

print('alert.wav créé avec succès')
