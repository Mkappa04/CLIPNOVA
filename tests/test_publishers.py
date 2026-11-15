import json

import httpx
import pytest

from backend.publishing import crypto
from backend.publishing.base import PublisherError, PublishRequest
from backend.publishing.instagram import InstagramPublisher
from backend.publishing.tiktok import TikTokPublisher
from backend.publishing.youtube import YouTubePublisher


@pytest.fixture
def req(tmp_path):
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"\x00" * 1000)
    return PublishRequest(video=v, title="Titolo", description="Desc", caption="Caption #GTA6",
                          hashtags=["GTA6"], privacy="public")


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_crypto_roundtrip_and_mask():
    token = crypto.encrypt_json({"access_token": "abcdefghijklmnop"})
    assert "abcdefgh" not in token
    assert crypto.decrypt_json(token) == {"access_token": "abcdefghijklmnop"}
    assert crypto.mask({"access_token": "abcdefghijklmnop"}) == {"access_token": "••••mnop"}


def test_youtube_resumable_upload(req):
    calls = []

    def h(r: httpx.Request):
        calls.append((r.method, r.url.host + r.url.path))
        if r.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "AT"})
        if r.method == "POST":
            meta = json.loads(r.content)
            assert r.headers["authorization"] == "Bearer AT" and r.url.params["uploadType"] == "resumable"
            assert meta["snippet"]["categoryId"] == "20" and meta["status"]["privacyStatus"] == "public"
            assert "#Shorts" in meta["snippet"]["description"]
            return httpx.Response(200, headers={"Location": "https://upload.example/session1"})
        assert r.method == "PUT" and len(r.content) == 1000
        return httpx.Response(200, json={"id": "VID123"})

    res = YouTubePublisher().publish(req, {"client_id": "c", "client_secret": "s", "refresh_token": "r"}, client(h), print)
    assert res.remote_id == "VID123" and res.url == "https://youtube.com/shorts/VID123"
    assert [c[0] for c in calls] == ["POST", "POST", "PUT"]


def test_youtube_errors_are_classified(req):
    def h(r):
        if r.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "AT"})
        return httpx.Response(503, text="backend error")
    with pytest.raises(PublisherError) as e:
        YouTubePublisher().publish(req, {"client_id": "c", "client_secret": "s", "refresh_token": "r"}, client(h), print)
    assert e.value.retryable

    with pytest.raises(PublisherError) as e:
        YouTubePublisher().publish(req, {"client_id": "c", "client_secret": "s", "refresh_token": "r"},
                                   client(lambda r: httpx.Response(400, json={"error": "invalid_grant"})), print)
    assert not e.value.retryable and "reconnect" in str(e.value)


def test_tiktok_direct_post_with_privacy_fallback(req, monkeypatch):
    monkeypatch.setattr(TikTokPublisher, "poll_interval_s", 0)
    seen = {}

    def h(r: httpx.Request):
        p = r.url.path
        if p.endswith("creator_info/query/"):
            return httpx.Response(200, json={"data": {"privacy_level_options": ["SELF_ONLY"]}})
        if p.endswith("video/init/"):
            body = json.loads(r.content)
            seen["privacy"] = body["post_info"]["privacy_level"]
            assert body["source_info"] == {"source": "FILE_UPLOAD", "video_size": 1000, "chunk_size": 1000,
                                           "total_chunk_count": 1}
            return httpx.Response(200, json={"data": {"upload_url": "https://up.tiktok/x", "publish_id": "P1"}})
        if r.method == "PUT":
            assert r.headers["content-range"] == "bytes 0-999/1000"
            return httpx.Response(201)
        if p.endswith("status/fetch/"):
            seen["polls"] = seen.get("polls", 0) + 1
            status = "PROCESSING_UPLOAD" if seen["polls"] == 1 else "PUBLISH_COMPLETE"
            return httpx.Response(200, json={"data": {"status": status, "publicaly_available_post_id": [777]}})
        raise AssertionError(p)

    res = TikTokPublisher().publish(req, {"access_token": "T"}, client(h), print)
    assert seen["privacy"] == "SELF_ONLY"  # requested public, but unaudited app → private
    assert res.remote_id == "777" and seen["polls"] == 2


def test_instagram_requires_public_url(req):
    with pytest.raises(PublisherError) as e:
        InstagramPublisher().publish(req, {"ig_user_id": "1", "access_token": "t", "public_base_url": ""},
                                     client(lambda r: httpx.Response(500)), print)
    assert not e.value.retryable and "public" in str(e.value)


def test_instagram_reels_flow(req, monkeypatch):
    monkeypatch.setattr(InstagramPublisher, "poll_interval_s", 0)

    def h(r: httpx.Request):
        if r.url.path.endswith("/media"):
            assert "video_url=https%3A%2F%2Fcdn.example%2Fclip.mp4" in r.content.decode()
            return httpx.Response(200, json={"id": "C1"})
        if r.url.path.endswith("/C1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if r.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "M1"})
        raise AssertionError(r.url)

    res = InstagramPublisher().publish(req, {"ig_user_id": "1", "access_token": "t",
                                             "public_base_url": "https://cdn.example"}, client(h), print)
    assert res.remote_id == "M1"
