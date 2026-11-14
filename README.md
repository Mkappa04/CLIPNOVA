# CLIPNOVA

Piattaforma **locale** per trasformare registrazioni gaming autorizzate in contenuti verticali
(TikTok, Instagram Reels, YouTube Shorts). Gira interamente dentro **Ubuntu su WSL 2**, budget 0 €,
nessun servizio cloud obbligatorio. Primo gioco supportato: **GTA 6**, ma è indipendente dal gioco.

> Stato: **Milestone 2** completata. M1: import video, libreria, diritti, job queue, dashboard.
> M2: analisi video/audio, trascrizione faster-whisper (GPU), clip detection con scoring configurabile, anteprime.
> Editing/sottotitoli/render (M3) e approvazione/export (M4) sono in roadmap.

## Requisiti

| Componente | Versione | Note |
|---|---|---|
| Windows 11 + WSL 2 | — | Ubuntu 22.04+ |
| Python | ≥ 3.10 | con `python3-venv` |
| Node.js / npm | ≥ 18 | solo per buildare la dashboard |
| FFmpeg | ≥ 4.4 | `sudo apt install ffmpeg` |
| GPU NVIDIA | opzionale | driver **solo su Windows**; in WSL non installare driver NVIDIA Linux |

Il progetto deve stare nel filesystem Linux (`/home/...`), **non** in `/mnt/c`.

## Installazione

```bash
cd /home/flavio/projects/clipnova
./install.sh          # verifica ambiente, crea .venv, installa dipendenze, builda la dashboard, crea .env
./install.sh --dev    # in più: pytest + httpx per i test
./install.sh --no-ai  # salta lo stack AI (~1,5 GB): niente clip detection
```

`install.sh` è idempotente: non sovrascrive mai `.env` né la cartella `data/`.
Se manca un pacchetto di sistema, stampa il comando `apt` da eseguire (non usa `sudo` da solo).

## Avvio / arresto

```bash
./start.sh            # API + dashboard su http://localhost:8000 (apribile dal browser di Windows)
./start.sh --dev      # backend con auto-reload + Vite su http://localhost:5173
./start.sh -f         # backend in foreground (Ctrl+C per uscire)
./stop.sh             # ferma solo i processi avviati da start.sh
```

- Documentazione API interattiva: http://localhost:8000/docs
- Log: `data/logs/clipnova.log` (rotazione 5×5 MB), `data/logs/backend.out`

## Funzionalità (Milestone 1)

- **Import video**: upload multiplo (drag & drop, barra di avanzamento) oppure **import da percorso locale**
  - *Riferimento*: il file resta dov'è e CLIPNOVA **non lo cancella mai**
  - *Copia*: copiato in `data/videos` con progresso e annullamento
  - percorsi Windows (`C:\...`) tradotti automaticamente in `/mnt/c/...`
  - formati: mp4, mkv, mov, avi, webm, flv, m4v, ts, mts, wmv
- **Metadati automatici** (ffprobe): durata, risoluzione, FPS, codec, bitrate, rotazione; thumbnail
- **Libreria**: ricerca, filtri per gioco e stato, player integrato (streaming con HTTP Range), modifica metadati
- **Diritti**: proprietario, fonte/URL, licenza, stato autorizzazione, uso commerciale, attribuzione,
  scadenza, restrizioni, prova del permesso, con verifica automatica per export commerciale/non commerciale.
  *Il solo credito non è considerato un'autorizzazione.*
- **Job queue** persistente (SQLite): progresso, annullamento, recupero dopo riavvio, 1 worker di default
- **Dashboard**: video, clip, revisioni, approvate, render, errori, storage, job attivi
- **Settings**: stato WSL, GPU/VRAM, NVENC, RAM, disco, runtime AI
- Eliminazione sempre con **conferma esplicita**; i file vengono cancellati solo se gestiti da CLIPNOVA e su richiesta

## Funzionalità (Milestone 2): Clip Detection

Pagina **Clip Detection** → scegli un video → *Analizza video*. Tutto gira in locale:

| Fase | Tecnologia | Note |
|---|---|---|
| Proxy + audio | FFmpeg, una sola decodifica | proxy 320 px / 10 fps + WAV 16 kHz mono, in cache |
| Audio | NumPy | loudness, picchi sopra la mediana locale (30 s), spectral flux, silenzi |
| Scene | PySceneDetect (AdaptiveDetector) | sul proxy, a blocchi (progresso + annullamento) |
| Movimento | OpenCV | differenza tra frame e flash di luminosità |
| Parlato | faster-whisper `large-v3-turbo` int8 su GPU | VAD, timestamp per parola, filtro allucinazioni; fallback CPU `small` |
| Scoring | euristiche spiegabili | keyword IT/EN + profilo GTA, risate, parlato concitato, picchi, movimento, cambi scena |

