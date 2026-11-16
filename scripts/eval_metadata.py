"""Quality evaluation of the social metadata generator with the REAL local model (not mocked).

    .venv/bin/python scripts/eval_metadata.py [out.json]

Eight scenarios (gaming funny/competitive, football, interview, podcast, streamer reaction, little speech,
no context). Besides JSON validity it checks semantics:
- titles concrete (not generic) and anchored to the facts; no invented names/numbers anywhere;
- captions differ across platforms and do not repeat the title; emoji ≤ 1;
- hashtags: no #fyp/#viral filler, subject first, counts within the configured limits;
- insufficient context → flagged, prudent texts;
- variety: title openings differ across scenarios.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.content_generation import metadata as M  # noqa: E402
from backend.content_generation.context import ClipContext  # noqa: E402
from backend.core.config import get_settings  # noqa: E402


def ctx(cid, *, game, category, transcript, visual=None, creator="", preset="custom", duration=30.0, semantic=None,
        signals=None, language="it", before="", after=""):
    words = transcript.split()
    timed = "\n".join(f"({i * 0.4:.1f}s) {' '.join(words[i:i + 12])}" for i in range(0, len(words), 12))
    return ClipContext(clip_id=cid, language=language, speech_language="it", game=game, creator=creator,
                       category=category, preset=preset, duration=duration, transcript=transcript,
                       timed_transcript=timed, before=before, after=after, semantic=semantic or {},
                       detection_reason="", signals=signals or [], visual=visual or {}, word_count=len(words))


SCENARIOS = {
    "gaming_divertente": ctx(
        "eval-funny", game="Minecraft", category="funny",
        transcript="ok adesso metto la TNT sotto la casa di Luca così vede cosa succede aspetta aspetta no no "
                   "è esplosa la mia casa ho sbagliato casa ragazzi ho fatto saltare la mia base",
        visual={"setting": "mondo a blocchi di Minecraft, villaggio con case di legno", "people": "un personaggio in prima persona",
                "action": "una casa esplode dopo che il giocatore piazza dei blocchi rossi", "kind": "videogioco",
                "on_screen_text": "", "confidence": 0.8},
        semantic={"payoff_type": "colpo di scena", "reason": "Il giocatore fa esplodere la propria casa per errore"}),
    "gaming_competitivo": ctx(
        "eval-comp", game="Valorant", category="clutch",
        transcript="sono uno contro tre ho lo spike piantato devo solo difendere uno è dietro la cassa due tre "
                   "ce l'ho fatta uno contro tre ragazzi ace con lo sheriff",
        visual={"setting": "mappa di uno sparatutto tattico", "people": "visuale in prima persona con pistola",
                "action": "il giocatore elimina tre avversari in rapida successione", "kind": "videogioco",
                "on_screen_text": "ACE", "confidence": 0.75},
        signals=["12.4s: picco audio +18 dB con voce (urlo/reazione)"]),
    "calcio": ctx(
        "eval-calcio", game="Serie A", category="epic", preset="sports_highlights",
        transcript="palla al limite dell'area controllo e tiro da fuori area incredibile all'incrocio gol "
                   "che gol al novantesimo",
        visual={"setting": "stadio di calcio pieno di tifosi", "people": "giocatori in maglia bianca e in maglia blu",
                "action": "un giocatore calcia da fuori area e la palla entra all'incrocio dei pali", "kind": "sport",
                "on_screen_text": "90:00", "confidence": 0.8}),
    "intervista": ctx(
        "eval-intervista", game="", category="storytelling", creator="",
        transcript="la prima volta che sono salito su un palco avevo diciannove anni e mi tremavano le gambe "
                   "ho dimenticato il testo a metà canzone e il pubblico ha iniziato a cantarla al posto mio",
        visual={"setting": "studio con due sedie e microfoni", "people": "due persone sedute, una parla",
                "action": "una persona racconta un aneddoto all'altra", "kind": "podcast/intervista",
                "on_screen_text": "", "confidence": 0.7}),
    "podcast": ctx(
        "eval-podcast", game="", category="storytelling", preset="podcast_clean",
        transcript="secondo me il problema del lavoro da remoto non è la produttività è la solitudine "
                   "dopo sei mesi non parlavo più con nessuno durante il giorno",
        visual={"setting": "studio podcast con luci soffuse", "people": "due persone con cuffie e microfoni",
                "action": "conversazione seduti al tavolo", "kind": "podcast/intervista", "confidence": 0.8}),
    "reazione_streamer": ctx(
        "eval-reaction", game="Fortnite", category="reaction", creator="Marco",
        transcript="no no no no non ci credo mi ha sniperato da tre chilometri ma come ha fatto",
        visual={"setting": "partita a battle royale", "people": "facecam di un ragazzo con cuffie nell'angolo",
                "action": "il personaggio viene eliminato da lontano, il ragazzo in facecam si mette le mani in testa",
                "kind": "videogioco", "has_facecam": True, "confidence": 0.75},
        signals=["8.2s: picco audio +20 dB con voce (urlo/reazione)"]),
    "poco_parlato": ctx(
        "eval-poco", game="Forza Horizon 5", category="gameplay_highlight", transcript="vai vai",
        visual={"setting": "strada di montagna al tramonto", "people": "nessuna persona visibile",
                "action": "un'auto sportiva salta da un dosso e atterra continuando la corsa", "kind": "videogioco",
                "confidence": 0.7}),
    "senza_contesto": ctx("eval-nocontext", game="", category="gameplay_highlight", transcript="", visual={}),
}


def check(name: str, c: ClipContext, meta: M.SocialMetadata, warnings: list[str]) -> list[str]:
    s = get_settings()
    issues: list[str] = []
    facts = c.facts_text()
    a = meta.content_analysis
    for t in meta.titles.options:
        if M.is_generic(t, c.game):
            issues.append(f"titolo generico: {t}")
        if M.unsupported(t, facts + " " + a.event + " " + a.context):
            issues.append(f"titolo con elementi inventati: {t}")
        if len(M.EMOJI_RE.findall(t)) > 1:
            issues.append(f"troppe emoji: {t}")
    pl = meta.platforms
    texts = {"instagram": pl.instagram.caption, "tiktok": pl.tiktok.caption, "youtube": pl.youtube_shorts.description}
    for k, v in texts.items():
        bad = M.unsupported(v, facts + " " + a.event + " " + a.context + " " + a.key_moment)
        if bad:
            issues.append(f"{k}: elementi non presenti nei fatti {bad}")
        if len(M.EMOJI_RE.findall(v)) > 1:
            issues.append(f"{k}: troppe emoji")
        if "#" in v:
            issues.append(f"{k}: hashtag dentro il testo")
    if M.similarity(pl.instagram.caption, pl.tiktok.caption) > 0.6:
        issues.append("caption Instagram e TikTok troppo simili")
    if M.similarity(pl.instagram.caption, meta.titles.selected) > 0.7:
        issues.append("caption Instagram ripete il titolo")
    for p, tags, (lo, hi) in (("instagram", pl.instagram.hashtags, s.hashtags_instagram),
                              ("tiktok", pl.tiktok.hashtags, s.hashtags_tiktok),
                              ("youtube", pl.youtube_shorts.hashtags, s.hashtags_youtube)):
        if len(tags) > hi:
            issues.append(f"{p}: {len(tags)} hashtag > {hi}")
        if any(t.lower() in M.BANNED_TAGS for t in tags):
            issues.append(f"{p}: hashtag generici {tags}")
        if c.game and tags and tags[0].lower() != M.norm_tag(c.game).lower():
            issues.append(f"{p}: l'argomento non è il primo hashtag {tags}")
    if name == "senza_contesto" and not (a.insufficient_context or a.confidence <= 0.4):
        issues.append("contesto insufficiente non segnalato")
    return issues


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("metadata_eval.json")
    model = M.text_model()
    print(f"Modello: {model or 'NESSUNO (solo regole)'}")
    results, openings = {}, Counter()
    recent: list[str] = []
    for name, c in SCENARIOS.items():
        t0 = time.monotonic()
        meta, warnings = M.generate(c, recent_titles=recent[-10:])
        dt = time.monotonic() - t0
        issues = check(name, c, meta, warnings)
        recent.append(meta.titles.selected)
        openings[M.opening(meta.titles.selected)] += 1
        results[name] = {"elapsed_s": round(dt, 1), "issues": issues, "warnings": warnings,
                         "metadata": meta.model_dump()}
        print(f"\n=== {name}  ({dt:.0f} s, {meta.generated_by})  {'OK' if not issues else 'PROBLEMI: ' + '; '.join(issues)}")
        print(f"  analisi: {meta.content_analysis.event}  [conf {meta.content_analysis.confidence:.2f}"
              f"{', contesto insufficiente' if meta.content_analysis.insufficient_context else ''}]")
        for t in meta.titles.options:
            print(f"  {'→' if t == meta.titles.selected else ' '} {t}")
        print(f"  IG: {meta.platforms.instagram.caption}\n      #{' #'.join(meta.platforms.instagram.hashtags)}")
        print(f"  TT: {meta.platforms.tiktok.caption}\n      #{' #'.join(meta.platforms.tiktok.hashtags)}")
        print(f"  YT: {meta.platforms.youtube_shorts.title} — {meta.platforms.youtube_shorts.description}"
              f"\n      #{' #'.join(meta.platforms.youtube_shorts.hashtags)}")
        if warnings:
            print(f"  avvisi: {warnings}")
    repeated = {k: v for k, v in openings.items() if v > 1}
    print(f"\nAperture dei titoli ripetute tra scenari: {repeated or 'nessuna'}")
    total = sum(len(r["issues"]) for r in results.values())
    print(f"Problemi totali: {total} su {len(SCENARIOS)} scenari")
    out_path.write_text(json.dumps({"model": model, "results": results, "repeated_openings": repeated},
                                   ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
