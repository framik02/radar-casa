"""Filtri, durata del contratto, avvisi, punteggio e unione dei doppioni."""
from __future__ import annotations

import re

import config
from geo import km

# ------------------------------------------------------------------ durata

NO_DURATA = [
    (r"\btransitori[oa]?\b", "contratto transitorio"),
    (r"(settembre|ottobre|novembre)\s*(?:a|al|-|–|/|fino\s+a)\s*(maggio|giugno|luglio)",
     "solo da autunno a primavera"),
    (r"\bfino\s+(?:a|al(?:la)?\s+fine\s+di)\s+(maggio|giugno|luglio)\b", "libero solo fino all'estate"),
    (r"\bperiodo\s+invernale\b|\binvernal[ei]\b", "solo inverno"),
    (r"\bstagional[ei]\b|\bstagione\s+estiva\b|(?:solo|periodo|affitto|locazione|appartamenti|"
     r"stagione)\s+estiv[oaie]", "affitto stagionale"),
    (r"(?<!non )(?<!non è disponibile per )\buso\s+turistico\b|(?<!per )\baffitt[oi]\s+brev[ei]\b"
     r"|\bcasa?e?\s+vacanz", "uso turistico"),
    (r"\bsettiman[ae]l[ei]\b|\ba\s+settimana\b|\bweek\s*end\b", "affitto a settimane"),
    (r"(?:durata|contratto|affitt\w*|locazione|periodo)\s+(?:di\s+|da\s+|per\s+)?(?:max\s+)?"
     r"([1-9]|1[01])\s*mesi\b", "durata sotto i 12 mesi"),
]
# transitorio lungo: puo' arrivare a 18 mesi, quindi non si scarta, si chiede
TRANSITORIO_LUNGO = r"(?:un\s+anno|12\s*mesi|18\s*mesi)"
SI_DURATA = [
    (r"\b4\s*\+\s*4\b", "4+4"),
    (r"\b3\s*\+\s*2\b", "3+2"),
    (r"canone\s+concordato", "canone concordato"),
    (r"\bannual[ei]\b|\b12\s*mesi\b|\b(18|24|36|48)\s*mesi\b", "annuale o più"),
    (r"lungo\s+(?:periodo|termine)|\btutto\s+l'anno\b|\bresidenzial[ei]\b|\bresidenti\b",
     "lungo periodo"),
    (r"cedolare\s+secca", "cedolare secca"),
]

AVVISI = [
    (r"quota\s+fissa|servizio\s+di\s+ricerca|non\s+[èe]\s+un'?\s*agenzia|iscrizione\s+al\s+servizio|tessera",
     "possibile ufficio a pagamento che vende liste di case"),
    (r"tempo\s+indeterminato|busta\s+paga|referenz", "chiede garanzie di reddito o referenze"),
    (r"no\s+residenza|senza\s+residenza", "senza residenza"),
    (r"(?:spese|consumi|utenze)\s+inclus", "spese o consumi inclusi"),
    (r"no\s+animali|animali\s+non\s+ammessi", "niente animali"),
    (r"\bstudent[ie]\b", "pensato per studenti"),
    (r"solo\s+(?:a\s+)?(?:donne|ragazze|uomini|ragazzi)", "solo uomini o solo donne"),
]


def valuta_durata(a: dict) -> None:
    t = f"{a['titolo']} {a['descrizione']}".lower()
    no = [m for r, m in NO_DURATA if re.search(r, t)]
    si = [m for r, m in SI_DURATA if re.search(r, t)]
    # "annuale" con "studenti settembre-giugno" resta un no: vince il segnale negativo
    if no == ["contratto transitorio"] and re.search(TRANSITORIO_LUNGO, t):
        a["durata"], a["durata_motivo"] = "chiedere", "transitorio fino a 12-18 mesi, chiedere se si rinnova"
    elif no:
        a["durata"], a["durata_motivo"] = "no", no[0]
    elif si:
        a["durata"], a["durata_motivo"] = "si", ", ".join(dict.fromkeys(si))
    else:
        a["durata"], a["durata_motivo"] = "chiedere", "l'annuncio non dice la durata"
    if re.search(r"annual[ei]\s+no\s+lungo|solo\s+un\s+anno|non\s+rinnovabil", t):
        a["durata_motivo"] += ", solo un anno"
    a["avvisi"] = [m for r, m in AVVISI if re.search(r, t)]
    if a["giardino"] is None and re.search(r"giardin", t):
        a["giardino"] = "privato" if re.search(r"giardino\s+(privato|esclusivo|di\s+propriet)", t) else "si"
    if a["posto_auto"] is None and re.search(r"posto\s+auto|garage|\bbox\b", t):
        a["posto_auto"] = True
    if a["spese"] is None:
        m = re.search(r"spese\s+(?:condominiali|condominio)?\s*(?:di|:)?\s*(?:€|euro)?\s*(\d{2,3})\s*(?:€|euro)?", t)
        if m:
            a["spese"] = int(m.group(1))