Ogni clip ha: inizio/fine/durata, categoria (Funny, Rage, Epic, Fail, Reaction, Clutch, Storytelling,
Unexpected, Gameplay Highlight), score 0-100, confidenza, trascrizione, **motivazione con le evidenze**,
titolo suggerito (cita solo frasi realmente pronunciate vicino al picco), segnali e categorie candidate.

- **Timeline** interattiva dell'interesse stimato con clip, cambi scena e parlato
- **Scoring configurabile**: pesi dei 7 segnali, durata min/max, contesto prima/dopo, numero clip,
  score minimo, ricalcolo istantaneo dalla cache (nessuna nuova trascrizione)
- **Anteprima** MP4 ≤720p per clip (NVENC), modifica timestamp ±1 s, categoria, titolo;
  stati *in revisione / scartata / archiviata*; clip manuali; le clip toccate dall'utente sopravvivono al ricalcolo
- Download trascrizione in **SRT** o testo
- Keyword personalizzabili in `data/config/lexicon.json` (vedi `backend/clip_detection/lexicon.py`)

**Limiti (onestamente):** categorie e score sono *euristiche*: indicano dove è probabile che succeda qualcosa,
non capiscono il gioco. Le risate sono rilevate solo quando compaiono nella trascrizione (ahah, haha, [risate]):
non c'è ancora un classificatore audio di eventi. Senza parlato la confidenza è ridotta del 25%.

### Prestazioni misurate (i5-11400H, RTX 3060 Laptop 6 GB, WSL 2)

| Video | Tempo analisi | Note |
|---|---|---|
| 60 s, 720p | ~10 s | |
| 10 min, 1080p60 | **45 s** | preparazione 33 s, scene 5 s, trascrizione 7 s |
| Primo avvio | +~90 s | download unico di `large-v3-turbo` (1,6 GB) |

- VRAM: picco ~1,2 GB durante la trascrizione (limite 6 GB); torna al livello base a fine job
- RAM: Whisper gira in un **processo separato** per ogni job → il server resta ~250 MB
- Decodifica: su questa CPU FFmpeg decodifica 1080p60 più velocemente di NVDEC (30 s vs 51 s per 10 min),
  quindi il default è `CLIPNOVA_ANALYSIS_DECODER=cpu` con NVDEC come fallback

## Configurazione

Tutto in `.env` (vedi `.env.example`), variabili con prefisso `CLIPNOVA_`.
Il server rifiuta di mettersi in ascolto su indirizzi diversi da localhost a meno di
`CLIPNOVA_ALLOW_PUBLIC_BIND=true`.

## Test

```bash
./install.sh --dev
.venv/bin/pytest                  # backend: API, job queue, ffmpeg, diritti, analisi, scoring, Whisper (modello tiny)
cd frontend && npm run typecheck  # frontend: TypeScript strict
```

## Struttura

```
backend/            FastAPI app (main.py)
  api/routers/      endpoint REST (videos, jobs, system/dashboard)
  core/             config, logging, eccezioni
  database/         engine SQLAlchemy + sessioni (SQLite WAL)
  models/           entità ORM + schemi Pydantic
  services/         ffmpeg, import video, info di sistema
  workers/          job queue + handler
  rights_management/ policy diritti/export
  clip_detection/   media prep, audio, scene/movimento, lessico, scoring, pipeline
  transcription/    faster-whisper (GPU/CPU, processo isolato)
  database/migrations/  migrazioni Alembic (applicate automaticamente all'avvio)
  editing/ subtitles/ publishing/   (milestone successive)
frontend/src/       React + TS + Tailwind (components, pages, hooks, services, stores, types)
tests/              pytest
scripts/            helper bash (check_env.sh, common.sh)
docs/               architettura e note
data/               (gitignored) video, thumbnail, DB, log, render
```

Vedi [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Uso responsabile

CLIPNOVA lavora solo su file locali ottenuti legittimamente. Non esegue scraping di Twitch/YouTube,
non aggira DRM o autenticazioni e non pubblica nulla senza approvazione esplicita (pubblicazione
disabilitata per default).
