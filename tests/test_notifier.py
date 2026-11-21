"""
Testes da formatação do Telegram — a referência de texto do agente, com o
momento do tweet (fuso de Brasília) próximo do link, sem rede.
"""
from datetime import datetime

from database import Database
from notifier import TelegramNotifier
from worker import Tweet


def _promocao(db: Database, publicado_em=datetime(2026, 11, 20, 23, 0)):
    # datetime é imutável: None explícito passa None de verdade.
    tweet = Tweet(
        hash="h1",
        url="https://x.com/x/status/h1",
        conteudo="Bug! Notebook por R$0,01",
        perfil_origem="perfil",
        publicado_em=publicado_em,
    )
    return db.salvar_promocao(tweet, {
        "tier": "S", "produto": "Notebook Lenovo", "categoria": "Informática",
        "loja": "Kabum", "desconto_estimado": 95.0, "preco_original": "R$ 3.999",
        "preco_promocional": "R$ 0,01", "urgencia": 10, "motivo": "Bug de preço",
    })


def test_linha_do_momento_proximo_do_link_com_escape():
    db = Database("sqlite:///:memory:")
    p = _promocao(db)
    notifier = TelegramNotifier(token="t", chat_id="c")
    texto = notifier._formatar(p)

    # Momento em Brasília (20/11 23h00 UTC = 20h00 BRT), entre o motivo e
    # o link — o relativo segue a hora real, então casamos por padrão.
    import re
    assert re.search(r"📅 20/11, 20h00 \\\(há \d+(?:min|h|d)\\\)", texto)
    assert texto.index("📅") < texto.index("🔗")


def test_sem_publicado_em_omite_a_linha():
    db = Database("sqlite:///:memory:")
    p = _promocao(db, publicado_em=None)
    notifier = TelegramNotifier(token="t", chat_id="c")
    texto = notifier._formatar(p)
    assert "📅" not in texto
    assert "🔗" in texto  # o link segue
