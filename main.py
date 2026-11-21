"""
main.py — Entry point do monitor de promoções.
Uso: python main.py

O ciclo de polling (60s) só coleta: cada tweet novo é gravado no banco com
tier P (pendente) e o webhook do classificador é disparado numa fila em
processo — nem a IA nem o webhook atrasam o próximo ciclo. Pendentes sem
resposta são re-disparados no ciclo seguinte (o receptor pode estar
reiniciando). A notificação por Telegram fica com o agente classificador;
notifier.py e classifier.py permanecem no repo como referência.
"""
import logging
import queue
import threading
import time
from datetime import timedelta

import schedule

import config
import webhook
from database import Database, Promocao
from feed import ExportadorPromos
from worker import RSSWorker, Tweet

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
worker     = RSSWorker(
    perfis=config.PERFIS_MONITORADOS,
    instancias=config.NITTER_INSTANCES,
    falhas_para_rotacionar=config.FALHAS_PARA_ROTACIONAR,
)
exportador = ExportadorPromos(config.PROMOS_JSON_PATH, limite=config.PROMOS_LIMITE)

# Sincroniza hashes do banco no worker para não reprocessar ao reiniciar
hashes_existentes = db.listar_hashes()
worker.sync_hashes_from_db(hashes_existentes)
logger.info(f"Worker iniciado com {len(hashes_existentes)} hashes do banco")

# Sincroniza perfis monitorados no banco
db.sincronizar_perfis(config.PERFIS_MONITORADOS)


# ------------------------------------------------------------------
# Fila de disparo do webhook — fora do ciclo de polling
# ------------------------------------------------------------------
fila: "queue.Queue[Promocao]" = queue.Queue()


def processar_fila():
    """
    Thread consumidora: dispara o webhook de cada pendente. Lenta ou fora
    do ar? O item continua pendente e o ciclo seguinte re-enfileira.
    """
    while True:
        promocao = fila.get()
        try:
            if not config.PROMO_WEBHOOK_URL:
                logger.debug("Webhook desligado (PROMO_WEBHOOK_URL vazio) — item segue pendente.")
                continue

            resultado = webhook.disparar(
                config.PROMO_WEBHOOK_URL,
                config.PROMO_WEBHOOK_SECRET,
                webhook.payload_do_tweet(promocao),
                # O hash do tweet é o delivery ID: idempotente por natureza.
                delivery_id=promocao.tweet_hash,
            )
            if resultado is webhook.ResultadoDisparo.ACEITO:
                db.marcar_webhook_disparado(promocao.id)
                logger.info(f"Webhook aceitou {promocao.tweet_url} — aguardando classificação.")
            elif resultado is webhook.ResultadoDisparo.DESCARTAR:
                # Corpo inválido: sem re-tentativa — sai da fila também.
                db.marcar_webhook_disparado(promocao.id)
                logger.error(f"Webhook descartou {promocao.tweet_url} (corpo inválido).")
            # RETENTAR: nada a marcar — o próximo ciclo re-dispara.
        except Exception as e:
            logger.error(f"Falha ao disparar webhook para {promocao.tweet_url}: {e}")
        finally:
            fila.task_done()


def ciclo():
    """
    Coleta + dispara + exporta. Tudo que pode demorar fica na fila; o
    ciclo em si é rápido para a 'hora do post' não esperar ninguém.
    """
    logger.debug("Iniciando ciclo de coleta...")
    novos = worker.fetch_new_tweets()

    # 1. Grava cada tweet novo como PENDENTE e enfileira o disparo.
    enfileirados = 0
    for tweet in novos:
        promocao = db.salvar_promocao_pendente(tweet)
        if not promocao:
            continue  # duplicata rara, ignora
        fila.put(promocao)
        enfileirados += 1

    # 2. Retentativa: pendentes sem resposta voltam para a fila.
    pendentes = db.buscar_pendentes_webhook(tentar_novamente_apos=timedelta(seconds=config.INTERVALO_POLLING))
    for promocao in pendentes:
        fila.put(promocao)

    # 3. Feed do site — sempre fresco a cada ciclo (pendentes aparecem
    # como 'analisando…' e a classificação chega segundos depois).
    exportador.exportar(db)

    if enfileirados or pendentes:
        logger.info(
            f"Ciclo: {enfileirados} novo(s) enfileirado(s), {len(pendentes)} pendente(s) re-disparado(s) "
            f"(fila: {fila.qsize()})."
        )


def limpeza_semanal():
    """Remove promoções com mais de 7 dias — executa toda segunda às 03h."""
    removidos = db.excluir_antigos(dias=7)
    logger.info(f"Limpeza semanal concluída: {removidos} registro(s) removido(s).")
    exportador.exportar(db)


# ------------------------------------------------------------------
# Agendamento
# ------------------------------------------------------------------
schedule.every(config.INTERVALO_POLLING).seconds.do(ciclo)
schedule.every().monday.at("03:00").do(limpeza_semanal)


# ------------------------------------------------------------------
# Loop
# ------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Monitor de Promoções iniciado")
    logger.info(f"Perfis: {config.PERFIS_MONITORADOS}")
    logger.info(f"Instâncias Nitter: {config.NITTER_INSTANCES}")
    logger.info(f"Intervalo: {config.INTERVALO_POLLING}s")
    logger.info(f"Webhook do classificador: {config.PROMO_WEBHOOK_URL or '(desligado)'}")
    logger.info(f"Feed do site: {config.PROMOS_JSON_PATH}")
    logger.info("=" * 50)

    # Thread consumidora da fila — daemon para morrer junto com o processo.
    threading.Thread(target=processar_fila, name="disparador", daemon=True).start()

    # Executa um ciclo imediato antes de entrar no loop
    ciclo()

    while True:
        schedule.run_pending()
        time.sleep(1)
