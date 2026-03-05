"""
config.py — Configurações centrais do monitor de promoções.
Edite este arquivo para adicionar perfis, trocar instância do Nitter, etc.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
# Perfis monitorados — adicione ou remova à vontade
# ------------------------------------------------------------------
PERFIS_MONITORADOS = [
    "@LinksBrazil",
    "@oigatuna",
    "@gamerdasofertas",
    "@buscopobres",
    "@tudonapromo",
    "@xetdaspromocoes",
    "@ofcpromo",
    "@urubupromo",
    "@CapivaraPromoss",
    "@lobaopromo",
    "@nossaspromocoes",
    "@sdmlinks",
]

# ------------------------------------------------------------------
# Nitter — instância RSS
# Troque se a instância atual estiver fora do ar
# ------------------------------------------------------------------
NITTER_BASE = os.getenv("NITTER_BASE", "https://twiiit.com")

# ------------------------------------------------------------------
# Intervalo de polling (segundos)
# 60s = checa todo minuto | Não use menos de 30s pra evitar bloqueio
# ------------------------------------------------------------------
INTERVALO_POLLING = int(os.getenv("INTERVALO_POLLING", "60"))

# ------------------------------------------------------------------
# Z.ai / GLM-4.7
# ------------------------------------------------------------------
ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")

# ------------------------------------------------------------------
# Telegram
# ------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # seu chat ID pessoal

# Tiers que geram notificação imediata
TIERS_NOTIFICAR = {"S", "A"}

# ------------------------------------------------------------------
# Banco de dados
# ------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///promocoes.db")

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
