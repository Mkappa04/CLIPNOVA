"""Keyword lexicons (Italian + English) per clip category, plus per-game profiles.

Matching is accent/case-insensitive on Whisper word tokens. A trailing ``*``
means prefix match ("maledett*" -> maledetto, maledetta…). These are *cues*,
not semantic understanding: a keyword raises the evidence for a category, it
does not prove what happened. Users can extend them in data/config/lexicon.json:
  {"categories": {"funny": ["parola", ...]}, "games": {"GTA 6": ["parola", ...]}}
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from backend.core.config import get_settings

log = logging.getLogger(__name__)

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "funny": [
        "che ridere", "sto morendo", "muoio", "troppo forte", "ridicolo", "assurdo ahah", "scemo",
        "lol", "lmao", "hilarious", "i'm dying", "so funny", "that's funny", "bro what",
    ],
    "rage": [
        "cazzo", "porca", "porco", "maledett*", "basta", "odio", "ma dai", "ma come", "non è possibile",
        "ma vaffa*", "vaffanculo", "che schifo", "incazzat*", "ma perché",
        "what the hell", "are you kidding", "i hate", "so stupid", "bullshit", "wtf", "fuck*", "damn",
        "come on", "seriously",
    ],
    "epic": [
        "incredibile", "pazzesco", "pazzesca", "che giocata", "andiamo", "spettacolo", "leggendario",
        "fortissimo", "bellissimo", "mostruoso", "goduria",
        "let's go", "lets go", "insane", "epic", "unbelievable", "legendary", "sick", "huge", "massive",
    ],
    "fail": [
        "sono morto", "mi hanno ucciso", "ho sbagliato", "che figura", "sbagliato", "ho perso", "fallito",
        "wasted", "busted", "i died", "i'm dead", "oops", "fail", "my bad", "missed", "i lost",
    ],
    "reaction": [
        "oh mio dio", "oddio", "ma cosa", "cosa è successo", "ma che", "no no no", "nooo*", "wow", "aiuto",
        "oh my god", "omg", "wait what", "no way", "holy",
    ],
    "clutch": [
        "ce l'ho fatta", "per un pelo", "appena in tempo", "salvo", "salvato", "scappato", "ultimo secondo",
        "ce la faccio", "dai dai dai",
        "clutch", "last second", "just made it", "barely", "one hp", "1 hp", "close one", "got away",
    ],
    "storytelling": [
        "allora", "praticamente", "vi racconto", "la storia", "una volta", "vi spiego", "ascoltate",
        "so basically", "story time", "let me tell you", "long story", "so anyway",
    ],
    "unexpected": [
        "non me lo aspettavo", "dal nulla", "all'improvviso", "ma chi", "da dove", "non ci credo", "colpo di scena",
        "out of nowhere", "didn't expect", "plot twist", "where did", "who the", "can't believe",
    ],
}

GAME_KEYWORDS: dict[str, list[str]] = {
    "_generic": [
        "boss", "kill", "uccis*", "headshot", "vittoria", "victory", "win", "vinto", "sparatoria", "combo",
        "inseguimento", "chase", "esplo*", "explosion",
    ],
    "gta": [
        "polizia", "police", "cops", "sbirri", "stelle", "stella", "wanted", "ricercato", "rapina", "colpo",
        "heist", "elicottero", "helicopter", "carro armato", "tank", "moto", "macchina", "auto", "car",
        "salto", "jump", "schianto", "crash", "banca", "bank", "gioielleria", "soldi", "money", "cash",
        "lucia", "jason", "vice city", "leonida", "missione", "mission",
    ],
}

LAUGH_TOKEN = re.compile(r"^(?:a?h[aeiu]){2,}h?$|^(?:ah){2,}$|^(?:ja){2,}$|^(?:ih){2,}$|^lol+$|^lmao+$|^ahah\w*$|^haha\w*$")
LAUGH_MARKER = re.compile(r"\b(?:risat\w*|ride|ridono|laugh\w*|giggl\w*)\b", re.IGNORECASE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("'", " ").replace("’", " ")
    return re.sub(r"[^\w\s*]", " ", text).strip()


@dataclass(frozen=True)
class Pattern:
    tokens: tuple[str, ...]
    prefix: bool
    raw: str


def _compile(phrases: list[str]) -> list[Pattern]:
    out = []
    for p in phrases:
        prefix = p.endswith("*")
        toks = tuple(normalize(p.rstrip("*")).split())
        if toks:
            out.append(Pattern(toks, prefix, p.rstrip("*")))
    return out


def game_profile_key(game: str) -> str:
    g = normalize(game)
    return "gta" if "gta" in g or "grand theft" in g else g


@lru_cache(maxsize=32)
def load_patterns(game: str) -> dict[str, list[Pattern]]:
    cats = {k: list(v) for k, v in CATEGORY_KEYWORDS.items()}
    game_words = list(GAME_KEYWORDS["_generic"]) + list(GAME_KEYWORDS.get(game_profile_key(game), []))
    custom = get_settings().data_dir / "config" / "lexicon.json"
    if custom.exists():
        try:
            data = json.loads(custom.read_text(encoding="utf-8"))
            for k, words in data.get("categories", {}).items():
                cats.setdefault(k, []).extend(words)
            for gname, words in data.get("games", {}).items():
                if game_profile_key(gname) == game_profile_key(game):
                    game_words.extend(words)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Invalid custom lexicon %s: %s", custom, e)
    cats["gameplay_highlight"] = game_words
    return {k: _compile(v) for k, v in cats.items()}


@dataclass
class Hit:
    category: str
    keyword: str
    time: float


def find_hits(words: list[tuple[float, str]], game: str) -> tuple[list[Hit], list[float]]:
    """words: [(time, raw_word)]. Returns (keyword hits, laughter times)."""
    tokens: list[tuple[float, str]] = []
    laughs: list[float] = []
    for t, w in words:
        if LAUGH_MARKER.search(w):
            laughs.append(t)
        for tok in normalize(w).split():
            tokens.append((t, tok))
            if LAUGH_TOKEN.match(tok):
                laughs.append(t)
    toks = [tok for _, tok in tokens]
    hits: list[Hit] = []
    for cat, patterns in load_patterns(game).items():
        for p in patterns:
            n = len(p.tokens)
            for i in range(len(toks) - n + 1):
                if all(toks[i + j] == p.tokens[j] for j in range(n - 1)) and (
                    toks[i + n - 1].startswith(p.tokens[-1]) if p.prefix else toks[i + n - 1] == p.tokens[-1]
                ):
                    hits.append(Hit(cat, p.raw, tokens[i][0]))
    return hits, laughs
