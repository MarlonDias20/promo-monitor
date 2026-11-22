"""
Testes do dedup de produto — perfis repetem promoções uns dos outros e o
Marlon não quer receber duas vezes: promo cujo produto/loja já foi
notificado dentro da janela é marcada e NÃO reenviada. A checagem é SQL
local (zero custo de IA); lojas distintas são promoções válidas.
"""
import io
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta

import config
from cli import cmd_notificar
from database import Database


@dataclass
class TweetFake:
    hash: str
    url: str
    conteudo: str
    perfil_origem: str
    publicado_em: datetime


def _tweet(h: str, perfil: str = "p1", horas_atras: float = 1.0) -> TweetFake:
    return TweetFake(
        hash=h,
        url=f"https://x.com/{perfil}/status/{h}",
        conteudo=f"promo {h}",
        perfil_origem=perfil,
        publicado_em=datetime.utcnow() - timedelta(hours=horas_atras),
    )


def _classificar(db, h: str, perfil: str = "p1", produto="Notebook Lenovo", loja="Kabum", horas=1.0):
    db.salvar_promocao_pendente(_tweet(h, perfil, horas))
    return db.aplicar_classificacao(h, {
        "tier": "A",
        "produto": produto,
        "loja": loja,
        "desconto_estimado": 50.0,
        "preco_original": "R$ 100",
        "preco_promocional": "R$ 50",
        "urgencia": 7,
        "motivo": "teste",
    })


def test_duplicata_recente_e_encontrada():
    db = Database("sqlite:///:memory:")
    original = _classificar(db, "h1", perfil="p1")
    db.marcar_notificado(original.id)

    repetida = _classificar(db, "h2", perfil="p2")
    achou = db.buscar_duplicata_recente(repetida, janela_horas=24)
    assert achou is not None and achou.tweet_hash == "h1"


def test_loja_diferente_nao_e_duplicata():
    db = Database("sqlite:///:memory:")
    original = _classificar(db, "h1", perfil="p1", loja="Kabum")
    db.marcar_notificado(original.id)

    outra_loja = _classificar(db, "h2", perfil="p2", loja="Amazon")
    assert db.buscar_duplicata_recente(outra_loja, janela_horas=24) is None


def test_loja_ausente_compara_so_o_produto():
    db = Database("sqlite:///:memory:")
    original = _classificar(db, "h1", perfil="p1", loja=None)
    db.marcar_notificado(original.id)

    sem_loja = _classificar(db, "h2", perfil="p2", loja=None)
    assert db.buscar_duplicata_recente(sem_loja, janela_horas=24) is not None


def test_produto_nulo_e_janela_zero_nunca_bloqueiam():
    db = Database("sqlite:///:memory:")
    original = _classificar(db, "h1", perfil="p1", produto=None)
    db.marcar_notificado(original.id)

    sem_produto = _classificar(db, "h2", perfil="p2", produto=None)
    assert db.buscar_duplicata_recente(sem_produto, janela_horas=24) is None

    igual = _classificar(db, "h3", perfil="p2")
    assert db.buscar_duplicata_recente(igual, janela_horas=0) is None


def test_fora_da_janela_nao_e_duplicata():
    db = Database("sqlite:///:memory:")
    original = _classificar(db, "h1", perfil="p1", horas=30.0)
    db.marcar_notificado(original.id)

    recente = _classificar(db, "h2", perfil="p2", horas=1.0)
    assert db.buscar_duplicata_recente(recente, janela_horas=24) is None


def test_notificar_pula_duplicata_e_marca(tmp_path, monkeypatch):
    caminho = tmp_path / "dedup.db"
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{caminho}")
    monkeypatch.setattr(config, "DEDUP_JANELA_HORAS", 24.0)

    db = Database(config.DATABASE_URL)
    original = _classificar(db, "h1", perfil="p1")
    db.marcar_notificado(original.id)
    _classificar(db, "h2", perfil="p2")

    saida = io.StringIO()
    with redirect_stdout(saida):
        codigo = cmd_notificar(["h2", "--canal", "telegram"])
    assert codigo == 0
    assert "PULADA" in saida.getvalue()
    assert "@p1" in saida.getvalue()

    with db._Session() as s:
        marcada = s.query(__import__("database").Promocao).filter_by(tweet_hash="h2").one()
    assert marcada.duplicata is True and marcada.notificado is True


def test_listar_recentes_leva_duplicata(tmp_path):
    db = Database("sqlite:///:memory:")
    original = _classificar(db, "h1")
    db.marcar_notificado(original.id)
    repetida = _classificar(db, "h2", perfil="p2")
    db.marcar_duplicata(repetida.id)

    por_perfil = {p["perfil_origem"]: p for p in db.listar_recentes(10)}
    assert por_perfil["p2"]["duplicata"] is True
    assert por_perfil["p1"]["duplicata"] is False


def test_duplicata_candidata_sem_notificado_ainda_conta():
    """Regressão do perfume 212: a primeira promo estava classificada S/A
    mas com notificado=0 quando a segunda consultou — candidata S/A dentro
    da janela vale mesmo sem o registro de envio."""
    db = Database("sqlite:///:memory:")
    _classificar(db, "h1", perfil="p1", loja=None)  # sem marcar_notificado

    repetida = _classificar(db, "h2", perfil="p2", loja="Mercado Livre")
    achou = db.buscar_duplicata_recente(repetida, janela_horas=24)
    assert achou is not None and achou.tweet_hash == "h1"
