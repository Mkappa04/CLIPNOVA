# CLIPNOVA

Piattaforma **locale** per trasformare registrazioni gaming autorizzate in contenuti verticali
(TikTok, Instagram Reels, YouTube Shorts). Gira interamente dentro **Ubuntu su WSL 2**, budget 0 €,
nessun servizio cloud obbligatorio. Primo gioco supportato: **GTA 6**, ma è indipendente dal gioco.

> Stato: **Milestone 1** completata: import video, libreria, gestione diritti, job queue, dashboard.
> Clip detection (M2), editing/sottotitoli/render (M3), approvazione/export (M4) sono in roadmap.

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

## Configurazione

Tutto in `.env` (vedi `.env.example`), variabili con prefisso `CLIPNOVA_`.
Il server rifiuta di mettersi in ascolto su indirizzi diversi da localhost a meno di
`CLIPNOVA_ALLOW_PUBLIC_BIND=true`.

## Test

```bash
./install.sh --dev
.venv/bin/pytest                  # backend: API, job queue, ffmpeg, policy diritti
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
  clip_detection/ transcription/ editing/ subtitles/ publishing/   (milestone successive)
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
