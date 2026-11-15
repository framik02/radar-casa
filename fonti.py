"""Raccolta annunci da Immobiliare.it, Casa.it e Subito.it.

Ogni funzione restituisce (annunci, esito). Un annuncio e' un dizionario
normalizzato, vedi `vuoto()`. L'esito dice quante pagine sono andate e se
la fonte ha bloccato: se blocca, il run non segna i suoi annunci come spariti.
"""
from __future__ import annotations

import json
import logging
import random
import re
import subprocess
import time

import config

log = logging.getLogger("fonti")


def vuoto(fonte: str, id_: str) -> dict:
    return {
        "id": f"{fonte}:{id_}", "fonte": fonte, "url": "", "titolo": "",
        "prezzo": None, "spese": None, "mq": None, "locali": None,
        "bagni": None, "piano": None, "ascensore": None, "arredato": None,
        "giardino": None, "balcone": None, "terrazzo": None,
        "posto_auto": None, "riscaldamento": None, "classe_energetica": None,
        "stato_immobile": None, "tipologia": None, "comune": None,
        "zona": None, "indirizzo": None, "provincia": None,
        "lat": None, "lon": None, "coord": None,
        "inserzionista": None, "inserzionista_nome": None, "telefono": None,
        "foto": [], "descrizione": "", "pubblicato": None,
        "caratteristiche": [], "disponibilita": None,
    }


def _pausa():
    time.sleep(random.uniform(*config.PAUSA_PAGINE))


def _intero(s) -> int | None:
    if s is None:
        return None
    m = re.search(r"\d+", str(s).replace(".", ""))
    return int(m.group()) if m else None


def _next_data(html: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


# --------------------------------------------------------------- Immobiliare

def _imm_risultati(d: dict) -> tuple[list, int]:
    for q in d["props"]["pageProps"]["dehydratedState"]["queries"]:
        data = (q.get("state") or {}).get("data") or {}
        if isinstance(data, dict) and "results" in data:
            return data["results"], int(data.get("maxPages") or 1)
    return [], 0


def _imm_annuncio(r: dict) -> dict:
    re_ = r["realEstate"]
    a = vuoto("immobiliare", str(re_["id"]))
    p = (re_.get("properties") or [{}])[0]
    a["url"] = (r.get("seo") or {}).get("url") or f"https://www.immobiliare.it/annunci/{re_['id']}/"
    a["titolo"] = re_.get("title") or ""
    a["prezzo"] = (re_.get("price") or {}).get("value")
    a["mq"] = _intero(p.get("surface"))
    a["locali"] = _intero(p.get("rooms"))
    a["bagni"] = _intero(p.get("bathrooms"))
    a["piano"] = (p.get("floor") or {}).get("value")
    a["ascensore"] = p.get("elevator")
    a["riscaldamento"] = p.get("ga4Heating")
    a["stato_immobile"] = p.get("ga4Condition")
    a["tipologia"] = (p.get("typology") or re_.get("typology") or {}).get("name")
    feats = [f.lower() for f in (p.get("ga4features") or [])]
    labels = [f.get("label", "") for f in (p.get("featureList") or [])]
    a["caratteristiche"] = sorted(set(feats) | {l.lower() for l in labels if l})
    testo = " ".join(a["caratteristiche"])
    a["arredato"] = True if "arredato" in testo and "non arredato" not in testo else (
        False if "non arredato" in testo else None)
    if "giardino privato" in testo:
        a["giardino"] = "privato"
    elif "giardino comune" in testo:
        a["giardino"] = "comune"
    elif "giardino" in testo:
        a["giardino"] = "si"
    a["balcone"] = "balcon" in testo or None
    a["terrazzo"] = "terrazz" in testo or None
    a["posto_auto"] = ("box" in testo or "posto auto" in testo or "garage" in testo) or None
    loc = p.get("location") or {}
    a["lat"], a["lon"] = loc.get("latitude"), loc.get("longitude")
    a["coord"] = "indirizzo" if loc.get("address") else "zona"
    a["comune"] = loc.get("city")
    a["zona"] = ", ".join(x for x in [loc.get("macrozone"), loc.get("microzone")] if x) or None
    a["indirizzo"] = loc.get("address")
    a["provincia"] = loc.get("province")
    adv = re_.get("advertiser") or {}
    ag = adv.get("agency") or {}
    sup = adv.get("supervisor") or {}
    if ag and ag.get("type") == "agency":
        a["inserzionista"] = "agenzia"
        a["inserzionista_nome"] = ag.get("displayName")
        tel = ag.get("phones") or []
    else:
        a["inserzionista"] = "privato"
        a["inserzionista_nome"] = sup.get("displayName") or ag.get("displayName")
        tel = sup.get("phones") or ag.get("phones") or []
    a["telefono"] = ", ".join(t["value"] for t in tel if t.get("value")) or None
    foto = (p.get("multimedia") or {}).get("photos") or []
    a["foto"] = [f["urls"]["small"].replace("xxs-c.jpg", "m-c.jpg")
                 for f in foto if (f.get("urls") or {}).get("small")][:15]
    a["descrizione"] = p.get("caption") or ""
    a["descrizione_parziale"] = True
    return a


def immobiliare(pagina) -> tuple[list, dict]:
    annunci, esito = [], {"pagine": 0, "bloccata": False}
    for prov, _, _ in config.PROVINCE:
        pag, max_pag = 1, 1
        while pag <= max_pag:
            url = (f"https://www.immobiliare.it/affitto-case/{prov}/?prezzoMassimo="
                   f"{config.PREZZO_MAX}&superficieMinima={config.MQ_MIN}"
                   + (f"&pag={pag}" if pag > 1 else ""))
            r = pagina.goto(url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)
            d = _next_data(pagina.content())
            if not d:
                log.warning("immobiliare %s pag %d: niente dati (HTTP %s)", prov, pag,
                            r.status if r else "?")
                esito["bloccata"] = True
                return annunci, esito
            risultati, max_pag = _imm_risultati(d)
            esito["pagine"] += 1
            for x in risultati:
                try:
                    annunci.append(_imm_annuncio(x))
                except Exception as e:  # un annuncio storto non ferma il giro
                    log.warning("immobiliare annuncio scartato: %s", e)
            log.info("immobiliare %-24s pag %d/%d  %d annunci", prov, pag, max_pag, len(risultati))
            pag += 1
            _pausa()
    return annunci, esito


# --------------------------------------------------------------------- Casa

def _casa_stato(html: str) -> dict | None:
    m = re.search(r'window\.__INITIAL_STATE__ = JSON\.parse\((".*?")\);', html, re.S)
    return json.loads(json.loads(m.group(1))) if m else None


def _casa_annuncio(x: dict) -> dict:
    a = vuoto("casa", str(x["id"]))
    f = x.get("features") or {}
    g = x.get("geoInfos") or {}
    pub = x.get("publisher") or {}
    a["url"] = "https://www.casa.it" + x.get("uri", f"/immobili/{x['id']}/")
    t = x.get("title") or {}
    a["titolo"] = " ".join([t.get("main", "")] + (t.get("additional") or [])).strip()
    a["prezzo"] = _intero((f.get("price") or {}).get("value"))
    a["mq"] = f.get("mq")
    a["locali"] = f.get("rooms")
    a["bagni"] = f.get("bathrooms")
    a["piano"] = f.get("level")
    a["classe_energetica"] = f.get("energyClass")
    a["disponibilita"] = f.get("availability")
    a["posto_auto"] = bool(f.get("parkings")) or None
    a["tipologia"] = x.get("propertyType")
    a["descrizione"] = x.get("description") or ""
    a["lat"], a["lon"] = g.get("lat"), g.get("lon")
    a["coord"] = "indirizzo" if g.get("has_street") and g.get("show_address") else "zona"
    a["comune"] = g.get("city")
    a["zona"] = g.get("district_name")
    a["indirizzo"] = g.get("street")
    a["provincia"] = g.get("province_full_name") or g.get("province")
    tipo = (pub.get("publisherType") or "").lower()
    a["inserzionista"] = "agenzia" if tipo in ("agency", "agencies", "builder") else "privato"
    a["inserzionista_nome"] = pub.get("publisherName")
    if pub.get("showPhoneNumber") and pub.get("publisherPhone"):
        a["telefono"] = pub["publisherPhone"]
    a["foto"] = ["https://images-1.casa.it/800x600" + m["uri"]
                 for m in (x.get("media") or {}).get("items") or [] if m.get("uri")][:15]
    return a


def casa(pagina) -> tuple[list, dict]:
    annunci, esito = [], {"pagine": 0, "bloccata": False}
    for prov, _, _ in config.PROVINCE:
        url = (f"https://www.casa.it/affitto/residenziale/{prov}/?priceMax="
               f"{config.PREZZO_MAX}&mqMin={config.MQ_MIN}")
        pag, tot = 1, 1
        base = None
        while pag <= tot:
            r = pagina.goto(url if pag == 1 else f"{base}&page={pag}",
                            timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)
            s = _casa_stato(pagina.content())
            if not s:
                log.warning("casa %s pag %d: niente dati (HTTP %s)", prov, pag,
                            r.status if r else "?")
                esito["bloccata"] = True
                return annunci, esito
            if pag == 1:
                base = pagina.url.split("&page=")[0]
            srch = s["search"]
            tot = int((srch.get("paginator") or {}).get("totalPages") or 1)
            esito["pagine"] += 1
            for x in srch.get("list") or []:
                try:
                    annunci.append(_casa_annuncio(x))
                except Exception as e:
                    log.warning("casa annuncio scartato: %s", e)
            log.info("casa        %-24s pag %d/%d  %d annunci", prov, pag, tot, len(srch.get("list") or []))
            pag += 1
            _pausa()
    return annunci, esito


# ------------------------------------------------------------------- Subito

def _get(url: str) -> str:
    # curl e non urllib: Subito risponde 403 all'impronta TLS di Python
    r = subprocess.run(["curl", "-s", "-f", "--max-time", "40", "-A", config.UA_SEMPLICE,
                        "-H", "Accept-Language: it-IT,it;q=0.9", url],
                       capture_output=True)
    if r.returncode:
        raise RuntimeError(f"curl uscito con {r.returncode}")
    return r.stdout.decode("utf-8", "replace")


def _trova(o, chiave):
    if isinstance(o, dict):
        if chiave in o:
            return o
        for v in o.values():
            r = _trova(v, chiave)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _trova(v, chiave)
            if r is not None:
                return r
    return None


def _sub_val(feats: dict, k: str):
    v = (feats.get(k) or {}).get("values") or []
    return v[0].get("value") if v else None


def _sub_bool(feats: dict, k: str):
    v = (feats.get(k) or {}).get("values") or []
    return (v[0].get("key") == "1") if v else None


def _subito_annuncio(x: dict, provincia: str) -> dict:
    id_ = x["urn"].split(":")[-1]
    a = vuoto("subito", id_)
    f = x.get("features") or {}
    a["url"] = (x.get("urls") or {}).get("default") or ""
    a["titolo"] = x.get("subject") or ""
    a["descrizione"] = (x.get("body") or "").replace("###phonenumber###", "[numero nascosto da Subito]")
    a["pubblicato"] = x.get("date")
    a["prezzo"] = _intero(_sub_val(f, "/price"))
    a["mq"] = _intero(_sub_val(f, "/size"))
    a["locali"] = _intero(_sub_val(f, "/room"))
    a["bagni"] = _intero(_sub_val(f, "/bathrooms"))
    a["piano"] = _sub_val(f, "/floor")
    a["ascensore"] = _sub_bool(f, "/elevator")
    a["arredato"] = _sub_bool(f, "/furnished")
    a["giardino"] = "si" if _sub_bool(f, "/garden") else None
    a["balcone"] = _sub_bool(f, "/balcony") or None
    a["posto_auto"] = (_sub_val(f, "/parking") not in (None, "Nessuno")) or None
    a["riscaldamento"] = _sub_val(f, "/heating")
    a["classe_energetica"] = _sub_val(f, "/energy_class")
    a["stato_immobile"] = _sub_val(f, "/building_condition")
    a["disponibilita"] = "immediata" if _sub_bool(f, "/available_now") else None
    a["tipologia"] = (x.get("category") or {}).get("label")
    a["caratteristiche"] = sorted(
        f"{v['label'].lower()}: {v['values'][0]['value']}"
        for v in f.values() if v.get("values") and v.get("label"))
    g = x.get("geo") or {}
    a["comune"] = (g.get("town") or {}).get("value")
    a["provincia"] = (g.get("city") or {}).get("value") or provincia
    a["coord"] = "comune"
    adv = x.get("advertiser") or {}
    a["inserzionista"] = "agenzia" if adv.get("company") else "privato"
    a["inserzionista_nome"] = adv.get("shopName") or adv.get("name") or None
    a["foto"] = [i["cdnBaseUrl"] + "?rule=card-desktop-new-large-1x-auto"
                 for i in x.get("images") or [] if i.get("cdnBaseUrl")][:15]
    return a


def subito() -> tuple[list, dict]:
    annunci, esito = [], {"pagine": 0, "bloccata": False}
    for _, regione, prov in config.PROVINCE:
        for cat in config.SUBITO_CATEGORIE:
            o, tot = 1, 1
            while o <= tot and o <= 12:
                url = (f"https://www.subito.it/annunci-{regione}/affitto/{cat}/{prov}/"
                       f"?pe={config.PREZZO_MAX}" + (f"&o={o}" if o > 1 else ""))
                try:
                    html = _get(url)
                except Exception as e:
                    log.warning("subito %s %s: %s", prov, cat, e)
                    if o == 1 and cat == "appartamenti":
                        esito["bloccata"] = True
                    break
                d = _next_data(html)
                items = _trova(d, "originalList") if d else None
                if not items:
                    break
                tot = int(items.get("totalPages") or 1)
                esito["pagine"] += 1
                for x in items.get("originalList") or []:
                    if x.get("kind") != "AdItem":
                        continue
                    try:
                        annunci.append(_subito_annuncio(x, prov))
                    except Exception as e:
                        log.warning("subito annuncio scartato: %s", e)
                log.info("subito      %-24s pag %d/%d  %d annunci", f"{prov}/{cat[:5]}", o, tot,
                         len(items.get("originalList") or []))
                o += 1
                time.sleep(random.uniform(1.5, 3.5))
    return annunci, esito
