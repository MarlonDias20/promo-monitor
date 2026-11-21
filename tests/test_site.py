"""
Testes do site estático — a página da spec de UI sem browser:
segurança (renderização só via textContent — nunca innerHTML), textos
P1–P37 e as 16 categorias com os nomes exatos.
"""
import os

SITE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site", "index.html")

CATEGORIAS = [
    "Eletrônicos", "Smartphones", "Informática", "Games", "Eletrodomésticos",
    "Moda e Vestuário", "Beleza e Perfumaria", "Saúde e Bem-estar",
    "Alimentos e Bebidas", "Livros e Cursos", "Casa e Decoração",
    "Brinquedos", "Esporte e Lazer", "Serviços e Assinaturas", "Viagens", "Outros",
]

TEXTOS_OBRIGATORIOS = [
    "Promoções Monitor",                                     # P1
    "Promoções publicadas por perfis de achados no X",        # P2
    "O que significam os tiers?",                             # P3
    "S · bug de preço",                                       # P4
    "A · muito boa",                                          # P5
    "B · comum",                                              # P6
    "N · não é promoção",                                     # P7
    "Mostrar tweet",                                          # P20
    "Ocultar",                                                # P21
    "Buscar produto, loja ou cupom…",                         # P22
    "Promoções",                                              # P23 (chip padrão)
    "Categoria — todas as categorias",                        # P24
    "Perfil — todos os perfis",                               # P25
    "mais recentes",                                           # P26
    "Carregando promoções…",                                  # P31
    "Sem promoções no momento. O monitor atualiza sozinho — volte mais tarde.",  # P29
    "Nenhuma promoção com esses filtros.",                    # P30
    "Não foi possível carregar as promoções agora.",          # P32
    "Tentar de novo",                                         # P33
    "Dados coletados de perfis públicos do X. Sem cadastro, sem cookies.",  # P34
    "Promoções expiram rápido — confira sempre no tweet antes de comprar.",  # P35
    "A lista cobre os últimos 7 dias.",                        # P36
    "Promoções Monitor — achados de promoção triados por urgência",           # P37
    "Ver tweet",                                              # P18
    "lang=\"pt-BR\"",
]

# Caminhos que viram dados do feed em HTML executável — proibidos.
PADROES_PROIBIDOS = [
    "innerHTML",
    "insertAdjacentHTML",
    "document.write",
    "outerHTML",
    "eval(",
    "new Function",
    "dangerouslySetInnerHTML",
]


def _pagina() -> str:
    with open(SITE, encoding="utf-8") as f:
        return f.read()


def test_pagina_existe_e_e_leve():
    conteudo = _pagina()
    assert len(conteudo.encode("utf-8")) <= 50 * 1024, "página deve ficar em ~50 KB fora o JSON"


def test_renderizacao_somente_com_textcontent():
    """
    Segurança da spec: conteúdo de tweet NUNCA vira HTML. A página não pode
    conter nenhum caminho que interprete string como HTML.
    """
    conteudo = _pagina()
    for padrao in PADROES_PROIBIDOS:
        assert padrao not in conteudo, f"'{padrao}' é proibido: dados do tweet virariam HTML"
    # O caminho de renderização existe e é o seguro.
    assert "createTextNode" in conteudo
    assert "textContent" in conteudo or "createTextNode" in conteudo


def test_textos_da_spec_estao_presentes():
    conteudo = _pagina()
    for texto in TEXTOS_OBRIGATORIOS:
        assert texto in conteudo, f"texto da spec ausente: {texto!r}"


def test_categorias_com_os_16_nomes_exatos():
    conteudo = _pagina()
    for categoria in CATEGORIAS:
        assert f'"{categoria}"' in conteudo, f"categoria ausente no select: {categoria}"


def test_sem_cookies_e_sem_armazenamento_local():
    conteudo = _pagina()
    assert "localStorage" not in conteudo
    assert "sessionStorage" not in conteudo
    assert "document.cookie" not in conteudo


def test_filtros_e_ordenacao_da_spec_existem():
    conteudo = _pagina()
    for trecho in ('data-filtro="promocoes"', 'id="categoria"', 'id="perfil"', 'id="ordenar"', 'aria-pressed'):
        assert trecho in conteudo
