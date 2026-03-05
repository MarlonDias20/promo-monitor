"""
main.py — Entry point do monitor de promoções.
Uso: python main.py
"""
import logging
import time
from datetime import datetime

import schedule

import config
from classifier import Classifier
from database import Database
from notifier import TelegramNotifier
from worker import RSSWorker

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ------------------------------------------------------------------
# Inicialização dos componentes
# ------------------------------------------------------------------
db         = Database(config.DATABASE_URL)
worker     = RSSWorker(config.PERFIS_MONITORADOS, config.NITTER_BASE)
classifier = Classifier(api_key=config.ZAI_API_KEY)
notifier   = TelegramNotifier(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID)

# Sincroniza hashes do banco no worker para não reprocessar ao reiniciar
hashes_existentes = db.listar_hashes()
worker.sync_hashes_from_db(hashes_existentes)
logger.info(f"Worker iniciado com {len(hashes_existentes)} hashes do banco")

# Sincroniza perfis monitorados no banco
db.sincronizar_perfis(config.PERFIS_MONITORADOS)


# ------------------------------------------------------------------
# Ciclo principal
# ------------------------------------------------------------------
def ciclo():
    logger.debug("Iniciando ciclo de coleta...")
    novos = worker.fetch_new_tweets()

    if not novos:
        return

    logger.info(f"{len(novos)} tweets novos — classificando...")

    for tweet in novos:
        # 1. Classifica com GLM-4.7
        classificacao = classifier.classify(tweet.conteudo)

        # 2. Persiste no banco
        promocao = db.salvar_promocao(tweet, classificacao)
        if not promocao:
            continue  # duplicata rara, ignora

        # 3. Notifica se tier relevante
        if classificacao["tier"] in config.TIERS_NOTIFICAR:
            enviado = notifier.send(promocao)
            if enviado:
                db.marcar_notificado(promocao.id)


def resumo_diario():
    """Envia stats do dia no Telegram todo dia às 20h."""
    stats = db.stats()
    notifier.send_resumo_diario(stats)
    logger.info(f"Resumo diário enviado: {stats}")


# ------------------------------------------------------------------
# Agendamento
# ------------------------------------------------------------------
schedule.every(config.INTERVALO_POLLING).seconds.do(ciclo)
schedule.every().day.at("20:00").do(resumo_diario)


# ------------------------------------------------------------------
# Loop
# ------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("="*50)
    logger.info("Monitor de Promoções iniciado")
    logger.info(f"Perfis: {config.PERFIS_MONITORADOS}")
    logger.info(f"Intervalo: {config.INTERVALO_POLLING}s")
    logger.info(f"Tiers notificados: {config.TIERS_NOTIFICAR}")
    logger.info("="*50)

    # Executa um ciclo imediato antes de entrar no loop
    ciclo()

    while True:
        schedule.run_pending()
        time.sleep(1)
