# Changelog

## 2.0.0 — AI Video Editing Engine

Piano tecnico e architettura: `docs/EDITING_ENGINE_2.md`.

- **AI Video Director** (`backend/editing/director.py`).
  - **Classifica i momenti**: divertente, spettacolare, competitivo, narrativo, emozionante, informativo, tensione.
    Il *solo movimento* viene declassato: un'azione movimentata da sola non vale un effetto.
  - **Legge la clip**: energia, ritmo del parlato, cambi di scena, copertura del parlato, musica già presente
    nell'audio (stima) e comprensibilità senza contesto (autonomia semantica, parlato, descrizione visiva).
  - **Sceglie lo stile** (minimale, equilibrato, energico, cinematografico) dentro il preset: un dialogo calmo in
    "Gaming Dynamic" riceve un montaggio minimale.
  - **Decide** effetti di tempo, transizioni, grafiche, look, musica e suoni.
- **Piano v2** (Pydantic).
  - **Tracce**: accenti visivi, tempo, transizioni, testi, suoni, musica, look e la lettura del regista.
  - **Ogni elemento** ha id, priorità e motivazione.
  - **Il validatore ripara e annota**:
    - timestamp fuori dalla clip;
    - effetti incompatibili, per esempio shake o zoom sul fermo immagine, o glitch nello slow motion;
    - effetti di tempo nelle pause tagliate o sul parlato;
    - allungamento oltre il 30 %;
    - transizioni fuori dai tagli;
    - testi sovrapposti;
    - suoni impilati;
    - testo ASS iniettato.
  - **L'LLM locale** sceglie solo tra opzioni consentite (effetto, effetto di tempo, mood). Non scrive mai comandi
    FFmpeg.
- **Audio Engine.**
  - **Libreria audio** (tabella `audio_assets`, migrazione 0007):
    - sei tracce originali generate proceduralmente (CC0), una per mood: cinematografica, dinamica, elettronica,
      rilassata, drammatica, gaming;
    - effetti sonori di serie in 12 categorie: whoosh, impact, bass drop, riser, explosion, hit, transition, UI,
      cinematic, gaming, pop, ding;
    - import dei tuoi file con licenza obbligatoria, conferma dei diritti, attribuzione per CC BY e fonte;
    - analisi automatica di durata, livello, BPM, beat, drop e loop;
    - anteprima, volume per file, attivazione e disattivazione.
  - **Colonna sonora**:
    - musica scelta dal regista per mood, con le tue tracce preferite;
    - il drop o il battere della musica cade sul culmine della clip;
    - loop su battute con crossfade, fade in e out, livello automatico;
    - ducking sotto il parlato, guidato dalla trascrizione;
    - SFX mai impilati, limitatore;
    - opzione per tenere solo l'audio originale.
- **Visual Effects Engine** (`vfx.py`).
  - **Effetti**:
    - camera shake con motion blur, flash, blur, zoom blur, glitch;
    - fermo immagine con push-in;
    - slow motion e speed ramping con frame blending, e frame reali se la sorgente ha più fps;
    - color grading in 7 look più vignettatura;
    - transizioni sui tagli: dissolvenza, zoom blur, flash, glitch, passaggio al nero.
  - **Prestazioni**: tutti deterministici, ≤ 23 ms per frame a 1080×1920.
- **Motion Graphics.**
  - **Titolo hook animato** quando la clip ha bisogno di contesto.
  - **Callout** con parole dette nella clip o testo leggibile a schermo, mai inventati.
  - **Watermark testuale** dal Brand Kit.
  - **Sottotitoli personalizzabili**: font, colori, animazione.
- **Preset**: nuovi **Gaming Cinematic** e **Storytelling**; Gaming Dynamic, Sports Highlights e Podcast Clean
  aggiornati con stile, effetti di tempo, look e musica.
- **Rendering.**
  - **Time remapping** esatto, con durate quantizzate al frame e la stessa mappatura per video e audio:
    l'audio è montato per segmenti con `atempo`, nessuna deriva A/V.
  - **Audio nello slow motion**: ovattato, rallentato o muto.
  - **Robustezza**: colonna sonora in un file temporaneo rimosso a fine render; NVENC con fallback libx264.
  - **Report del render**: musica, effetti di tempo, transizioni e grafiche nelle statistiche.
