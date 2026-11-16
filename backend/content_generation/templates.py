"""Template-based (no LLM) social copy. Uses only facts from the clip."""

from __future__ import annotations

import re
import unicodedata

from backend.clip_detection.lexicon import game_profile_key, load_patterns

PLATFORM_LIMITS = {
    "tiktok": {"caption": 2200, "hashtags": 8},
    "instagram": {"caption": 2200, "hashtags": 30},
    "youtube": {"title": 100, "description": 5000, "hashtags": 15},
}

CATEGORY_LABEL = {
    "it": {"funny": "momento divertente", "rage": "momento rage", "epic": "momento epico", "fail": "fail",
           "reaction": "reazione", "clutch": "clutch", "storytelling": "racconto", "unexpected": "imprevisto",
           "gameplay_highlight": "highlight di gameplay"},
    "en": {"funny": "funny moment", "rage": "rage moment", "epic": "epic moment", "fail": "fail",
           "reaction": "reaction", "clutch": "clutch", "storytelling": "story time", "unexpected": "unexpected moment",
           "gameplay_highlight": "gameplay highlight"},
}
CATEGORY_EMOJI = {"funny": "😂", "rage": "😡", "epic": "🔥", "fail": "💀", "reaction": "😱", "clutch": "😮‍💨",
                  "storytelling": "🎙️", "unexpected": "🤯", "gameplay_highlight": "⚡"}
CATEGORY_TAGS = {
    "it": {"funny": ["divertente", "risate"], "rage": ["rage"], "epic": ["epico"], "fail": ["fail"],
           "reaction": ["reazione"], "clutch": ["clutch"], "storytelling": ["storytime"], "unexpected": ["plottwist"],
           "gameplay_highlight": ["gameplay"]},
    "en": {"funny": ["funny", "funnymoments"], "rage": ["rage"], "epic": ["epic"], "fail": ["fail", "gamingfails"],
           "reaction": ["reaction"], "clutch": ["clutch"], "storytelling": ["storytime"], "unexpected": ["plottwist"],
           "gameplay_highlight": ["gameplay"]},
}
GAME_TAGS = {
    "gta": ["GTA6", "GTAVI", "GTA", "GrandTheftAuto", "Rockstar"],
}
GENERIC = {"it": ["gaming", "videogiochi", "gamer"], "en": ["gaming", "gamer", "videogames"]}
CTA = {"it": "Seguimi per altre clip di {game}!", "en": "Follow for more {game} clips!"}


def _hashtag(word: str) -> str:
    w = unicodedata.normalize("NFKD", word)
    w = "".join(c for c in w if not unicodedata.combining(c))
    parts = re.findall(r"[A-Za-z0-9]+", w)
    if not parts:
        return ""
    return "".join(p[:1].upper() + p[1:] if len(parts) > 1 else p for p in parts)


def _game_tags(game: str) -> list[str]:
    key = game_profile_key(game)
    tags = list(GAME_TAGS.get(key, []))
    own = _hashtag(game)
    if own and own.lower() not in {t.lower() for t in tags}:
        tags.insert(0, own)
    return tags


def _best_quote(transcript: str, max_len: int = 90) -> str:
    """The most 'quotable' sentence actually spoken in the clip."""
    sentences = [s.strip(" -–—\"'“”") for s in re.split(r"(?<=[.!?…])\s+", transcript or "") if s.strip()]
    pieces: list[str] = []
    for sent in sentences:  # long sentences: fall back to their comma-separated clauses
        if len(sent.split()) <= 18:
            pieces.append(sent)
        else:
            pieces += [c.strip(" ,;") for c in re.split(r"[,;:]\s+", sent)]
    sentences = [s for s in pieces if 3 <= len(s.split()) <= 18]
    if not sentences:
        return ""
    best = max(sentences, key=lambda s: (s.count("!") + s.count("?"), -abs(len(s) - 45)))
    return best if len(best) <= max_len else best[: max_len].rsplit(" ", 1)[0] + "…"


def generate(*, category: str, transcript: str, keywords: list[str], game: str, creator: str,
             language: str, attribution: str = "") -> dict:
    lang = language if language in ("it", "en") else "it"
    label = CATEGORY_LABEL[lang].get(category, CATEGORY_LABEL[lang]["gameplay_highlight"])
    emoji = CATEGORY_EMOJI.get(category, "🎮")
    quote = _best_quote(transcript)

    hook = f"“{quote}” {emoji}" if quote else f"{game}: {label} {emoji}"
    title = (f"“{quote}” {emoji} | {game}" if quote else f"{game} – {label[:1].upper() + label[1:]} {emoji}")
    if len(title) > 100:
        title = title[:97].rstrip() + "…"
    cta = CTA[lang].format(game=game)

    # Only game-vocabulary keywords become hashtags (rage/fail cues like swear words never do)
    game_words = {p.raw.lower() for p in load_patterns(game).get("gameplay_highlight", [])}
    kw_tags = [_hashtag(k) for k in keywords if k.lower() in game_words]
    tags: list[str] = []
    for t in _game_tags(game) + CATEGORY_TAGS[lang].get(category, []) + kw_tags + GENERIC[lang]:
        if t and t.lower() not in {x.lower() for x in tags} and len(t) <= 30:
            tags.append(t)
    hashtags = tags[:10]

    caption = f"{hook}\n\n{cta}"
    lines = [title, ""]
    if quote:
        lines += [("Dal video: " if lang == "it" else "From the video: ") + f"“{quote}”", ""]
    if creator:
        lines.append(("Creator: " if lang == "it" else "Creator: ") + creator)
    if attribution:
        lines.append(attribution)
    lines += ["", cta]
    description = "\n".join(lines).strip()
    return {"language": lang, "title": title, "hook": hook, "caption": caption, "description": description,
            "hashtags": hashtags, "cta": cta, "category": category, "generated_by": "template"}


META_KEY = {"tiktok": "tiktok", "instagram": "instagram", "youtube": "youtube_shorts"}


def for_platform(content: dict, platform: str, attribution: str = "") -> dict:
    """Platform-specific text respecting length limits; attribution is always kept.

    Content generated since 1.3 carries per-platform texts in content["metadata"]["platforms"]; older
    content (one caption for every platform) still works."""
    pl = ((content.get("metadata") or {}).get("platforms") or {}).get(META_KEY.get(platform, platform))
    if pl:
        content = {**content, "hashtags": pl.get("hashtags") or content.get("hashtags", [])}
        if platform == "youtube":
            content["title"] = pl.get("title") or content.get("title", "")
            content["description"] = pl.get("description") or content.get("description", "")
        else:
            content["caption"] = pl.get("caption") or content.get("caption", "")
    tags = content.get("hashtags", [])
    lim = PLATFORM_LIMITS.get(platform, {"caption": 2200, "hashtags": 10})
    tags = tags[: lim.get("hashtags", 10)]
    tag_str = " ".join(f"#{t}" for t in tags)
    if platform == "youtube":
        tag_str = (tag_str + " #Shorts").strip()
        title = content.get("title", "")[: lim["title"]]
        desc = content.get("description", "")
        if attribution and attribution not in desc:
            desc += f"\n\n{attribution}"
        desc = f"{desc}\n\n{tag_str}"[: lim["description"]]
        return {"title": title, "description": desc, "hashtags": tags}
    caption = content.get("caption", "")
    if attribution and attribution not in caption:
        caption += f"\n{attribution}"
    max_len = lim["caption"] - len(tag_str) - 2
    caption = caption[:max_len]
    return {"caption": f"{caption}\n\n{tag_str}".strip(), "hashtags": tags}
