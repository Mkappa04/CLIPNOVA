from backend.publishing.base import Publisher
from backend.publishing.instagram import InstagramPublisher
from backend.publishing.tiktok import TikTokPublisher
from backend.publishing.youtube import YouTubePublisher

PUBLISHERS: dict[str, Publisher] = {p.platform: p for p in (TikTokPublisher(), InstagramPublisher(), YouTubePublisher())}


def get_publisher(platform: str) -> Publisher:
    if platform not in PUBLISHERS:
        raise ValueError(f"Unsupported platform: {platform}")
    return PUBLISHERS[platform]
