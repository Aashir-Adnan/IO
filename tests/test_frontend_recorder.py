import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_encode_wav_shape():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = f"""
      import {{ encodeWav }} from {json.dumps((FRONTEND / 'vendor' / 'recorder.js').as_uri())};
      const n = 48000;
      const f = new Float32Array(n).fill(0.2);
      const b = new Uint8Array(encodeWav(f, 48000));
      const rate = b[24] | (b[25]<<8) | (b[26]<<16) | (b[27]<<24);
      const samples = (b.length - 44) / 2;
      console.log(JSON.stringify({{
        riff: String.fromCharCode(b[0],b[1],b[2],b[3]),
        rate, samples,
      }}));
    """
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["riff"] == "RIFF"
    assert got["rate"] == 16000
    assert abs(got["samples"] - 16000) <= 2
