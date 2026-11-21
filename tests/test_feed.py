"""
Testes do feed do site — promos.json conforme a spec de UI (seção 8):
`gerado_em` no topo, `promocoes[]` com campos snake_case espelhando as
colunas do banco, null quando ausente, e `conteudo` incluído (o card
recolhe o tweet em 3 linhas — sempre texto, nunca HTML).
"""
import json
import os
from datetime import datetime

from database import Database
from feed import ExportadorPromos
from worker import Tweet


def _tweet(h: str, conteudo="Bug!"):
    return Tweet(hash=h, url=f"https://x.com/x/status/{h}", conteudo=conteudo,
                 perfil_origem="perfil", publicado_em=datetime.utcnow())


def _classificacao(tier="S", **extras):
    base = {
        "tier": tier, "produto": "Notebook", "categoria": "Informática",
        "loja": "Kabum", "desconto_estimado": 95.0, "preco_original": "R$ 3.999",
        "preco_promocional": "R$ 0,01", "urgencia": 10, "motivo": "Bug de preço",
    }
    base.update(extras)
    return base


CAMPOS_DO_CONTRATO = {
    "id", "tier", "produto", "categoria", "loja", "desconto_estimado",
    "preco_original", "preco_promocional", "urgencia", "motivo",
    "perfil_origem", "tweet_url", "conteudo", "publicado_em", "criado_em",
}


def test_exporta_campos_snake_case_do_contrato(tmp_path):
    db = Database("sqlite:///:memory:")
    db.salvar_promocao(_tweet("h1"), _classificacao("S"))
    db.salvar_promocao(_tweet("h2"), _classificacao("A"))

    caminho = str(tmp_path / "site" / "promos.json")
    assert ExportadorPromos(caminho).exportar(db) == 2

    payload = json.load(open(caminho, encoding="utf-8"))
    # gerado_em obrigatório no topo (alimenta o "Atualizado em …").
    assert "gerado_em" in payload and payload["gerado_em"]
    assert payload["total"] == 2

    p = payload["promocoes"][0]
    assert set(p) == CAMPOS_DO_CONTRATO
    assert p["perfil_origem"] == "perfil"
    assert p["tweet_url"].startswith("https://x.com/")
    assert p["desconto_estimado"] == 95.0
    # O tweet viaja no feed — o card recolhe em 3 linhas no navegador.
    assert p["conteudo"] == "Bug!"


def test_campos_ausentes_veem_null_nunca_string_vazia(tmp_path):
    db = Database("sqlite:///:memory:")
    db.salvar_promocao(_tweet("h1"), {
        "tier": "N", "produto": None, "categoria": "Outros", "loja": None,
        "desconto_estimado": None, "preco_original": None,
        "preco_promocional": None, "urgencia": None, "motivo": None,
    })

    caminho = str(tmp_path / "promos.json")
    ExportadorPromos(caminho).exportar(db)
    p = json.load(open(caminho, encoding="utf-8"))["promocoes"][0]
    for campo in ("produto", "loja", "desconto_estimado", "preco_original",
                  "preco_promocional", "urgencia", "motivo"):
        assert p[campo] is None, f"{campo} deveria ser null"


def test_pendentes_aparecem_no_feed_para_o_estado_analisando(tmp_path):
    db = Database("sqlite:///:memory:")
    db.salvar_promocao_pendente(_tweet("hp"))
    db.salvar_promocao(_tweet("h1"), _classificacao("S"))

    caminho = str(tmp_path / "promos.json")
    ExportadorPromos(caminho).exportar(db)
    promocoes = json.load(open(caminho, encoding="utf-8"))["promocoes"]
    tiers = [p["tier"] for p in promocoes]
    assert "P" in tiers and "S" in tiers


def test_exporta_no_maximo_o_limite(tmp_path):
    db = Database("sqlite:///:memory:")
    for i in range(8):
        db.salvar_promocao(_tweet(f"h{i:02d}"), _classificacao())

    caminho = str(tmp_path / "promos.json")
    assert ExportadorPromos(caminho, limite=5).exportar(db) == 5
    assert len(json.load(open(caminho, encoding="utf-8"))["promocoes"]) == 5


def test_mais_recentes_primeiro_e_escrita_atomica(tmp_path):
    db = Database("sqlite:///:memory:")
    db.salvar_promocao(_tweet("h1"), _classificacao())
    db.salvar_promocao(_tweet("h2"), _classificacao("A"))

    caminho = str(tmp_path / "promos.json")
    ExportadorPromos(caminho).exportar(db)
    promocoes = json.load(open(caminho, encoding="utf-8"))["promocoes"]
    assert promocoes[0]["tweet_url"].endswith("h2")
    assert not os.path.exists(caminho + ".tmp")


def test_tweet_com_tentativa_de_xss_viaja_como_texto(tmp_path):
    """
    O conteúdo do tweet não é confiável: um tweet com <img onerror> entra
    no feed como string — quem renderiza é a página, sempre via
    textContent (verificado no test_site). Aqui garantimos que o export
    não corrompe nem escapa o texto: ele viaja exatamente como veio.
    """
    db = Database("sqlite:///:memory:")
    xss = 'Bug! <img src=x onerror="alert(1)"><script>alert(2)</script>'
    db.salvar_promocao(_tweet("hx", conteudo=xss), _classificacao())

    caminho = str(tmp_path / "promos.json")
    ExportadorPromos(caminho).exportar(db)
    p = json.load(open(caminho, encoding="utf-8"))["promocoes"][0]
    assert p["conteudo"] == xss  # string pura, nada executável no JSON


def test_exportador_desligado_retorna_none(tmp_path):
    db = Database("sqlite:///:memory:")
    assert ExportadorPromos(None).exportar(db) is None
    assert not os.path.exists(tmp_path / "promos.json")
