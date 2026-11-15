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
import sys
from collections import Counter
from datetime import datetime, timedelta

import config
import cripta
import fonti
import geo
import regole

config.DATI.mkdir(exist_ok=True)
config.LOG.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)-6s %(message)s", datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(config.LOG / f"{datetime.now():%Y-%m-%d}.log", encoding="utf-8")])
log = logging.getLogger("run")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=config.RADICE, capture_output=True, text=True)


def raccogli(solo_subito: bool) -> tuple[list[dict], dict]:
    grezzi, esiti = [], {}
    try:
        a, e = fonti.subito()
        grezzi += a; esiti["subito"] = e | {"annunci": len(a)}
    except Exception as ex:
        log.exception("subito"); esiti["subito"] = {"bloccata": True, "errore": str(ex)}
    if solo_subito:
        return grezzi, esiti
    from camoufox.sync_api import Camoufox
    with Camoufox(headless=True, humanize=True, locale="it-IT", os="windows") as browser:
        for nome, fn in (("immobiliare", fonti.immobiliare), ("casa", fonti.casa)):
            pagina = browser.new_page()
            try:
                a, e = fn(pagina)
                grezzi += a; esiti[nome] = e | {"annunci": len(a)}
            except Exception as ex:
                log.exception(nome); esiti[nome] = {"bloccata": True, "errore": str(ex)}
            finally:
                pagina.close()
    return grezzi, esiti


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--solo-subito", action="store_true")
    args = ap.parse_args()
    adesso = datetime.now().replace(microsecond=0)
    ora = adesso.isoformat()

    if not args.no_push:
        r = git("pull", "--rebase", "--autostash")
        if r.returncode:
            log.warning("git pull: %s", r.stderr.strip())

    grezzi, esiti = raccogli(args.solo_subito)
    log.info("raccolti %d annunci grezzi", len(grezzi))

    # archivio: quando l'abbiamo visto la prima e l'ultima volta
    pa = config.DATI / "archivio.json"
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
    uniti = regole.unisci_doppioni(tenuti)
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
    }
    (config.DATI / "ultimo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    config.DOCS.mkdir(exist_ok=True)
    (config.DOCS / "dati.enc").write_text(cripta.cifra(out), encoding="utf-8")
    log.info("pubblicabili %d (doppioni uniti %d), esclusi %s", len(uniti),
             len(tenuti) - len(uniti), dict(esclusi))

    if not args.no_push:
        git("add", "docs/dati.enc")
        r = git("commit", "-m", f"Radar {adesso:%Y-%m-%d %H:%M}: {len(uniti)} annunci")
        if r.returncode == 0:
            r = git("push")
            log.info("push: %s", "ok" if r.returncode == 0 else r.stderr.strip())


if __name__ == "__main__":
    main()
