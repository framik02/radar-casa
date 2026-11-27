"""Ascolta le richieste di giro arrivate dal telefono, ogni 5 minuti.

Due strade: il tasto Aggiorna della dashboard (scrive docs/richiesta.json su
GitHub con il token di Sincronizza) oppure /aggiorna al bot Telegram. Se c'è una
richiesta nuova lancia l'operazione pianificata "Radar casa", che non parte due
volte se un giro è già in corso.
"""
from __future__ import annotations

import base64
import json
import logging
import subprocess
import time
import urllib.request

import config
import telegram_bot as tg

config.LOG.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-6s %(message)s", datefmt="%d/%m %H:%M:%S",
                    handlers=[logging.FileHandler(config.LOG / "ascolto.log", encoding="utf-8")])
log = logging.getLogger("ascolto")
PA = config.DATI / "ascolto.json"
API = "https://api.github.com/repos/framik02/radar-casa/contents/docs/richiesta.json?ref=main"


def richiesta_github() -> int:
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "radar-casa"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode())
        return int(json.loads(base64.b64decode(j["content"]))["t"])
    except Exception:
        return 0


def giro_in_corso() -> bool:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-ScheduledTask -TaskName 'Radar casa').State"],
                       capture_output=True, text=True)
    return "Running" in r.stdout


def main() -> None:
    # al primo avvio le richieste già presenti non fanno partire niente
    st = json.loads(PA.read_text(encoding="utf-8")) if PA.exists() else {"github_t": int(time.time() * 1000)}
    chi = []
    try:
        chi = tg.iscrizioni()["_richieste"]
    except Exception as ex:
        log.warning("telegram: %s", ex)
    t = richiesta_github()
    if t > st["github_t"]:
        chi.append("dashboard")
    st["github_t"] = max(t, st["github_t"])
    PA.write_text(json.dumps(st), encoding="utf-8")
    if not chi:
        return
    chat = [c for c in chi if c != "dashboard"]
    if giro_in_corso():
        log.info("richiesta da %s, giro già in corso", chi)
        tg.accoda_avviso(chat)
        tg.scrivi(chat, "C'è già un giro in corso. Ti scrivo appena finisce.")
        return
    minuti = (time.time() - (config.DOCS / "dati.json").stat().st_mtime) / 60
    if minuti < 10:
        log.info("richiesta da %s, ultimo giro %.0f minuti fa", chi, minuti)
        tg.scrivi(chat, f"L'ultimo giro è finito {minuti:.0f} minuti fa, gli annunci sono già aggiornati.")
        return
    subprocess.run(["schtasks", "/run", "/tn", "Radar casa"], capture_output=True)
    log.info("richiesta da %s, giro lanciato", chi)
    tg.accoda_avviso(chat)
    tg.scrivi(chat, "Parto. Il giro dura circa 20 minuti, poi ti mando gli annunci nuovi.")


if __name__ == "__main__":
    main()
