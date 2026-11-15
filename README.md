# CLIPNOVA

Piattaforma **locale** per trasformare registrazioni gaming autorizzate in contenuti verticali
(TikTok, Instagram Reels, YouTube Shorts). Gira interamente dentro **Ubuntu su WSL 2**, budget 0 €,
nessun servizio cloud obbligatorio. Primo gioco supportato: **GTA 6**, ma è indipendente dal gioco.

> **Versione 1.0.0 — release locale** (Milestone 5). Guida d'uso: [docs/USER_GUIDE.md](docs/USER_GUIDE.md) ·
> novità: [CHANGELOG.md](CHANGELOG.md).
>
> Milestone completate: M1: import, libreria, diritti, job queue, dashboard.
> M2: analisi, trascrizione faster-whisper (GPU), clip detection con scoring configurabile.
> M3: editor automatico 9:16, layout gameplay/webcam, smart crop, zoom, sottotitoli ASS animati, rendering NVENC.
> M4: approvazione, gestione diritti nell'export, export manuale assistito, architettura di pubblicazione (API ufficiali).
> M4B: import automatico da cartelle monitorate, scoperta contenuti via API ufficiali, CRM permessi dei creator.
> M5: Analytics, trascrizione a blocchi ripristinabile, manutenzione spazio, backup, diagnostica, release.

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

## Funzionalità (Milestone 3): editing e rendering

**Clip Editor** (`/editor`) → scegli una clip → configura → *Render*. Output: **MP4 1080×1920, H.264 (NVENC, fallback
libx264), AAC 48 kHz**, 30 o 60 fps, più sottotitoli `.srt` e `.ass` e una thumbnail.

