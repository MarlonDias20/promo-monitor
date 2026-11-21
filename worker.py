import hashlib
import logging
import re
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


@dataclass
class EstadoInstancia:
    """Saúde de uma instância do Nitter — alimenta a rotação automática."""

    url: str
    falhas_seguidas: int = 0
    ultima_falha: Optional[datetime] = None
    em_uso: bool = False


class RSSWorker:
    def __init__(
        self,
        perfis: list[str],
        nitter_base: str = "https://nitter.privacydev.net",
        instancias: Optional[list[str]] = None,
        falhas_para_rotacionar: int = 2,
    ):
        """
        perfis: lista de @handles a monitorar, ex: ["@opromocionista", "@pelando"]
        nitter_base: retrocompatível — vira a primeira instância quando
                     `instancias` não é passada.
        instancias: lista completa de instâncias Nitter. Com mais de uma, o
                    worker rotaciona automaticamente: a instância atual que
                    acumula `falhas_para_rotacionar` falhas seguidas sai do
                    uso até que uma saudável seja encontrada.
        """
        self.perfis = [p.lstrip("@") for p in perfis]
        self.falhas_para_rotacionar = max(1, falhas_para_rotacionar)

        lista = instancias or [nitter_base]
        self.instancias = [u.rstrip("/") for u in lista]
        self._estados = {url: EstadoInstancia(url=url) for url in self.instancias}
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
        Um perfil que falha em TODAS as instâncias não para os demais.
        """
        novos: list[Tweet] = []

        for perfil in self.perfis:
            try:
                tweets = self._fetch_perfil_com_fallback(perfil)
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
        Verifica quais instâncias configuradas estão respondendo.
        """
        resultado = {}
        for url in self.instancias:
            try:
                r = self._client.get(url, timeout=5)
                resultado[url] = r.status_code == 200
            except Exception:
                resultado[url] = False
        return resultado

    def _instancias_saudaveis(self) -> list[str]:
        """Ordem de preferência: saudáveis primeiro, a atual na frente."""
        ordenadas = sorted(
            self.instancias,
            key=lambda url: (self._estados[url].falhas_seguidas >= self.falhas_para_rotacionar, url != self._instancia_atual()),
        )
        return ordenadas

    def _instancia_atual(self) -> str:
        atuais = [url for url in self.instancias if self._estados[url].em_uso]
        return atuais[0] if atuais else self.instancias[0]

    def _registrar_falha(self, url: str):
        estado = self._estados[url]
        estado.falhas_seguidas += 1
        estado.ultima_falha = datetime.utcnow()
        if estado.falhas_seguidas >= self.falhas_para_rotacionar and estado.em_uso:
            estado.em_uso = False
            logger.warning(
                f"Instância {url} acumulou {estado.falhas_seguidas} falhas seguidas — rotacionando."
            )

    def _registrar_sucesso(self, url: str):
        estado = self._estados[url]
        estado.falhas_seguidas = 0
        estado.em_uso = True

    # ------------------------------------------------------------------
    # Privado
    # ------------------------------------------------------------------

    def _fetch_perfil_com_fallback(self, perfil: str) -> list[Tweet]:
        """
        Tenta as instâncias em ordem de saúde. A falha de uma instância
        (rede, 5xx, RSS inválido) registra no contador de rotação; quando a
        atual quebra `falhas_para_rotacionar` vezes seguidas, as próximas
        chamadas já começam pela próxima saudável.
        """
        ultimo_erro: Optional[Exception] = None
        for url in self._instancias_saudaveis():
            try:
                tweets = self._fetch_perfil(perfil, url)
                self._registrar_sucesso(url)
                return tweets
            except Exception as e:
                self._registrar_falha(url)
                ultimo_erro = e
                logger.warning(f"Instância {url} falhou para @{perfil}: {e}")

        raise ultimo_erro or RuntimeError("Nenhuma instância do Nitter disponível")

    def _fetch_perfil(self, perfil: str, nitter_base: Optional[str] = None) -> list[Tweet]:
        """Baixa e parseia o RSS de um perfil numa instância específica."""
        feed_url = f"{nitter_base or self._instancia_atual()}/{perfil}/rss"
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
