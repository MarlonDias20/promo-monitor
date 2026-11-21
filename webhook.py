"""
webhook.py — ida do pipeline para o classificador (agente OpenBot).

Cada tweet novo é gravado no banco com tier P (pendente) e disparado para o
webhook do OpenBot com assinatura HMAC-SHA256:
  - x-openbot-timestamp: Unix em segundos (receptor aceita ±300 s)
  - x-openbot-delivery-id: O HASH DO TWEET — idempotente por natureza;
    o receptor descarta entregas repetidas
  - x-openbot-signature: sha256=<hex HMAC-SHA256 de
    "<timestamp>.<delivery ID>.<corpo exato em bytes>" com PROMO_WEBHOOK_SECRET

Respostas do receptor:
  - 202: aceito — o item sai da fila de retentativa
  - 401/503 (ou erro de rede): NÃO aceito — o ciclo seguinte re-dispara
  - 400: corpo inválido — DESCARTADO, não re-tenta

Quem volta com a resposta é o agente: cli.py classificar HASH JSON
aplica a classificação no banco e re-exporta o feed do site.
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Webhook de promoções do OpenBot (o segredo vem de env — nunca hardcode).
WEBHOOK_PROMOCOES = "https://signal.openbot.run/v1/webhooks/1a7a2fc3-b3fb-4500-b7fc-54eb209a7d33"

# Limite do receptor (o tweet cabe com folha; serve de guarda).
LIMITE_CORPO_BYTES = 64 * 1024


class ResultadoDisparo(Enum):
    ACEITO = "aceito"        # 202 — marca como disparado
    RETENTAR = "retentar"    # 401/503/erro — segue pendente p/ o próximo ciclo
    DESCARTAR = "descartar"  # 400 — corpo inválido, não adianta re-tentar


def payload_do_tweet(promocao, agora: Optional[datetime] = None) -> dict:
    """
    Corpo do webhook (limite 64 KB): só o que o classificador precisa.
    `occurredAt` ISO8601; `data` com hash, url, conteudo, perfil, publicado_em.
    """
    return {
        "type": "promocao",
        "occurredAt": (agora or datetime.utcnow()).isoformat(timespec="seconds") + "Z",
        "data": {
            "hash": promocao.tweet_hash,
            "url": promocao.tweet_url,
            "conteudo": promocao.conteudo,
            "perfil": promocao.perfil_origem,
            "publicado_em": promocao.publicado_em.isoformat() if promocao.publicado_em else None,
        },
    }


def assinar(timestamp: str, delivery_id: str, corpo: bytes, segredo: str) -> str:
    """
    sha256=<hex HMAC-SHA256 de "<timestamp>.<delivery ID>.<corpo exato em
    bytes>", chaveado com o segredo — o contrato do receptor OpenBot.
    """
    mac = hmac.new(
        segredo.encode("utf-8"),
        f"{timestamp}.{delivery_id}.".encode("utf-8") + corpo,
        hashlib.sha256,
    )
    return f"sha256={mac.hexdigest()}"


def disparar(url: str, segredo: str, payload: dict, delivery_id: str, timeout: float = 10.0, _transport: object = None) -> ResultadoDisparo:
    """
    POST assinado para o webhook do OpenBot.

    `_transport` injeta um MockTransport nos testes; fora deles, o httpx
    usa o transporte real. O corpo é serializado UMA vez e enviado em
    bytes exatos — a assinatura cobre exatamente o que trafega.
    """
    corpo = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(corpo) > LIMITE_CORPO_BYTES:
        logger.error(f"Corpo do webhook passa de {LIMITE_CORPO_BYTES} bytes — descartando {delivery_id}.")
        return ResultadoDisparo.DESCARTAR

    timestamp = str(int(time.time()))
    assinatura = assinar(timestamp, delivery_id, corpo, segredo)

    try:
        cliente = httpx.Client(timeout=timeout, transport=_transport) if _transport else httpx.Client(timeout=timeout)
        try:
            resposta = cliente.post(
                url,
                content=corpo,
                headers={
                    "Content-Type": "application/json",
                    "x-openbot-timestamp": timestamp,
                    "x-openbot-delivery-id": delivery_id,
                    "x-openbot-signature": assinatura,
                },
            )
        finally:
            cliente.close()

        if resposta.status_code == 202:
            return ResultadoDisparo.ACEITO
        if resposta.status_code == 400:
            logger.error(f"Webhook rejeitou o corpo (400) — {delivery_id} descartado.")
            return ResultadoDisparo.DESCARTAR
        # 401 (assinatura/horário) e 503 (ocupado/offline): re-tenta depois.
        logger.warning(f"Webhook respondeu {resposta.status_code} — {delivery_id} segue pendente.")
        return ResultadoDisparo.RETENTAR
    except Exception as e:
        logger.warning(f"Webhook falhou ({e}) — {delivery_id} segue pendente para retentativa.")
        return ResultadoDisparo.RETENTAR
