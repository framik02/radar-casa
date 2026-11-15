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
    r"\b((?:via|viale|v\.le|piazza|p\.zza|piazzale|corso|largo|vicolo|strada|lungomare)"
    r"\s+[A-ZÀ-Ú0-9][\w'À-ú\.]*(?:\s+(?:[A-ZÀ-Ú0-9][\w'À-ú\.]*|d[ei]|del|della|dei|degli|delle|di|da|e)){0,4})",
    re.I)


def indirizzi_dal_testo(annunci: list[dict]) -> None:
    """Se manca la via, la cerca nel testo e la geocodifica dentro il comune.

    Si accetta solo un risultato che cade entro 8 km dal centro del comune,
    cosi' una "via Roma" non finisce in un'altra citta'.
    """
    cache = _carica("vie.json")
    comuni = _carica("comuni.json")
    cambiato = False
    for a in annunci:
        if a["coord"] in ("indirizzo", "zona") or not a["comune"]:
            continue
        m = VIA.search(f"{a['titolo']} . {a['descrizione']}")
        if not m:
            continue
        via = re.sub(r"\s+", " ", m.group(1)).strip(" .")
        if len(via.split()) < 2 or via.lower().split()[1] in ("mare", "centro", "email", "whatsapp", "sms"):
            continue
        chiave = f"{via}|{a['comune']}|{a['provincia'] or ''}"
        if chiave not in cache:
            q = urllib.parse.urlencode({"street": via, "city": a["comune"], "county": a["provincia"] or "",
                                        "country": "Italia", "format": "json", "limit": 1})
            try:
                r = _json("https://nominatim.openstreetmap.org/search?" + q)
                cache[chiave] = [float(r[0]["lat"]), float(r[0]["lon"])] if r else None
            except Exception as e:
                log.warning("nominatim via %s: %s", chiave, e)
                continue
            cambiato = True
            time.sleep(1.1)
        c, centro = cache.get(chiave), comuni.get(f"{a['comune']}|{a['provincia'] or ''}")
        if c and (not centro or km(c[0], c[1], centro[0], centro[1]) <= 8):
            a["lat"], a["lon"] = c
            a["indirizzo"] = f"{via} (dal testo)"
            a["coord"] = "testo"
    if cambiato:
        _salva("vie.json", cache)


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
