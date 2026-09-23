import os

import pytest

from io_assistant.sync.gdrive import GoogleDriveStore


class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeFiles:
    """Just enough of the Drive v3 `files()` resource, with pagination."""

    def __init__(self, page=2):
        self.data: dict[str, tuple[str, bytes]] = {}
        self.n = 0
        self.page = page
        self.parents: list = []

    def list(self, spaces, fields, pageSize, pageToken=None):
        assert spaces == "appDataFolder"
        ids = sorted(self.data)
        start = int(pageToken or 0)
        chunk = ids[start:start + self.page]
        nxt = str(start + self.page) if start + self.page < len(ids) else None
        return _Exec(lambda: {"files": [{"id": i, "name": self.data[i][0]} for i in chunk],
                              **({"nextPageToken": nxt} if nxt else {})})

    def create(self, body, media_body, fields=None):
        self.n += 1
        fid = f"id{self.n}"
        self.parents.append(body.get("parents"))
        self.data[fid] = (body["name"], media_body.getbytes(0, media_body.size()))
        return _Exec(lambda: {"id": fid})

    def update(self, fileId, media_body):
        name = self.data[fileId][0]
        self.data[fileId] = (name, media_body.getbytes(0, media_body.size()))
        return _Exec(lambda: {"id": fileId})

    def get_media(self, fileId):
        return _Exec(lambda: self.data[fileId][1])

    def delete(self, fileId):
        return _Exec(lambda: self.data.pop(fileId) and None)


class FakeService:
    def __init__(self, **kw):
        self._files = FakeFiles(**kw)

    def files(self):
        return self._files


def test_paths_are_flattened_into_app_data_names():
    svc = FakeService()
    st = GoogleDriveStore(svc)
    st.put("dev-A/batch-00000001.json.gz", b"one")
    assert [n for n, _ in svc.files().data.values()] == ["dev-A__batch-00000001.json.gz"]
    assert svc.files().parents == [["appDataFolder"]]
    assert st.get("dev-A/batch-00000001.json.gz") == b"one"


def test_list_filters_by_prefix_and_follows_pages():
    st = GoogleDriveStore(FakeService(page=2))
    for p in ("dev-A/batch-00000001.json.gz", "dev-A/batch-00000002.json.gz",
              "dev-B/snapshot-00000005.json.gz", "other/readme"):
        st.put(p, b"x")
    assert st.list("dev-") == ["dev-A/batch-00000001.json.gz", "dev-A/batch-00000002.json.gz",
                               "dev-B/snapshot-00000005.json.gz"]
    assert st.list("dev-A/") == ["dev-A/batch-00000001.json.gz", "dev-A/batch-00000002.json.gz"]


def test_put_twice_updates_in_place_instead_of_duplicating():
    svc = FakeService()
    st = GoogleDriveStore(svc)
    st.put("dev-A/batch-00000001.json.gz", b"v1")
    st.put("dev-A/batch-00000001.json.gz", b"v2")
    assert len(svc.files().data) == 1
    assert st.get("dev-A/batch-00000001.json.gz") == b"v2"


def test_delete_removes_and_ignores_missing():
    st = GoogleDriveStore(FakeService())
    st.put("dev-A/batch-00000001.json.gz", b"x")
    st.delete("dev-A/batch-00000001.json.gz")
    st.delete("dev-A/batch-00000001.json.gz")          # already gone: no error
    assert st.list("dev-") == []


def test_missing_file_raises_a_clear_error():
    with pytest.raises(FileNotFoundError):
        GoogleDriveStore(FakeService()).get("dev-A/batch-00000009.json.gz")


@pytest.mark.skipif(os.environ.get("IO_GDRIVE_TESTS") != "1",
                    reason="opt-in: needs a signed-in Google account (see .claude/knowledge/memory-sync.md)")
def test_real_drive_round_trip():
    from io_assistant.config import load_config
    from io_assistant.sync import auth

    cfg = load_config().sync
    creds = auth.load(cfg.client_id, cfg.client_secret)
    assert creds is not None, "sign in from Settings → Account first"
    st = GoogleDriveStore(auth.build_service(creds))
    st.put("dev-test/probe.txt", b"hello")
    try:
        assert st.get("dev-test/probe.txt") == b"hello"
        assert "dev-test/probe.txt" in st.list("dev-test/")
    finally:
        st.delete("dev-test/probe.txt")
