#!/usr/bin/env bash
# run.sh — sobe o ambiente e roda o monitor.
# Uso: ./run.sh   (dentro do diretório do projeto)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[run] Criando venv…"
  python3 -m venv .venv
fi

# Sobe sozinho se o requirements mudar (compara data de modificação).
if [ requirements.txt -nt .venv/.installed ] 2>/dev/null || [ ! -f .venv/.installed ]; then
  echo "[run] Instalando dependências…"
  .venv/bin/pip install -q -r requirements.txt
  touch .venv/.installed
fi

if [ ! -f .env ]; then
  echo "[run] ATENÇÃO: .env não encontrado — copie .env.example e preencha as chaves."
fi

echo "[run] Iniciando promo-monitor…"
exec .venv/bin/python main.py
