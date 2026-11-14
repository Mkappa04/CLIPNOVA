from backend.clip_detection.lexicon import find_hits, game_profile_key, normalize


def words(text: str, t0: float = 10.0):
    return [(t0 + i * 0.3, " " + w) for i, w in enumerate(text.split())]


def cats(hits):
    return {h.category for h in hits}


def test_normalize_strips_accents_and_apostrophes():
    assert normalize("Non è POSSIBILE!") == "non e possibile"
    assert normalize("ce l'ho fatta") == "ce l ho fatta"


def test_multiword_and_apostrophe_phrase():
    hits, _ = find_hits(words("raga ce l'ho fatta per un pelo"), "GTA 6")
    assert "clutch" in cats(hits)
    assert {h.keyword for h in hits} >= {"ce l'ho fatta", "per un pelo"}


def test_prefix_match_and_rage():
    hits, _ = find_hits(words("maledetta polizia ma porca miseria"), "GTA 6")
    assert "rage" in cats(hits)
    assert any(h.keyword == "maledett" for h in hits)
    assert "gameplay_highlight" in cats(hits)  # 'polizia' from the GTA profile


def test_game_profile_only_for_matching_game():
    assert game_profile_key("GTA 6") == "gta" and game_profile_key("Grand Theft Auto VI") == "gta"
    gta, _ = find_hits(words("arriva la polizia"), "GTA 6")
    other, _ = find_hits(words("arriva la polizia"), "Minecraft")
    assert "gameplay_highlight" in cats(gta) and "gameplay_highlight" not in cats(other)


def test_laughter_tokens_and_markers():
    _, laughs = find_hits(words("ahahah ma sei scemo hahaha [risate] lol"), "GTA 6")
    assert len(laughs) >= 4
    _, none = find_hits(words("ha detto che ah va bene"), "GTA 6")
    assert none == []


def test_english_cues():
    hits, _ = find_hits(words("oh my god let's go that was insane"), "GTA 6")
    assert {"reaction", "epic"} <= cats(hits)


def test_hit_time_is_word_time():
    hits, _ = find_hits([(42.0, " wasted")], "GTA 6")
    assert hits[0].category == "fail" and hits[0].time == 42.0
