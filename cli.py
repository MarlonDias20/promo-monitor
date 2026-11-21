"""
cli.py — caminho de VOLTA do webhook: o agente classificador (OpenBot)
entrega a classificação por aqui e o registro deixa de ser pendente.

Uso (a partir da pasta do projeto, com o venv ativo):
    python cli.py classificar HASH '<json>'
    python cli.py pendentes            # o que ainda aguarda classificação

O JSON aceita exatamente os campos do classificador:
    {"tier": "S", "produto": "...", "categoria": "Games", "loja": "...",
     "desconto_estimado": 50, "preco_original": "R$ 299",
     "preco_promocional": "R$ 149", "urgencia": 9, "motivo": "..."}

Tier inválido ou hash desconhecido não gravam nada (código de saída 1).
"""
import json
import sys

import config
from database import Database
from feed import ExportadorPromos


def _erro(mensagem: str) -> None:
    print(f"ERRO: {mensagem}", file=sys.stderr)


def cmd_classificar(args: list[str]) -> int:
    if len(args) < 2:
        _erro("uso: cli.py classificar HASH '<json da classificação>'")
        return 1

    hash_, json_bruto = args[0], args[1]
    try:
        classificacao = json.loads(json_bruto)
    except json.JSONDecodeError as e:
        _erro(f"JSON inválido: {e}")
        return 1

    db = Database(config.DATABASE_URL)
    promocao = db.aplicar_classificacao(hash_, classificacao)
    if promocao is None:
        _erro("não gravado — tier inválido ou hash desconhecido")
        return 1

    # O site atualiza na hora: re-exporta o feed com a classificação nova.
    ExportadorPromos(config.PROMOS_JSON_PATH).exportar(db)
    print(
        f"OK — hash {hash_} classificado como tier {classificacao.get('tier')} "
        f"({promocao.produto or promocao.tweet_url})"
    )
    return 0


def cmd_pendentes(_args: list[str]) -> int:
    db = Database(config.DATABASE_URL)
    pendentes = db.buscar_pendentes_webhook()
    if not pendentes:
        print("Nenhum item pendente de classificação.")
        return 0
    for p in pendentes:
        print(f"{p.tweet_hash} | @{p.perfil_origem} | {p.conteudo[:100]}")
    return 0


def main() -> int:
    comandos = {"classificar": cmd_classificar, "pendentes": cmd_pendentes}
    if len(sys.argv) < 2 or sys.argv[1] not in comandos:
        _erro("uso: cli.py classificar HASH '<json>' | cli.py pendentes")
        return 1
    return comandos[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
