"""AI capability tools: LLM, vision, TTS, STT."""
import base64
import tempfile

from openai import OpenAI
from core.config import OPENAI_API_KEY
from core.log import get_logger

log = get_logger("tools.ai")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def ask_llm(prompt: str, image_url: str = "") -> str:
    """Ask GPT-4o-mini a question. Optionally include image_url for vision analysis (use data:image/png;base64,... or https:// URL). Returns text response."""
    log.info("LLM call: %s", prompt[:100])
    client = _get_client()

    content = [{"type": "text", "text": prompt}]
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": content}],
        max_tokens=4096,
    )
    result = resp.choices[0].message.content or ""
    log.info("LLM response: %s", result[:200])
    return result


def text_to_speech(text: str) -> str:
    """Convert text to speech using OpenAI TTS. Returns base64-encoded MP3 audio."""
    log.info("TTS: %s", text[:100])
    client = _get_client()

    resp = client.audio.speech.create(
        model="tts-1",
        voice="onyx",
        input=text,
        response_format="mp3",
    )
    audio_bytes = resp.content
    b64 = base64.b64encode(audio_bytes).decode()
    log.info("TTS: %d bytes audio", len(audio_bytes))
    return b64


def speech_to_text(audio_base64: str) -> str:
    """Transcribe base64-encoded audio (MP3/WAV) to text using OpenAI Whisper. Returns transcribed text."""
    log.info("STT: %d chars base64", len(audio_base64))
    client = _get_client()

    audio_bytes = base64.b64decode(audio_base64)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f:
        f.write(audio_bytes)
        f.flush()
        with open(f.name, "rb") as audio_file:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="pl",
            )
    log.info("STT result: %s", resp.text[:200])
    return resp.text