| Funzione | Dettagli |
|---|---|
| Layout | **A** Full · **B** Stack (gameplay sopra, webcam sotto) · **C** PiP (angoli arrotondati, 4 posizioni) · **D** Split dinamico (il gameplay si allarga sui picchi d'azione) |
| Webcam | rilevamento automatico (volto stabile con YuNet + bordi statici dell'overlay) o **selezione manuale** trascinando sul fotogramma; una scelta manuale non viene mai sovrascritta |
| Inquadratura | **smart crop** (camera virtuale che segue il movimento, con zona morta e velocità limitata), centrale, o *fit* (frame intero su sfondo sfocato). Mai deformazioni |
| Zoom | punch-in morbido sul picco della clip e sui forti picchi audio (max 3) |
| Transizioni | fade in/out, crossfade sui jump cut, intro/outro con titolo su sfondo sfocato |
| Audio | taglio silenzi (pause silenziose o ogni pausa nel parlato), high-pass, denoise opzionale, compressore, **loudnorm a due passaggi a −14 LUFS** |
| Sottotitoli | da timestamp per parola, evidenziazione della parola attiva, safe area social, preset **Clean** (Lato), **Gaming** (Anton, pop), **Viral** (Luckiest Guy, bounce); posizione auto (sulla giunzione gameplay/webcam) |
| Anteprima | fotogramma 9:16 composto lato server con le impostazioni correnti (anche non salvate) |

**Subtitle Editor** (`/subtitles`): modifica testo/tempi riga per riga; se il numero di parole non cambia i tempi per
parola restano quelli di Whisper, altrimenti vengono ridistribuiti. Export SRT/ASS. Dopo il render la clip passa in
**review** (workflow `… → RENDERING → REVIEW`). Le emoji vengono rimosse dal testo bruciato (i font non le hanno).

Font inclusi in `assets/fonts` (Anton: SIL OFL; Luckiest Guy: Apache 2.0); modello volti in `assets/models`
(YuNet, MIT). Licenze accanto ai file.

## Funzionalità (Milestone 4): approvazione, export, pubblicazione

Workflow: `IMPORT → ANALYSIS → CLIP DETECTION → EDITING → RENDERING → REVIEW → APPROVED → EXPORT / PUBLISH`

**Approval Center** (`/approval`): per ogni clip renderizzata vedi il video 9:16, la verifica dei diritti
(commerciale / non commerciale) e i testi. Azioni: **Approva** (solo da *review* e con un render completato),
Rifiuta (con nota), Archivia, Riapri, Rigenera (nuovo render), link a editor e sottotitoli.
Se modifichi i testi o rifai il render di una clip approvata, **l'approvazione viene revocata** e la clip torna in
revisione: si approva sempre esattamente ciò che verrà pubblicato.

**Testi social** (titolo, hook, caption, descrizione, hashtag, CTA; italiano/inglese):
- *modalità senza LLM* (default): template che citano solo frasi realmente pronunciate nella clip; hashtag dal
  gioco, dalla categoria e solo dalle keyword di gioco (mai le parolacce usate come indizi di "rage");
- *LLM locale opzionale* (`CLIPNOVA_LLM_PROVIDER=ollama`, default `qwen3.5:4b`): riscrive solo i testi brevi; la
  descrizione resta fattuale; ogni campo con >20% di parole non presenti nella clip viene **scartato** e segnalato;
  i nomi propri nuovi vengono evidenziati. Il modello viene scaricato dalla VRAM subito dopo (keep_alive 0).

**Diritti → export**: l'export è bloccato (HTTP 403 con le motivazioni) se la licenza è sconosciuta o
*solo credito*, l'autorizzazione non è "autorizzato" o è scaduta, manca il testo di attribuzione richiesto, o per
uso commerciale con licenza NC / uso commerciale non consentito. L'attribuzione viene aggiunta automaticamente ai testi.

**Export manuale assistito**: `data/exports/<id>/` con MP4, `tiktok.txt` / `instagram.txt` / `youtube.txt`
(entro i limiti di ogni piattaforma, #Shorts per YouTube), `subtitles.srt`, `thumbnail.jpg`, `CHECKLIST.txt`
(passi di caricamento + diritti e restrizioni), `metadata.json`, `package.zip`. Opzionale: copia automatica in
una cartella Windows (`CLIPNOVA_EXPORT_COPY_DIR=/mnt/c/Users/<tu>/Videos/CLIPNOVA`).

**Pubblicazione (disabilitata per default)** — pagina *Published Content*:
- solo **API ufficiali**: YouTube Data API v3 (upload resumable), TikTok Content Posting API (Direct Post),
  Instagram Graph API (Reels; richiede un URL pubblico del video che CLIPNOVA non espone → usa l'export manuale);
- account con credenziali **cifrate** (Fernet, chiave in `data/secret.key` 0600 o `CLIPNOVA_SECRET_KEY`), mai
  restituite in chiaro dall'API;
- pubblicazione solo con `CLIPNOVA_PUBLISHING_ENABLED=true` **e** clip approvata **e** conferma esplicita;
  diritti ricontrollati al momento dell'invio (un'autorizzazione scaduta blocca la pubblicazione);
- scheduling, retry con backoff esponenziale (2, 4, 8 min) per errori temporanei, log per ogni tentativo;
- le app non verificate dalle piattaforme possono pubblicare solo in privato (TikTok SELF_ONLY, YouTube private).
- **Testato contro API simulate** (sequenza di chiamate, errori, retry); non contro le piattaforme reali, che
  richiedono le tue credenziali sviluppatore.

## Funzionalità (Milestone 4B): import automatico, scoperta, permessi

### Auto Import (`/auto-import`)
Aggiungi le cartelle dove OBS / NVIDIA ShadowPlay salvano le registrazioni (anche percorsi Windows: `C:\...`
diventa `/mnt/c/...`). Per ogni cartella: gioco, creator, profilo diritti, riferimento/copia, estensioni,
sottocartelle e la **pipeline automatica**:

`import → metadati → analisi + trascrizione → clip detection → rilevamento webcam → render delle migliori N clip → Approval Center`

Mai approvazione o pubblicazione automatica.
- **Polling** (inotify non vede le scritture di Windows su `/mnt/c`), ogni 15 s.
- Un file viene importato solo quando **dimensione e data non cambiano per 10 s** e il contenitore è finalizzato
  (un MP4 in registrazione non ha ancora l'atomo `moov` → ffprobe fallisce → si aspetta).
- File temporanei/parziali ignorati (`.part`, `.tmp`, `~$…`, nascosti).
- **Remux di OBS**: se compare `X.mp4` accanto a `X.mkv` si importa solo l'mp4; un `.mkv` da solo aspetta 60 s
  in più per un eventuale remux; un mp4 remuxato da un mkv già importato viene scartato.
- **Deduplicazione** con firma rapida (dimensione + 3 blocchi da 1 MB): lo stesso video non entra mai due volte.
- **Risorse**: tutta la pipeline di un file è un unico job, quindi un solo lavoro pesante alla volta (Whisper, NVENC,
  Ollama non si sovrappongono). Pausa/ripresa globale, **fascia oraria**, **solo a PC inattivo** (stimato da carico
  CPU e uso GPU: se stai giocando la GPU è occupata e la pipeline aspetta). Dopo un riavvio i lavori interrotti
  ripartono da soli.
- **Notifiche** nella barra laterale quando nuove clip sono pronte da revisionare.

Misurato su una cartella Windows reale: file scritto in 24 s → importato appena stabile → clip in revisione
**63 s dopo l'inizio della scrittura** (video di 60 s).

### Discovery (`/discovery`): solo ricerca, nessun download
- **YouTube Data API v3**: video/Shorts per parole chiave, lingua, periodo; classifica per popolarità, crescita
  (visualizzazioni/ora) ed engagement con il motivo del punteggio; filtro e badge **CC BY** con l'attribuzione da usare.
  Contatore della quota giornaliera (10.000 unità, una ricerca ≈ 101, reset a mezzanotte ora del Pacifico) e cache
  locale (6 h).
- **Twitch Helix**: clip e VOD più visti del gioco per periodo e lingua.
- Classifica dei creator che producono contenuti adatti, con aggiunta al CRM.
- **CLIPNOVA non scarica mai video di terzi**, nemmeno CC BY: i termini di YouTube e Twitch non lo consentono con
  strumenti non ufficiali. Il file va ottenuto in modo legittimo (es. dal creator).

**Chiavi gratuite** (Settings → Scoperta contenuti, salvate cifrate; senza chiavi la funzione è solo disattivata):
- YouTube: [Google Cloud Console](https://console.cloud.google.com/) → nuovo progetto → *API e servizi* → abilita
  **YouTube Data API v3** → *Credenziali* → *Crea credenziali* → **Chiave API** (consigliato: limitala a quell'API).
- Twitch: [dev.twitch.tv/console](https://dev.twitch.tv/console) → *Register Your Application* (categoria *Application
  Integration*, OAuth Redirect `http://localhost`) → **Client ID** e *New Secret* → **Client Secret**.

### Creators (`/creators`): permessi dei creator
- Stati: da contattare → contattato → in attesa → autorizzato / rifiutato / scaduto, con storico e note.
- **Messaggio di richiesta permesso** (it/en; template, LLM locale opzionale con verifica che non aggiunga link,
  numeri o promesse): cosa, come, uso commerciale sì/no, attribuzione, revocabilità. **L'invio resta manuale**.
- **Prova del consenso**: testo e/o file (screenshot, PDF, email), data, ambito, scadenza, uso commerciale, restrizioni.
- **Cartella dedicata** al creator autorizzato: ogni file depositato lì viene importato con i **diritti già compilati**
  dal consenso ed entra nella pipeline automatica.
- **Scadenze**: notifica 7 giorni prima; alla scadenza il creator passa a "scaduto", i diritti dei suoi video tornano
  "in attesa" e l'export si blocca. La revoca ha lo stesso effetto.

### Prestazioni misurate (i5-11400H, RTX 3060 Laptop 6 GB, WSL 2)

| Video | Tempo analisi | Note |
|---|---|---|
| 60 s, 720p | ~10 s | |
| 10 min, 1080p60 | **45 s** | preparazione 33 s, scene 5 s, trascrizione 7 s |
| Primo avvio | +~90 s | download unico di `large-v3-turbo` (1,6 GB) |

| Render (clip 60 s, sorgente 1080p60, stack + sottotitoli + intro/outro) | Tempo |
|---|---|
| 30 fps, qualità standard | **24 s** (2,6× tempo reale) |
| 60 fps | 45 s (1,4×) |

Server durante il render: ~330 MB di RAM. Anteprima fotogramma: < 1 s.

- VRAM: picco ~1,2 GB durante la trascrizione (limite 6 GB); torna al livello base a fine job
- RAM: Whisper gira in un **processo separato** per ogni job → il server resta ~250 MB
- Decodifica: su questa CPU FFmpeg decodifica 1080p60 più velocemente di NVDEC (30 s vs 51 s per 10 min),
  quindi il default è `CLIPNOVA_ANALYSIS_DECODER=cpu` con NVDEC come fallback

## Configurazione

Tutto in `.env` (vedi `.env.example`), variabili con prefisso `CLIPNOVA_`.
Il server rifiuta di mettersi in ascolto su indirizzi diversi da localhost a meno di
`CLIPNOVA_ALLOW_PUBLIC_BIND=true`.

## Funzionalità (Milestone 5): release locale

- **Analytics** (`/analytics`): produzione giornaliera, workflow, categorie, distribuzione degli score, prestazioni,
  import automatico, spazio su disco.
- **Trascrizione GPU robusta**: blocchi da ~45 s tagliati nei silenzi; un crash CUDA fa ripartire il worker GPU dal
  blocco fallito (vedi *Note tecniche*). Il server non viene mai abbattuto da un crash del modello.
- **Manutenzione spazio** in Settings, **backup** (`scripts/backup.sh`), **diagnostica** (`scripts/doctor.sh`),
  servizio systemd opzionale (`scripts/install-service.sh`).

### Note tecniche: crash CUDA della trascrizione
Su questo PC (RTX 3060 Laptop, driver Windows 610.74, WSL 2) CTranslate2 va in errore CUDA
(`cudaErrorIllegalAddress` / `IllegalInstruction`) dopo decine di secondi di inferenza continua su audio reale,
in modo casuale, con qualunque modello e precisione (anche CTranslate2 4.6). FFmpeg/NVENC e i campioni brevi non ne
risentono. La trascrizione a blocchi rende il problema innocuo (10 min di audio in 202 s con 5 crash). Probabili
cause da verificare: driver NVIDIA di Windows o librerie CUDA 12.9 / cuDNN 9.28 installate via pip.

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
  editing/          config, timeline (tagli silenzi), webcam, reframe (smart crop), compositor, renderer
  subtitles/        cue da parole, preset, writer ASS/SRT
  content_generation/  testi social: template + LLM locale opzionale con guardrail
  publishing/       export manuale, provider (YouTube/TikTok/Instagram), cifratura token, scheduler
  services/approval.py  workflow di revisione e approvazione
  automation/       watcher a polling, pipeline automatica, gating risorse, CRM creator, notifiche
  discovery/        YouTube Data API v3 e Twitch Helix (solo ricerca), quota, cache, ranking
assets/             font e modello YuNet (con licenze)
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
