"""Coordinate dei comuni, tempi in auto dalla sede e stazioni ferroviarie.

Tutto in cache dentro dati/, cosi' ogni servizio esterno si interroga una
volta sola per luogo.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
import urllib.parse
import urllib.request

import config

log = logging.getLogger("geo")


def _carica(nome: str) -> dict:
    p = config.DATI / nome
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _salva(nome: str, d: dict) -> None:
    (config.DATI / nome).write_text(json.dumps(d, ensure_ascii=False, indent=0), encoding="utf-8")


def _json(url: str, dati: bytes | None = None) -> object:
    req = urllib.request.Request(url, data=dati, headers={"User-Agent": config.UA_SERVIZI})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ------------------------------------------------------------------ comuni

def geocodifica_comuni(annunci: list[dict]) -> None:
    """Per gli annunci senza coordinate usa il centro del comune."""
    cache = _carica("comuni.json")
    cambiato = False
    for a in annunci:
        if a["lat"] is not None or not a["comune"]:
            continue
        chiave = f"{a['comune']}|{a['provincia'] or ''}"
        if chiave not in cache:
            q = urllib.parse.urlencode({
                "city": a["comune"], "county": a["provincia"] or "", "country": "Italia",
                "format": "json", "limit": 1})
            try:
                r = _json("https://nominatim.openstreetmap.org/search?" + q)
                cache[chiave] = [float(r[0]["lat"]), float(r[0]["lon"])] if r else None
            except Exception as e:
                log.warning("nominatim %s: %s", chiave, e)
                continue
            cambiato = True
            time.sleep(1.1)  # regola d'uso di Nominatim
        if cache.get(chiave):
            a["lat"], a["lon"] = cache[chiave]
    if cambiato:
        _salva("comuni.json", cache)


VIA = re.compile(
    r"\b((?i:via|viale|v\.le|piazza|p\.zza|piazzale|corso|largo|vicolo|strada|lungomare)"
    r"\s+(?:(?:dell'|dall'|della\s+|delle\s+|dei\s+|degli\s+|del\s+|di\s+)?[A-ZÀ-Ú][\w'À-ú\.]*|\d{1,2}\s+[A-Z][a-zà-ú]+)"
    r"(?:\s+(?:[A-ZÀ-Ú][\w'À-ú\.]*|d[ei]|del|dell'\w+|della|dei|degli|delle|di|da|e)){0,4})"
    r"(?:\s*,?\s*(?:[nN]\.?\s*)?(\d{1,4}(?:\s*/?\s*[a-hA-H])?)\b"
    r"(?!\s*(?i:mq|m2|m²|locali|camer|euro|€|mesi|piano|min)))?")
PAROLE_NON_VIA = {"mare", "centro", "email", "whatsapp", "sms", "telefono", "mail", "messaggio"}


def _geocodifica_via(cache: dict, via: str, civico: str | None, comune: str, provincia: str) -> list | None:
    chiave = f"{via}|{civico or ''}|{comune}|{provincia}"
    if chiave not in cache:
        strada = f"{civico} {via}" if civico else via
        q = urllib.parse.urlencode({"street": strada, "city": comune, "county": provincia,
                                    "country": "Italia", "format": "json", "limit": 1})
        try:
            r = _json("https://nominatim.openstreetmap.org/search?" + q)
        except Exception as e:
            log.warning("nominatim via %s: %s", chiave, e)
            return None
        cache[chiave] = [float(r[0]["lat"]), float(r[0]["lon"]), r[0].get("addresstype") or r[0].get("type")] if r else None
        cache["_cambiato"] = True
        time.sleep(1.1)
    return cache.get(chiave)


def indirizzi_dal_testo(annunci: list[dict]) -> None:
    """Cerca via e civico nel titolo, nell'indirizzo o nel testo e li geocodifica.

    Vale per chi ha solo il comune (risultato entro 8 km dal centro) e per chi
    ha solo una zona (entro 3 km dal punto della zona), cosi' una "via Roma"
    non finisce in un'altra citta'. Se c'e' il civico e Nominatim lo trova,
    la posizione diventa esatta.
    """
    cache = _carica("vie.json")
    comuni = _carica("comuni.json")
    for a in annunci:
        if a["coord"] not in ("comune", "zona") or not a["comune"]:
            continue
        testo = " . ".join(x for x in [a.get("indirizzo") or "", a["titolo"], a["descrizione"]] if x)
        m = None
        for cand in VIA.finditer(testo):
            parole = cand.group(1).split()
            if len(parole) >= 2 and parole[1].lower() not in PAROLE_NON_VIA:
                m = cand
                break
        if not m:
            continue
        via = re.sub(r"\s+", " ", m.group(1)).strip(" .")
        civico = re.sub(r"\s+", "", m.group(2)) if m.group(2) else None
        prov = a["provincia"] or ""
        c = _geocodifica_via(cache, via, civico, a["comune"], prov) if civico else None
        esatto = bool(c and c[2] in ("house", "building", "place"))
        if not esatto:
            c = _geocodifica_via(cache, via, None, a["comune"], prov)
        if not c:
            continue
        if a["coord"] == "zona" and a["lat"] is not None:
            rif, raggio = (a["lat"], a["lon"]), 3
        else:
            centro = comuni.get(f"{a['comune']}|{prov}")
            rif, raggio = (centro[0], centro[1]) if centro else (c[0], c[1]), 8
        if km(c[0], c[1], rif[0], rif[1]) > raggio:
            continue
        a["lat"], a["lon"] = c[0], c[1]
        a["indirizzo"] = f"{via} {civico}" if esatto else via
        a["coord"] = "indirizzo" if esatto else "testo"
        a["fonte_indirizzo"] = "testo dell'annuncio"
    if cache.pop("_cambiato", False):
        _salva("vie.json", cache)


def via_vicina(annunci: list[dict]) -> None:
    """Per i punti approssimati scrive su che via cadono, come indicazione."""
    cache = _carica("vicine.json")
    cambiato = False
    for a in annunci:
        if a["coord"] != "zona" or a["lat"] is None:
            continue
        k = f"{a['lat']:.4f},{a['lon']:.4f}"
        if k not in cache:
            q = urllib.parse.urlencode({"lat": a["lat"], "lon": a["lon"], "format": "json", "zoom": 17})
            try:
                r = _json("https://nominatim.openstreetmap.org/reverse?" + q)
                ad = r.get("address") or {}
                cache[k] = ad.get("road") or ad.get("pedestrian") or ad.get("square")
            except Exception as e:
                log.warning("nominatim inverso %s: %s", k, e)
                continue
            cambiato = True
            time.sleep(1.1)
        if cache.get(k):
            a["via_vicina"] = cache[k]
    if cambiato:
        _salva("vicine.json", cache)


# ---------------------------------------------------------------- percorsi

def _k(lat, lon) -> str:
    return f"{lat:.4f},{lon:.4f}"


def tempi_in_auto(annunci: list[dict]) -> None:
    """Minuti e km in auto dalla sede, via OSRM, a gruppi di 80."""
    cache = _carica("percorsi.json")
    mancanti = []
    for a in annunci:
        if a["lat"] is None:
            continue
        a["km_aria"] = round(km(config.SEDE["lat"], config.SEDE["lon"], a["lat"], a["lon"]), 1)
        k = _k(a["lat"], a["lon"])
        if k not in cache and a["km_aria"] <= config.KM_LINEA_D_ARIA_MAX and k not in mancanti:
            mancanti.append(k)
    for i in range(0, len(mancanti), 80):
        gruppo = mancanti[i:i + 80]
        punti = [f"{config.SEDE['lon']},{config.SEDE['lat']}"] + [
            ",".join(reversed(k.split(","))) for k in gruppo]
        url = ("https://router.project-osrm.org/table/v1/driving/" + ";".join(punti)
               + "?sources=0&annotations=duration,distance")
        try:
            r = _json(url)
            for j, k in enumerate(gruppo, start=1):
                d, s = r["durations"][0][j], r["distances"][0][j]
                if d is not None:
                    cache[k] = [round(d / 60), round(s / 1000, 1)]
        except Exception as e:
            log.warning("osrm: %s", e)
        time.sleep(1.5)
    if mancanti:
        _salva("percorsi.json", cache)
    for a in annunci:
        if a["lat"] is None:
            continue
        v = cache.get(_k(a["lat"], a["lon"]))
        if v:
            a["minuti_auto"], a["km_auto"] = v


# ---------------------------------------------------------------- stazioni

def stazioni() -> list[dict]:
    p = config.DATI / "stazioni.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    q = """[out:json][timeout:60];
    node["railway"="station"]["disused"!="yes"]["abandoned"!="yes"]
      ["station"!="subway"]["station"!="light_rail"](43.40,11.80,44.50,13.70);
    out;"""
    r = _json("https://overpass-api.de/api/interpreter",
              urllib.parse.urlencode({"data": q}).encode())
    out = []
    for e in r["elements"]:
        t = e.get("tags", {})
        if t.get("railway:historic") or t.get("tourism") or t.get("usage") == "tourism":
            continue
        out.append({"nome": t.get("name", "stazione"), "lat": e["lat"], "lon": e["lon"]})
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def stazione_vicina(a: dict, elenco: list[dict]) -> None:
    if a["lat"] is None or not elenco:
        return
    s = min(elenco, key=lambda s: km(a["lat"], a["lon"], s["lat"], s["lon"]))
    a["stazione"] = s["nome"]
    a["stazione_km"] = round(km(a["lat"], a["lon"], s["lat"], s["lon"]), 1)
