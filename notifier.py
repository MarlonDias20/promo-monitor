import logging
from database import Promocao
from tempo import momento_notificacao
import httpx

logger = logging.getLogger(__name__)

TIER_CONFIG = {
    "S": {"emoji": "🔥", "label": "IMPERDÍVEL",  "header": "🚨 BUG / OFERTA ABSURDA"},
    "A": {"emoji": "⚡", "label": "MUITO BOA",   "header": "⚡ OFERTA RELÂMPAGO"},
}


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id
        self._base   = f"https://api.telegram.org/bot{token}"
        self._client = httpx.Client(timeout=10)

    # ------------------------------------------------------------------
    # Público
    # ------------------------------------------------------------------

    def send(self, promocao: Promocao) -> bool:
        """
        Envia uma promoção formatada ao Telegram.
        Retorna True se enviou com sucesso.
        """
        try:
            texto = self._formatar(promocao)
            self._enviar_mensagem(texto)
            logger.info(f"Notificação enviada — Tier {promocao.tier} | {promocao.tweet_url}")
            return True
        except Exception as e:
            logger.error(f"Falha ao enviar notificação: {e}")
            return False

    def send_resumo_diario(self, stats: dict):
        """Envia um resumo diário com estatísticas do banco."""
        texto = (
            "📊 *Resumo do dia*\n\n"
            f"Total coletado: `{stats['total']}`\n"
            f"🔥 Tier S: `{stats['por_tier']['S']}`\n"
            f"⚡ Tier A: `{stats['por_tier']['A']}`\n"
            f"💤 Tier B: `{stats['por_tier']['B']}`\n"
            f"❌ Não promoção: `{stats['por_tier']['N']}`\n"
            f"📲 Notificadas: `{stats['notificadas']}`"
        )
        try:
            self._enviar_mensagem(texto)
        except Exception as e:
            logger.error(f"Falha ao enviar resumo diário: {e}")

    # ------------------------------------------------------------------
    # Privado
    # ------------------------------------------------------------------

    def _formatar(self, p: Promocao) -> str:
        cfg = TIER_CONFIG.get(p.tier, {"emoji": "💤", "label": p.tier, "header": "Oferta"})

        linhas = [f"{cfg['header']}\n"]

        if p.produto:
            linhas.append(f"🛍 *{self._escape(p.produto)}*")
        if p.loja:
            linhas.append(f"🏪 {self._escape(p.loja)}")

        # Preço
        if p.preco_original and p.preco_promocional:
            linhas.append(
                f"💰 ~~{self._escape(p.preco_original)}~~ → *{self._escape(p.preco_promocional)}*"
            )
        elif p.preco_promocional:
            linhas.append(f"💰 *{self._escape(p.preco_promocional)}*")

        if p.desconto_estimado:
            linhas.append(f"📉 Desconto estimado: *{p.desconto_estimado:.0f}%*")

        linhas.append(f"\n⚡ Urgência: {'🔴' * min(int(p.urgencia / 2), 5)}")
        linhas.append(f"💬 _{self._escape(p.motivo)}_")

        # Momento do tweet (fuso de Brasília) — saber se ainda dá tempo.
        momento = momento_notificacao(p.publicado_em.isoformat() if p.publicado_em else None)
        if momento:
            linhas.append(f"📅 {self._escape(momento)}")

        linhas.append(f"\n🔗 [Ver tweet]({p.tweet_url})")
        linhas.append(f"👤 @{self._escape(p.perfil_origem)}")

        return "\n".join(linhas)

    def _enviar_mensagem(self, texto: str):
        response = self._client.post(
            f"{self._base}/sendMessage",
            json={
                "chat_id":    self.chat_id,
                "text":       texto,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": False,
            },
        )
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API erro: {data.get('description')}")

    @staticmethod
    def _escape(texto: str) -> str:
        """Escapa caracteres especiais do MarkdownV2."""
        if not texto:
            return ""
        for ch in r"\_*[]()~`>#+-=|{}.!":
            texto = texto.replace(ch, f"\\{ch}")
        return texto

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass
