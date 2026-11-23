"""Un giro del radar: raccoglie, filtra, cifra e pubblica.

    python run.py              giro completo con pubblicazione su GitHub
    python run.py --no-push    giro completo, niente git
    python run.py --solo-subito  prova veloce senza browser
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

import config
import cripta
import fonti
import fonti_protette
import geo
import regole
import statistiche
import telegram_bot

config.DATI.mkdir(exist_ok=True)
config.LOG.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)-6s %(message)s", datefmt="%H:%M:%S",
    handlers=([logging.StreamHandler(sys.stdout)] if sys.stdout else [])  # pythonw non ha console
    + [logging.FileHandler(config.LOG / f"{datetime.now():%Y-%m-%d}.log", encoding="utf-8")])
log = logging.getLogger("run")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=config.RADICE, capture_output=True, text=True)


def aspetta_rete(minuti: int = 15) -> bool:
    """Al risveglio dalla sospensione il Wi-Fi arriva dopo qualche minuto."""
    import socket
    import time
    for i in range(minuti * 2):
        try:
            socket.create_connection(("github.com", 443), timeout=5).close()
            return True
        except OSError:
            if i == 0:
                log.info("rete assente, aspetto fino a %d minuti", minuti)
            time.sleep(30)
    return False


BLOCCATI = []  # fonti abbandonate perché ferme: a fine giro si chiude il processo


def fonte_isolata(nome: str, fn, minuti: int = 30) -> tuple[list, dict]:
    """Ogni portale gira nel suo browser e in un thread a parte. Se Camoufox si
    pianta (succede dopo un timeout di pagina) il portale si abbandona e il giro
    continua con gli altri."""
    ris: dict = {}

    def lavoro():
        from camoufox.sync_api import Camoufox
        try:
            with Camoufox(headless=True, humanize=True, locale="it-IT", os="windows") as browser:
                ris["r"] = fn(browser.new_page())
        except Exception as ex:
            if "r" not in ris:
                log.exception(nome); ris["err"] = str(ex)

    t = threading.Thread(target=lavoro, daemon=True, name=nome)
    t.start()
    fine = time.monotonic() + minuti * 60
    while t.is_alive() and "r" not in ris and time.monotonic() < fine:
        t.join(5)
    if "r" in ris:
        if t.is_alive():  # dati presi, ma il browser non si chiude
            BLOCCATI.append(nome)
        a, e = ris["r"]
        return a, e | {"annunci": len(a)}
    if t.is_alive():
        log.error("%s fermo da oltre %d minuti, abbandonato", nome, minuti)
        BLOCCATI.append(nome)
        return [], {"bloccata": True, "errore": f"fermo da oltre {minuti} minuti"}
    return [], {"bloccata": True, "errore": ris.get("err", "?")}


def raccogli(solo_subito: bool) -> tuple[list[dict], dict]:
    grezzi, esiti = [], {}
    try:
        a, e = fonti.subito()
        grezzi += a; esiti["subito"] = e | {"annunci": len(a)}
    except Exception as ex:
        log.exception("subito"); esiti["subito"] = {"bloccata": True, "errore": str(ex)}
    if solo_subito:
        return grezzi, esiti
    for nome, fn in (("immobiliare", fonti.immobiliare), ("casa", fonti.casa),
                     ("idealista", fonti_protette.idealista), ("bakeca", fonti_protette.bakeca)):
        a, e = fonte_isolata(nome, fn)
        grezzi += a; esiti[nome] = e
    return grezzi, esiti


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--solo-subito", action="store_true")
    ap.add_argument("--senza-raccolta", action="store_true",
                    help="rielabora l'archivio dell'ultimo giro senza scaricare")
    args = ap.parse_args()
    adesso = datetime.now().replace(microsecond=0)
    ora = adesso.isoformat()
    pa = config.DATI / "archivio.json"
    if args.senza_raccolta:
        arch = json.loads(pa.read_text(encoding="utf-8"))
        ora = max(v["ultimo"] for v in arch.values())
        adesso = datetime.fromisoformat(ora)

    if not args.senza_raccolta and not aspetta_rete():
        log.error("niente rete dopo 15 minuti, giro annullato")
        return

    if not args.no_push:
        r = git("pull", "--rebase", "--autostash")
        if r.returncode:
            log.warning("git pull: %s", r.stderr.strip())

    if args.senza_raccolta:
        grezzi = []
        esiti = json.loads((config.DATI / "ultimo.json").read_text(encoding="utf-8"))["fonti"]
    else:
        grezzi, esiti = raccogli(args.solo_subito)
    log.info("raccolti %d annunci grezzi", len(grezzi))
    if not args.senza_raccolta and not grezzi:
        log.error("nessun annuncio da nessun portale, giro annullato senza pubblicare")
        return

    # archivio: quando l'abbiamo visto la prima e l'ultima volta
    archivio = json.loads(pa.read_text(encoding="utf-8")) if pa.exists() else {}
    for a in grezzi:
        v = archivio.get(a["id"])
        archivio[a["id"]] = {"primo": v["primo"] if v else ora, "ultimo": ora, "a": a}
    pa.write_text(json.dumps(archivio, ensure_ascii=False), encoding="utf-8")

    soglia = (adesso - timedelta(days=config.GIORNI_SPARITO)).isoformat()
    vivi = []
    for v in archivio.values():
        if v["ultimo"] < soglia:
            continue
        a = dict(v["a"])
        a["primo_visto"], a["ultimo_visto"] = v["primo"], v["ultimo"]
        a["online"] = v["ultimo"] == ora or esiti.get(a["fonte"], {}).get("bloccata", False)
        vivi.append(a)

    geo.geocodifica_comuni(vivi)
    # la via dal testo solo per chi ha gia' passato i filtri economici:
    # una richiesta a Nominatim al secondo, non va sprecata
    geo.indirizzi_dal_testo([a for a in vivi if (a["prezzo"] or 9999) <= config.PREZZO_MAX
                             and not (a["mq"] and a["mq"] < config.MQ_MIN)])
    geo.tempi_in_auto(vivi)
    try:
        staz = geo.stazioni()
    except Exception as e:
        log.warning("stazioni: %s", e); staz = []
    esclusi, tenuti = Counter(), []
    for a in vivi:
        regole.valuta_durata(a)
        geo.stazione_vicina(a, staz)
        motivo = regole.esclusione(a)
        if motivo:
            esclusi[motivo] += 1
        else:
            tenuti.append(a)
    # per le statistiche: quali annunci rispettano i criteri
    for a in vivi:
        if a["id"] in archivio:
            archivio[a["id"]]["utile"] = False
    for a in tenuti:
        archivio[a["id"]]["utile"] = True
    pa.write_text(json.dumps(archivio, ensure_ascii=False), encoding="utf-8")
    uniti = regole.unisci_doppioni(tenuti)
    # l'unione puo' aver dato a una scheda una posizione migliore: ricalcolo
    geo.tempi_in_auto(uniti)
    geo.via_vicina(uniti)
    for a in uniti:
        geo.stazione_vicina(a, staz)
    primo = {a["id"]: a["primo_visto"] for a in tenuti}
    for a in uniti:
        a["primo_visto"] = min(primo[i] for i in a["ids"])
        regole.punteggio(a)
    uniti.sort(key=lambda a: -a["punteggio"])

    sede_staz = None
    if staz:
        s = min(staz, key=lambda s: geo.km(config.SEDE["lat"], config.SEDE["lon"], s["lat"], s["lon"]))
        sede_staz = {"nome": s["nome"], "lat": s["lat"], "lon": s["lon"],
                     "km": round(geo.km(config.SEDE["lat"], config.SEDE["lon"], s["lat"], s["lon"]), 1)}

    out = {
        "aggiornato": ora, "sede": config.SEDE, "stazione_sede": sede_staz,
        "criteri": {"prezzo_max": config.PREZZO_MAX, "mq_min": config.MQ_MIN,
                    "locali": sorted(config.LOCALI_AMMESSI), "minuti_max": config.MINUTI_MAX},
        "fonti": esiti, "esclusi": dict(esclusi.most_common()),
        "doppioni_uniti": len(tenuti) - len(uniti), "annunci": uniti,
        "statistiche": statistiche.calcola(archivio, ora),
    }
    (config.DATI / "ultimo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    config.DOCS.mkdir(exist_ok=True)
    (config.DOCS / "dati.enc").write_text(cripta.cifra(out), encoding="utf-8")
    log.info("pubblicabili %d (doppioni uniti %d), esclusi %s", len(uniti),
             len(tenuti) - len(uniti), dict(esclusi))

    if not args.senza_raccolta:
        try:
            telegram_bot.invia_nuovi(uniti, ora)
        except Exception as ex:
            log.warning("telegram: %s", ex)

    if not args.no_push:
        git("add", "docs/dati.enc")
        r = git("commit", "-m", f"Radar {adesso:%Y-%m-%d %H:%M}: {len(uniti)} annunci")
        if r.returncode == 0:
            r = git("push")
            log.info("push: %s", "ok" if r.returncode == 0 else r.stderr.strip())


if __name__ == "__main__":
    main()
    if BLOCCATI:  # i browser piantati tengono vivo il processo: si chiude tutto l'albero
        logging.shutdown()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(os.getpid())], capture_output=True)
