"""
Testes do tempo.py — o momento do tweet (fuso de Brasília + relativo curto)
numa função única para Telegram, WhatsApp e o espelho JS do site.
"""
from datetime import datetime, timezone

from tempo import (
    data_hora_brasilia,
    momento_notificacao,
    momento_tweet,
    relativo,
)

AGORA = datetime(2026, 11, 21, 2, 0, tzinfo=timezone.utc)


def _iso_utc(ano, mes, dia, hora, minuto):
    return datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc).isoformat()


def test_data_hora_no_fuso_de_brasilia():
    # 23:21 UTC de 20/11 = 20/11 às 20h21 em Brasília (UTC-3).
    assert data_hora_brasilia(_iso_utc(2026, 11, 20, 23, 21)) == "20/11 às 20h21"
    # Com outro separador, o formato das notificações.
    assert data_hora_brasilia(_iso_utc(2026, 11, 20, 23, 21), entre=", ") == "20/11, 20h21"


def test_relativo_curto():
    assert relativo(_iso_utc(2026, 11, 21, 2, 0), agora=AGORA) == "agora"
    assert relativo(_iso_utc(2026, 11, 21, 1, 44), agora=AGORA) == "há 16min"
    assert relativo(_iso_utc(2026, 11, 20, 23, 0), agora=AGORA) == "há 3h"
    assert relativo(_iso_utc(2026, 11, 18, 0, 0), agora=AGORA) == "há 3d"


def test_momento_do_site_formato_exato():
    momento = momento_tweet(_iso_utc(2026, 11, 20, 23, 0), agora=AGORA)
    assert momento == "20/11 às 20h00 · há 3h"
    # Minuto recente: 'agora' colado ao relativo.
    agora = momento_tweet(_iso_utc(2026, 11, 21, 1, 59), agora=AGORA)
    assert agora.endswith("· há 1min")


def test_momento_da_notificacao_formato_exato():
    momento = momento_notificacao(_iso_utc(2026, 11, 20, 23, 0), agora=AGORA)
    assert momento == "20/11, 20h00 (há 3h)"


def test_sem_publicado_em_tudo_devolve_none():
    assert data_hora_brasilia(None) is None
    assert relativo(None) is None
    assert momento_tweet(None) is None
    assert momento_notificacao(None) is None
    # Quem chama omite a linha — a conversão de vazio não explode.
    assert momento_tweet("") is None


def test_data_malformada_nao_explode_e_omite():
    assert data_hora_brasilia("não é data") is None
    assert momento_notificacao("20/11/2026 23h21") is None


def test_data_naiva_tratada_como_utc_do_feed():
    """O feed manda ISO com Z; sobra sem offset cai como UTC, sem crash."""
    assert data_hora_brasilia("2026-11-20T23:21:00").endswith("20h21")
