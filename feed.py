"""Exporta o feed promos.json para o site estático (spec de UI, seção 8)."""
import json
import logging
import os
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Últimas N promoções no feed — página e filtro rodam no navegador.
LIMITE_PADRAO = 500


class ExportadorPromos:
    """
    Escreve promos.json a cada ciclo — o site estático lê esse arquivo.
    Thread-safe: o disparo de webhooks roda em thread separada.

    Contrato (spec da Prisma, seção 8): `gerado_em` obrigatório no topo
    (alimenta o "Atualizado em …" do rodapé) e `promocoes[]` com os campos
    snake_case espelhando as colunas do banco, null quando ausente.
    """

    def __init__(self, caminho: Optional[str], limite: int = LIMITE_PADRAO):
        self.caminho = caminho
        self.limite = limite
        self._lock = threading.Lock()

    def exportar(self, db) -> Optional[int]:
        """
        Gera o JSON com as promoções mais recentes (mais recentes primeiro).
        Atômico: escreve em .tmp e renomeia — o site nunca lê um arquivo pela
        metade. Retorna a quantidade exportada, ou None se desligado.
        """
        if not self.caminho:
            return None

        try:
            promocoes = db.listar_recentes(self.limite)
            payload = {
                "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
                "total": len(promocoes),
                "promocoes": promocoes,
            }

            pasta = os.path.dirname(self.caminho) or "."
            os.makedirs(pasta, exist_ok=True)

            with self._lock:
                tmp = self.caminho + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                os.replace(tmp, self.caminho)

            return len(promocoes)
        except Exception as e:
            logger.error(f"Falha ao exportar promos.json: {e}")
            return None
