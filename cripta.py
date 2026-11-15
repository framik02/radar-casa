"""Cifra i dati pubblicati: il repo e' pubblico, i telefoni no.

AES-GCM con chiave derivata dalla frase segreta via PBKDF2-SHA256, lo stesso
schema che la pagina decifra con WebCrypto.
"""
from __future__ import annotations

import base64
import json
import os
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import config

ITERAZIONI = 250_000
ENV = config.RADICE / ".env"

PAROLE = ("ulivo vigna torre colle mare fiume ponte borgo pino quercia salvia "
          "rondine falco lepre volpe grano mulino cantina portico corte").split()


def chiave() -> str:
    if os.environ.get("RADAR_CHIAVE"):
        return os.environ["RADAR_CHIAVE"]
    if ENV.exists():
        for riga in ENV.read_text(encoding="utf-8").splitlines():
            if riga.startswith("RADAR_CHIAVE="):
                return riga.split("=", 1)[1].strip()
    frase = "-".join(secrets.choice(PAROLE) for _ in range(4)) + "-" + str(secrets.randbelow(900) + 100)
    with ENV.open("a", encoding="utf-8") as f:
        f.write(f"RADAR_CHIAVE={frase}\n")
    return frase


def cifra(oggetto: object) -> str:
    sale, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    k = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sale,
                   iterations=ITERAZIONI).derive(chiave().encode())
    ct = AESGCM(k).encrypt(iv, json.dumps(oggetto, ensure_ascii=False).encode(), None)
    b = lambda x: base64.b64encode(x).decode()
    return json.dumps({"v": 1, "iter": ITERAZIONI, "salt": b(sale), "iv": b(iv), "ct": b(ct)})
