# AI Video Editing Engine 2.0 — piano tecnico

Stato di partenza (1.3.0): il montaggio è già un'architettura a piano controllato.

```
PlannerInput (parole, segnali audio/video, picco, hook) → candidati con evidenze
  → decisione (regole del preset | LLM locale che sceglie solo tra i candidati) → limiti rigidi
  → EditPlan (Pydantic) → renderer: decode FFmpeg → compositor OpenCV → encode FFmpeg (ASS, logo, loudnorm, SFX)
```

La 2.0 **estende** questa catena. Non la sostituisce.

## Cosa si riusa, cosa cambia, cosa è nuovo

| Componente | Destino |
|---|---|
| `planner.py` (candidati, regole, LLM, `enforce`, `EditPlan`) | **Modificato**. Il piano passa alla v2 con nuove tracce: tempo, transizioni, testi, musica, suoni, look. Ogni elemento ha `id`, priorità e motivazione. I piani v1 salvati restano validi e vengono ricalcolati. |
| `presets.py` | **Modificato**. Due preset nuovi (Gaming Cinematic, Storytelling). La policy aggiunge stile, effetti di tempo, transizioni, look, musica, grafiche. |
| `effects.py` (SFX sintetizzati CC0) | **Esteso**. Dieci categorie richieste (whoosh, impact, bass drop, riser, explosion, hit, transition, UI, cinematic, gaming). `pop` e `ding` restano. |
| `timeline.py` | **Modificato**. I segmenti hanno una velocità (slow motion, speed ramp) e un fermo immagine. La mappatura è invertibile (uscita → sorgente). |
| `renderer.py` | **Modificato**. Il ciclo è guidato dai frame di uscita (time remapping con frame blending). L'audio è costruito per segmenti (`atrim` + `atempo` + `concat`). La colonna sonora è mixata come traccia unica. Il fallback NVENC → libx264 resta. |
| `compositor.py`, `reframe.py`, `logo_overlay.py`, `subtitles/*` | Riusati così come sono. Solo piccole aggiunte agli stili dei sottotitoli: font, colori e animazione configurabili. |
| `content_generation/vision.py` | Riusato. La descrizione visiva (in cache) entra nel Director. |
| **`director.py`** | **Nuovo**. AI Video Director: analizza la clip, classifica i momenti, decide lo stile e sceglie effetti di tempo, transizioni, grafiche, look e musica. |
| **`vfx.py`** | **Nuovo**. Visual Effects Engine: registro di effetti parametrizzati in numpy/OpenCV (grade, vignette, glitch, blur, motion blur, freeze look, transizioni). |
| **`motion_graphics.py`** | **Nuovo**. Titolo hook animato, callout, watermark testuale. Sono eventi ASS (libass) con animazioni di ingresso e uscita. |
| **`audio_library.py`** + **`music_synth.py`** | **Nuovi**. Libreria audio su DB (tabella `audio_assets`, migrazione 0007) con licenza e provenienza obbligatorie e analisi di durata, BPM, beat e drop. Le tracce di serie sono originali, generate proceduralmente (CC0). |
| **`audio_engine.py`** | **Nuovo**. Colonna sonora in numpy: musica in loop, allineata al beat sul culmine, fade, volume automatico, ducking sul parlato, SFX senza sovrapposizioni, limitatore. |
| Frontend | **Modificato**. Editor con tracce del piano e interruttori per ogni elemento, pannello Musica, look e grafiche. Pagina nuova **Libreria audio** (import con licenza, anteprima, volumi). |

## Principi

- **L'LLM non esegue niente.** Sceglie solo tra candidati ed effetti consentiti, con identificatori. Il backend traduce il piano in operazioni predefinite (funzioni numpy/OpenCV, filtri FFmpeg costruiti dal codice). Nessun comando FFmpeg viene scritto dall'AI.
- **Ogni intervento ha una causa nel contenuto**: un'evidenza audio, testuale, visiva o semantica. Senza evidenza la scelta è "nessun effetto". Il movimento da solo non basta a rendere un momento interessante: viene declassato.
- **Lo stile viene dal preset, la scelta dal Director.** Il preset dà un budget e un elenco di effetti consentiti. Il Director decide quanto usarne e può scegliere un montaggio minimalista.
- **Validazione dopo la decisione, sempre.** Timestamp entro i limiti, niente sovrapposizioni, compatibilità tra effetti, budget, volumi, durata massima. Gli errori vengono riparati, se non si può l'elemento viene scartato, e ogni correzione viene annotata nel piano.
- **Licenze.** Un file audio senza licenza dichiarata non può essere importato. Ogni asset tiene licenza, attribuzione e fonte. Le tracce di serie sono originali (CC0).

## Fasi

1. Analisi e piano: questo documento.
2. Director e piano v2: modelli Pydantic, classificazione dei momenti, stile, regole di compatibilità, LLM vincolato.
3. Audio Engine: libreria, sintesi musicale e SFX, analisi BPM e drop, colonna sonora (ducking, beat sync, fade).
4. Visual Effects Engine: effetti e transizioni parametrizzati.
5. Motion Graphics: hook, callout, watermark, stile sottotitoli configurabile.
6. Rendering: time remapping, audio per segmenti, mix della colonna sonora, pulizia dei file temporanei.
7. Preset: Gaming Dynamic, Gaming Cinematic, Podcast Clean, Sports Highlights, Storytelling.
8. Frontend: editor, piano a tracce, musica, libreria audio.
9. Test end-to-end su contenuti diversi e documentazione.

## Limiti dichiarati

- **Musica di serie.** È generata proceduralmente: funzionale e originale, ma non vale una produzione professionale. Il motore preferisce le tracce importate dall'utente (con licenza) quando sono adatte al mood.
- **Slow motion.** Usa il frame blending. Dove la sorgente ha più fps dell'uscita (per esempio 60 → 30) usa frame reali. Non c'è interpolazione ottica.
- **Ducking.** Si basa sulla trascrizione: abbassa la musica dove ci sono parole. La musica già presente nell'audio originale è solo una stima (fondo costante senza parlato).
- **Loudness della musica.** Viene stimata in RMS dBFS, senza K-weighting. Il mix finale passa comunque da loudnorm e da un limitatore.
