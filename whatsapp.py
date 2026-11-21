"""
whatsapp.py — sender do WhatsApp Cloud API oficial (Meta Graph).

Quem chama é o AGENTE classificador (Passo 3 do fluxo do webhook), o mesmo
papel que o Telegram tem hoje — o worker não envia nada. Formatação
espelhada no notifier.py: cabeçalho por tier, produto, loja, preços,
desconto, urgência, motivo, link e perfil — TEXTO PLANO com emojis
(a Cloud API de texto não tem markdown), sem dados além da própria promo.

Configuração por env (valores vêm do painel da Meta — nunca hardcode):
    WHATSAPP_TOKEN           token de system user
    WHATSAPP_PHONE_NUMBER_ID  phone number ID do número
    WA_DESTINO               número do destinatário, dígitos + DDI (ex.: 5521999999999)

Janela de 24 h: a Cloud API só entrega dentro da janela de atendimento
aberta pela última mensagem do destinatário — quem for receber precisa
mandar um 'oi' pro número antes (o modelo de teste é mais generoso; ver
README).
"""
import logging
from typing import Optional

import httpx

from database import Promocao

logger = logging.getLogger(__name__)

GRAPH_VERSAO = "v20.0"

TIER_CONFIG = {
    "S": {"header": "🚨 BUG / OFERTA ABSURDA"},
    "A": {"header": "⚡ OFERTA RELÂMPAGO"},
}


def formatar(promocao: Promocao) -> str:
    """
    Texto plano da promoção, no mesmo esqueleto do notifier.py — emojis ok,
    sem markdown (a Cloud API de texto não tem parse mode).
    """
    cfg = TIER_CONFIG.get(promocao.tier, {"header": "💤 Oferta"})

    linhas = [cfg["header"]]

    if promocao.produto:
        linhas.append(f"🛍 {promocao.produto}")
    if promocao.loja:
        linhas.append(f"🏪 {promocao.loja}")

    if promocao.preco_original and promocao.preco_promocional:
        linhas.append(f"💰 {promocao.preco_original} → {promocao.preco_promocional}")
    elif promocao.preco_promocional:
        linhas.append(f"💰 {promocao.preco_promocional}")

    if promocao.desconto_estimado:
        linhas.append(f"📉 Desconto estimado: {promocao.desconto_estimado:.0f}%")

    if promocao.urgencia:
        linhas.append(f"⚡ Urgência: {'🔴' * min(int(promocao.urgencia / 2), 5)}")

    if promocao.motivo:
        linhas.append(f"💬 {promocao.motivo}")

    linhas.append(f"🔗 {promocao.tweet_url}")
    linhas.append(f"👤 @{promocao.perfil_origem}")

    return "\n".join(linhas)


class WhatsAppNotifier:
    def __init__(
        self,
        token: str,
        phone_number_id: str,
        destino: str,
        timeout: float = 10.0,
        _transport: Optional[object] = None,
    ):
        self.token = token
        self.phone_number_id = phone_number_id
        self.destino = destino
        self._url = f"https://graph.facebook.com/{GRAPH_VERSAO}/{phone_number_id}/messages"
        self._client = (
            httpx.Client(timeout=timeout, transport=_transport)
            if _transport
            else httpx.Client(timeout=timeout)
        )

    def enviar(self, promocao: Promocao) -> bool:
        """
        Envia a promoção formatada por texto. Retorna True com 2xx da
        Cloud API; 401 (token errado) e qualquer outro erro retornam False
        sem explodir — o chamador decide o que fazer (o cli.py, por
        exemplo, só reporta).
        """
        try:
            resposta = self._client.post(
                self._url,
                json={
                    "messaging_product": "whatsapp",
                    "to": self.destino,
                    "type": "text",
                    "text": {"body": formatar(promocao)},
                },
                headers={"Authorization": f"Bearer {self.token}"},
            )

            if 200 <= resposta.status_code < 300:
                logger.info(f"WhatsApp enviado — Tier {promocao.tier} | {promocao.tweet_url}")
                return True

            logger.error(
                f"WhatsApp API respondeu {resposta.status_code} — não enviado ({promocao.tweet_url})."
            )
            return False
        except Exception as e:
            logger.error(f"Falha ao enviar WhatsApp ({e}) — não enviado.")
            return False

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass
