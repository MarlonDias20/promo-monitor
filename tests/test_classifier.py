"""
Testes do classificador — validação e fallback SEM rede, e classificação
real quando há uma API key no ambiente (skip senão).

Antes um script main() que pedia a key no stdin (PR de saúde): a validação
de resposta e o fallback são agora determinísticos; a chamada real à IA
fica marcada como integração opcional.
"""
import json

import pytest

from classifier import Classifier, SYSTEM_PROMPT


def test_validate_aceita_resposta_completa():
    clf = Classifier(api_key="key-de-teste")
    resultado = {
        "tier": "S",
        "produto": "Notebook Lenovo",
        "categoria": "Informática",
        "loja": "Kabum",
        "desconto_estimado": 95,
        "preco_original": "R$ 3.999",
        "preco_promocional": "R$ 0,01",
        "urgencia": 10,
        "motivo": "Bug de preço",
    }
    clf._validate(resultado)
    assert resultado["categoria"] == "Informática"


def test_validate_corrige_categoria_desconhecida():
    clf = Classifier(api_key="key-de-teste")
    resultado = {
        "tier": "B",
        "urgencia": 3,
        "motivo": "ok",
        "categoria": "Categoria Que Nao Existe",
    }
    clf._validate(resultado)
    assert resultado["categoria"] == "Outros"


def test_validate_rejeita_tier_invalido():
    clf = Classifier(api_key="key-de-teste")
    with pytest.raises(AssertionError):
        clf._validate({"tier": "X", "urgencia": 1, "motivo": "ok"})


def test_fallback_nao_bloqueia_o_fluxo():
    clf = Classifier(api_key="key-de-teste")
    fallback = clf._fallback("Erro na classificação: API fora do ar")
    assert fallback["tier"] == "N"
    assert fallback["urgencia"] == 0
    assert "Classificação falhou" in fallback["motivo"]


def test_classify_sem_conexao_cai_no_fallback():
    """
    Endereço local fechado (porta 9, discard) falha na hora: a chamada
    quebra e o classificador devolve tier N — o pipeline nunca quebra por
    causa da IA, e sem pendurar a fila por timeouts longos.
    """
    clf = Classifier(api_key="key-invalida", base_url="http://127.0.0.1:9/v1", timeout=2, max_retries=0)
    resultado = clf.classify("Bug de preço! Notebook por R$0,01!")
    assert resultado["tier"] == "N"
    assert resultado["motivo"].startswith("Classificação falhou")


def test_prompt_pede_somente_json():
    assert "JSON" in SYSTEM_PROMPT
    assert "tier" in SYSTEM_PROMPT
    # Categorias do prompt batem com as validadas.
    for categoria in Classifier.CATEGORIAS_VALIDAS:
        assert f'"{categoria}"' in SYSTEM_PROMPT


@pytest.mark.skipif(
    not __import__("os").environ.get("ZAI_API_KEY"),
    reason="requer ZAI_API_KEY — integração opcional com a IA",
)
def test_classificacao_real_marca_promocao_e_trailer():
    clf = Classifier(api_key=__import__("os").environ["ZAI_API_KEY"])
    bug = clf.classify(
        "🚨 BUG DE PREÇO! Notebook Lenovo IdeaPad saindo por R$0,01 na Kabum! "
        "Corre antes de corrigirem!"
    )
    assert bug["tier"] == "S"
    assert bug["urgencia"] >= 8

    trailer = clf.classify("Saiu o novo trailer do iPhone 17! O que acharam do design?")
    assert trailer["tier"] == "N"
