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
3. **Clip Editor**
   - **Preset**: scegline uno tra Gaming Dynamic, Gaming Cinematic, Sports Highlights, Podcast Clean e
     Storytelling.
   - **Piano AI**: il regista spiega cosa ha capito (stile, energia, se la clip si capisce da sola, tipo di ogni
     momento) e cosa farà: zoom, slow motion o speed ramp, transizioni, titoli e scritte, suoni, musica, look. Per
     ogni intervento c'è il motivo; togli la spunta per escluderlo. *Rigenera con AI locale* lo fa ragionare con
     Ollama, guardando anche i fotogrammi.
   - **Audio**: musica scelta dal regista oppure solo l'audio originale, con mood, traccia, volume e quanto
     abbassarla sotto il parlato.
   - **Altre regolazioni**: layout, webcam, inquadratura, sottotitoli (font, colori, animazione), logo, watermark,
     intro e outro.
   - **Render**: *Anteprima* produce il video completo in bozza; *Render* la qualità finale.
   - Il logo e il watermark testuale si impostano una volta in **Brand Kit**. Le musiche e gli effetti sonori tuoi,
     sempre con licenza, si importano in **Libreria audio**.
4. **Subtitle Editor**: correggi il testo dei sottotitoli; poi rifai il render.
5. **Approval Center**: guarda il video finale; *Genera* (circa 1 minuto): l'AI guarda la clip e propone 3 titoli,
   caption per Instagram e TikTok, titolo e descrizione YouTube e hashtag per ogni piattaforma. Apri "Cosa ha capito
   l'AI" per controllare l'interpretazione; modifica, copia o rigenera solo titoli, caption o hashtag; **Approva**.
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
