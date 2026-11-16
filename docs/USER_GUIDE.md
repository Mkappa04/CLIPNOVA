# CLIPNOVA — guida d'uso

## Avvio quotidiano

```bash
cd /home/flavio/projects/clipnova
./start.sh            # poi apri http://localhost:8000 nel browser di Windows
./stop.sh             # quando hai finito
scripts/doctor.sh     # se qualcosa non va
```

Facoltativo: `scripts/install-service.sh` avvia CLIPNOVA automaticamente con WSL (servizio systemd utente).

## Il flusso di lavoro

1. **Importa**
   - *Auto Import*: aggiungi la cartella di OBS/ShadowPlay (anche `C:\...`). Ogni nuova registrazione viene
     importata quando OBS ha finito di scriverla, analizzata, e le migliori clip vengono montate da sole.
   - *Video Library → Importa*: upload o percorso locale (consigliato per file grandi: niente copia).
   - Imposta sempre i **diritti** (proprietario, licenza, autorizzazione): senza, l'export resta bloccato.
2. **Clip Detection**: *Analizza video* → timeline dell'interesse, clip con categoria, score e motivazione.
   Puoi cambiare i pesi e ricalcolare all'istante, correggere i tempi, aggiungere clip a mano.
3. **Clip Editor**: scegli il **preset** (Gaming Dynamic, Sports Highlights, Podcast Clean), guarda il **piano
   dell'AI Editing Planner** (dove zooma, quali parole evidenzia, dove mette un suono, dove *non* fa nulla e perché;
   *Genera con AI locale* per farlo ragionare con Ollama), poi regola quello che vuoi: layout, webcam, inquadratura
   (segue l'azione o lo speaker), sottotitoli (Dynamic/Clean Captions), effetti sonori, logo, audio, intro/outro.
   *Anteprima* = video completo in bozza da guardare subito; *Render* = qualità finale; *Rigenera* su ogni render.
   Il logo si carica una volta sola in **Brand Kit**.
4. **Subtitle Editor**: correggi il testo dei sottotitoli; poi rifai il render.
5. **Approval Center**: guarda il video finale, genera/modifica titolo, caption e hashtag, **Approva**.
6. **Export**: scegli piattaforme e uso (commerciale o no) → pacchetto con video, testi, sottotitoli e checklist.
   Carica tu il video seguendo `CHECKLIST.txt`.
7. **Published Content**: storico degli export; la pubblicazione via API è disabilitata di default.

Nulla viene approvato, esportato o pubblicato senza una tua azione esplicita.

## Contenuti di altri creator

- **Discovery** trova cosa funziona su GTA 6 (YouTube, Twitch) ma **non scarica mai** video di terzi.
- **Creators**: aggiungi il creator, genera il messaggio di richiesta permesso e invialo tu; quando risponde,
  registra il consenso (testo/screenshot, scadenza, uso commerciale) e crea la sua **cartella dedicata**:
  i file che ti manda, messi lì, entrano con i diritti già compilati.
- Il solo credito non è un permesso. Alla scadenza o revoca del consenso l'export si blocca da solo.

## Prestazioni tipiche (i5-11400H, RTX 3060 Laptop 6 GB)

| Operazione | Tempo |
|---|---|
| Analisi di 10 min di gameplay (con trascrizione GPU) | ~45 s – 3,5 min (dipende da quanto parlato c'è) |
| Trascrizione solo su CPU | ~1,5 min per minuto di audio |
| Render di una clip da 60 s (30 fps) | ~25 s |

## Risoluzione problemi

| Problema | Cosa fare |
|---|---|
| La dashboard non si apre | `./start.sh`; se la porta 8000 è occupata, cambia `CLIPNOVA_PORT` in `.env` |
| "GPU non disponibile" in Settings | Aggiorna il **driver NVIDIA di Windows** (non installare driver NVIDIA dentro WSL); poi `wsl --shutdown` da PowerShell e riapri Ubuntu |
| Trascrizione lenta / "Errore GPU sul blocco N" | Su questo PC CTranslate2 ha crash CUDA intermittenti su audio lunghi: CLIPNOVA riprende dal blocco e continua. Se succede spesso: aggiorna il driver NVIDIA di Windows e chiudi i giochi durante l'analisi (o usa *Auto Import → solo a PC inattivo*). In `.env` puoi forzare un modello più piccolo: `CLIPNOVA_WHISPER_MODEL=small` |
| Poca RAM (WSL vede ~7,6 GB) | In `%UserProfile%\.wslconfig` su Windows: `[wsl2]` `memory=12GB` (se il PC ne ha di più), poi `wsl --shutdown` |
| Un file della cartella monitorata non viene importato | *Auto Import → File rilevati* mostra il motivo (in scrittura, remux OBS, duplicato…) |
| Export bloccato | L'Approval Center mostra perché: correggi i diritti nella scheda del video |
| Spazio su disco | *Settings → Manutenzione spazio* |
| Qualcosa si è rotto | `scripts/doctor.sh`, poi i log in `data/logs/` |

## Backup

```bash
scripts/backup.sh            # → backups/clipnova-backup-<data>.tar.gz
```
Contiene database, chiave di cifratura delle credenziali, `.env`, prove dei consensi. **Non** contiene i video.
Ripristino: `./stop.sh`, estrai l'archivio nella cartella del progetto, `./start.sh`.
