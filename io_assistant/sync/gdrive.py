"""SyncStore over the Google Drive appDataFolder: a hidden, per-app area that the
`drive.appdata` scope can reach, and nothing else in the user's Drive.

appData has no directories, so "dev-A/batch-00000001.json.gz" is stored as a
file named "dev-A__batch-00000001.json.gz"."""
from __future__ import annotations

import io

_SEP = "__"


class GoogleDriveStore:
    def __init__(self, service):
        self._files = service.files()
        self._known: dict[str, str] = {}      # name -> id, for files we just created

    @staticmethod
    def _name(path: str) -> str:
        return path.replace("/", _SEP, 1)

    @staticmethod
    def _path(name: str) -> str:
        return name.replace(_SEP, "/", 1)

    def _index(self) -> dict[str, str]:
        out: dict[str, str] = {}
        token = None
        while True:
            resp = self._files.list(
                spaces="appDataFolder", fields="nextPageToken, files(id, name)",
                pageSize=1000, pageToken=token).execute()
            for f in resp.get("files", []):
                out[f["name"]] = f["id"]
            token = resp.get("nextPageToken")
            if not token:
                return {**self._known, **out}

    def _id(self, name: str) -> str | None:
        return self._known.get(name) or self._index().get(name)

    @staticmethod
    def _media(data: bytes):
        from googleapiclient.http import MediaIoBaseUpload

        return MediaIoBaseUpload(io.BytesIO(data), mimetype="application/gzip")

    def put(self, path: str, data: bytes) -> None:
        name = self._name(path)
        fid = self._id(name)
        if fid is not None:                    # a retried push: overwrite, don't duplicate
            self._files.update(fileId=fid, media_body=self._media(data)).execute()
            return
        res = self._files.create(
            body={"name": name, "parents": ["appDataFolder"]},
            media_body=self._media(data), fields="id").execute()
        self._known[name] = res["id"]

    def get(self, path: str) -> bytes:
        fid = self._id(self._name(path))
        if fid is None:
            raise FileNotFoundError(path)
        return self._files.get_media(fileId=fid).execute()

    def list(self, prefix: str) -> list[str]:
        return sorted(p for p in (self._path(n) for n in self._index()) if p.startswith(prefix))

    def delete(self, path: str) -> None:
        name = self._name(path)
        fid = self._id(name)
        if fid is not None:
            self._files.delete(fileId=fid).execute()
            self._known.pop(name, None)
