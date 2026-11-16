"""Social metadata generator: understand the clip, then write titles, captions and hashtags per platform.

1. Analysis (local LLM, JSON): subject, event, context, key moment, why it is interesting, speaker, tone,
   emotion, verbatim evidence, confidence, "insufficient context". Built from ClipContext (speech with
   timestamps, before/after, semantic judgement, signals, frames described by the vision model).
2. Writing (local LLM, JSON): 3 titles with different structures + platform-specific copy
   (Instagram caption, TikTok caption, YouTube Shorts title + description) + topic keywords.
   Parts can be regenerated alone: titles, captions, hashtags.
3. Checks (always): Pydantic validation, length limits, generic/clickbait titles rejected, invented names
   or numbers rejected (every capitalised word / number must be traceable to the clip facts),
   emoji capped, captions must differ across platforms and from the title, no hashtags inside texts.
4. Hashtags: built deterministically from the declared game/topic, the kind of content, the event and
   keywords found in the facts — no automatic #fyp/#viral — with configurable counts per platform and
   less reuse of the same tags across clips.
5. Fallback: without the AI (or if it fails) a prudent, descriptive copy from the facts only.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import unicodedata
from collections import Counter
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from backend.content_generation.context import ClipContext
from backend.content_generation.llm import STOPWORDS as LLM_STOPWORDS
from backend.content_generation.templates import GAME_TAGS, _best_quote, _hashtag
from backend.clip_detection.lexicon import game_profile_key
from backend.core.config import get_settings

log = logging.getLogger(__name__)

VERSION = 2
Tone = Literal["divertente", "teso", "drammatico", "epico", "arrabbiato", "informativo", "emozionante",
               "rilassato", "sorpreso", "neutro"]
PLATFORMS = ("instagram", "tiktok", "youtube_shorts")
LIMITS = {"title": 100, "yt_title": 100, "ig_caption": 600, "tt_caption": 300, "yt_description": 600}

# Titles made only of these (plus the game name / punctuation) say nothing about the clip
GENERIC_PHRASES = [
    r"non ci posso credere", r"non ci credo", r"momento incredibile", r"guard(a|ate) cosa (succede|è successo|fa)",
    r"che spettacolo", r"incredibile", r"pazzesc[oa]", r"assurd[oa]", r"questa storia è assurda", r"epico",
    r"guarda fino alla fine", r"aspetta(te)? la fine", r"da non perdere", r"momento epico", r"che momento",
    r"you won'?t believe( this)?", r"insane( moment)?", r"wait for it", r"watch (this|till the end)",
    r"epic moment", r"unbelievable", r"crazy moment", r"omg", r"wtf moment", r"this is insane",
]
_GENERIC_RE = re.compile(r"\b(" + "|".join(GENERIC_PHRASES) + r")\b", re.IGNORECASE)
BANNED_TAGS = {"viral", "fyp", "foryou", "foryoupage", "perte", "trending", "funny", "gaming", "video", "videos",
               "gamer", "xyzbca", "tiktok", "reels", "shorts", "explore", "explorepage", "virale", "neiperte"}
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")

# Content-kind and event tags (curated, specific; chosen by facts, never all at once)
KIND_TAGS = {
    "it": {"gaming": ["GamingItalia"], "sport": [], "podcast": ["PodcastItaliano"], "talk": ["IntervisteItaliane"]},
    "en": {"gaming": [], "sport": [], "podcast": ["PodcastClips"], "talk": ["InterviewClips"]},
}
EVENT_TAGS = {
    "it": {"fail": ["FailGaming"], "funny": ["MomentiDivertenti"], "rage": ["GamingRage"], "epic": ["Highlights"],
           "clutch": ["Clutch"], "storytelling": ["StoryTime"], "unexpected": ["PlotTwist"], "reaction": ["Reaction"],
           "gameplay_highlight": ["Gameplay"]},
    "en": {"fail": ["GamingFails"], "funny": ["FunnyMoments"], "rage": ["GamingRage"], "epic": ["Highlights"],
           "clutch": ["Clutch"], "storytelling": ["StoryTime"], "unexpected": ["PlotTwist"], "reaction": ["Reaction"],
           "gameplay_highlight": ["Gameplay"]},
}


GAMING_ONLY_TAGS = {"failgaming", "gamingfails", "gamingrage", "gameplay"}
CATEGORIES = ("funny", "rage", "epic", "fail", "reaction", "clutch", "storytelling", "unexpected", "gameplay_highlight")


# filler sentences that add nothing (removed wherever they appear as a whole sentence)
FILLER_RE = re.compile(
    r"(?:(?<=[.!?])|^)\s*(?:che (?:\w+\s?){1,3}[!.]|momento (?:di )?(?:tensione|emozionante)[^.!?]*|"
    r"che (?:momento|tensione|spettacolo|scena)|che succede\??|incredibile|pazzesco|assurdo|"
    r"(?:la scena|l'azione|l'atmosfera) è (?:intensa|tesa)[^.!?]*(?:dettagli|azione)[^.!?]*|"
    r"insane|unbelievable|what a moment)[.!?]*(?=\s|$)", re.IGNORECASE)


class GenerationError(Exception):
    pass


# ------------------------------------------------------------------ models
def _clean(v, limit: int) -> str:
    s = " ".join(str(v or "").replace("\r", "").split(" "))
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s[:limit].rstrip()


def norm_tag(t: str) -> str:
    h = _hashtag(str(t).lstrip("#").strip())[:30]
    return h[:1].upper() + h[1:]


def dedupe_tags(tags: list[str]) -> list[str]:
    out, seen = [], set()
    for t in tags:
        n = norm_tag(t)
        if n and n.lower() not in seen and n.lower() not in BANNED_TAGS:
            seen.add(n.lower())
            out.append(n)
    return out


class ContentAnalysis(BaseModel):
    category: str = ""
    subject: str = Field("", description="Game / sport / topic")
    event: str = Field("", description="What happens (main event)")
    context: str = ""
    key_moment: str = ""
    why_interesting: str = ""
    speaker: str = "non identificabile"
    tone: Tone = "neutro"
    emotion: str = ""
    evidence: list[str] = Field(default_factory=list, description="Verbatim quotes from the clip speech")
    confidence: float = Field(0.5, ge=0, le=1)
    insufficient_context: bool = False
    source: Literal["llm", "rules"] = "rules"

    @field_validator("category", "subject", "event", "context", "key_moment", "why_interesting", "speaker", "emotion",
                     mode="before")
    @classmethod
    def _txt(cls, v) -> str:
        return _clean(v, 300)

    @field_validator("tone", mode="before")
    @classmethod
    def _tone(cls, v) -> str:
        v = str(v or "").strip().lower()
        alias = {"humorous": "divertente", "funny": "divertente", "tense": "teso", "dramatic": "drammatico",
                 "epic": "epico", "angry": "arrabbiato", "informative": "informativo", "emotional": "emozionante",
                 "relaxed": "rilassato", "surprised": "sorpreso", "neutral": "neutro"}
        v = alias.get(v, v)
        return v if v in Tone.__args__ else "neutro"  # type: ignore[attr-defined]

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v) -> float:
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


class TitleSet(BaseModel):
    options: list[str] = Field(min_length=1, max_length=3)
    selected: str

    @field_validator("options", mode="before")
    @classmethod
    def _opts(cls, v) -> list[str]:
        out = []
        for t in v or []:
            t = _clean(re.sub(r"#\w+", "", str(t)), LIMITS["title"]).strip(" \"'")
            if t and t.lower() not in {o.lower() for o in out}:
                out.append(t)
        return out[:3]

    @model_validator(mode="after")
    def _sel(self) -> TitleSet:
        if self.selected not in self.options:
            self.selected = self.options[0]
        return self


class SocialPost(BaseModel):
    caption: str = Field("", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=15)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _tags(cls, v) -> list[str]:
        return dedupe_tags(list(v or []))


class YouTubeShort(BaseModel):
    title: str = Field("", max_length=100)
    description: str = Field("", max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=15)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _tags(cls, v) -> list[str]:
        return dedupe_tags(list(v or []))


class Platforms(BaseModel):
    instagram: SocialPost
    tiktok: SocialPost
    youtube_shorts: YouTubeShort


class SocialMetadata(BaseModel):
    version: int = VERSION
    language: Literal["it", "en"] = "it"
    content_analysis: ContentAnalysis
    titles: TitleSet
    platforms: Platforms
    generated_by: str = "rules"
    visual_used: bool = False

    def legacy(self) -> dict:
        """Fields of the pre-1.3 content dict (exporter, approval, older UI) kept in sync."""
        ig = self.platforms.instagram
        return {"language": self.language, "title": self.titles.selected, "hook": self.platforms.tiktok.caption[:150],
                "caption": ig.caption, "description": self.platforms.youtube_shorts.description,
                "hashtags": ig.hashtags, "cta": "", "category": self.content_analysis.category}


# ------------------------------------------------------------------ checks
def _words(text: str) -> list[str]:
    return re.findall(r"[\wÀ-ÿ']+", (text or "").lower())


def _stem_set(text: str) -> set[str]:
    return {w[:5] for w in _words(text)}


def is_generic(title: str, game: str = "") -> bool:
    """True when nothing concrete is left after removing generic phrases, the game name and filler."""
    t = _GENERIC_RE.sub(" ", title)
    for g in filter(None, [game]):
        t = re.sub(re.escape(g), " ", t, flags=re.IGNORECASE)
    content = [w for w in _words(EMOJI_RE.sub(" ", t)) if len(w) >= 3 and w not in LLM_STOPWORDS
               and w not in {"cosa", "succede", "questo", "questa", "this", "what", "happens", "guys", "ragazzi"}]
    return len(content) < 2


def unsupported(text: str, facts: str) -> list[str]:
    """Capitalised words (names, teams, places) and numbers that appear nowhere in the facts."""
    known = _stem_set(facts)
    known_lower = set(_words(facts))
    out: list[str] = []
    long_words = [w for w in re.findall(r"[\wÀ-ÿ']{3,}", text or "")]
    title_case = len(long_words) >= 3 and sum(w[:1].isupper() for w in long_words) / len(long_words) > 0.6
    for m in re.finditer(r"\b([A-ZÀ-Ý][\wà-ÿ']{2,})\b", text or ""):
        w = m.group(1)
        start = m.start()
        sentence_start = start == 0 or re.search(r"(^|[.!?:;“\"(\-—\n•])\s*$", text[max(0, start - 3):start])
        if w.lower() in known_lower or w.lower()[:5] in known or (sentence_start and w.lower() in LLM_STOPWORDS):
            continue
        if (sentence_start or title_case) and w.lower() not in _PROPERISH:
            continue  # sentence-initial / Title Case ordinary word (Racconta, Gets, Choked…)
        out.append(w)
    facts_l = (facts or "").lower()
    for m in re.finditer(r"\b\d+(?:[.,]\d+)?\b", text or ""):
        n = m.group(0)
        if n in facts or any(w in facts_l for w in number_words(n)):
            continue
        out.append(n)
    return list(dict.fromkeys(out))


_IT_UNITS = "zero uno due tre quattro cinque sei sette otto nove dieci undici dodici tredici quattordici quindici sedici " \
    "diciassette diciotto diciannove".split()
_IT_TENS = {20: "venti", 30: "trenta", 40: "quaranta", 50: "cinquanta", 60: "sessanta", 70: "settanta", 80: "ottanta",
            90: "novanta"}
_EN_UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
    "seventeen eighteen nineteen".split()
_EN_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}


def number_words(n: str) -> list[str]:
    """'19' → ['diciannove', 'nineteen'] (0-99, plus 100/novantesimo-style ordinals by stem)."""
    try:
        v = int(n)
    except ValueError:
        return []
    out = []
    if v < 20:
        out += [_IT_UNITS[v], _EN_UNITS[v]]
    elif v < 100:
        t, u = v // 10 * 10, v % 10
        it = _IT_TENS[t] + ("" if not u else ("" if u in (1, 8) else "") + _IT_UNITS[u])
        if u in (1, 8):
            it = _IT_TENS[t][:-1] + _IT_UNITS[u]
        out += [it, _EN_TENS[t] + ("" if not u else "-" + _EN_UNITS[u]), _IT_TENS[t][:-1]]  # 90 → "novant…"
    elif v == 100:
        out += ["cento", "hundred"]
    return [w for w in out if w]


# sentence-initial capitalised words that are still suspicious (names commonly invented by models)
_PROPERISH = {"messi", "ronaldo", "ninja", "shroud", "tfue", "juventus", "milan", "inter", "roma", "napoli",
              "fortnite", "warzone", "valorant", "minecraft", "fifa", "trevor", "franklin", "michael", "arthur"}


def cap_emoji(text: str, max_emoji: int = 1) -> str:
    n = 0

    def repl(m):
        nonlocal n
        n += 1
        return m.group(0) if n <= max_emoji else ""
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub(repl, text)).strip()


def similarity(a: str, b: str) -> float:
    wa, wb = set(_words(a)), set(_words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def opening(text: str, n: int = 2) -> str:
    return " ".join(_words(text)[:n])


# ------------------------------------------------------------------ LLM plumbing
def text_model() -> str | None:
    s = get_settings()
    if s.metadata_ai == "off":
        return None
    from backend.clip_detection import semantic

    st = semantic.status()
    return st["model"] if st.get("available") else None


def _call(client: httpx.Client, model: str, prompt: str, temperature: float, *, grammar: bool = True) -> dict:
    """grammar=True: Ollama JSON mode. Its grammar sampler occasionally breaks ("Unexpected empty grammar
    stack") and keeps failing while the model stays loaded, so the retry path unloads the model and asks for
    free text, extracting the JSON object from it."""
    from backend.clip_detection import semantic

    s = get_settings()
    body = {"model": model, "prompt": prompt, "stream": False, "think": False, "keep_alive": "1m",
            "options": {"temperature": temperature, "num_ctx": semantic.NUM_CTX, "top_p": 0.9}}
    if grammar:
        body["format"] = "json"
        data = semantic._generate_raw(client, body, timeout=s.llm_timeout_s)
    else:
        semantic._unload(client, model)
        semantic.wait_unloaded(client, model)
        for attempt in (1, 2):  # a crashed runner (intermittent CUDA errors under WSL) is restarted by Ollama
            try:
                r = client.post(f"{s.llm_url}/api/generate", json=body, timeout=s.llm_timeout_s)
                r.raise_for_status()
                break
            except httpx.HTTPStatusError:
                if attempt == 2:
                    raise
                time.sleep(3)
        data = extract_json(r.json().get("response", ""))
    if not isinstance(data, dict) or not data:
        raise ValueError("risposta vuota o non JSON")
    return data


def extract_json(text: str) -> dict:
    """First top-level {...} object in a free-text answer (handles ```json fences and chatter)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("nessun oggetto JSON nella risposta")


LANG_NAME = {"it": "italiano", "en": "English"}

ANALYSIS_PROMPT = """Sei un analista di contenuti video. Devi capire COSA SUCCEDE in una clip verticale ({duration:.0f} s)
usando SOLO le prove qui sotto. Le prove automatiche possono contenere errori: non trattarle come certezze.

PROVE
- Gioco/sport/argomento dichiarato dall'utente: {game}
- Creator dichiarato: {creator}
- Categoria stimata dall'analisi: {category} · preset di montaggio: {preset}
- Cosa si vede nei fotogrammi (descrizione automatica): {visual}
- Parlato NELLA clip (trascrizione automatica con secondi):
{timed}
- Parlato subito PRIMA della clip (solo contesto): "{before}"
- Parlato subito DOPO la clip (solo contesto): "{after}"
- Giudizio dell'analisi semantica (indizio, può sbagliare su chi parla): {semantic}
- Segnali audio/video: {signals}

REGOLE
- Non inventare nomi di persone, personaggi, squadre, luoghi, risultati o numeri che non compaiono nelle prove.
- "speaker": chi parla SOLO se è chiaro (es. il creator con facecam, un commentatore, i personaggi del gioco);
  altrimenti "non identificabile". Nei videogiochi le voci possono essere dei personaggi, non del giocatore.
- "evidence": 1-3 frasi copiate ALLA LETTERA dal parlato nella clip (vuoto se non c'è parlato).
- Se le prove non bastano per capire l'evento, scrivi una descrizione prudente, confidence <= 0.4 e
  insufficient_context true.
- Scrivi i campi in italiano.

Rispondi SOLO con JSON:
{{"category": "funny|rage|epic|fail|reaction|clutch|storytelling|unexpected|gameplay_highlight", "subject": "gioco/sport/argomento", "event": "evento principale in una frase",
 "context": "contesto della scena", "key_moment": "il momento più interessante", "why_interesting": "perché può
 interessare", "speaker": "...", "tone": "divertente|teso|drammatico|epico|arrabbiato|informativo|emozionante|rilassato|sorpreso|neutro",
 "emotion": "...", "evidence": ["..."], "confidence": 0.0, "insufficient_context": false}}"""

WRITE_PROMPT = """Sei un social media editor per TikTok, Instagram Reels e YouTube Shorts. Scrivi in {lang}.
Clip verticale di {duration:.0f} s su: {subject}.

COSA HA CAPITO L'ANALISI (usa solo questo e le prove, non aggiungere fatti):
{analysis}
Frasi realmente dette nella clip: {quotes}
Cosa si vede: {visual}

DA SCRIVERE: {wanted}

REGOLE GENERALI
- Descrivi concretamente la scena: chi/che cosa + azione + dettaglio. Niente titoli vuoti come "Non ci posso
  credere!", "Momento incredibile!", "Guardate cosa succede!", "Che spettacolo!", "Incredibile!".
- Non inventare nomi, risultati, numeri, luoghi o eventi. {speaker_rule}
- {context_rule}
- Tono {tone}, naturale, non pubblicitario, non artificialmente entusiasta. Massimo 1 emoji per testo (facoltativa).
- Grammatica e concordanze corrette (tempi verbali coerenti, articoli giusti: "uno studio", "un'auto").
- Niente hashtag dentro i testi. La caption non deve ripetere il titolo.
- Non citare elementi dell'interfaccia del gioco (HUD, comandi, "testi a schermo") se non sono l'evento stesso.
- Niente frasi di riempimento: "Che tensione!", "Che succede?", "Che momento", "scena intensa e ricca di dettagli",
  "da non perdere". Una domanda finale solo se invita davvero a dire la propria sull'evento
  (es. "Tu cosa avresti fatto?"), mai domande generiche o senza senso.
- Instagram e TikTok devono avere apertura e struttura diverse tra loro.
- Evita queste aperture già usate di recente: {recent}.

STILE PER PIATTAFORMA
- titles: 3 titoli 30-75 caratteri, con STRUTTURE DIVERSE (es. 1 azione diretta, 2 curiosità con contesto
  senza ingannare, 3 dettaglio o citazione breve). "best" = indice del migliore (0-2).
- youtube_title: descrittivo e chiaro, con le parole chiave dell'argomento, max 90 caratteri.
- instagram: 1-3 frasi naturali che spiegano cosa succede (o cosa viene detto) e perché è interessante, anche per
  chi non conosce il creator; domanda finale solo se pertinente. Non aprire con un elenco di dettagli visivi:
  usa ciò che si vede solo se aiuta a capire l'evento. Max 400 caratteri.
- tiktok: diretto, inizia con un hook concreto sulla scena, linguaggio contemporaneo, max 150 caratteri.
- youtube_description: 1-2 frasi sintetiche con parole chiave pertinenti. Max 300 caratteri.
- keywords: 2-4 parole chiave per hashtag prese da argomento/evento/prove (niente "viral", "fyp", "gaming").

Rispondi SOLO con JSON con queste chiavi: {keys}"""

PART_KEYS = {
    "titles": ['"titles": ["...", "...", "..."]', '"best": 0', '"youtube_title": "..."'],
    "captions": ['"instagram": "..."', '"tiktok": "..."', '"youtube_description": "..."'],
    "hashtags": ['"keywords": ["...", "..."]'],
}
PART_WANTED = {"titles": "3 titoli + titolo YouTube", "captions": "caption Instagram, caption TikTok, descrizione YouTube",
               "hashtags": "parole chiave per gli hashtag"}


def _visual_text(ctx: ClipContext) -> str:
    v = ctx.visual or {}
    if not v:
        return "non disponibile"
    parts = [v.get("setting"), v.get("people"), v.get("action")]
    txt = "; ".join(p for p in parts if p)
    if v.get("on_screen_text"):
        txt += f"; testo a schermo: {v['on_screen_text']}"
    return f"{txt} (tipo: {v.get('kind', '?')}, affidabilità {v.get('confidence', 0.5):.1f})"


def analyze(ctx: ClipContext, client: httpx.Client, model: str, *, grammar: bool = True) -> ContentAnalysis:
    sem = ctx.semantic
    sem_txt = "; ".join(f"{k}: {v}" for k, v in sem.items()) if sem else "non disponibile"
    prompt = ANALYSIS_PROMPT.format(
        duration=ctx.duration, game=ctx.game or "non indicato", creator=ctx.creator or "non indicato",
        category=ctx.category, preset=ctx.preset, visual=_visual_text(ctx),
        timed=ctx.timed_transcript or "(nessun parlato)", before=ctx.before or "-", after=ctx.after or "-",
        semantic=sem_txt, signals="; ".join(ctx.signals) or "nessuno")
    raw = _call(client, model, prompt, temperature=0.2, grammar=grammar)
    a = ContentAnalysis.model_validate({**raw, "source": "llm"})
    # evidence must be verbatim; claims with invented names lower the confidence
    norm_t = " ".join(_words(ctx.transcript))
    a.evidence = [e for e in a.evidence if e and " ".join(_words(e)) in norm_t][:3]
    facts = ctx.facts_text()
    bad = unsupported(" ".join([a.subject, a.event, a.context, a.key_moment]), facts)
    if bad:
        a.confidence = min(a.confidence, 0.4)
        for f in ("event", "context", "key_moment", "why_interesting", "subject"):
            for w in bad:
                setattr(a, f, re.sub(rf"\b{re.escape(w)}\b", "", getattr(a, f)).strip())
    if ctx.speech_poor and not ctx.visual:
        a.insufficient_context = True
        a.confidence = min(a.confidence, 0.35)
    if not a.subject:
        a.subject = ctx.game
    a.category = a.category if a.category in CATEGORIES else ctx.category
    return a


# ------------------------------------------------------------------ deterministic fallback
CATEGORY_IT = {"funny": "scena comica", "rage": "momento di rabbia", "epic": "giocata spettacolare", "fail": "errore",
               "reaction": "reazione a caldo", "clutch": "salvataggio all'ultimo", "storytelling": "racconto",
               "unexpected": "imprevisto", "gameplay_highlight": "momento di gameplay"}
CATEGORY_EN = {"funny": "funny scene", "rage": "rage moment", "epic": "great play", "fail": "mistake",
               "reaction": "live reaction", "clutch": "last-second save", "storytelling": "story",
               "unexpected": "unexpected turn", "gameplay_highlight": "gameplay moment"}


def rules_analysis(ctx: ClipContext) -> ContentAnalysis:
    v = ctx.visual or {}
    quote = ctx.semantic.get("hook") or _best_quote(ctx.transcript)
    event = v.get("action") or ""
    insufficient = not event and (ctx.speech_poor or not quote)
    return ContentAnalysis(
        category=ctx.category, subject=ctx.game, event=event, context=v.get("setting", ""),
        key_moment=f"“{quote}”" if quote else "", why_interesting="", speaker="non identificabile",
        tone="neutro", evidence=[quote] if quote and quote in ctx.transcript else [],
        confidence=0.3 if insufficient else 0.5, insufficient_context=insufficient, source="rules")


def _short(text: str, limit: int = 80) -> str:
    """First clause of a sentence, cut at a word boundary: an analysis sentence → a usable title."""
    t = re.split(r"(?<=[.!?;])\s|,\s(?=(?:mentre|ma|e poi|culminando|sottolineando)\b)", (text or "").strip())[0]
    t = t.rstrip(" .;,")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return t[:1].upper() + t[1:]


def rules_texts(ctx: ClipContext, a: ContentAnalysis, rng: random.Random) -> dict:
    """Prudent texts from the facts (and the AI analysis when that step worked): no invented details."""
    it = ctx.language == "it"
    cat = (CATEGORY_IT if it else CATEGORY_EN).get(ctx.category, "momento" if it else "moment")
    quote = (a.evidence or [_best_quote(ctx.transcript, 70)])[0] if (a.evidence or ctx.transcript) else ""
    event = _short(a.event) if a.event else ""
    game = ctx.game
    cap_cat = cat[:1].upper() + cat[1:]
    titles: list[str] = []
    if event:
        titles.append(f"{event} in {game}" if game and game.lower() not in event.lower() and len(event) < 70 else event)
    if quote:
        titles.append(f"{cap_cat} in {game}: “{quote}”" if game else f"“{quote}”")
        if game:
            titles.append(f"“{quote}” · {game}")
    if not titles:
        titles.append(f"{cap_cat} in {game}" if game else
                      (f"Clip di {ctx.duration:.0f} secondi da descrivere" if it else f"{ctx.duration:.0f}-second clip to describe"))
    titles = [t[:LIMITS["title"]] for t in dict.fromkeys(titles)]
    what = a.event.rstrip(".") if a.event else (f"{cat} in {game}" if game else "")
    if it:
        ig = (f"{what[:1].upper() + what[1:]}." if what else "Clip senza parlato: descrivi tu cosa succede.") + \
            (f" La frase che resta: “{quote}”." if quote else "")
        tt = f"“{quote}”" if quote else (event + "." if event else ig)
        yt = (f"{what[:1].upper() + what[1:]}." if what else "") + (f" «{quote}»" if quote else "")
    else:
        ig = (f"{what[:1].upper() + what[1:]}." if what else "Clip without speech: describe what happens.") + \
            (f" The line that sticks: “{quote}”." if quote else "")
        tt = f"“{quote}”" if quote else (event + "." if event else ig)
        yt = (f"{what[:1].upper() + what[1:]}." if what else "") + (f" \"{quote}\"" if quote else "")
    return {"titles": titles[:3], "best": 0, "youtube_title": titles[0][:90], "instagram": ig[:LIMITS["ig_caption"]],
            "tiktok": tt[:LIMITS["tt_caption"]], "youtube_description": (yt or ig)[:LIMITS["yt_description"]],
            "keywords": []}


# ------------------------------------------------------------------ writing
def _write_prompt(ctx: ClipContext, a: ContentAnalysis, parts: list[str], recent: list[str], current: dict) -> str:
    keys = [k for p in parts for k in PART_KEYS[p]]
    analysis = {k: getattr(a, k) for k in ("event", "context", "key_moment", "why_interesting", "speaker", "tone",
                                           "emotion") if getattr(a, k)}
    speaker_rule = ("Chi parla non è identificato: non attribuire le frasi a una persona precisa (niente 'lo streamer "
                    "dice'), descrivi la scena." if a.speaker.lower().startswith("non") else
                    f"Chi parla: {a.speaker} (non aggiungere nomi).")
    context_rule = ("CONTESTO INSUFFICIENTE: scrivi testi prudenti e descrittivi di ciò che si vede/sente, senza "
                    "supporre cosa sia successo." if a.insufficient_context else
                    "Il contesto è sufficiente: sii specifico.")
    wanted = ", ".join(PART_WANTED[p] for p in parts)
    if "captions" in parts and "titles" not in parts and current.get("titles", {}).get("selected"):
        wanted += f" (il titolo scelto è: \"{current['titles']['selected']}\", non ripeterlo)"
    return WRITE_PROMPT.format(
        lang=LANG_NAME[ctx.language], duration=ctx.duration, subject=a.subject or ctx.game or "argomento non indicato",
        analysis=json.dumps(analysis, ensure_ascii=False), quotes="; ".join(f"“{q}”" for q in a.evidence) or "nessuna",
        visual=_visual_text(ctx), wanted=wanted, speaker_rule=speaker_rule, context_rule=context_rule,
        tone=a.tone, recent=", ".join(f"\"{r}\"" for r in recent[:8]) or "nessuna", keys="{" + ", ".join(keys) + "}")


def _check_texts(raw: dict, ctx: ClipContext, a: ContentAnalysis, recent: list[str], warnings: list[str]) -> dict:
    """Validate/repair LLM texts; drop what is generic or not grounded."""
    facts = ctx.facts_text() + " " + " ".join([a.subject, a.event, a.context, a.key_moment])
    out: dict = {}
    if "titles" in raw:
        good, why = [], []
        for t in raw.get("titles") or []:
            t = cap_emoji(_clean(re.sub(r"#\w+", "", str(t)), LIMITS["title"]).strip(" \"'"), 1)
            if not t:
                continue
            if is_generic(t, ctx.game):
                why.append(f"titolo generico scartato: “{t}”")
                continue
            bad = unsupported(t, facts)
            if bad:
                why.append(f"titolo con elementi non presenti nella clip scartato ({', '.join(bad)}): “{t}”")
                continue
            if any(similarity(t, g) > 0.7 for g in good):
                continue
            good.append(t)
        warnings += why
        best = raw.get("best", 0)
        try:
            best = int(best)
        except (TypeError, ValueError):
            best = 0
        titles = raw.get("titles") or []
        best_text = titles[best] if 0 <= best < len(titles) else None
        recent_open = {opening(r) for r in recent}
        # prefer the model's choice; demote titles whose opening was used recently
        good.sort(key=lambda t: (t != best_text and t.strip(" \"'") != (best_text or "").strip(" \"'"),
                                 opening(t) in recent_open))
        out["titles"] = good
        yt = cap_emoji(_clean(raw.get("youtube_title", ""), 90), 1)
        if yt and not is_generic(yt, ctx.game) and not unsupported(yt, facts):
            out["youtube_title"] = yt
    for key, lim in (("instagram", LIMITS["ig_caption"]), ("tiktok", LIMITS["tt_caption"]),
                     ("youtube_description", LIMITS["yt_description"])):
        if key not in raw:
            continue
        v = cap_emoji(_clean(re.sub(r"(^|\s)#\w+", " ", str(raw.get(key) or "")), lim), 1)
        v = FILLER_RE.sub("", v).strip()
        bad = unsupported(v, facts)
        if not v:
            continue
        if bad:
            warnings.append(f"{key}: testo scartato, contiene elementi non presenti nella clip ({', '.join(bad)})")
            continue
        out[key] = v
    kws = []
    spoken = " ".join(_words(" ".join([ctx.transcript, ctx.game, ctx.creator, (ctx.visual or {}).get("on_screen_text", "")])))
    facts_norm = " ".join(_words(facts))
    for k in raw.get("keywords") or []:
        toks = [w for w in _words(str(k)) if len(w) > 1]
        if not toks:
            continue
        phrase = " ".join(toks)
        if len(toks) == 1:
            # single words only if spoken / declared / readable on screen, and not too short or generic
            raw_k = str(k).strip()
            acronym = raw_k.isupper() and 2 <= len(raw_k) <= 6 and re.search(rf"\b{re.escape(raw_k)}\b", ctx.facts_text())
            if acronym or (len(phrase) >= 5 and re.search(rf"\b{re.escape(phrase[:6])}", spoken)
                           and phrase not in LLM_STOPWORDS):
                kws.append(raw_k)
        elif phrase in facts_norm:  # multi-word topics must appear as such in the facts
            kws.append(str(k))
    if "keywords" in raw:
        out["keywords"] = kws
    return out


# ------------------------------------------------------------------ hashtags
def _kind(ctx: ClipContext) -> str:
    """What kind of content this is — from what is seen, then the declared topic; the editing preset is
    only a last resort (it describes how the clip is edited, not what it is about)."""
    k = (ctx.visual or {}).get("kind", "")
    if "sport" in k:
        return "sport"
    if "podcast" in k:
        return "podcast"
    if "intervista" in k:
        return "talk"
    if k.startswith("video"):
        return "gaming"
    if not k:
        if ctx.preset == "sports_highlights":
            return "sport"
        if ctx.preset == "podcast_clean" and not ctx.game:
            return "podcast"
    return "gaming" if ctx.game else "talk"


def build_hashtags(ctx: ClipContext, a: ContentAnalysis, keywords: list[str], recent_tags: Counter,
                   seed: int) -> dict[str, list[str]]:
    s = get_settings()
    lang = ctx.language
    subject = [norm_tag(ctx.game)] if ctx.game else []
    aliases = [t for t in GAME_TAGS.get(game_profile_key(ctx.game), []) if t.lower() != (subject[0].lower() if subject else "")]
    kind = _kind(ctx)
    known = bool(ctx.game or ctx.visual)
    kind_tags = list(KIND_TAGS[lang].get(kind, [])) if known else []
    event = [t for t in EVENT_TAGS[lang].get(a.category or ctx.category, [])
             if kind == "gaming" or t.lower() not in GAMING_ONLY_TAGS]
    if a.tone == "informativo" and (a.category or ctx.category) == "storytelling":
        event = []  # news/analysis talk is not a "story time"
    kw = dedupe_tags([norm_tag(k) for k in keywords])
    kw = [k for k in kw if k.lower() not in {t.lower() for t in subject + aliases}]
    rng = random.Random(seed)
    rng.shuffle(aliases)
    # tags reused on most recent clips go last (except the subject tag): less repetition across posts
    def fresh(tags: list[str]) -> list[str]:
        return sorted(tags, key=lambda t: recent_tags.get(t.lower(), 0))
    pools = {
        "tiktok": subject + fresh(kw[:2] + event + aliases[:1] + kind_tags + kw[2:]),
        "instagram": subject + fresh(event + kind_tags + kw[:2] + aliases[:1] + kw[2:]),
        "youtube_shorts": subject + fresh(kw[:1] + aliases[:1] + event + kw[1:]),
    }
    limits = {"tiktok": s.hashtags_tiktok, "instagram": s.hashtags_instagram, "youtube_shorts": s.hashtags_youtube}
    # fewer than the minimum only when the facts give nothing more (better 2 good tags than 5 filler ones)
    return {p: dedupe_tags(pool)[: limits[p][1]] for p, pool in pools.items()}


# ------------------------------------------------------------------ entry point
def generate(ctx: ClipContext, *, parts: list[str] | None = None, current: dict | None = None,
             recent_titles: list[str] | None = None, recent_tags: Counter | None = None,
             use_ai: bool = True, client: httpx.Client | None = None,
             model: str | None = None) -> tuple[SocialMetadata, list[str]]:
    """parts: subset of titles | captions | hashtags (None = everything). `current` = stored metadata dict
    whose other parts are kept when regenerating only some of them."""
    parts = [p for p in (parts or ["titles", "captions", "hashtags"]) if p in PART_KEYS] or list(PART_KEYS)
    current = current or {}
    recent_titles = recent_titles or []
    recent_tags = recent_tags or Counter()
    warnings: list[str] = []
    seed = int.from_bytes(f"{ctx.clip_id}:{len(recent_titles)}".encode()[:8], "little")
    rng = random.Random(seed)

    model = model or (text_model() if use_ai else None)
    own = client is None and model is not None
    client = client or (httpx.Client(timeout=get_settings().llm_timeout_s) if model else None)
    try:
        # 1. analysis (reused when regenerating a single part)
        analysis = None
        if current.get("content_analysis") and set(parts) != set(PART_KEYS):
            try:
                analysis = ContentAnalysis.model_validate(current["content_analysis"])
            except ValidationError:
                analysis = None
        if analysis is None and model and (ctx.word_count or ctx.visual):
            for attempt in (1, 2):
                try:
                    analysis = analyze(ctx, client, model, grammar=attempt == 1)
                    if not (analysis.event or analysis.context):
                        raise ValueError("analisi vuota")
                    break
                except (httpx.HTTPError, ValueError, ValidationError) as e:
                    analysis = None
                    if attempt == 2:
                        warnings.append(f"Analisi AI non riuscita ({str(e)[:80]}): uso un'analisi prudente dai dati")
        analysis = analysis or rules_analysis(ctx)

        # 2. texts
        texts: dict = {}
        if model:
            prompt = _write_prompt(ctx, analysis, parts, recent_titles, current)
            if ctx.word_count == 0 and not ctx.visual:
                # nothing to describe: writing would only invent. Prudent texts + ask the user.
                prompt = ""
                warnings.append("Nessun parlato e nessuna descrizione visiva: non genero testi inventati, "
                                "scrivi tu titolo e caption (sotto trovi una base prudente)")
            required = {"titles": "titles", "captions": "instagram", "hashtags": "keywords"}
            # an invalid/empty answer or a crashed runner (intermittent CUDA errors under WSL) gets one more,
            # calmer try before falling back to the prudent texts
            for attempt, temp in (((1, 0.6), (2, 0.4)) if prompt else ()):
                try:
                    raw = _call(client, model, prompt, temperature=temp, grammar=attempt == 1)
                    missing = [p for p in parts if not raw.get(required[p])]
                    if missing:
                        raise ValueError(f"mancano {', '.join(missing)}")
                    texts = _check_texts(raw, ctx, analysis, recent_titles, warnings)
                    break
                except (httpx.HTTPError, ValueError) as e:
                    log.info("metadata writing attempt %d failed: %s", attempt, e)
                    if attempt == 2:
                        warnings.append(f"Scrittura AI non riuscita ({str(e)[:80]}): testi prudenti dai dati")
        fallback = rules_texts(ctx, analysis, rng)
        if not model:
            warnings.append("AI locale non disponibile: testi prudenti costruiti solo dai dati della clip")
    finally:
        if own and client is not None:
            client.close()

    cur_titles = current.get("titles") or {}
    cur_pl = current.get("platforms") or {}

    # titles: AI ones (validated) topped up by grounded fallbacks if fewer than 3 survived
    if "titles" in parts:
        opts = list(texts.get("titles") or [])
        for t in fallback["titles"]:
            if len(opts) >= 3:
                break
            if all(similarity(t, o) < 0.85 and t != o for o in opts):
                opts.append(t)
        titles = TitleSet(options=opts[:3] or fallback["titles"], selected=(opts or fallback["titles"])[0])
        yt_title = texts.get("youtube_title") or titles.selected[:90]
    else:
        titles = TitleSet.model_validate(cur_titles) if cur_titles.get("options") else \
            TitleSet(options=fallback["titles"], selected=fallback["titles"][0])
        yt_title = (cur_pl.get("youtube_shorts") or {}).get("title") or titles.selected[:90]

    def cap(key: str, plat: str, field_: str = "caption") -> str:
        if "captions" in parts:
            return texts.get(key) or fallback[key]
        return (cur_pl.get(plat) or {}).get(field_) or fallback[key]

    ig, tt, ytd = cap("instagram", "instagram"), cap("tiktok", "tiktok"), cap("youtube_description", "youtube_shorts", "description")
    # different platforms, different texts; caption ≠ title
    if similarity(tt, ig) > 0.6:
        if similarity(fallback["tiktok"], ig) < 0.6 and similarity(tt, ig) > 0.8:
            tt = fallback["tiktok"]
            warnings.append("Caption TikTok troppo simile a Instagram: sostituita")
        else:
            warnings.append("Le caption di Instagram e TikTok si somigliano: valuta di differenziarle")
    if similarity(ig, titles.selected) > 0.85:
        warnings.append("La caption Instagram ripete quasi il titolo: valuta di modificarla")

    if "hashtags" in parts:
        tags = build_hashtags(ctx, analysis, texts.get("keywords", []), recent_tags, seed)
    else:
        tags = {p: (cur_pl.get(p) or {}).get("hashtags") or [] for p in PLATFORMS}
        if not any(tags.values()):
            tags = build_hashtags(ctx, analysis, [], recent_tags, seed)

    meta = SocialMetadata(
        language=ctx.language, content_analysis=analysis, titles=titles,
        platforms=Platforms(
            instagram=SocialPost(caption=ig, hashtags=tags["instagram"]),
            tiktok=SocialPost(caption=tt, hashtags=tags["tiktok"]),
            youtube_shorts=YouTubeShort(title=yt_title, description=ytd, hashtags=tags["youtube_shorts"])),
        generated_by=f"ollama:{model}" if model and texts else "rules",
        visual_used=bool(ctx.visual))
    if analysis.insufficient_context:
        warnings.append("Contesto insufficiente: i testi descrivono solo ciò che si vede/sente, verificali")
    return meta, list(dict.fromkeys(warnings))
