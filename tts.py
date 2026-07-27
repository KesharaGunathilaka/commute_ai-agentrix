# from gtts import gTTS

# text = input("Enter text: ")

# tts = gTTS(text=text, lang='ta')  #english - en # sinhala - si
# tts.save("output_tamil.mp3")

# print("Saved as output.mp3")


import asyncio
import edge_tts
import pygame
import io

text = input("Enter text: ")

VOICE = "en-US-JennyNeural"  # en -> en-US-JennyNeural  ta -> ta-IN-PallaviNeural

async def get_audio():
    communicate = edge_tts.Communicate(text, VOICE)
    audio_data = b""

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]

    return audio_data

audio_bytes = asyncio.run(get_audio())

# Play directly from memory
pygame.mixer.init()

pygame.mixer.music.load(io.BytesIO(audio_bytes))
pygame.mixer.music.play()

while pygame.mixer.music.get_busy():
    pass