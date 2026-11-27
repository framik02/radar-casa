"""Manda su Telegram gli annunci nuovi di ogni giro.

Il token sta in .env (TELEGRAM_TOKEN), fuori da git. Per iscriversi si scrive al
bot la frase segreta della dashboard: al giro dopo, o lanciando
    python telegram_bot.py
la chat entra nell'elenco dati/telegram.json e riceve gli annunci.
"""
from __future__ import annotations

import html
import json
import logging
import urllib.parse
import urllib.request

import config
import cripta

log = logging.getLogger("telegram")
DASHBOARD = "https://framik02.github.io/radar-casa/"
PA = config.DATI / "telegram.json"


def _env(nome: str) -> str | None:
    p = config.RADICE / ".env"
    if p.exists():
        for riga in p.read_text(encoding="utf-8").splitlines():
            if riga.startswith(nome + "="):
                return riga.split("=", 1)[1].strip()
    return None


def _api(metodo: str, **dati) -> dict:
    url = f"https://api.telegram.org/bot{_env('TELEGRAM_TOKEN')}/{metodo}"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(dati).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _stato() -> dict:
    return json.loads(PA.read_text(encoding="utf-8")) if PA.exists() else {"chat": [], "offset": 0, "inviati": []}


def iscrizioni() -> dict:
    """Legge i messaggi arrivati al bot e iscrive chi ha scritto la frase segreta."""
    st = _stato()
    frase = cripta.chiave().strip().lower()
    r = _api("getUpdates", offset=st["offset"], timeout=0)
    richieste = []
    for u in r.get("result", []):
        st["offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        chat, testo = (m.get("chat") or {}).get("id"), (m.get("text") or "").strip().lower()
        if not chat:
            continue
        if frase in testo and chat not in st["chat"]:
            st["chat"].append(chat)
            _api("sendMessage", chat_id=chat, text="Iscritto. Ti scrivo qui gli annunci nuovi a ogni giro del radar.")
            log.info("telegram: iscritta la chat %s", chat)
        elif chat not in st["chat"]:
            _api("sendMessage", chat_id=chat, text="Scrivimi la frase segreta della dashboard per ricevere gli annunci.")
        elif "aggiorna" in testo:
            if chat not in richieste:
                richieste.append(chat)
        else:
            _api("sendMessage", chat_id=chat, text="Scrivi /aggiorna per far partire un giro adesso.")
    _salva(st)
    st["_richieste"] = richieste
    return st


def _salva(st: dict) -> None:
    PA.write_text(json.dumps({k: v for k, v in st.items() if not k.startswith("_")}), encoding="utf-8")


def scrivi(chat: list, testo: str) -> None:
    for c in chat:
        try:
            _api("sendMessage", chat_id=c, text=testo)
        except Exception as ex:
            log.warning("telegram invio a %s: %s", c, ex)


def accoda_avviso(chat: list) -> None:
    """Chi ha chiesto un giro riceve un messaggio a fine giro anche se non c'è niente di nuovo."""
    if not chat:
        return
    st = _stato()
    st["da_avvisare"] = sorted(set(st.get("da_avvisare", [])) | set(chat))
    _salva(st)


def fine_giro(n_nuovi: int) -> None:
    st = _stato()
    chi = st.pop("da_avvisare", [])
    if not chi:
        return
    _salva(st)
    scrivi(chi, "Giro finito, nessun annuncio nuovo." if n_nuovi == 0 else
           f"Giro finito, {n_nuovi} annunci nuovi qui sopra.")


def _riga(a: dict) -> str:
    e = html.escape
    tipo = {2: "bilocale", 3: "trilocale", 4: "quadrilocale"}.get(a.get("locali"), "casa")
    via = a.get("indirizzo") or (("zona " + a["via_vicina"]) if a.get("via_vicina") else "")
    extra = []
    if a.get("giardino"):
        extra.append("giardino" + (" privato" if a["giardino"] == "privato" else ""))
    if a.get("clima") == "si":
        extra.append("aria condizionata")
    if a.get("classe_energetica") and len(a["classe_energetica"]) <= 3:
        extra.append("classe " + a["classe_energetica"])
    if a.get("treno") == "comodo":
        extra.append(f"stazione a {a['stazione_km']} km")
    if a.get("durata") == "si":
        extra.append("12 mesi chiari")
    pezzi = [f"<b>{a['prezzo']} €</b>", tipo + (f" {a['mq']} m²" if a.get("mq") else ""),
             e(a.get("comune") or "") + (", " + e(via) if via else ""), f"{a['minuti_auto']} min in auto"]
    link = [f'<a href="{e(a["url"])}">{e(a["fonte"])}</a>'] + [
        f'<a href="{e(x["url"])}">{e(x["fonte"])}</a>' for x in a.get("altre_fonti") or []]
    tel = f"\n☎ {e(a['telefono'])}" if a.get("telefono") else ""
    return " · ".join(pezzi) + (f"\n{e(', '.join(extra))}" if extra else "") + tel + "\n" + " · ".join(link)


def invia_nuovi(annunci: list[dict], ora: str) -> int:
    if not _env("TELEGRAM_TOKEN"):
        return 0
    try:
        st = iscrizioni()
    except Exception as ex:
        log.warning("telegram getUpdates: %s", ex); return 0
    accoda_avviso(st["_richieste"])
    if not st["chat"]:
        log.info("telegram: nessuna chat iscritta"); return 0
    gia = set(st["inviati"])
    nuovi = [a for a in annunci if a["primo_visto"] == ora and not set(a["ids"]) & gia]
    if not nuovi:
        return 0
    nuovi.sort(key=lambda a: -a["punteggio"])
    blocchi, corrente = [], f"<b>{len(nuovi)} annunci nuovi</b> nel radar\n"
    for a in nuovi:
        r = "\n" + _riga(a) + "\n"
        if len(corrente) + len(r) > 3800:
            blocchi.append(corrente); corrente = ""
        corrente += r
    blocchi.append(corrente + f'\n<a href="{DASHBOARD}">Apri la dashboard</a>')
    for chat in st["chat"]:
        for b in blocchi:
            try:
                _api("sendMessage", chat_id=chat, text=b, parse_mode="HTML", disable_web_page_preview="true")
            except Exception as ex:
                log.warning("telegram invio a %s: %s", chat, ex)
    st = _stato()
    st["inviati"] = (st["inviati"] + [i for a in nuovi for i in a["ids"]])[-5000:]
    _salva(st)
    log.info("telegram: %d annunci nuovi a %d chat", len(nuovi), len(st["chat"]))
    return len(nuovi)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("chat iscritte:", iscrizioni()["chat"])
