"""
Audiobookshelf uploader for Echo-Scribe.
Uploads EPUB/MP3 exports to a local or remote Audiobookshelf instance.
"""
import logging
import requests
from pathlib import Path

logger = logging.getLogger(__name__)


class AudiobookshelfUploader:
    def __init__(self, server_url: str, token: str):
        self.server_url = server_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def _check_connection(self):
        try:
            resp = requests.get(f"{self.server_url}/ping", timeout=5)
            resp.raise_for_status()
        except Exception as e:
            raise ConnectionError(f"Cannot reach Audiobookshelf server: {e}") from e

    def get_libraries(self) -> list[dict]:
        """Return list of libraries from the server."""
        self._check_connection()
        resp = requests.get(
            f"{self.server_url}/api/libraries",
            headers=self.headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("libraries", [])

    def upload_files(
        self,
        library_id: str,
        title: str,
        author: str,
        files: list[Path],
        on_progress=None,
    ) -> dict:
        """
        Upload one or more files (EPUB, MP3) as a new audiobook item.
        on_progress: optional callable(uploaded_bytes, total_bytes)
        """
        self._check_connection()
        upload_url = f"{self.server_url}/api/libraries/{library_id}/items"

        form_data = {"title": title, "author": author}
        file_handles = []
        try:
            multipart = []
            for file_path in files:
                if not file_path.exists():
                    raise FileNotFoundError(f"Export file not found: {file_path}")
                fh = open(file_path, "rb")
                file_handles.append(fh)
                multipart.append(("files", (file_path.name, fh, _mime_for(file_path))))

            resp = requests.post(
                upload_url,
                headers=self.headers,
                data=form_data,
                files=multipart,
                timeout=300,
            )
            resp.raise_for_status()
            logger.info(f"Upload successful: {resp.json()}")
            return resp.json()
        finally:
            for fh in file_handles:
                fh.close()


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".epub": "application/epub+zip",
        ".mp3": "audio/mpeg",
        ".m4b": "audio/mp4",
    }.get(ext, "application/octet-stream")
