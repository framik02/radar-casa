# Radar casa

Cerca due volte al giorno gli affitti entro un'ora di auto da Extrapola
(Via Torconca 17/g, San Giovanni in Marignano) e li pubblica in una pagina
con mappa e lista, apribile anche dal telefono.

Pagina: https://framik02.github.io/radar-casa/

## Criteri

Fino a 800 € al mese, almeno 50 m², bilocale o trilocale, entro 60 minuti di
auto, durata di almeno 12 mesi. I valori stanno in `config.py`.

La durata si legge dal testo dell'annuncio (`regole.py`). Si scartano
transitori brevi, "settembre-maggio", "fino a giugno", stagionali, settimane e
uso turistico. Se l'annuncio non dice niente l'annuncio resta, marcato "da
chiedere".

Il punteggio parte dai minuti in auto e aggiunge punti per giardino, stazione
vicina, durata chiara, posto auto e prezzo basso. Toglie punti agli uffici che
vendono liste di case a pagamento.

## Fonti

| Fonte | Come | Cosa manca |
|---|---|---|
| Immobiliare.it | Camoufox, pagine di ricerca | descrizione completa, le schede sono protette |
| Casa.it | Camoufox, pagine di ricerca | niente di rilevante |
| Subito.it | curl | coordinate (solo il comune), telefono quasi sempre nascosto |

Idealista, Wikicasa e Bakeca bloccano la lettura automatica e non sono incluse.

Lo stesso appartamento pubblicato su più portali viene unito in una scheda sola
con tutti i link.

## Dati e riservatezza

Il repository è pubblico perché GitHub Pages gratuito lo richiede. Gli annunci
con telefoni e nomi stanno in `docs/dati.enc`, cifrati con AES-GCM. La frase
segreta è in `.env`, fuori da git, e la pagina la chiede la prima volta.
L'archivio in chiaro resta in `dati/` sul PC.

Tieni, scarta e note si salvano nel browser. Per averli uguali fra PC e
telefono si incolla nella pagina (pulsante Sincronizza) un token GitHub a grana
fine con permesso Contents in scrittura sul solo repository `radar-casa`. Le
scelte finiscono in `docs/decisioni.json`, che contiene solo identificativi.

## Uso

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py            # giro completo e push
.venv\Scripts\python run.py --no-push  # prova senza pubblicare
powershell -File install_task.ps1      # giri alle 8:00 e alle 19:00
```

Il PC deve essere acceso. Se all'ora del giro è spento, parte alla riaccensione.
Il log di ogni giorno è in `logs/`.
