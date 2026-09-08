from io_assistant.voice.loop import VoiceLoop
from io_assistant.service.schemas import UtteranceOut


class _Client:
    def __init__(self, out):
        self.out = out
        self.sent = []

    def send(self, u):
        self.sent.append(u)
        return self.out

    def health(self):
        return True


def test_handle_wav_speaks_reply(config, fake_transcriber, fake_speaker):
    fake_transcriber.set_text("what work do I have today")
    fake_transcriber.set_confidence(0.9)
    client = _Client(UtteranceOut(intent="query", message="Two tasks are open."))
    loop = VoiceLoop(config, transcriber=fake_transcriber, speaker=fake_speaker, client=client)
    msg = loop.handle_wav("x.wav")
    assert msg == "Two tasks are open."
    assert fake_speaker.said == ["Two tasks are open."]
    assert client.sent[0].text == "what work do I have today"
    assert client.sent[0].source == "voice"


def test_handle_wav_empty_transcript_is_silent(config, fake_transcriber, fake_speaker):
    fake_transcriber.set_text("   ")
    client = _Client(UtteranceOut(intent="unknown", message="?"))
    loop = VoiceLoop(config, transcriber=fake_transcriber, speaker=fake_speaker, client=client)
    assert loop.handle_wav("x.wav") == ""
    assert fake_speaker.said == [] and client.sent == []


def test_speak_failure_is_not_fatal(config, fake_transcriber):
    from io_assistant.speak.interface import SpeakError

    fake_transcriber.set_text("hello")

    class BadSpeaker:
        def say(self, t):
            raise SpeakError("no audio device")

        def synthesize(self, t):
            return b""

    client = _Client(UtteranceOut(intent="store", message="Stored."))
    loop = VoiceLoop(config, transcriber=fake_transcriber, speaker=BadSpeaker(), client=client)
    assert loop.handle_wav("x.wav") == "Stored."
