from __future__ import annotations

import importlib.util

from io_assistant.config import Config

__all__ = ["VoiceModels", "VoiceUnavailable"]


class VoiceUnavailable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class VoiceModels:
    """Lazily builds and caches Whisper + Piper for the service. A text-only
    user never loads a model."""

    def __init__(self, config: Config):
        self._config = config
        self._transcriber = None
        self._speaker = None

    def transcriber(self):
        if self._transcriber is None:
            try:
                from io_assistant.transcribe.whisper import WhisperTranscriber

                self._transcriber = WhisperTranscriber(self._config)
            except Exception as e:  # noqa: BLE001
                raise VoiceUnavailable(f"speech-to-text unavailable: {e}") from e
        return self._transcriber

    def speaker(self):
        if self._speaker is None:
            try:
                from io_assistant.speak.piper import PiperSpeaker

                sp = PiperSpeaker(self._config)
                sp._check_voice()  # fail now, not on first synthesize
                self._speaker = sp
            except Exception as e:  # noqa: BLE001
                raise VoiceUnavailable(f"text-to-speech unavailable: {e}") from e
        return self._speaker

    def health(self) -> dict:
        whisper = importlib.util.find_spec("faster_whisper") is not None
        voice_path = self._config.voice.resolved_voice_path
        piper = (
            importlib.util.find_spec("piper") is not None
        ) and voice_path.exists()
        reason = None
        if not whisper:
            reason = "faster-whisper not installed"
        elif not piper:
            reason = f"Piper voice model missing: {voice_path}"
        return {
            "whisper": whisper,
            "piper": piper,
            "voice": self._config.voice.tts_voice,
            "reason": reason,
        }
