"""Instagram Graph API (Reels).

The API only accepts a video *URL* that Instagram's servers download: the file must
be reachable on the public internet. CLIPNOVA never exposes services publicly, so
this works only if you upload the export yourself to storage you control and set
`public_base_url` (the file name is appended). Otherwise use the manual export.
Credentials: ig_user_id + access_token (Instagram professional account).
"""

from __future__ import annotations

import time

import httpx

from backend.publishing.base import Log, Publisher, PublisherError, PublishRequest, PublishResult

GRAPH = "https://graph.facebook.com/v21.0"


class InstagramPublisher(Publisher):
    platform = "instagram"
    name = "Instagram Reels"
    docs_url = "https://developers.facebook.com/docs/instagram-platform/content-publishing"
    credential_fields = ["ig_user_id", "access_token", "public_base_url"]
    notes = ("Richiede che il video sia raggiungibile da un URL pubblico (public_base_url) caricato da te: "
             "CLIPNOVA non espone file su internet. In alternativa usa l'export manuale.")
    poll_interval_s = 5.0
    poll_timeout_s = 600.0

    def publish(self, req: PublishRequest, creds: dict, client: httpx.Client, log: Log) -> PublishResult:
        base = (creds.get("public_base_url") or "").rstrip("/")
        if not base.startswith("https://"):
            raise PublisherError("public_base_url (https) required: Instagram downloads the video from a public URL",
                                 retryable=False)
        video_url = f"{base}/{req.video.name}"
        token, user = creds["access_token"], creds["ig_user_id"]
        r = client.post(f"{GRAPH}/{user}/media", data={"media_type": "REELS", "video_url": video_url,
                                                       "caption": req.caption[:2200], "access_token": token})
        self.raise_for(r, "Create container")
        creation_id = r.json()["id"]
        log(f"Container {creation_id} created from {video_url}")
        deadline = time.monotonic() + self.poll_timeout_s
        while time.monotonic() < deadline:
            r = client.get(f"{GRAPH}/{creation_id}", params={"fields": "status_code", "access_token": token})
            self.raise_for(r, "Container status")
            code = r.json().get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise PublisherError(f"Instagram could not process the video ({code})", retryable=False)
            time.sleep(self.poll_interval_s)
        else:
            raise PublisherError("Instagram processing timed out", retryable=True)
        r = client.post(f"{GRAPH}/{user}/media_publish", data={"creation_id": creation_id, "access_token": token})
        self.raise_for(r, "Publish")
        media_id = r.json()["id"]
        log(f"Published media {media_id}")
        return PublishResult(remote_id=media_id, status="published")
