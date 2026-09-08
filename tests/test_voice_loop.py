from io_assistant.voice.loop import VoiceLoop


class _Client:
    def __init__(self, reply):
        self.reply = reply
        self.sent = []

    def send_voice(self, wav, *, conversation_id=None, speak=True):
        self.sent.append((wav, speak))
        return self.reply


def test_handle_wav_prints_reply(config, tmp_path, capsys):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF0000WAVEfmt ")
    client = _Client({"transcript": "what work do I have",
                      "text": "Two tasks are open.", "kind": "answer",
                      "conversation_id": 3, "audio_b64": None})
    out = VoiceLoop(config, client=client).handle_wav(str(wav))
    assert out == "Two tasks are open."
    printed = capsys.readouterr().out
    assert "what work do I have" in printed and "Two tasks are open." in printed
    assert client.sent and client.sent[0][1] is True  # speak (auto_speak=voice)


def test_handle_wav_swallows_failure(config, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF0000WAVEfmt ")

    class C:
        def send_voice(self, *a, **k):
            raise RuntimeError("422 no speech")

    assert VoiceLoop(config, client=C()).handle_wav(str(wav)) == ""


def test_conversation_id_is_carried(config, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF0000WAVEfmt ")
    client = _Client({"text": "ok", "kind": "ack", "conversation_id": 9})
    loop = VoiceLoop(config, client=client)
    loop.handle_wav(str(wav))
    assert loop._conversation_id == 9
