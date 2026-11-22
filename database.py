import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, Numeric,
    String, Text, create_engine, text
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

# As 16 categorias do classificador (spec de UI, seção 6) — "Outros" é o
# fallback de valor fora da lista.
CATEGORIAS_VALIDAS = {
    "Eletrônicos", "Smartphones", "Informática", "Games", "Eletrodomésticos",
    "Moda e Vestuário", "Beleza e Perfumaria", "Saúde e Bem-estar",
    "Alimentos e Bebidas", "Livros e Cursos", "Casa e Decoração",
    "Brinquedos", "Esporte e Lazer", "Serviços e Assinaturas", "Viagens", "Outros",
}


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
    categoria          = Column(String(50), nullable=False, default="Outros", index=True)
    loja               = Column(Text, nullable=True)
    desconto_estimado  = Column(Numeric(5, 2), nullable=True)
    preco_original     = Column(String(50), nullable=True)
    preco_promocional  = Column(String(50), nullable=True)
    urgencia           = Column(Integer, nullable=True)
    motivo             = Column(Text, nullable=True)

    # Controle
    notificado         = Column(Boolean, default=False, nullable=False)
    criado_em          = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Webhook do classificador (agente OpenBot): tier "P" = pendente de
    # análise; disparo retentado no ciclo seguinte enquanto sem resposta.
    webhook_disparado_em = Column(DateTime, nullable=True)

    # Dedup de produto: promo cujo produto/loja já foi notificado dentro
    # da janela por outro perfil — marcada em vez de reenviada.
    duplicata          = Column(Boolean, default=False, nullable=False)


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
        self._aplicar_migracoes()

    def _aplicar_migracoes(self):
        """Adiciona colunas novas em bancos existentes sem perder dados."""
        with self.engine.connect() as conn:
            try:
                conn.execute(text(
                    "ALTER TABLE promocoes ADD COLUMN categoria VARCHAR(50) NOT NULL DEFAULT 'Outros'"
                ))
                conn.commit()
                logger.info("Migração aplicada: coluna 'categoria' adicionada.")
            except Exception:
                pass  # coluna já existe — ignorar
            try:
                conn.execute(text(
                    "ALTER TABLE promocoes ADD COLUMN webhook_disparado_em DATETIME"
                ))
                conn.commit()
                logger.info("Migração aplicada: coluna 'webhook_disparado_em' adicionada.")
            except Exception:
                pass  # coluna já existe — ignorar
            try:
                conn.execute(text(
                    "ALTER TABLE promocoes ADD COLUMN duplicata BOOLEAN NOT NULL DEFAULT 0"
                ))
                conn.commit()
                logger.info("Migração aplicada: coluna 'duplicata' adicionada.")
            except Exception:
                pass  # coluna já existe — ignorar

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
                    categoria         = classificacao.get("categoria", "Outros"),
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

    def salvar_promocao_pendente(self, tweet) -> Optional[Promocao]:
        """
        Caminho de IDA do webhook (PR do desenho do classificador-agente):
        grava o tweet com tier P — aguardando classificação — e devolve a
        entidade para o disparo. Duplicata retorna None, como sempre.
        """
        return self.salvar_promocao(
            tweet,
            {
                "tier": "P",
                "produto": None,
                "categoria": "Outros",
                "loja": None,
                "desconto_estimado": None,
                "preco_original": None,
                "preco_promocional": None,
                "urgencia": None,
                "motivo": None,
            },
        )

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

    def listar_recentes(self, limite: int = 500) -> list[dict]:
        """
        As promoções mais recentes como dicionários prontos pro feed do site
        (promos.json) — snake_case espelhando as colunas do banco, null
        quando ausente (contrato da spec de UI, seção 8).
        """
        with self._Session() as s:
            promos = (
                s.query(Promocao)
                .order_by(Promocao.criado_em.desc())
                .limit(limite)
                .all()
            )
            return [
                {
                    "id": p.id,
                    "tier": p.tier,
                    "produto": p.produto,
                    "categoria": p.categoria,
                    "loja": p.loja,
                    "desconto_estimado": float(p.desconto_estimado) if p.desconto_estimado is not None else None,
                    "preco_original": p.preco_original,
                    "preco_promocional": p.preco_promocional,
                    "urgencia": p.urgencia,
                    "motivo": p.motivo,
                    "perfil_origem": p.perfil_origem,
                    "tweet_url": p.tweet_url,
                    "conteudo": p.conteudo,
                    "publicado_em": p.publicado_em.isoformat() if p.publicado_em else None,
                    "criado_em": p.criado_em.isoformat() if p.criado_em else None,
                    "duplicata": bool(p.duplicata),
                }
                for p in promos
            ]

    # ------------------------------------------------------------------
    # Webhook do classificador (agente OpenBot)
    # ------------------------------------------------------------------

    def marcar_webhook_disparado(self, promocao_id: int):
        """Registra o disparo bem-sucedido do webhook para retentativa."""
        with self._session() as s:
            s.query(Promocao).filter(Promocao.id == promocao_id).update(
                {"webhook_disparado_em": datetime.utcnow()}
            )

    def buscar_duplicata_recente(self, promocao: Promocao, janela_horas: float) -> Optional[Promocao]:
        """
        Promoção JÁ CLASSIFICADA como S/A, dentro da janela, com o mesmo
        produto (trim + casefold) e loja compatível — perfis repetem
        promoções uns dos outros e o Marlon não quer receber duas vezes.

        Candidata vale mesmo se ainda não marcou notificado (o envio do
        Telegram pode não ter registrado): se o produto já APARECEU como
        S/A recente, a repetida não precisa reenviar. Lojas ambas
        preenchidas e DIFERENTES não são duplicata (mesmo produto em
        lojas distintas são promoções válidas); loja ausente em qualquer
        lado compara só o produto. Produto nulo nunca bloqueia.
        Janela 0 desliga. Retorna a original ou None.
        """
        if not janela_horas or not promocao.produto or not promocao.publicado_em:
            return None

        alvo = promocao.produto.strip().casefold()
        limite = promocao.publicado_em - timedelta(hours=janela_horas)
        with self._Session() as s:
            candidatas = (
                s.query(Promocao)
                .filter(
                    Promocao.tweet_hash != promocao.tweet_hash,
                    Promocao.tier.in_(["S", "A"]),
                    Promocao.duplicata.is_(False),
                    Promocao.produto.isnot(None),
                    Promocao.publicado_em.isnot(None),
                    Promocao.publicado_em >= limite,
                )
                .order_by(Promocao.publicado_em.desc())
                .limit(200)
                .all()
            )
            for candidata in candidatas:
                if candidata.produto.strip().casefold() != alvo:
                    continue
                if (
                    promocao.loja
                    and candidata.loja
                    and promocao.loja.strip().casefold() != candidata.loja.strip().casefold()
                ):
                    continue
                return candidata
            return None

    def marcar_duplicata(self, promocao_id: int):
        """Duplicata confirmada: sai da fila de notificação sem reenviar."""
        with self._session() as s:
            s.query(Promocao).filter(Promocao.id == promocao_id).update(
                {"duplicata": True, "notificado": True}
            )

    def buscar_pendentes_webhook(self, tentar_novamente_apos: timedelta = timedelta(0)) -> list[Promocao]:
        """
        Promoções com tier P (aguardando o agente classificar) para
        (re)disparar: nunca disparadas, ou disparadas há mais de
        `tentar_novamente_apos` sem resposta — a retentativa do ciclo.
        """
        corte = datetime.utcnow() - tentar_novamente_apos
        with self._Session() as s:
            return (
                s.query(Promocao)
                .filter(
                    Promocao.tier == "P",
                    (Promocao.webhook_disparado_em.is_(None))
                    | (Promocao.webhook_disparado_em <= corte),
                )
                .order_by(Promocao.criado_em.asc())
                .all()
            )

    def aplicar_classificacao(self, tweet_hash: str, classificacao: dict) -> Optional[Promocao]:
        """
        Caminho de VOLTA do webhook: o agente classificador entrega
        {tier, produto, categoria, loja, desconto_estimado, ...} para o hash
        pendente e o registro deixa de ser P. Valida igual ao classificador
        (tiers/categorias conhecidos); classificação inválida não grava.
        """
        tier = classificacao.get("tier")
        if tier not in ("S", "A", "B", "N"):
            logger.warning(f"Classificação descartada (tier inválido '{tier}') para {tweet_hash}")
            return None

        categoria = classificacao.get("categoria")
        if categoria not in CATEGORIAS_VALIDAS:
            categoria = "Outros"

        urgencia = classificacao.get("urgencia")
        try:
            urgencia = int(urgencia) if urgencia is not None else None
        except (TypeError, ValueError):
            urgencia = None

        desconto = classificacao.get("desconto_estimado")
        try:
            desconto = float(desconto) if desconto is not None else None
        except (TypeError, ValueError):
            desconto = None

        with self._session() as s:
            promocao = s.query(Promocao).filter(Promocao.tweet_hash == tweet_hash).one_or_none()
            if promocao is None:
                logger.warning(f"Classificação para hash desconhecido: {tweet_hash}")
                return None

            promocao.tier = tier
            promocao.produto = classificacao.get("produto")
            promocao.categoria = categoria
            promocao.loja = classificacao.get("loja")
            promocao.desconto_estimado = desconto
            promocao.preco_original = classificacao.get("preco_original")
            promocao.preco_promocional = classificacao.get("preco_promocional")
            promocao.urgencia = urgencia
            promocao.motivo = classificacao.get("motivo")
            s.flush()
            logger.info(f"Classificação aplicada — Tier {tier} | {promocao.tweet_url}")
            return promocao

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

    def excluir_antigos(self, dias: int = 7) -> int:
        """
        Remove promoções criadas há mais de `dias` dias.
        Retorna a quantidade de registros excluídos.
        """
        corte = datetime.utcnow() - timedelta(days=dias)
        with self._session() as s:
            deletados = (
                s.query(Promocao)
                .filter(Promocao.criado_em < corte)
                .delete(synchronize_session=False)
            )
        logger.info(f"Limpeza do banco: {deletados} promoção(ões) com mais de {dias} dias removida(s).")
        return deletados

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