- **Editor.**
  - **Timeline a 6 tracce**: FX, tempo, tagli, testi, suoni, musica.
  - **Riepilogo del regista**: stile, energia, comprensibilità, momenti classificati.
  - **Interruttore per ogni intervento**: si possono disattivare singoli effetti, la musica o il look.
  - **Pannello Musica**: anteprima, mood, traccia, volume, ducking.
  - **Look e grafiche** configurabili.
  - **Nuova pagina Libreria audio.**
- **Test**: Director su 5 tipi di contenuto (verifica che ricevano montaggi diversi), validazione, Audio Engine
  (tempo, sync, ducking, loop, licenze via API), VFX (pixel), timeline e un render reale con slow motion,
  fermo immagine e musica che verifica la sincronia audio/video di un evento.

## 1.3.0 — titoli, caption e hashtag che descrivono la clip

- **Analisi del contenuto prima di scrivere**: parlato con i tempi, contesto prima e dopo la clip, giudizio
  semantico, segnali audio/video, preset e — novità — **cosa si vede nei fotogrammi** (modello visivo locale
  `qwen3.5:4b`). Il risultato (evento, contesto, momento chiave, perché interessa, chi parla, tono, prove citate
  alla lettera, affidabilità, "contesto insufficiente") è visibile nella revisione.
