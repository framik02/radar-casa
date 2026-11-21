"""Quando escono gli annunci, per decidere quanti giri fare e a che ora.

Due misure diverse.
1. L'ora di pubblicazione che dichiara il portale. Subito la da' al minuto,
   Bakeca solo il giorno, gli altri niente. Subito puo' dare l'ora di una
   ripubblicazione: per chi cerca casa conta lo stesso, l'annuncio torna in cima.
2. Quanti annunci nuovi trova ogni giro del radar, per tutti i portali, divisi
   per le ore passate dal giro prima.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from itertools import combinations

import config

ORE_PC = range(6, 24)  # ore in cui ha senso far partire un giro col PC acceso


def _giri(archivio: dict) -> list[str]:
    p = config.DATI / "giri.json"
    giri = set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()
    for v in archivio.values():
        giri.add(v["primo"]); giri.add(v["ultimo"])
    giri = sorted(giri)
    p.write_text(json.dumps(giri), encoding="utf-8")
    return giri


def _attesa_media(minuti: list[int], ore: tuple[int, ...]) -> float:
    """Minuti medi fra la pubblicazione e il giro successivo."""
    giri = sorted(h * 60 for h in ore)
    tot = 0
    for m in minuti:
        dopo = [g for g in giri if g >= m]
        tot += (dopo[0] - m) if dopo else (giri[0] + 1440 - m)
    return tot / len(minuti)


def _nel_filtro(v: dict) -> bool:
    """Passa i criteri? Dal 21/11 il giro lo scrive nell'archivio, prima si stima."""
    if "utile" in v:
        return v["utile"]
    a = v["a"]
    return (a.get("prezzo") or 9999) <= config.PREZZO_MAX and not (a.get("mq") and a["mq"] < config.MQ_MIN)


def calcola(archivio: dict, ora: str, attuali: tuple[int, ...] = (8, 19)) -> dict:
    giri = _giri(archivio)
    oggi = datetime.fromisoformat(ora)
    # solo le pubblicazioni da quando il radar guarda: quelle piu' vecchie
    # sono sopravvissute fino a oggi e falserebbero giorni e ore
    da = giri[0][:10]

    # 1. ora e giorno dichiarati dal portale
    stamp = []
    giorni = Counter()
    for v in archivio.values():
        a = v["a"]
        p = (a.get("pubblicato") or "").replace("T", " ")
        if not p or p[:10] < da or not _nel_filtro(v):
            continue
        try:
            d = datetime.fromisoformat(p) if len(p) > 10 else datetime.fromisoformat(p + " 12:00")
        except ValueError:
            continue
        # Bakeca rimette la data di oggi a ogni ripubblicazione: conta solo Subito
        if a["fonte"] == "subito" and len(p) > 10:
            giorni[d.weekday()] += 1
            stamp.append(d)
    ore = Counter(d.hour for d in stamp)
    minuti = [d.hour * 60 + d.minute for d in stamp]

    # 2. annunci nuovi per giro
    # il primo giro di ogni portale trova lo stock, non gli arrivi
    esordio: dict[str, str] = {}
    for v in archivio.values():
        f = v["a"]["fonte"]
        esordio[f] = min(esordio.get(f, v["primo"]), v["primo"])
    nuovi = Counter()
    per_fonte: dict[str, Counter] = {}
    for v in archivio.values():
        if v["primo"] == esordio[v["a"]["fonte"]] or not _nel_filtro(v):
            continue
        nuovi[v["primo"]] += 1
        per_fonte.setdefault(v["primo"], Counter())[v["a"]["fonte"]] += 1
    righe = []
    for prec, g in zip(giri, giri[1:]):
        if g <= max(esordio.values()):
            continue  # giornata in cui i portali entravano uno alla volta
        ore_fin = (datetime.fromisoformat(g) - datetime.fromisoformat(prec)).total_seconds() / 3600
        righe.append({"giro": g, "ore": round(ore_fin, 1), "nuovi": nuovi.get(g, 0),
                      "fonti": dict(per_fonte.get(g, {}))})

    # 3. orari migliori: per ogni numero di giri, quello che fa aspettare meno
    proposte = []
    if len(minuti) >= 30:
        for k in (1, 2, 3, 4):
            migliore = min(combinations(ORE_PC, k), key=lambda c: _attesa_media(minuti, c))
            proposte.append({"giri": k, "ore": list(migliore),
                             "attesa_min": round(_attesa_media(minuti, migliore))})

    return {
        "campione_ore": len(stamp), "da": da,
        "per_ora": [ore.get(h, 0) for h in range(24)],
        "per_giorno": [giorni.get(i, 0) for i in range(7)],
        "giri": giri,
        "per_giro": righe,
        "attuali": {"ore": list(attuali),
                    "attesa_min": round(_attesa_media(minuti, attuali)) if minuti else None},
        "proposte": proposte,
    }
