# CLIPNOVA: architettura

## Panoramica

```
Browser (Windows) ──HTTP localhost──▶ FastAPI (uvicorn, 127.0.0.1:8000)
                                         │  ├─ /api/*        REST
                                         │  └─ /*            dashboard React buildata (SPA)
                                         ├─ SQLite (WAL)  data/clipnova.db
                                         ├─ JobManager ── ThreadPool (N=1) ──▶ ffmpeg/ffprobe (subprocess)
                                         │                                  └▶ (M2) faster-whisper / OpenCV / PySceneDetect
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
| Scene/audio/trascrizione, scoring | 2 | `clip_detection/`, `transcription/` |
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

- RTX 3060 Laptop 6 GB: NVENC verificato per il rendering (M3). Per Whisper (M2) i modelli
  `small`/`medium` con `int8_float16` restano sotto ~3 GB di VRAM; il budget è `CLIPNOVA_MAX_VRAM_MB`.
- RAM visibile a WSL ~7,6 GB (limite di default di WSL). Si può alzare in `%UserProfile%\.wslconfig`
  (`[wsl2] memory=12GB`) se il PC ha più RAM fisica: è un'impostazione di sistema, da fare manualmente.
- Fallback CPU: libx264 per l'encoding, Whisper su CPU int8.

## Schema DB

`videos` 1─1 `rights_records`, `videos` 1─N `clips`, `jobs` (N─1 opzionale su `videos`).
Le tabelle vengono create all'avvio (`create_all`). Dalla Milestone 2, con le prime modifiche di
schema, verranno introdotte le migrazioni Alembic.
