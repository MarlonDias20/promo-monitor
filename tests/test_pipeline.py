"""
Testes do pipeline — desenho do classificador-agente:
tweet novo → tier P no banco → webhook assinado → retentativa no ciclo →
classificação aplicada (o agente chama db.aplicar_classificacao).
Tudo com receptor fake: determinístico, sem rede.
"""
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


def test_webhook_dispara_com_segredo_no_header():
    """POST assinado: o receptor confere X-Secret antes de processar."""
    recebidos = []

    def handler(request):
        recebidos.append(request)
        return httpx.Response(202)

    ok = webhook.disparar(
        "http://receptor.test/hook",
        "segredo-de-teste",
        {"hash": "h1", "url": "https://x.com/1", "conteudo": "Bug!", "perfil": "p"},
        _transport=httpx.MockTransport(handler),
    )
    assert ok
    assert recebidos[0].headers["X-Secret"] == "segredo-de-teste"
    corpo = __import__("json").loads(recebidos[0].content)
    assert corpo == {"hash": "h1", "url": "https://x.com/1", "conteudo": "Bug!", "perfil": "p"}


def test_webhook_sem_resposta_retorna_false_e_segue_pendente():
    """Receptor fora (conexão recusada): item continua pendente p/ retentativa."""
    ok = webhook.disparar("http://127.0.0.1:9/hook", "segredo", {"hash": "h1"}, timeout=1)
    assert not ok


def test_payload_do_tweet_nao_carrega_dados_do_banco(db):
    p = db.salvar_promocao_pendente(_tweet("h1"))
    payload = webhook.payload_do_tweet(p)
    assert set(payload) == {"hash", "url", "conteudo", "perfil", "publicado_em"}
    assert payload["hash"] == "h1"
