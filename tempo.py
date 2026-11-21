"""
tempo.py — momento do tweet, no fuso de Brasília, UMA função para todos
os canais (Telegram, WhatsApp) e o espelho exato do site (index.html tem
a versão JavaScript da mesma especificação).

Formatos:
  - site:          "20/11 às 23h21 · há 3h"      (momento_tweet)
  - notificações:  "20/11, 23h21 (há 3h)"        (momento_notificacao)
  - relativo:      "agora" | "há Xmin" | "há Xh" | "há Xd"

Sem publicado_em: tudo devolve None — quem chama omite a linha.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem tzdata no host: Brasil sem DST desde 2019, -3 fixo
    FUSO_BRASILIA = timezone(timedelta(hours=-3))


def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def data_hora_brasilia(iso: Optional[str], entre: str = " às ") -> Optional[str]:
    """'20/11 às 23h21' (site) — com `entre=', '` vira '20/11, 23h21' (notificações)."""
    data = _parse(iso)
    if data is None:
        return None

    local = data.astimezone(FUSO_BRASILIA)
    return f"{local.day:02d}/{local.month:02d}{entre}{local.hour:02d}h{local.minute:02d}"


def relativo(iso: Optional[str], agora: Optional[datetime] = None) -> Optional[str]:
    """
    Curto: 'agora' (<1 min), 'há Xmin', 'há Xh', 'há Xd'. Sem data → None.
    """
    data = _parse(iso)
    if data is None:
        return None

    base = (agora or datetime.now(timezone.utc))
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)

    segundos = (base - data).total_seconds()
    if segundos < 60:
        return "agora"
    if segundos < 3600:
        return f"há {int(segundos // 60)}min"
    if segundos < 86400:
        return f"há {int(segundos // 3600)}h"
    return f"há {int(segundos // 86400)}d"


def momento_tweet(iso: Optional[str], agora: Optional[datetime] = None) -> Optional[str]:
    """Linha do card no site: '20/11 às 23h21 · há 3h'."""
    parte = data_hora_brasilia(iso)
    if parte is None:
        return None
    rel = relativo(iso, agora)
    return f"{parte} · {rel}" if rel else parte


def momento_notificacao(iso: Optional[str], agora: Optional[datetime] = None) -> Optional[str]:
    """Linha das notificações (sem o emoji, quem chama escolhe): '20/11, 23h21 (há 3h)'."""
    parte = data_hora_brasilia(iso, entre=", ")
    if parte is None:
        return None
    rel = relativo(iso, agora)
    return f"{parte} ({rel})" if rel else parte