# ------------------------------------------------------------------ filtri

def esclusione(a: dict) -> str | None:
    tip = (a["tipologia"] or "").lower()
    if any(x in tip for x in ("stanza", "camera", "posto letto", "garage", "ufficio", "negozio")):
        return "non è un'abitazione intera"
    if a["prezzo"] is None or a["prezzo"] > config.PREZZO_MAX:
        return "prezzo"
    if a["prezzo"] < 150:
        return "prezzo"  # quasi sempre a settimana o un errore
    if a["mq"] is not None and a["mq"] < config.MQ_MIN:
        return "metri quadri"
    if a["locali"] is not None and a["locali"] not in config.LOCALI_AMMESSI:
        return "numero di locali"
    if "monolocale" in tip or "monolocale" in a["titolo"].lower():
        return "numero di locali"
    if a["lat"] is None:
        return "posizione sconosciuta"
    if a.get("km_aria", 999) > config.KM_LINEA_D_ARIA_MAX:
        return "troppo lontano"
    if a.get("minuti_auto") is None:
        return "percorso non calcolato"
    if a["minuti_auto"] > config.MINUTI_MAX:
        return "troppo lontano"
    if a["durata"] == "no":
        return "durata sotto i 12 mesi"
    return None


# ---------------------------------------------------------------- punteggio

def punteggio(a: dict) -> None:
    p, perche = 100 - a["minuti_auto"] * 1.2, [f"{a['minuti_auto']} min in auto"]
    if a["giardino"] == "privato":
        p += 14; perche.append("giardino privato")
    elif a["giardino"] in ("si", "comune"):
        p += 8; perche.append("giardino" + (" condominiale" if a["giardino"] == "comune" else ""))
    sk = a.get("stazione_km")
    if sk is not None and a["coord"] == "indirizzo" and sk <= config.STAZIONE_COMODA_KM:
        p += 6; perche.append(f"stazione a {sk} km")
        a["treno"] = "comodo"
    elif sk is not None and a["coord"] != "indirizzo" and sk <= 3:
        p += 2; perche.append(f"stazione di {a['stazione']} nel comune")
        a["treno"] = "nel comune"
    else:
        a["treno"] = None
    if a["durata"] == "si":
        p += 8; perche.append("durata chiara")
    if a["posto_auto"]:
        p += 3; perche.append("posto auto")
    if a["prezzo"] <= 650:
        p += 4; perche.append("prezzo sotto 650 €")
    if any("ufficio a pagamento" in x for x in a["avvisi"]):
        p -= 20; perche.append("possibile ufficio a pagamento")
    if a["coord"] != "indirizzo":
        perche.append("posizione approssimata")
    a["punteggio"] = round(p, 1)
    a["perche"] = perche


# ----------------------------------------------------------------- doppioni

PESO_FONTE = {"casa": 3, "immobiliare": 2, "subito": 1}  # chi ha la descrizione intera


def _ricchezza(a: dict) -> tuple:
    return (len(a["descrizione"]) > 200, a["coord"] == "indirizzo",
            PESO_FONTE.get(a["fonte"], 0), len(a["foto"]))


def unisci_doppioni(annunci: list[dict]) -> list[dict]:
    """Stesso prezzo, stessi metri (piu' o meno 3), stessi locali, vicini."""
    gruppi: list[list[dict]] = []
    for a in annunci:
        for g in gruppi:
            b = g[0]
            # sullo stesso portale due annunci uguali sono quasi sempre due case
            if a["fonte"] in {x["fonte"] for x in g}:
                continue
            if a["prezzo"] != b["prezzo"] or a["locali"] != b["locali"]:
                continue
            if a["mq"] and b["mq"] and abs(a["mq"] - b["mq"]) > 3:
                continue
            vicino = km(a["lat"], a["lon"], b["lat"], b["lon"])
            precisi = a["coord"] == "indirizzo" and b["coord"] == "indirizzo"
            if (precisi and vicino <= 0.4) or (not precisi and (a["comune"] or "").lower() == (b["comune"] or "").lower() and vicino <= 3):
                g.append(a)
                break
        else:
            gruppi.append([a])
    out = []
    for g in gruppi:
        g.sort(key=_ricchezza, reverse=True)
        capo = dict(g[0])
        capo["altre_fonti"] = [{"fonte": x["fonte"], "url": x["url"], "id": x["id"],
                                "telefono": x["telefono"], "inserzionista_nome": x["inserzionista_nome"]}
                               for x in g[1:]]
        for x in g[1:]:  # riempi i buchi del capo con gli altri
            for k in ("telefono", "spese", "classe_energetica", "piano", "riscaldamento",
                      "giardino", "arredato", "disponibilita", "pubblicato"):
                if capo.get(k) in (None, "") and x.get(k) not in (None, ""):
                    capo[k] = x[k]
            for f in x["foto"]:
                if len(capo["foto"]) < 20 and f not in capo["foto"]:
                    capo["foto"].append(f)
        capo["ids"] = [x["id"] for x in g]
        out.append(capo)
    return out
