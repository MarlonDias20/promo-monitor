"""
webhook.py — ida do pipeline para o classificador (agente OpenBot).

Cada tweet novo é gravado no banco com tier P (pendente) e disparado por
POST HTTP assinado (header X-Secret). O webhook pode falhar (o OpenBot
reiniciando, por exemplo): o ciclo seguinte re-dispara os pendentes — a
retentativa é automática e não perde tweet.

Quem volta com a resposta é o agente: cli.py classificar HASH JSON
aplica a classificação no banco e re-exporta o feed do site.
"""
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

HEADER_SEGREDO = "X-Secret"


def payload_do_tweet(promocao) -> dict:
    """Corpo do webhook: só o que o classificador precisa — sem segredos."""
    return {
        "hash": promocao.tweet_hash,
        "url": promocao.tweet_url,
        "conteudo": promocao.conteudo,
        "perfil": promocao.perfil_origem,
        "publicado_em": promocao.publicado_em.isoformat() if promocao.publicado_em else None,
    }


def disparar(url: str, segredo: str, payload: dict, timeout: float = 10.0, _transport: object = None) -> bool:
    """
    POST assinado. Retorna True só com 2xx do receptor — senão o item
    continua pendente e o próximo ciclo tenta de novo.

    `_transport` injeta um MockTransport nos testes; fora deles, o httpx
    usa o transporte real.
    """
    try:
        cliente = httpx.Client(timeout=timeout, transport=_transport) if _transport else httpx.Client(timeout=timeout)
        try:
            resposta = cliente.post(
                url,
                json=payload,
                headers={HEADER_SEGREDO: segredo},
            )
        finally:
            cliente.close()
        if 200 <= resposta.status_code < 300:
            return True
        logger.warning(f"Webhook respondeu {resposta.status_code} — item segue pendente.")
    except Exception as e:
        logger.warning(f"Webhook falhou ({e}) — item segue pendente para retentativa.")
    return False
