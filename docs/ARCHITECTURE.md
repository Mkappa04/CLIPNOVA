# CLIPNOVA: architettura

## Panoramica

```
Browser (Windows) ──HTTP localhost──▶ FastAPI (uvicorn, 127.0.0.1:8000)
                                         │  ├─ /api/*        REST
                                         │  └─ /*            dashboard React buildata (SPA)
                                         ├─ SQLite (WAL)  data/clipnova.db
                                         ├─ JobManager ── ThreadPool (N=1) ──▶ ffmpeg/ffprobe (subprocess)
                                         │      └─ video.analyze ─▶ ffmpeg proxy+wav ─▶ NumPy / PySceneDetect / OpenCV
                                         │                          └▶ processo figlio (spawn): faster-whisper CUDA/CPU
                                         └─ data/ videos · thumbnails · cache · renders · logs
```

Un solo processo, nessun broker esterno (Redis/Celery): su un portatile con 8 GB di RAM e 6 GB di VRAM
il collo di bottiglia è la GPU, non la coda. I job sono persistiti in SQLite, quindi sono visibili nella
UI, sopravvivono ai riavvii (i `queued` ripartono, i `running` interrotti vengono marcati `failed`)
e sono annullabili.

## Pipeline

`IMPORT → ANALYSIS → CLIP DETECTION → EDITING → RENDERING → REVIEW → APPROVED → EXPORT/PUBLISH`

| Fase | Milestone | Modulo |
|---|---|---|
| Import, metadati, thumbnail | 1 ✅ | `services/video_service.py`, `workers/handlers.py` |
| Diritti e policy di export | 1 ✅ (policy) / 4 (enforcement export) | `rights_management/policy.py` |
| Scene/audio/trascrizione, scoring | 2 ✅ | `clip_detection/`, `transcription/` |
| Editing 9:16, layout, sottotitoli, render | 3 | `editing/`, `subtitles/` |
| Revisione, approvazione, export, publishing | 4 | `publishing/` |

## Job queue (`backend/workers/queue.py`)

- `job_manager.register("tipo")` registra un handler `fn(ctx) -> dict | None`.
- `ctx.progress(0..1, msg)` aggiorna il DB (throttling 0,5 s); `ctx.check_cancelled()` solleva `JobCancelled`.
- `services/ffmpeg.run_ffmpeg()` legge `-progress pipe:1` per il progresso e termina il processo se il job viene annullato.
- `CLIPNOVA_WORKER_CONCURRENCY=1` di default: i job pesanti (Whisper, render) non devono competere per la VRAM.

## Diritti (`backend/rights_management/policy.py`)

`evaluate(rights, purpose)` restituisce `allowed`, `blockers`, `warnings`.

- `internal`: sempre consentito (l'elaborazione locale non distribuisce nulla).
- Export (`non_commercial` / `commercial`) bloccato se: record mancante, licenza `unknown` o `credit_only`,
  stato ≠ `authorized`, autorizzazione scaduta, attribuzione richiesta senza testo,
  (commerciale) licenza NC o uso commerciale non consentito.
- Avvisi: scadenza entro 7 giorni, restrizioni presenti, permesso senza prova, policy dell'editore per gameplay proprio.

## Sicurezza

- Bind solo su loopback (rifiuto esplicito altrimenti).
- Nessun segreto nel codice; `.env` è in `.gitignore`. I token social (M4) saranno cifrati a riposo.
- Delete: richiede `confirm=true`; i file "referenced" non vengono mai cancellati; i file gestiti
  solo se dentro `data/videos` (controllo sul path risolto).
- Nessuna richiesta di rete esterna: la dashboard usa font di sistema, niente CDN.

## Hardware target e scelte

- RTX 3060 Laptop 6 GB: NVENC per anteprime e rendering; Whisper `large-v3-turbo` int8_float16 ~1,2 GB di VRAM.
- RAM visibile a WSL ~7,6 GB (limite di default di WSL). Si può alzare in `%UserProfile%\.wslconfig`
  (`[wsl2] memory=12GB`) se il PC ha più RAM fisica: è un'impostazione di sistema, da fare manualmente.
- Fallback CPU: libx264 per l'encoding, Whisper `small` su CPU int8.
- PyTorch non è installato: faster-whisper usa CTranslate2, che non lo richiede (−2,5 GB).

## Analisi e clip detection (Milestone 2)

`clip_detection/pipeline.py` orchestra il job `video.analyze` (pesi di progresso: preparazione 0-25%,
audio 25-30%, scene 30-42%, movimento 42-50%, trascrizione 50-95%, scoring 95-100%).
Artefatti in `data/cache/<video_id>/`: `proxy.mp4`, `audio.wav`, `signals.npz` (segnali grezzi a finestre di 0,5 s),
`transcript.json`. Il ricalcolo (`POST /api/videos/{id}/detect`) riusa questi file: ~60 ms.

**Scoring** (`clip_detection/scoring.py`): 7 segnali normalizzati 0-1 per finestra; l'interesse è la media pesata
delle **3 evidenze più forti** (un'esplosione senza parlato non viene diluita dai canali silenziosi), smussata.
Selezione greedy dei picchi → finestra con contesto prima/dopo, aggancio a inizio/fine frase e ai cambi scena,
vincoli min/max, nessuna sovrapposizione. Score = 100·(1−e^(−2,2·(0,65·picco+0,35·media))).
Le categorie "semantiche" (rage, fail, clutch, funny) richiedono evidenza verbale (keyword/risate);
le altre (epic, reaction, unexpected, highlight) derivano dai segnali. La confidenza dipende dal margine tra
prima e seconda categoria e viene ridotta senza trascrizione.

**Whisper** (`transcription/whisper_engine.py`): processo figlio `spawn` per job → RAM/VRAM liberate
all'uscita (in-process restavano ~1,9 GB), crash CUDA isolati, annullamento immediato. Scelta del device:
CUDA se presente, librerie cuBLAS/cuDNN caricate (wheel pip, preload `ctypes`) e VRAM libera ≥
`WHISPER_MIN_FREE_VRAM_MB`; altrimenti CPU. Errore GPU → retry automatico su CPU.
Filtro allucinazioni: frasi tipiche ("Sottotitoli a cura di QTSS", "thanks for watching"…) e segmenti con
`no_speech_prob > 0,6` e `avg_logprob < −1`.

## Migrazioni

Alembic (`backend/database/migrations`). All'avvio `init_db()` applica `upgrade head`; un DB creato dalla
Milestone 1 (senza `alembic_version`) viene prima marcato alla baseline `0001`. Nuova migrazione:
`.venv/bin/alembic revision --autogenerate -m "..."`.

## Schema DB

`videos` 1─1 `rights_records`, `videos` 1─1 `analyses`, `videos` 1─N `clips`, `jobs` (N─1 opzionale su `videos`).
