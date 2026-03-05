import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, Numeric,
    String, Text, create_engine, text
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Base e Engine
# ------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


def criar_engine(database_url: str):
    kwargs = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------

class PerfilMonitorado(Base):
    __tablename__ = "perfis_monitorados"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    handle       = Column(String(100), nullable=False, unique=True)
    ativo        = Column(Boolean, default=True, nullable=False)
    criado_em    = Column(DateTime, default=datetime.utcnow, nullable=False)


class Promocao(Base):
    __tablename__ = "promocoes"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    tweet_hash         = Column(String(32), nullable=False, unique=True, index=True)
    tweet_url          = Column(Text, nullable=False)
    conteudo           = Column(Text, nullable=False)
    perfil_origem      = Column(String(100), nullable=False, index=True)
    publicado_em       = Column(DateTime, nullable=True)

    # Campos preenchidos pelo classificador
    tier               = Column(String(1), nullable=False, default="N", index=True)
    produto            = Column(Text, nullable=True)
    loja               = Column(Text, nullable=True)
    desconto_estimado  = Column(Numeric(5, 2), nullable=True)
    preco_original     = Column(String(50), nullable=True)
    preco_promocional  = Column(String(50), nullable=True)
    urgencia           = Column(Integer, nullable=True)
    motivo             = Column(Text, nullable=True)

    # Controle
    notificado         = Column(Boolean, default=False, nullable=False)
    criado_em          = Column(DateTime, default=datetime.utcnow, nullable=False)


# ------------------------------------------------------------------
# Database — classe principal de acesso
# ------------------------------------------------------------------

class Database:
    def __init__(self, database_url: str):
        self.engine = criar_engine(database_url)
        self._Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._criar_tabelas()
        logger.info(f"Banco inicializado: {database_url}")

    def _criar_tabelas(self):
        Base.metadata.create_all(self.engine)

    @contextmanager
    def _session(self):
        session: Session = self._Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Promoções
    # ------------------------------------------------------------------

    def salvar_promocao(self, tweet, classificacao: dict) -> Optional[Promocao]:
        """
        Persiste um tweet com sua classificação.
        Retorna None se o tweet já existe (hash duplicado).
        """
        if self.hash_existe(tweet.hash):
            logger.debug(f"Tweet já existe no banco: {tweet.hash}")
            return None

        try:
            with self._session() as s:
                promocao = Promocao(
                    tweet_hash        = tweet.hash,
                    tweet_url         = tweet.url,
                    conteudo          = tweet.conteudo,
                    perfil_origem     = tweet.perfil_origem,
                    publicado_em      = tweet.publicado_em,
                    tier              = classificacao.get("tier", "N"),
                    produto           = classificacao.get("produto"),
                    loja              = classificacao.get("loja"),
                    desconto_estimado = classificacao.get("desconto_estimado"),
                    preco_original    = classificacao.get("preco_original"),
                    preco_promocional = classificacao.get("preco_promocional"),
                    urgencia          = classificacao.get("urgencia"),
                    motivo            = classificacao.get("motivo"),
                    notificado        = False,
                )
                s.add(promocao)
                s.flush()
                logger.info(f"Promoção salva — Tier {promocao.tier} | {tweet.url}")
                return promocao
        except Exception as e:
            logger.error(f"Erro ao salvar promoção: {e}")
            return None

    def marcar_notificado(self, promocao_id: int):
        """Marca uma promoção como já notificada no Telegram."""
        with self._session() as s:
            s.query(Promocao).filter(
                Promocao.id == promocao_id
            ).update({"notificado": True})

    def hash_existe(self, hash_: str) -> bool:
        with self._Session() as s:
            return s.query(
                s.query(Promocao).filter(Promocao.tweet_hash == hash_).exists()
            ).scalar()

    def listar_hashes(self) -> list[str]:
        """Retorna todos os hashes salvos — usado para inicializar o worker."""
        with self._Session() as s:
            rows = s.query(Promocao.tweet_hash).all()
            return [r[0] for r in rows]

    def buscar_pendentes_notificacao(self, tiers: set[str]) -> list[Promocao]:
        """Retorna promoções que ainda não foram notificadas e são do tier desejado."""
        with self._Session() as s:
            return (
                s.query(Promocao)
                .filter(
                    Promocao.tier.in_(tiers),
                    Promocao.notificado == False,
                )
                .order_by(Promocao.urgencia.desc(), Promocao.criado_em.asc())
                .all()
            )

    def listar_por_tier(self, tier: str, limite: int = 20) -> list[Promocao]:
        """Útil para consultas manuais e futuro frontend."""
        with self._Session() as s:
            return (
                s.query(Promocao)
                .filter(Promocao.tier == tier)
                .order_by(Promocao.criado_em.desc())
                .limit(limite)
                .all()
            )

    def stats(self) -> dict:
        """Retorna um resumo rápido do banco — útil para monitorar o sistema."""
        with self._Session() as s:
            total      = s.query(Promocao).count()
            por_tier   = {
                t: s.query(Promocao).filter(Promocao.tier == t).count()
                for t in ("S", "A", "B", "N")
            }
            notificadas = s.query(Promocao).filter(Promocao.notificado == True).count()
            return {
                "total": total,
                "por_tier": por_tier,
                "notificadas": notificadas,
                "pendentes": total - notificadas,
            }

    # ------------------------------------------------------------------
    # Perfis
    # ------------------------------------------------------------------

    def sincronizar_perfis(self, handles: list[str]):
        """
        Garante que todos os handles configurados existem no banco.
        Não remove perfis antigos — apenas adiciona os novos.
        """
        with self._session() as s:
            existentes = {
                r[0] for r in s.query(PerfilMonitorado.handle).all()
            }
            novos = [h for h in handles if h not in existentes]
            for handle in novos:
                s.add(PerfilMonitorado(handle=handle))
            if novos:
                logger.info(f"Perfis adicionados ao banco: {novos}")
