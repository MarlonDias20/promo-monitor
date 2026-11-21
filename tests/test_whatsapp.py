"""
Testes do WhatsApp Cloud API (Meta Graph) — sender chamado pelo AGENTE
classificador (mesma forma do Telegram), sem rede: MockTransport valida
URL, headers e corpo. 401 não explode — retorna False.
"""
import json
from datetime import datetime

import httpx
import pytest

from database import Database
from whatsapp import WhatsAppNotifier, formatar
from worker import Tweet


def _promocao(db: Database, tier="S", **extras):
    tweet = Tweet(
        hash="h1",
        url="https://x.com/x/status/h1",
        conteudo="Bug! Notebook por R$0,01",
        perfil_origem="perfil",
        publicado_em=datetime.utcnow(),
    )
    base = {
        "tier": tier, "produto": "Notebook Lenovo", "categoria": "Informática",
        "loja": "Kabum", "desconto_estimado": 95.0, "preco_original": "R$ 3.999",
        "preco_promocional": "R$ 0,01", "urgencia": 10,
        "motivo": "Bug de preço absurdo",
    }
    base.update(extras)
    return db.salvar_promocao(tweet, base)


def _receptor(status=200, resposta=None):
    recebidos = []

    def handler(request):
        recebidos.append(request)
        return httpx.Response(status, json=resposta or {"messages": [{"id": "wamid.1"}]})

    return httpx.MockTransport(handler), recebidos


def test_envia_para_graph_com_bearer_e_corpo_da_cloud_api():
    db = Database("sqlite:///:memory:")
    promocao = _promocao(db)
    transport, recebidos = _receptor(200)

    notifier = WhatsAppNotifier(
        token="token-de-teste",
        phone_number_id="123456789",
        destino="5521999999999",
        _transport=transport,
    )
    assert notifier.enviar(promocao) is True

    pedido = recebidos[0]
    # URL oficial: graph.facebook.com/<versão>/<phone number id>/messages
    assert str(pedido.url) == "https://graph.facebook.com/v20.0/123456789/messages"
    assert pedido.headers["Authorization"] == "Bearer token-de-teste"

    corpo = json.loads(pedido.content)
    assert corpo["messaging_product"] == "whatsapp"
    assert corpo["to"] == "5521999999999"
    assert corpo["type"] == "text"
    assert set(corpo["text"]) == {"body"}


def test_texto_e_plano_com_emojis_e_espelha_o_notifier():
    db = Database("sqlite:///:memory:")
    promocao = _promocao(db)

    texto = formatar(promocao)
    # Cabeçalho por tier, produto, loja, preços, urgência, motivo, link, perfil.
    assert texto.startswith("🚨 BUG / OFERTA ABSURDA")
    assert "Notebook Lenovo" in texto
    assert "Kabum" in texto
    assert "R$ 3.999" in texto and "R$ 0,01" in texto
    assert "🔴" in texto
    assert "Bug de preço absurdo" in texto
    # Momento do tweet (fuso de Brasília) próximo do link — o helper cria
    # o tweet AGORA, então casamos o padrão (agora/há Xmin/h/d), sem fixar data.
    import re
    assert re.search(r"📅 \d{2}/\d{2}, \d{2}h\d{2} \((?:agora|há \d+(?:min|h|d))\)", texto)
    assert texto.index("📅") < texto.index("https://x.com/x/status/h1")
    assert "@perfil" in texto
    # Texto plano: sem markdown do Telegram.
    assert "*" not in texto and "_(" not in texto


def test_campos_ausentes_nao_viram_placeholder():
    db = Database("sqlite:///:memory:")
    promocao = _promocao(db, tier="A", produto=None, loja=None,
                         preco_original=None, preco_promocional=None,
                         desconto_estimado=None, urgencia=None, motivo=None)
    texto = formatar(promocao)
    assert "🛍" not in texto and "🏪" not in texto
    assert "💰" not in texto and "📉" not in texto and "💬" not in texto
    # Link e perfil sempre; o ⚡ do cabeçalho do tier A segue — é do tier.
    assert "https://x.com/x/status/h1" in texto and "@perfil" in texto
    assert texto.startswith("⚡ OFERTA RELÂMPAGO")

    # Sem publicado_em: a linha do momento também não aparece.
    from datetime import datetime as _dt
    promocao.publicado_em = None
    texto = formatar(promocao)
    assert "📅" not in texto
    # E com data volta a aparecer (mesma promoção, só o campo preenchido).
    promocao.publicado_em = _dt(2026, 11, 20, 23, 0)
    assert "📅 20/11, 20h00 (" in formatar(promocao)
    # Texto plano: sem o escape de MarkdownV2 do Telegram.
    assert "\\(há" not in formatar(promocao)


def test_erro_401_nao_explode_e_retorna_false():
    """Token errado: False silencioso — o chamador decide o que reportar."""
    db = Database("sqlite:///:memory:")
    promocao = _promocao(db)
    transport, _ = _receptor(401, resposta={"error": {"message": "token inválido"}})

    notifier = WhatsAppNotifier(
        token="token-errado", phone_number_id="1", destino="5521", _transport=transport
    )
    assert notifier.enviar(promocao) is False


def test_erro_500_tambem_retorna_false():
    db = Database("sqlite:///:memory:")
    promocao = _promocao(db)
    transport, _ = _receptor(500)

    notifier = WhatsAppNotifier(token="t", phone_number_id="1", destino="5521", _transport=transport)
    assert notifier.enviar(promocao) is False
