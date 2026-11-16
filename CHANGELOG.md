# Changelog

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
