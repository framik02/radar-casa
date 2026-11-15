"""Criteri di ricerca e costanti del radar casa."""
from pathlib import Path

RADICE = Path(__file__).parent
DATI = RADICE / "dati"          # locale, fuori da git
DOCS = RADICE / "docs"          # pubblicato su GitHub Pages
LOG = RADICE / "logs"

# Sede Extrapola, Via Torconca 17/g, San Giovanni in Marignano (RN)
SEDE = {"nome": "Extrapola, Via Torconca 17/g", "lat": 43.96196, "lon": 12.73305}

PREZZO_MAX = 800
MQ_MIN = 50
LOCALI_AMMESSI = {2, 3}          # bilocale o trilocale
MINUTI_MAX = 60                  # in auto dalla sede
KM_LINEA_D_ARIA_MAX = 80         # scarto prima di chiedere il percorso
STAZIONE_COMODA_KM = 1.2         # a piedi in un quarto d'ora

# Province entro un'ora di auto. Gli slug sono quelli dei portali.
PROVINCE = [
    # (immobiliare/casa, subito regione, subito provincia)
    ("rimini-provincia", "emilia-romagna", "rimini"),
    ("pesaro-urbino-provincia", "marche", "pesaro-urbino"),
    ("forli-cesena-provincia", "emilia-romagna", "forli-cesena"),
    ("ravenna-provincia", "emilia-romagna", "ravenna"),
    ("ancona-provincia", "marche", "ancona"),
]

SUBITO_CATEGORIE = ["appartamenti", "ville-singole-e-a-schiera"]

PAUSA_PAGINE = (4.0, 8.0)        # secondi fra una pagina e l'altra
GIORNI_SPARITO = 3               # dopo quanti giorni fuori linea si toglie

UA_SEMPLICE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) "
               "Gecko/20100101 Firefox/135.0")
UA_SERVIZI = "radar-casa/1.0"    # Nominatim, OSRM, Overpass
