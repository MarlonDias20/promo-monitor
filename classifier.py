import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um classificador especialista em promoções e ofertas do Brasil.
Analise o tweet fornecido e retorne SOMENTE um JSON válido, sem markdown, sem explicações.

Critérios de classificação:
- Tier S: Bug de preço, produto gratuito, desconto absurdo (acima de 70%). Janela de minutos.
- Tier A: Desconto significativo (40-70%), oferta relâmpago, frete grátis + bom desconto combinados.
- Tier B: Cupom comum, desconto pequeno (abaixo de 40%), promoção recorrente sem urgência.
- Tier N: Não é promoção (post informativo, meme, notícia sem oferta).

Retorne exatamente neste formato JSON:
{
  "tier": "S" | "A" | "B" | "N",
  "produto": "nome do produto ou null",
  "loja": "nome da loja ou null",
  "desconto_estimado": número percentual ou null,
  "preco_original": "valor como string ou null",
  "preco_promocional": "valor como string ou null",
  "urgencia": número de 1 a 10,
  "motivo": "uma frase curta explicando o tier"
}"""


class Classifier:
    def __init__(self, api_key: str):
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )
        self.model = "glm-4"  # GLM-4.7 — incluso no seu pacote

    def classify(self, tweet_text: str) -> dict:
        """
        Classifica um tweet e retorna um dicionário com tier, produto, urgência, etc.
        Em caso de erro, retorna tier N para não bloquear o fluxo.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Tweet:\n{tweet_text}"}
                ],
                temperature=0.1,   # baixo para respostas consistentes
                max_tokens=300,
            )

            raw = response.choices[0].message.content.strip()

            # Remove markdown caso o modelo inclua mesmo com instrução
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)
            self._validate(result)
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Erro ao parsear JSON da IA: {e} | Resposta: {raw}")
            return self._fallback("Erro ao parsear resposta da IA")

        except Exception as e:
            logger.error(f"Erro na classificação: {e}")
            return self._fallback(str(e))

    def _validate(self, result: dict):
        """Garante que os campos obrigatórios existem e são válidos."""
        assert result.get("tier") in ("S", "A", "B", "N"), "Tier inválido"
        assert isinstance(result.get("urgencia"), (int, float)), "Urgência inválida"
        assert isinstance(result.get("motivo"), str), "Motivo inválido"

    def _fallback(self, motivo: str) -> dict:
        """Retorno seguro quando a classificação falha — não bloqueia o pipeline."""
        return {
            "tier": "N",
            "produto": None,
            "loja": None,
            "desconto_estimado": None,
            "preco_original": None,
            "preco_promocional": None,
            "urgencia": 0,
            "motivo": f"Classificação falhou: {motivo}"
        }
