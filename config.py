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
# Nitter — instâncias RSS
# Lista configurável (vírgula na env NITTER_INSTANCES); o worker rotaciona
# automaticamente para a próxima saudável quando uma acumula falhas seguidas.
# ------------------------------------------------------------------
_INSTANCIAS_PADRAO = [
    "https://twiiit.com",
    "https://nitter.privacydev.net",
    "https://nitter.net",
    "https://nitter.1d4.us",
]

def _ler_instancias() -> list[str]:
    da_env = os.getenv("NITTER_INSTANCES", "")
    if da_env.strip():
        return [u.strip().rstrip("/") for u in da_env.split(",") if u.strip()]
    return list(_INSTANCIAS_PADRAO)

NITTER_INSTANCES = _ler_instancias()

# Retrocompatível com quem já usava NITTER_BASE — entra como primeira opção.
_nitter_base = os.getenv("NITTER_BASE", "").strip().rstrip("/")
if _nitter_base and _nitter_base not in NITTER_INSTANCES:
    NITTER_INSTANCES.insert(0, _nitter_base)

# Falhas seguidas de uma instância antes de rotacionar para a próxima
FALHAS_PARA_ROTACIONAR = int(os.getenv("FALHAS_PARA_ROTACIONAR", "2"))

# ------------------------------------------------------------------
# Webhook do classificador — um agente OpenBot acordado por POST
# ------------------------------------------------------------------
PROMO_WEBHOOK_URL = os.getenv("PROMO_WEBHOOK_URL", "")
PROMO_WEBHOOK_SECRET = os.getenv("PROMO_WEBHOOK_SECRET", "")

# ------------------------------------------------------------------
# Feed do site — promos.json exportado a cada ciclo
# ------------------------------------------------------------------
PROMOS_JSON_PATH = os.getenv("PROMOS_JSON_PATH", "site/promos.json")
PROMOS_LIMITE = int(os.getenv("PROMOS_LIMITE", "500"))

# ------------------------------------------------------------------
# Intervalo de polling (segundos)
# 60s = checa todo minuto | Não use menos de 30s pra evitar bloqueio
# ------------------------------------------------------------------
INTERVALO_POLLING = int(os.getenv("INTERVALO_POLLING", "60"))

# ------------------------------------------------------------------
# Z.ai / GLM
# Endpoint e modelo configuráveis: a conta internacional do Z.ai usa
# https://api.z.ai/api/paas/v4/ (OpenAI-compatível; modelos glm-4.6,
# glm-4.7, glm-5.x). A plataforma CN (Zhipu BigModel) usa
# https://open.bigmodel.cn/api/paas/v4/. Deixe o que combina com seu pacote.
# ------------------------------------------------------------------
ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
ZAI_BASE_URL = os.getenv("ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
ZAI_MODEL = os.getenv("ZAI_MODEL", "glm-4")

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
