"""
Testes do worker RSS — coleta, parse e deduplicação com RSS mockado
(httpx.MockTransport): determinístico, sem depender do Nitter estar no ar.
O health check de instâncias segue sendo utilidade pública, testada via
mock também.

Antes um script main() que fazia fetch real e sys.exit(1) quando vinho
vazio (PR de saúde): mesmas validações, agora em pytest.
"""
import pytest

from worker import RSSWorker

RSS_PERFIL = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>@perfildeteste</title>
    <item>
      <title>BUG DE PREÇO! Notebook por R$0,01 na Kabum</title>
      <link>https://x.com/perfildeteste/status/111</link>
      <description>BUG DE PREÇO! Notebook por R$0,01 na Kabum</description>
      <pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Cupom 10% OFF em tudo</title>
      <link>https://x.com/perfildeteste/status/222</link>
      <description>&lt;b&gt;Cupom&lt;/b&gt; PROMO10 dá 10% em tudo &lt;br/&gt; corre</description>
      <pubDate>Fri, 20 Nov 2026 10:05:00 GMT</pubDate>
    </item>
    <item>
      <title>RT @outro: oferta</title>
      <link>https://x.com/perfildeteste/status/333</link>
      <description>RT @outro: oferta retuitada</description>
      <pubDate>Fri, 20 Nov 2026 10:10:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def _transport(resposta_por_host: dict[str, object]):
    """MockTransport que responde por host: {host: texto_ou_status}."""
    import httpx

    def handler(request):
        host = request.url.host
        if host in resposta_por_host:
            corpo = resposta_por_host[host]
            if isinstance(corpo, int):
                return httpx.Response(corpo)
            return httpx.Response(200, text=corpo)
        return httpx.Response(503)

    return httpx.MockTransport(handler)


def _worker_com(rss: str, host: str = "nitter.test") -> RSSWorker:
    import httpx

    worker = RSSWorker(perfis=["@perfildeteste"], instancias=[f"https://{host}"])
    worker._client.close()
    worker._client = httpx.Client(
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 (compatible; RSS reader)"},
        follow_redirects=True,
        transport=_transport({host: rss}),
    )
    return worker


def test_fetch_coleta_tweets_e_ignora_retweets():
    worker = _worker_com(RSS_PERFIL)
    tweets = worker.fetch_new_tweets()

    assert len(tweets) == 2  # o RT é descartado
    textos = " | ".join(t.conteudo for t in tweets)
    assert "BUG DE PREÇO" in textos
    assert "PROMO10" in textos
    # HTML do summary sai limpo.
    assert "<b>" not in textos and "&lt;" not in textos


def test_deduplicacao_segundo_fetch_nao_traz_nada():
    worker = _worker_com(RSS_PERFIL)
    assert len(worker.fetch_new_tweets()) == 2
    assert len(worker.fetch_new_tweets()) == 0


def test_urls_e_perfis_corretos():
    worker = _worker_com(RSS_PERFIL)
    tweets = worker.fetch_new_tweets()
    assert all(t.url.startswith("https://x.com/") for t in tweets)
    assert all(t.perfil_origem == "perfildeteste" for t in tweets)
    assert all(len(t.hash) == 32 for t in tweets)  # MD5


def test_hash_do_mesmo_conteudo_eh_igual():
    worker = _worker_com(RSS_PERFIL)
    t1, t2 = worker.fetch_new_tweets()
    assert t1.hash != t2.hash  # conteúdos diferentes
    assert worker._gerar_hash("promo") == worker._gerar_hash("promo")


def test_sync_hashes_do_banco_evita_reprocessar():
    worker = _worker_com(RSS_PERFIL)
    tweets = worker.fetch_new_tweets()
    worker2 = _worker_com(RSS_PERFIL)
    worker2.sync_hashes_from_db([t.hash for t in tweets])
    assert worker2.fetch_new_tweets() == []


def test_falha_num_perfil_nao_para_os_demais(caplog):
    worker = _worker_com(RSS_PERFIL)
    worker.perfis = ["perfildeteste", "perfilmorto"]
    # O perfil morto não está no mock → 503 → warning, o outro segue.
    tweets = worker.fetch_new_tweets()
    assert len(tweets) == 2


def test_health_check_da_lista_configurada():
    worker = _worker_com(RSS_PERFIL)
    worker._client.close()
    import httpx

    worker._client = httpx.Client(
        transport=_transport({"ok.test": 200, "fora.test": 503}),
        follow_redirects=True,
    )
    worker.instancias = ["https://ok.test", "https://fora.test"]
    status = worker.health_check()
    assert status == {"https://ok.test": True, "https://fora.test": False}


# ------------------------------------------------------------------
# Filtro de idade na ingestão (tempo real): tweet velho não entra,
# marca como visto e não volta; sem data passa; 0 desliga.
# ------------------------------------------------------------------

def _tweet_idade(horas: float):
    from datetime import datetime, timedelta
    from worker import Tweet

    return Tweet(
        hash=f"h-{horas}",
        url=f"https://x.com/p/status/{horas}",
        conteudo="promo",
        perfil_origem="p",
        publicado_em=datetime.utcnow() - timedelta(hours=horas),
    )


def test_tweet_velho_descartado_e_nao_volta(monkeypatch):
    worker = RSSWorker(perfis=["p"], idade_maxima_horas=48)
    monkeypatch.setattr(
        worker, "_fetch_perfil_com_fallback", lambda perfil: [_tweet_idade(10 * 24), _tweet_idade(0.5)]
    )

    tweets = worker.fetch_new_tweets()
    assert [t.hash for t in tweets] == ["h-0.5"]
    # Descartado marca como visto: o próximo ciclo não reavalia.
    assert worker.fetch_new_tweets() == []


def test_tweet_sem_data_passa(monkeypatch):
    worker = RSSWorker(perfis=["p"], idade_maxima_horas=48)
    from worker import Tweet

    sem_data = Tweet(hash="h-sem-data", url="u", conteudo="c", perfil_origem="p", publicado_em=None)
    monkeypatch.setattr(worker, "_fetch_perfil_com_fallback", lambda perfil: [sem_data])
    assert [t.hash for t in worker.fetch_new_tweets()] == ["h-sem-data"]


def test_limite_zero_desliga_o_filtro(monkeypatch):
    worker = RSSWorker(perfis=["p"], idade_maxima_horas=0)
    monkeypatch.setattr(worker, "_fetch_perfil_com_fallback", lambda perfil: [_tweet_idade(10 * 24)])
    assert len(worker.fetch_new_tweets()) == 1


def test_limite_apertado_descarta_recente(monkeypatch):
    worker = RSSWorker(perfis=["p"], idade_maxima_horas=1)
    monkeypatch.setattr(worker, "_fetch_perfil_com_fallback", lambda perfil: [_tweet_idade(3)])
    assert worker.fetch_new_tweets() == []


def test_mesmo_tweet_de_instancias_diferentes_cai_no_mesmo_hash():
    """O quote embutido no texto varia pela instância Nitter que serviu o
    feed — o MESMO tweet precisa cair no MESMO hash, senão ingestão e
    classificação triplicam."""
    worker = _worker_com(RSS_PERFIL)
    a = worker._gerar_hash("olha isso — https://nitter.netbub.com/fulano/status/1#m promo")
    b = worker._gerar_hash("olha isso — http://nitter.mie.foundation/fulano/status/1 promo")
    c = worker._gerar_hash("olha isso — promo")
    assert a == b == c
