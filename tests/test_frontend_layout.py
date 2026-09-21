import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def js(expr: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = (f"import * as L from {json.dumps((FRONTEND / 'widgets' / 'layout.js').as_uri())};"
              f"console.log(JSON.stringify({expr}));")
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def pos(layout):
    return {i["id"]: (i["col"], i["row"]) for i in layout}


def test_spans():
    assert js("[L.span('S'), L.span('M'), L.span('L'), L.COLS]") == [
        {"w": 1, "h": 1}, {"w": 2, "h": 1}, {"w": 2, "h": 2}, 4]


def test_place_takes_the_first_free_slot():
    a = js("L.place([], {id:'a', type:'todo', size:'M'})")
    assert pos(a) == {"a": (0, 0)}
    b = js("L.place(L.place([], {id:'a', size:'M'}), {id:'b', size:'S'})")
    assert pos(b) == {"a": (0, 0), "b": (2, 0)}


def test_place_wraps_to_the_next_row_when_full():
    lay = js("L.place(L.place(L.place([], {id:'a', size:'M'}), {id:'b', size:'M'}), {id:'c', size:'S'})")
    assert pos(lay) == {"a": (0, 0), "b": (2, 0), "c": (0, 1)}


def test_a_large_widget_finds_a_two_by_two_hole():
    lay = js("L.place([{id:'a', size:'S', col:0, row:0}], {id:'b', size:'L'})")
    assert pos(lay)["b"] == (1, 0)


def test_move_pushes_a_collision_down():
    start = "[{id:'a',size:'M',col:0,row:0},{id:'b',size:'M',col:2,row:0},{id:'c',size:'M',col:0,row:1}]"
    lay = js(f"L.move({start}, 'c', 0, 0)")
    assert pos(lay) == {"c": (0, 0), "a": (0, 1), "b": (2, 0)}


def test_move_clamps_the_column_so_the_widget_fits():
    lay = js("L.move([{id:'a',size:'M',col:0,row:0}], 'a', 3, 0)")
    assert pos(lay) == {"a": (2, 0)}


def test_resize_up_pushes_neighbours():
    start = "[{id:'a',size:'S',col:0,row:0},{id:'b',size:'S',col:1,row:0},{id:'c',size:'S',col:0,row:1}]"
    lay = js(f"L.resize({start}, 'a', 'L')")
    p = pos(lay)
    assert p["a"] == (0, 0)
    assert p["b"] == (1, 2) and p["c"] == (0, 2)


def test_resize_clamps_at_the_right_edge():
    lay = js("L.resize([{id:'a',size:'S',col:3,row:0}], 'a', 'M')")
    assert pos(lay) == {"a": (2, 0)}


def test_remove_compacts_upward():
    lay = js("L.remove([{id:'a',size:'M',col:0,row:0},{id:'b',size:'M',col:0,row:1}], 'a')")
    assert pos(lay) == {"b": (0, 0)}


def test_normalize_repairs_bad_input():
    bad = ("[{id:'a',size:'XL',col:-2,row:-1},{id:'a',size:'S',col:0,row:0},"
           "{id:'b',size:'M',col:0,row:0},{id:'c',size:'M',col:9,row:0}]")
    lay = js(f"L.normalize({bad})")
    assert [i["id"] for i in lay] == ["a", "b", "c"]          # duplicate id dropped
    assert next(i for i in lay if i["id"] == "a")["size"] == "S"   # unknown size -> S
    p = pos(lay)
    assert all(0 <= c <= 4 for c, _ in p.values())
    cells = set()
    for i in lay:
        w = {"S": 1, "M": 2, "L": 2}[i["size"]]
        h = {"S": 1, "M": 1, "L": 2}[i["size"]]
        for dc in range(w):
            for dr in range(h):
                cell = (i["col"] + dc, i["row"] + dr)
                assert cell not in cells                        # no overlaps
                cells.add(cell)
