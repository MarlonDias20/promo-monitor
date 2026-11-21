"""
Testes do banco de dados — valida inserção, deduplicação e queries.
SQLite em memória: sem efeito colateral e determinístico.

Antes um script main() (PR de saúde): mesmas validações, agora pytest.
"""
from datetime import datetime
from dataclasses import dataclass

from database import Database


@dataclass
class TweetFake:
    hash: str
    url: str
    conteudo: str
    perfil_origem: str
    publicado_em: datetime


CLASSIFICACAO_S = {
    "tier": "S",
    "produto": "Notebook Lenovo",
    "loja": "Kabum",
    "desconto_estimado": 95.0,
    "preco_original": "R$ 3.999",
    "preco_promocional": "R$ 0,01",
    "urgencia": 10,
    "motivo": "Bug de preço absurdo — produto saindo por R$0,01",
}

CLASSIFICACAO_A = {
    "tier": "A",
    "produto": "iPhone 14",
    "loja": "Amazon",
    "desconto_estimado": 45.0,
    "preco_original": "R$ 3.999",
    "preco_promocional": "R$ 2.199",
    "urgencia": 7,
    "motivo": "Desconto significativo em produto de alta demanda",
}

CLASSIFICACAO_N = {
    "tier": "N",
    "produto": None,
    "loja": None,
    "desconto_estimado": None,
    "preco_original": None,
    "preco_promocional": None,
    "urgencia": 0,
    "motivo": "Não é uma promoção",
}


def test_insere_promocoes_e_deduplica():
    db = Database("sqlite:///:memory:")

    t1 = TweetFake("abc111", "https://x.com/1", "Bug! Notebook por R$0,01!", "opromocionista", datetime.utcnow())
    t2 = TweetFake("abc222", "https://x.com/2", "iPhone 14 com 45% OFF!", "pelando", datetime.utcnow())
    t3 = TweetFake("abc333", "https://x.com/3", "Novo trailer do iPhone 17", "opromocionista", datetime.utcnow())

    p1 = db.salvar_promocao(t1, CLASSIFICACAO_S)
    p2 = db.salvar_promocao(t2, CLASSIFICACAO_A)
    p3 = db.salvar_promocao(t3, CLASSIFICACAO_N)
    assert p1 is not None and p2 is not None and p3 is not None

    # Deduplicação por hash — mesma inserção retorna None.
    assert db.salvar_promocao(t1, CLASSIFICACAO_S) is None


def test_stats_contam_por_tier():
    db = Database("sqlite:///:memory:")
    db.salvar_promocao(TweetFake("h1", "https://x.com/1", "Bug!", "a", datetime.utcnow()), CLASSIFICACAO_S)
    db.salvar_promocao(TweetFake("h2", "https://x.com/2", "Oferta!", "b", datetime.utcnow()), CLASSIFICACAO_A)
    db.salvar_promocao(TweetFake("h3", "https://x.com/3", "Trailer", "c", datetime.utcnow()), CLASSIFICACAO_N)

    s = db.stats()
    assert s["total"] == 3
    assert s["por_tier"]["S"] == 1
    assert s["por_tier"]["A"] == 1
    assert s["por_tier"]["N"] == 1
    assert s["notificadas"] == 0
    assert s["pendentes"] == 3


def test_pendentes_e_marcar_notificado():
    db = Database("sqlite:///:memory:")
    p1 = db.salvar_promocao(TweetFake("h1", "https://x.com/1", "Bug!", "a", datetime.utcnow()), CLASSIFICACAO_S)
    p2 = db.salvar_promocao(TweetFake("h2", "https://x.com/2", "Oferta!", "b", datetime.utcnow()), CLASSIFICACAO_A)
    db.salvar_promocao(TweetFake("h3", "https://x.com/3", "Trailer", "c", datetime.utcnow()), CLASSIFICACAO_N)

    pendentes = db.buscar_pendentes_notificacao({"S", "A"})
    assert len(pendentes) == 2
    # Urgência maior primeiro — a ordem da fila de notificação.
    assert pendentes[0].id == p1.id

    db.marcar_notificado(p1.id)
    db.marcar_notificado(p2.id)
    assert len(db.buscar_pendentes_notificacao({"S", "A"})) == 0


def test_listar_hashes_para_sync_do_worker():
    db = Database("sqlite:///:memory:")
    db.salvar_promocao(TweetFake("abc111", "https://x.com/1", "Bug!", "a", datetime.utcnow()), CLASSIFICACAO_S)
    db.salvar_promocao(TweetFake("abc222", "https://x.com/2", "Oferta!", "b", datetime.utcnow()), CLASSIFICACAO_A)
    db.salvar_promocao(TweetFake("abc333", "https://x.com/3", "Trailer", "c", datetime.utcnow()), CLASSIFICACAO_N)

    assert set(db.listar_hashes()) == {"abc111", "abc222", "abc333"}


def test_sincronizar_perfis_nao_duplica():
    db = Database("sqlite:///:memory:")
    db.sincronizar_perfis(["opromocionista", "pelando", "desconto_e_oferta"])
    db.sincronizar_perfis(["opromocionista"])
    db.sincronizar_perfis(["opromocionista", "pelando"])
    # Idempotente: re-sincronizar não duplica nem cria novos.
    with db._Session() as s:
        assert s.query(__import__("database").PerfilMonitorado).count() == 3


def test_excluir_antigos_limpa_registros_velhos():
    db = Database("sqlite:///:memory:")
    db.salvar_promocao(TweetFake("h1", "https://x.com/1", "Bug!", "a", datetime.utcnow()), CLASSIFICACAO_S)

    # Puxa criado_em para 10 dias atrás e roda a limpeza de 7 dias.
    from database import Promocao
    with db._session() as s:
        s.query(Promocao).update({"criado_em": datetime.utcnow() - __import__("datetime").timedelta(days=10)})

    assert db.excluir_antigos(dias=7) == 1
    assert db.stats()["total"] == 0
