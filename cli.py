"""
cli.py — caminho de VOLTA do webhook: o agente classificador (OpenBot)
entrega a classificação por aqui e o registro deixa de ser pendente.

Uso (a partir da pasta do projeto, com o venv ativo):
    python cli.py classificar HASH '<json>'
    python cli.py pendentes            # o que ainda aguarda classificação
    python cli.py notificar HASH --canal whatsapp|telegram|ambos
                                       # reenvio manual da notificação

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


def cmd_notificar(args: list[str]) -> int:
    """
    Reenvio manual da notificação de uma promoção JÁ classificada:
        cli.py notificar HASH --canal whatsapp|telegram|ambos

    Quem envia é o agente (Passo 3 do fluxo) — o worker não notifica. O
    canal 'ambos' tenta os dois e falha só se ambos falharem.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="cli.py notificar", add_help=False)
    parser.add_argument("hash")
    parser.add_argument("--canal", required=True, choices=["whatsapp", "telegram", "ambos"])
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="pula a checagem de duplicata (reenvio manual)",
    )
    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        _erro("uso: cli.py notificar HASH --canal whatsapp|telegram|ambos [--forcar]")
        return 1

    db = Database(config.DATABASE_URL)
    with db._Session() as s:
        promocao = s.query(__import__("database").Promocao).filter_by(tweet_hash=parsed.hash).one_or_none()
    if promocao is None:
        _erro(f"hash desconhecido: {parsed.hash}")
        return 1

    # Dedup de produto: perfis repetem promoções uns dos outros — se o
    # mesmo produto/loja já foi notificado dentro da janela, marca e pula
    # sem enviar (a checagem é SQL local, zero custo de IA). --forcar pula.
    if not parsed.forcar:
        original = db.buscar_duplicata_recente(promocao, config.DEDUP_JANELA_HORAS)
        if original is not None:
            db.marcar_duplicata(promocao.id)
            print(
                f"PULADA: produto/loja já notificado por @{original.perfil_origem} "
                f"({original.tweet_url}) — marcada como duplicata, nenhum canal enviado."
            )
            return 0

    enviados = []
    if parsed.canal in ("whatsapp", "ambos"):
        if not (config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID and config.WA_DESTINO):
            _erro("WhatsApp não configurado — preencha WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID e WA_DESTINO no .env")
        else:
            from whatsapp import WhatsAppNotifier

            ok = WhatsAppNotifier(
                config.WHATSAPP_TOKEN, config.WHATSAPP_PHONE_NUMBER_ID, config.WA_DESTINO
            ).enviar(promocao)
            enviados.append(ok)
            print("WhatsApp: enviado" if ok else "WhatsApp: FALHOU (veja o log)")

    if parsed.canal in ("telegram", "ambos"):
        if not (config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID):
            _erro("Telegram não configurado — preencha TELEGRAM_TOKEN e TELEGRAM_CHAT_ID no .env")
        else:
            from notifier import TelegramNotifier

            ok = TelegramNotifier(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID).send(promocao)
            enviados.append(ok)
            print("Telegram: enviado" if ok else "Telegram: FALHOU (veja o log)")

    if enviados and any(enviados):
        # Fecha o ciclo do dedup: a próxima promo igual acha esta como
        # "já notificada" dentro da janela (SQL local, sem custo de IA).
        db.marcar_notificado(promocao.id)
        return 0
    _erro("nenhum canal enviou")
    return 1


def main() -> int:
    comandos = {
        "classificar": cmd_classificar,
        "pendentes": cmd_pendentes,
        "notificar": cmd_notificar,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in comandos:
        _erro("uso: cli.py classificar HASH '<json>' | cli.py pendentes | cli.py notificar HASH --canal …")
        return 1
    return comandos[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
