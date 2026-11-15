"""TikTok Content Posting API v2 (Direct Post, FILE_UPLOAD).

Credentials (TikTok for Developers app with the video.publish scope): access_token,
optionally refresh_token + client_key + client_secret for refresh. Unaudited apps can
only post with privacy SELF_ONLY (private): that is the default here.
"""

from __future__ import annotations

import math
import time

import httpx

from backend.publishing.base import Log, Publisher, PublisherError, PublishRequest, PublishResult

API = "https://open.tiktokapis.com/v2"
PRIVACY = {"private": "SELF_ONLY", "unlisted": "MUTUAL_FOLLOW_FRIENDS", "public": "PUBLIC_TO_EVERYONE"}
CHUNK = 10 * 1024 * 1024
SINGLE_CHUNK_MAX = 64 * 1024 * 1024


class TikTokPublisher(Publisher):
    platform = "tiktok"
    name = "TikTok"
    docs_url = "https://developers.tiktok.com/doc/content-posting-api-reference-direct-post"
    credential_fields = ["access_token"]
    notes = "Le app non verificate da TikTok possono pubblicare solo in privato (SELF_ONLY)."
    poll_interval_s = 5.0
    poll_timeout_s = 600.0

    def publish(self, req: PublishRequest, creds: dict, client: httpx.Client, log: Log) -> PublishResult:
        h = {"Authorization": f"Bearer {creds['access_token']}", "Content-Type": "application/json; charset=UTF-8"}
        r = client.post(f"{API}/post/publish/creator_info/query/", headers=h)
        if r.status_code == 401:
            raise PublisherError("TikTok token expired or revoked: reconnect the account", retryable=False)
        self.raise_for(r, "Creator info")
        info = r.json().get("data", {})
        privacy = PRIVACY.get(req.privacy, "SELF_ONLY")
        allowed = info.get("privacy_level_options") or ["SELF_ONLY"]
        if privacy not in allowed:
            log(f"Privacy {privacy} not allowed for this account, using SELF_ONLY")
            privacy = "SELF_ONLY"

        size = req.video.stat().st_size
        chunk = size if size <= SINGLE_CHUNK_MAX else CHUNK
        total = max(1, math.floor(size / chunk)) if size > SINGLE_CHUNK_MAX else 1
        body = {"post_info": {"title": req.caption[:2200], "privacy_level": privacy, "disable_duet": False,
                              "disable_comment": False, "disable_stitch": False},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
                                "total_chunk_count": total}}
        r = client.post(f"{API}/post/publish/video/init/", headers=h, json=body)
        self.raise_for(r, "Init upload")
        data = r.json()["data"]
        upload_url, publish_id = data["upload_url"], data["publish_id"]
        log(f"Upload initialised (publish_id {publish_id}, {total} chunk)")
        with req.video.open("rb") as fh:
            for i in range(total):
                start = i * chunk
                end = size - 1 if i == total - 1 else start + chunk - 1
                fh.seek(start)
                part = fh.read(end - start + 1)
                r = client.put(upload_url, content=part, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(part)),
                    "Content-Range": f"bytes {start}-{end}/{size}"})
                self.raise_for(r, f"Upload chunk {i + 1}/{total}")
        log("Video uploaded, waiting for TikTok processing")
        deadline = time.monotonic() + self.poll_timeout_s
        while time.monotonic() < deadline:
            r = client.post(f"{API}/post/publish/status/fetch/", headers=h, json={"publish_id": publish_id})
            self.raise_for(r, "Status")
            st = r.json().get("data", {})
            status = st.get("status")
            if status == "PUBLISH_COMPLETE":
                post_ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
                return PublishResult(remote_id=str(post_ids[0]) if post_ids else publish_id, status="published",
                                     details={"privacy": privacy})
            if status == "FAILED":
                raise PublisherError(f"TikTok processing failed: {st.get('fail_reason')}", retryable=False)
            time.sleep(self.poll_interval_s)
        return PublishResult(remote_id=publish_id, status="processing", details={"privacy": privacy})