- **3 titoli con strutture diverse** e scelta del migliore; **testi diversi per piattaforma** (caption Instagram,
  caption TikTok, titolo e descrizione YouTube Shorts); **hashtag specifici** per piattaforma (argomento, tipo di
  contenuto, evento, parole chiave presenti nella clip; niente #fyp/#viral automatici), quantità configurabili.
- **Controlli**: JSON validato (Pydantic), titoli generici scartati, nomi/numeri non presenti nella clip scartati,
  emoji limitate, riempitivi rimossi, caption diverse tra piattaforme, meno ripetizioni rispetto alle clip recenti.
- **Robustezza**: nuovo tentativo senza vincolo JSON quando il campionatore di Ollama si blocca, e dopo i crash CUDA
  intermittenti; testi prudenti costruiti solo dai dati quando l'AI non è disponibile; nessun testo inventato
  quando la clip non ha né parlato né immagini descrivibili.
- **Revisione**: modifica e copia di ogni testo, editor degli hashtag, rigenerazione separata di titoli, caption o
  hashtag; l'export usa i testi di ciascuna piattaforma. Compatibile con i testi salvati in precedenza.
- `scripts/eval_metadata.py`: valutazione della qualità con il modello reale su 8 scenari.

## 1.2.0 — montaggio automatico

- **Preset di editing**: Gaming Dynamic, Sports Highlights, Podcast Clean, cioè parametri dell'editor e regole del
  planner, personalizzabili in `data/config/editing_presets.json`.
- **AI Editing Planner**: piano JSON validato (Pydantic) per ogni clip, con zoom leggero, progressivo o rapido,
  enfasi sui sottotitoli, flash, shake, effetti sonori, pause tenute o tagliate. La scelta esplicita "none" è
  motivata. Le regole sono sempre disponibili; l'LLM locale (Ollama) sceglie solo tra i momenti candidati. Ci sono
  limiti di frequenza e durata e un budget per gli SFX. Il piano si vede in una timeline nel Clip Editor.
- **Inquadratura sullo speaker**: tracking dei volti (YuNet) con scelta di chi parla. Se i volti non sono
  affidabili si ripiega sull'azione e poi sul centro. Velocità della camera regolabile; Sports la usa più rapida.
- **Sottotitoli**: Dynamic Captions e Clean Captions, parole chiave in un colore dedicato.
- **Brand Kit**: upload del logo PNG (validato e ricodificato), posizione, dimensione, opacità, margine, zone
  sicure delle piattaforme, attivabile per singola clip. Overlay FFmpeg deterministico.
- **Effetti sonori**: libreria inclusa sintetizzata (CC0) e cartella `data/sfx/` per i tuoi file. Mix con
  `adelay`/`amix` più limiter, volume regolabile.
- FPS "come la sorgente", pulsante *Anteprima* (render bozza), *Rigenera* sui render.
- Migrazione 0006 (tabella `brand_assets`, `clips.edit_plan`), solo additiva. Il backup include logo e SFX.

## 1.1.0 — clip migliori

- **Analisi semantica con LLM locale** (Ollama, default `qwen3:8b`, ripiego su `qwen3.5:4b`): il parlato viene diviso
  in unità di pensiero (tagliate nelle pause) e valutato a blocchi di ~1 minuto con domande concrete (tipo e forza
  del culmine, autonomia, chiacchiera generica); le clip iniziano e finiscono su pensieri interi; l'hook è sempre
  una citazione verbatim. Poi una classifica comparativa di tutti i candidati.
- **Impara dai tuoi gusti**: le clip che approvi/esporti e quelle che rifiuti diventano esempi. Affinità di contenuto
  con embedding locali (`embeddinggemma`) a ogni ricalcolo + esempi nella classifica dell'LLM
  (pulsante *Riordina con i miei gusti*).
- Keyword pesate per rarità nel video (gli intercalari ripetuti non contano), clip più lunghe e complete (20–75 s),
  selezione relativa (i momenti migliori anche in video senza picchi virali).
- Stabilità LLM su GPU da 6 GB: valutazione e classifica usano la stessa istanza del modello (stesso contesto 4096,
  niente scarica/ricarica in mezzo: la ricarica a 8192 token mandava in crash Ollama per memoria video esaurita);
  il prompt della classifica viene accorciato per stare nel contesto (max 30 candidati); un nuovo tentativo
  automatico se Ollama risponde 500.
- Trascrizione: blocchi da 30 s, fino a 4 tentativi GPU per blocco prima della CPU (qualità del modello grande
  nonostante i crash CUDA intermittenti).

## 1.0.0 — release locale (Milestone 5)

- **Analytics**: produzione giornaliera (video importati, render), workflow (rilevate → renderizzate → approvate →
  esportate → pubblicate), categorie con score medio, distribuzione degli score, prestazioni di analisi e render,
  import automatico, spazio su disco.
- **Trascrizione a blocchi ripristinabile**: l'audio viene diviso in blocchi da ~45 s nei punti più silenziosi; se il
  worker GPU va in crash (errori CUDA intermittenti di CTranslate2 osservati su audio reale lungo in WSL) un nuovo
  worker riprende dal blocco fallito; un blocco che fallisce due volte viene fatto su CPU, poi si torna alla GPU.
  Misurato: 10 min di audio reale in 202 s nonostante 5 crash GPU (prima: tutto su CPU, ~16 min).
- Worker Whisper terminati automaticamente se il server muore (`PR_SET_PDEATHSIG`).
- **Manutenzione spazio** (Settings): file orfani, cache di video eliminati, audio di analisi rigenerabile, anteprime,
  render/export orfani, VACUUM del database. Solo dentro `data/`, solo con conferma, rimandata se ci sono job attivi.
- Calcolo dello spazio corretto: i link simbolici della cache Hugging Face venivano contati due volte (6,2 GB → 2,1 GB
  reali); hard link degli export contati una volta; misura in cache 60 s (la dashboard la chiedeva ogni 3 s).
- Frontend: pagine caricate on demand (bundle iniziale 356 → 231 KB), ErrorBoundary per pagina.
- Messaggi della policy diritti in italiano.
- Script: `scripts/backup.sh` (database con backup SQLite consistente, chiave, `.env`, prove dei consensi),
  `scripts/doctor.sh` (diagnostica), `scripts/install-service.sh` (servizio systemd utente, opzionale).
- Documentazione: `docs/USER_GUIDE.md`.

## 0.5.0 — Milestone 4B
Cartelle monitorate e pipeline automatica, scoperta contenuti via API ufficiali (solo ricerca), CRM dei permessi.

## 0.4.0 — Milestone 4
Approval Center, generazione testi (template + LLM locale opzionale con guardrail), export con controllo diritti,
architettura di pubblicazione (API ufficiali, disabilitata di default).

## 0.3.0 — Milestone 3
Editor verticale 1080×1920 (layout, smart crop, zoom, transizioni, audio), motore sottotitoli ASS, rendering NVENC.

## 0.2.0 — Milestone 2
Analisi video/audio, trascrizione faster-whisper, clip detection con scoring spiegabile e configurabile.

## 0.1.0 — Milestone 1
Base FastAPI + React, import video, libreria, gestione diritti, job queue, dashboard.
