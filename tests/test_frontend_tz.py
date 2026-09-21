import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
NOON_UTC = "2026-09-22T12:00:00Z"        # a Tuesday


def js(expr: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = (f"import * as T from {json.dumps((FRONTEND / 'widgets' / 'tz.js').as_uri())};"
              f"console.log(JSON.stringify({expr}));")
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.parametrize("zone,city,time,day,offset", [
    ("Asia/Karachi", "Karachi", "17:00", "Tue", "UTC+5"),
    ("America/New_York", "New York", "08:00", "Tue", "UTC-4"),      # EDT in September
    ("Asia/Kolkata", "Kolkata", "17:30", "Tue", "UTC+5:30"),
    ("Pacific/Auckland", "Auckland", "00:00", "Wed", "UTC+12"),      # next day, midnight
    ("UTC", "UTC", "12:00", "Tue", "UTC"),
])
def test_zone_info(zone, city, time, day, offset):
    got = js(f"T.zoneInfo({json.dumps(zone)}, new Date({json.dumps(NOON_UTC)}))")
    assert got == {"zone": zone, "city": city, "time": time, "day": day, "offset": offset}


def test_zone_validation():
    assert js("[T.isValidZone('Europe/London'), T.isValidZone('Mars/Base'), T.isValidZone('')]") == [
        True, False, False]
