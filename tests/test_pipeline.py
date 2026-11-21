"""
Testes do pipeline — desenho do classificador-agente:
tweet novo → tier P no banco → webhook assinado do OpenBot
(x-openbot-timestamp/delivery-id/signature HMAC-SHA256) → retentativa no
ciclo → classificação aplicada (o agente chama db.aplicar_classificacao).
Tudo com receptor fake: determinístico, sem rede.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta

import httpx
import pytest

import webhook
from database import Database
from worker import Tweet


def _tweet(h: str, conteudo="Bug! Notebook por R$0,01") -> Tweet:
    return Tweet(hash=h, url=f"https://x.com/x/status/{h}", conteudo=conteudo,
                 perfil_origem="perfil", publicado_em=datetime.utcnow())


CLASSIFICACAO_S = {
    "tier": "S", "produto": "Notebook", "categoria": "Informática",
    "loja": "Kabum", "desconto_estimado": 95.0, "preco_original": "R$ 3.999",
    "preco_promocional": "R$ 0,01", "urgencia": 10, "motivo": "Bug de preço",
}


@pytest.fixture
def db():
    return Database("sqlite:///:memory:")


# ------------------------------------------------------------------
# Banco: pendência e caminho de volta
# ------------------------------------------------------------------

def test_tweet_novo_fica_pendente(db):
    promocao = db.salvar_promocao_pendente(_tweet("h1"))
    assert promocao is not None
    assert promocao.tier == "P"
    # Duplicata não regrava.
    assert db.salvar_promocao_pendente(_tweet("h1")) is None


def test_pendentes_buscam_nao_disparados_ou_receptores_mutos(db):
    p1 = db.salvar_promocao_pendente(_tweet("h1"))

    # Nunca disparado: sempre pendente.
    pendentes = db.buscar_pendentes_webhook()
    assert [p.id for p in pendentes] == [p1.id]

    # Disparado agora: sai da fila de retentativa imediata.
    db.marcar_webhook_disparado(p1.id)
    assert db.buscar_pendentes_webhook(tentar_novamente_apos=timedelta(seconds=60)) == []

    # Sem resposta há mais de um ciclo: volta para retentativa.
    with db._session() as s:
        from database import Promocao
        s.query(Promocao).filter(Promocao.id == p1.id).update(
            {"webhook_disparado_em": datetime.utcnow() - timedelta(seconds=120)}
        )
    assert len(db.buscar_pendentes_webhook(tentar_novamente_apos=timedelta(seconds=60))) == 1


def test_aplicar_classificacao_tira_da_pendencia(db):
    p = db.salvar_promocao_pendente(_tweet("h1"))
    db.marcar_webhook_disparado(p.id)

    aplicado = db.aplicar_classificacao("h1", CLASSIFICACAO_S)
    assert aplicado is not None
    assert aplicado.tier == "S"
    assert aplicado.produto == "Notebook"
    assert aplicado.urgencia == 10
    # Nada mais pendente.
    assert db.buscar_pendentes_webhook() == []
    # Feed já mostra a classificação.
    recentes = db.listar_recentes(10)
    assert recentes[0]["tier"] == "S"


def test_aplicar_classificacao_rejeita_tier_invalido_e_hash_desconhecido(db):
    db.salvar_promocao_pendente(_tweet("h1"))
    assert db.aplicar_classificacao("h1", {**CLASSIFICACAO_S, "tier": "X"}) is None
    # Continua pendente — nada gravado.
    assert len(db.buscar_pendentes_webhook()) == 1
    assert db.aplicar_classificacao("inexistente", CLASSIFICACAO_S) is None


def test_aplicar_classificacao_corrige_categoria_fora_da_lista(db):
    db.salvar_promocao_pendente(_tweet("h1"))
    aplicado = db.aplicar_classificacao("h1", {**CLASSIFICACAO_S, "categoria": "Coisa Nova"})
    assert aplicado.categoria == "Outros"


# ------------------------------------------------------------------
# Webhook: assinatura HMAC-SHA256 do contrato OpenBot
# ------------------------------------------------------------------

def _receptor(status=202):
    recebidos = []

    def handler(request):
        recebidos.append(request)
        return httpx.Response(status)

    return httpx.MockTransport(handler), recebidos


def test_payload_tem_type_occurredat_e_data_do_tweet(db):
    p = db.salvar_promocao_pendente(_tweet("h1"))
    payload = webhook.payload_do_tweet(p)
    assert payload["type"] == "promocao"
    assert "occurredAt" in payload and payload["occurredAt"].endswith("Z")
    assert set(payload["data"]) == {"hash", "url", "conteudo", "perfil", "publicado_em"}
    assert payload["data"]["hash"] == "h1"


def test_webhook_aceito_202_com_assinatura_valida(db):
    p = db.salvar_promocao_pendente(_tweet("h1"))
    transport, recebidos = _receptor(202)

    resultado = webhook.disparar(
        webhook.WEBHOOK_PROMOCOES,
        "segredo-de-teste",
        webhook.payload_do_tweet(p),
        delivery_id=p.tweet_hash,
        _transport=transport,
    )
    assert resultado is webhook.ResultadoDisparo.ACEITO

    pedido = recebidos[0]
    timestamp = pedido.headers["x-openbot-timestamp"]
    assert timestamp.isdigit()  # Unix em segundos
    assert pedido.headers["x-openbot-delivery-id"] == "h1"  # hash do tweet

    # Assinatura conferida contra o corpo EXATO trafegado.
    corpo = pedido.content
    esperada = f"sha256={hmac.new(b'segredo-de-teste', f'{timestamp}.h1.'.encode() + corpo, hashlib.sha256).hexdigest()}"
    assert pedido.headers["x-openbot-signature"] == esperada

    # Corpo: contrato {"type","occurredAt","data"}.
    json.loads(corpo)


def test_webhook_401_assinatura_errada_retenta(db):
    """401: assinatura/horário errado — NÃO marca, ciclo seguinte re-dispara."""
    p = db.salvar_promocao_pendente(_tweet("h1"))
    transport, _ = _receptor(401)
    resultado = webhook.disparar(
        webhook.WEBHOOK_PROMOCOES, "segredo", webhook.payload_do_tweet(p),
        delivery_id=p.tweet_hash, _transport=transport,
    )
    assert resultado is webhook.ResultadoDisparo.RETENTAR


def test_webhook_503_host_ocupado_retenta(db):
    p = db.salvar_promocao_pendente(_tweet("h1"))
    transport, _ = _receptor(503)
    resultado = webhook.disparar(
        webhook.WEBHOOK_PROMOCOES, "segredo", webhook.payload_do_tweet(p),
        delivery_id=p.tweet_hash, _transport=transport,
    )
    assert resultado is webhook.ResultadoDisparo.RETENTAR


def test_webhook_400_corpo_invalido_descarta(db):
    """400: corpo inválido — descartado, sem re-tentativa."""
    p = db.salvar_promocao_pendente(_tweet("h1"))
    transport, _ = _receptor(400)
    resultado = webhook.disparar(
        webhook.WEBHOOK_PROMOCOES, "segredo", webhook.payload_do_tweet(p),
        delivery_id=p.tweet_hash, _transport=transport,
    )
    assert resultado is webhook.ResultadoDisparo.DESCARTAR


def test_webhook_sem_conexao_retenta():
    """Receptor fora (conexão recusada): item continua pendente p/ retentativa."""
    resultado = webhook.disparar(
        "http://127.0.0.1:9/hook", "segredo", {"type": "promocao"},
        delivery_id="h1", timeout=1,
    )
    assert resultado is webhook.ResultadoDisparo.RETENTAR


def test_corpo_acima_do_limite_descarta_sem_disparo():
    resultado = webhook.disparar(
        webhook.WEBHOOK_PROMOCOES, "segredo",
        {"type": "promocao", "data": {"conteudo": "x" * (64 * 1024)}},
        delivery_id="h1", _transport=_receptor(202)[0],
    )
    assert resultado is webhook.ResultadoDisparo.DESCARTAR
