"""Idealista e Bakeca, che stanno dietro DataDome.

L'utente ha autorizzato la lettura il 15/11/2026. Si passa dalla home, si va
piano, e al primo blocco che non si sblocca la fonte si ferma per quel giro.
"""
from __future__ import annotations

import html as html_mod
import json
import logging
import re
import time

import config
from fonti import _intero, _pausa, vuoto

log = logging.getLogger("fonti")


def _apri(pagina, url: str, referer: str | None = None, giri: int = 8) -> str | None:
    pagina.goto(url, timeout=60000, wait_until="domcontentloaded", referer=referer)
    for _ in range(giri):
        time.sleep(4)
        if "Ci siamo quasi" not in pagina.title() and len(pagina.content()) > 60000:
            return pagina.content()
    return None


def _riscalda(pagina, home: str) -> None:
    _apri(pagina, home, giri=5)
    pagina.mouse.move(400, 300)
    pagina.mouse.wheel(0, 500)
    time.sleep(3)


def _testo(s: str | None) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# ---------------------------------------------------------------- Idealista

VIA_INIZIO = re.compile(r"(?i)(via|viale|piazza|piazzale|corso|largo|vicolo|strada|lungomare)\b")


def _idealista_annuncio(art: str, id_: str) -> dict:
    a = vuoto("idealista", id_)
    a["url"] = f"https://www.idealista.it/immobile/{id_}/"
    m = re.search(r'class="item-link[^"]*"[^>]*title="([^"]+)"', art)
    a["titolo"] = _testo(m.group(1)) if m else ""
    m = re.search(r'class="item-price[^"]*">([\d\.]+)', art)
    a["prezzo"] = _intero(m.group(1)) if m else None
    dettagli = [_testo(x) for x in re.findall(r'<span class="item-detail">(.*?)</span>', art, re.S)]
    for d in dettagli:
        dl = d.lower()
        if "local" in dl:
            a["locali"] = _intero(d)
        elif "m²" in d or "m2" in dl or "mq" in dl:
            a["mq"] = _intero(d)
        elif "piano" in dl or "terra" in dl:
            a["piano"] = d
            a["ascensore"] = True if "con ascensore" in dl else (False if "senza ascensore" in dl else None)
    m = re.search(r'class="item-description[^"]*">(.*?)</div>', art, re.S)
    a["descrizione"] = _testo(m.group(1)) if m else ""
    a["descrizione_parziale"] = True
    tag = [_testo(x).lower() for x in re.findall(r'class="listing-tags[^"]*">(.*?)</span>', art, re.S)]
    a["caratteristiche"] = [t for t in tag if t] + [d.lower() for d in dettagli]
    a["inserzionista"] = "privato" if 'data-is-professional-ad="false"' in art else "agenzia"
    m = re.search(r'class="logo-branding[^"]*".*?alt="([^"]+)"', art, re.S)
    a["inserzionista_nome"] = _testo(m.group(1)) if m else None
    foto = re.findall(r'<img src="(https://img\d\.idealista\.it/[^"]+\.jpg)"', art)
    a["foto"] = list(dict.fromkeys(foto))[:15]
    # "Trilocale in Viale Porto Palos, 120, Viserbella, Rimini"
    resto = a["titolo"].split(" in ", 1)[1] if " in " in a["titolo"] else a["titolo"]
    parti = [p.strip() for p in resto.split(",") if p.strip()]
    a["comune"] = parti[-1] if parti else None
    a["zona"] = parti[-2] if len(parti) >= 2 and not re.match(r"^\d", parti[-2]) else None
    a["indirizzo"] = resto if VIA_INIZIO.match(resto) else None
    a["coord"] = "comune"
    return a


def idealista(pagina) -> tuple[list, dict]:
    annunci, esito = [], {"pagine": 0, "bloccata": False}
    _riscalda(pagina, "https://www.idealista.it/")
    for prov, _, _ in config.PROVINCE:
        # Idealista chiama queste due province senza "-provincia"
        prov = {"pesaro-urbino-provincia": "pesaro-urbino",
                "forli-cesena-provincia": "forli-cesena"}.get(prov, prov)
        base = (f"https://www.idealista.it/affitto-case/{prov}/con-prezzo_{config.PREZZO_MAX},"
                f"dimensione_{config.MQ_MIN}/")
        for n in range(1, 15):
            url = base if n == 1 else f"{base}pagina-{n}.htm"
            html = _apri(pagina, url, referer="https://www.idealista.it/")
            if not html:
                log.warning("idealista %s pag %d: bloccata", prov, n)
                esito["bloccata"] = esito["pagine"] == 0
                return annunci, esito
            if n > 1 and f"pagina-{n}" not in pagina.url:
                break  # oltre l'ultima pagina Idealista rimanda alla prima
            nuovi = 0
            for art in re.split(r'(?=<article class="item)', html)[1:]:
                m = re.search(r'data-element-id="(\d+)"', art[:600])
                if not m:
                    continue
                try:
                    annunci.append(_idealista_annuncio(art.split("</article>")[0], m.group(1)))
                    nuovi += 1
                except Exception as e:
                    log.warning("idealista annuncio scartato: %s", e)
            esito["pagine"] += 1
            log.info("idealista   %-24s pag %d  %d annunci", prov, n, nuovi)
            if nuovi < 25:
                break
            _pausa()
        _pausa()
    return annunci, esito


# ------------------------------------------------------------------- Bakeca

BAKECA_CITTA = ["rimini", "pesaro", "urbino", "forli", "cesena", "ravenna", "ancona"]


def _bakeca_annuncio(d: dict) -> dict:
    id_ = str(d.get("productID") or (d.get("identifier") or {}).get("value"))
    a = vuoto("bakeca", id_)
    a["url"] = d.get("url", "")
    a["titolo"] = _testo(d.get("name"))
    a["descrizione"] = _testo(d.get("description")).rstrip(" …")
    a["descrizione_parziale"] = True
    a["prezzo"] = _intero((d.get("offers") or {}).get("price"))
    t = f"{a['titolo']} {a['descrizione']}".lower()
    for parola, n in (("monolocal", 1), ("bilocal", 2), ("trilocal", 3), ("quadrilocal", 4)):
        if parola in t:
            a["locali"] = n
            break
    m = re.search(r"(\d{2,3})\s*(?:mq|m2|m²|metri)", t)
    a["mq"] = int(m.group(1)) if m else None
    venditore = ((d.get("offers") or {}).get("seller") or {}).get("@type")
    a["inserzionista"] = "agenzia" if venditore == "RealEstateAgent" else "privato"
    adr = d.get("address") or {}
    a["comune"] = adr.get("addressLocality")
    a["provincia"] = adr.get("addressRegion")
    g = d.get("geo") or {}
    if g.get("latitude"):
        a["lat"], a["lon"], a["coord"] = float(g["latitude"]), float(g["longitude"]), "zona"
    else:
        a["coord"] = "comune"
    if d.get("image"):
        a["foto"] = [d["image"]]
    return a


def bakeca(pagina) -> tuple[list, dict]:
    annunci, esito = [], {"pagine": 0, "bloccata": False}
    _riscalda(pagina, "https://www.bakeca.it/")
    visti = set()
    for citta in BAKECA_CITTA:
        for n in range(1, 8):
            url = f"https://{citta}.bakeca.it/annunci/offro-casa/" + (f"?page={n}" if n > 1 else "")
            html = _apri(pagina, url, referer="https://www.bakeca.it/")
            if not html:
                log.warning("bakeca %s pag %d: bloccata", citta, n)
                esito["bloccata"] = esito["pagine"] == 0
                return annunci, esito
            if "/offro-casa/" not in pagina.url:
                break  # sottodominio che non esiste
            nuovi = 0
            for blocco in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
                try:
                    d = json.loads(blocco)
                except ValueError:
                    continue
                if not isinstance(d, dict) or "SingleFamilyResidence" not in str(d.get("@type")):
                    continue
                a = _bakeca_annuncio(d)
                if a["id"] in visti:
                    continue
                visti.add(a["id"])
                annunci.append(a)
                nuovi += 1
            esito["pagine"] += 1
            log.info("bakeca      %-24s pag %d  %d annunci", citta, n, nuovi)
            if nuovi < 20:
                break
            _pausa()
    return annunci, esito
