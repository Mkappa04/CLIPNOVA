"""YouTube Data API v3: resumable upload (videos.insert). Shorts = vertical video ≤ 60 s + #Shorts.

Credentials (from Google Cloud Console, OAuth client of type "Desktop app", scope
https://www.googleapis.com/auth/youtube.upload): client_id, client_secret, refresh_token.
"""

from __future__ import annotations

import httpx

from backend.publishing.base import Log, Publisher, PublisherError, PublishRequest, PublishResult

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
PRIVACY = {"private": "private", "unlisted": "unlisted", "public": "public"}


class YouTubePublisher(Publisher):
    platform = "youtube"
    name = "YouTube Shorts"
    docs_url = "https://developers.google.com/youtube/v3/guides/uploading_a_video"
    credential_fields = ["client_id", "client_secret", "refresh_token"]
    notes = ("Video caricati da progetti API non verificati da Google restano privati: "
             "serve l'audit dell'API per pubblicare come pubblici.")

    def _access_token(self, creds: dict, client: httpx.Client, log: Log) -> str:
        r = client.post(TOKEN_URL, data={"client_id": creds["client_id"], "client_secret": creds["client_secret"],
                                         "refresh_token": creds["refresh_token"], "grant_type": "refresh_token"})
        if r.status_code in (400, 401):
            raise PublisherError(f"OAuth refresh rejected ({r.status_code}): reconnect the account", retryable=False)
        self.raise_for(r, "OAuth refresh")
        log("Access token refreshed")
        return r.json()["access_token"]

    def publish(self, req: PublishRequest, creds: dict, client: httpx.Client, log: Log) -> PublishResult:
        token = self._access_token(creds, client, log)
        size = req.video.stat().st_size
        description = req.description
        if "#shorts" not in description.lower():
            description += "\n#Shorts"
        meta = {
            "snippet": {"title": req.title[:100], "description": description[:5000],
                        "tags": req.hashtags[:15], "categoryId": "20"},  # 20 = Gaming
            "status": {"privacyStatus": PRIVACY.get(req.privacy, "private"), "selfDeclaredMadeForKids": False},
        }
        r = client.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, json=meta,
                        headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                                 "X-Upload-Content-Length": str(size)})
        self.raise_for(r, "Upload session")
        location = r.headers.get("Location")
        if not location:
            raise PublisherError("Upload session without Location header", retryable=True)
        log(f"Resumable session opened ({size} bytes)")
        with req.video.open("rb") as fh:
            r = client.put(location, content=fh.read(), headers={"Authorization": f"Bearer {token}",
                                                                 "Content-Type": "video/mp4"})
        self.raise_for(r, "Video upload")
        vid = r.json()["id"]
        log(f"Uploaded: video id {vid}")
        return PublishResult(remote_id=vid, url=f"https://youtube.com/shorts/{vid}", status="published")
