import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)


@dataclass
class Tweet:
    hash: str
    url: str
    conteudo: str
    perfil_origem: str
    publicado_em: datetime


class RSSWorker:
    def __init__(self, perfis: list[str], nitter_base: str = "https://nitter.privacydev.net"):
        """
        perfis: lista de @handles a monitorar, ex: ["@opromocionista", "@pelando"]
        nitter_base: instância do Nitter a usar
        """
        self.perfis = [p.lstrip("@") for p in perfis]
        self.nitter_base = nitter_base.rstrip("/")
        self._hashes_vistos: set[str] = set()  # cache em memória entre ciclos
        self._client = httpx.Client(
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RSS reader)"},
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Público
    # ------------------------------------------------------------------

    def fetch_new_tweets(self) -> list[Tweet]:
        """
        Itera todos os perfis configurados e retorna apenas tweets novos
        (não vistos desde que o worker iniciou e não existentes no banco).
        """
        novos: list[Tweet] = []

        for perfil in self.perfis:
            try:
                tweets = self._fetch_perfil(perfil)
                for tweet in tweets:
                    if tweet.hash not in self._hashes_vistos:
                        self._hashes_vistos.add(tweet.hash)
                        novos.append(tweet)
                        logger.info(f"Novo tweet de @{perfil}: {tweet.url}")
            except Exception as e:
                logger.warning(f"Falha ao buscar @{perfil}: {e}")
                # Continua pros próximos perfis — um erro não para tudo

        logger.debug(f"Ciclo concluído — {len(novos)} tweets novos encontrados")
        return novos

    def sync_hashes_from_db(self, hashes: list[str]):
        """
        Chamado na inicialização para carregar hashes já persistidos no banco,
        evitando reprocessar tweets antigos ao reiniciar o worker.
        """
        self._hashes_vistos.update(hashes)
        logger.info(f"{len(hashes)} hashes carregados do banco")

    def health_check(self) -> dict:
        """
        Verifica quais instâncias do Nitter estão respondendo.
        Útil para trocar de instância automaticamente no futuro.
        """
        instancias = [
            "https://nitter.privacydev.net",
            "https://nitter.net",
            "https://nitter.1d4.us",
        ]
        resultado = {}
        for url in instancias:
            try:
                r = self._client.get(url, timeout=5)
                resultado[url] = r.status_code == 200
            except Exception:
                resultado[url] = False
        return resultado

    # ------------------------------------------------------------------
    # Privado
    # ------------------------------------------------------------------

    def _fetch_perfil(self, perfil: str) -> list[Tweet]:
        """Baixa e parseia o RSS de um perfil."""
        feed_url = f"{self.nitter_base}/{perfil}/rss"
        response = self._client.get(feed_url)
        response.raise_for_status()

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            raise ValueError(f"RSS inválido ou vazio para @{perfil}")

        tweets = []
        for entry in feed.entries:
            tweet = self._parse_entry(entry, perfil)
            if tweet:
                tweets.append(tweet)

        return tweets

    def _parse_entry(self, entry, perfil: str) -> Optional[Tweet]:
        """Converte uma entrada do feed RSS num Tweet."""
        try:
            conteudo = self._extrair_texto(entry)
            if not conteudo:
                return None

            # Remove retweets — foca só em posts originais do perfil
            if conteudo.startswith("RT @"):
                return None

            url = entry.get("link", "")
            hash_ = self._gerar_hash(conteudo)
            publicado_em = self._parsear_data(entry)

            return Tweet(
                hash=hash_,
                url=url,
                conteudo=conteudo,
                perfil_origem=perfil,
                publicado_em=publicado_em,
            )
        except Exception as e:
            logger.warning(f"Erro ao parsear entrada do feed: {e}")
            return None

    def _extrair_texto(self, entry) -> str:
        """
        Extrai texto limpo do entry — o Nitter às vezes inclui HTML no summary.
        """
        # Tenta summary primeiro, depois title
        texto = entry.get("summary", "") or entry.get("title", "")

        # Remove tags HTML básicas
        import re
        texto = re.sub(r"<[^>]+>", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()

        return texto

    def _gerar_hash(self, conteudo: str) -> str:
        """MD5 do conteúdo — identifica duplicatas independente de horário."""
        return hashlib.md5(conteudo.encode("utf-8")).hexdigest()

    def _parsear_data(self, entry) -> datetime:
        """Converte a data do feed para datetime. Usa agora como fallback."""
        try:
            struct = entry.get("published_parsed") or entry.get("updated_parsed")
            if struct:
                return datetime(*struct[:6])
        except Exception:
            pass
        return datetime.utcnow()

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass
