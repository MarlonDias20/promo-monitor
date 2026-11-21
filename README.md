# promo-monitor

Monitor de promoções de perfis de achados no X (via instâncias Nitter), com
classificação feita por um **agente do OpenBot** (webhook assinado) e um
**site estático** para consultar as promoções.

## Como funciona

1. **Worker RSS** (`worker.py`) — varre os perfis a cada 60 s usando uma
   LISTA de instâncias Nitter (`NITTER_INSTANCES`); a instância que acumula
   falhas seguidas sai do uso e a próxima saudável assume, sozinho.
2. **Pendente + webhook** (`main.py` + `webhook.py`) — cada tweet novo é
   gravado no banco com tier `P` e disparado por POST assinado
   (header `X-Secret`) para o agente classificador. Sem resposta? O ciclo
   seguinte re-dispara — nenhum tweet se perde se o OpenBot reiniciar.
3. **Classificador-agente** — o agente responde gravando a classificação:
   `python cli.py classificar HASH '<json>'` (o feed do site se atualiza
   na hora). `python cli.py pendentes` lista o que aguarda. Quem notifica
   também é o agente — Telegram **ou WhatsApp**:
   `python cli.py notificar HASH --canal whatsapp|telegram|ambos`
   (reenvio manual de uma promoção já classificação; o fluxo normal usa o
   mesmo `whatsapp.py`/`notifier.py` por trás).
4. **Site** (`site/index.html`) — página estática que lê `promos.json`
   (exportado a cada ciclo), com filtros por tier/categoria/perfil, busca,
   ordenação e auto-refresh de 60 s. `notifier.py` fica como referência de
   formatação.

## Rodando

```bash
cp .env.example .env   # preencha PROMO_WEBHOOK_URL/SECRET etc.
./run.sh               # cria o venv, instala e roda
```

Serviço 24/7: `deploy/promo-monitor.service` (systemd) — ajuste User e
caminho, copie para `/etc/systemd/system/` e `systemctl enable --now
promo-monitor`.

## WhatsApp (Cloud API da Meta)

Preencha no `.env` os valores que você cria no painel da Meta:

```
WHATSAPP_TOKEN=            # token de system user
WHATSAPP_PHONE_NUMBER_ID=  # phone number ID do número
WA_DESTINO=               # seu número: DDI + DDD + dígitos, ex. 5521999999999
```

O que criar no painel (developers.facebook.com):

1. **App** tipo Business → adiciona o produto **WhatsApp**.
2. **Número de teste**: a aba WhatsApp → API Setup mostra o *phone number
   ID* (vai em `WHATSAPP_PHONE_NUMBER_ID`) e o **token temporário**.
   Para uso contínuo, crie um **system user** no app (Business settings →
   System Users) com a permissão `whatsapp_business_messaging` e gere o
   token dele — é o `WHATSAPP_TOKEN`.
3. **Abra a janela**: a Cloud API só entrega mensagens dentro da **janela
   de 24 h** aberta pela última mensagem que o destinatário mandou pro
   número — ou seja, **mande um 'oi' pro número de teste** e repita se a
   janela expirar (o número de teste costuma permitir reabrir; o definitivo
   exige resposta dentro do prazo).
4. Envio: `cli.py notificar HASH --canal whatsapp` (ou `ambos`). Fora da
   janela a API recusa (erro 401/470 no log) — reabra mandando mensagem.

## Testes

```bash
.venv/bin/python -m pytest tests/ -q
```

Sem rede e sem chaves: RSS mockado, webhook com receptor falso, feed e
site validados por contrato (o pulado é a integração real com o modelo,
que hoje é opcional — `classifier.py` segue no repo como referência).
