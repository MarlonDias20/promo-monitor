"""
Teste rápido do classificador — rode antes de subir o worker completo.
Uso: python test_classifier.py SUA_API_KEY_ZAI
"""
import sys
from classifier import Classifier

TWEETS_DE_TESTE = [
    # Esperado: Tier S
    "🚨 BUG DE PREÇO! Notebook Lenovo IdeaPad saindo por R$0,01 na Kabum! "
    "Corre antes de corrigirem! 💥 https://kabum.com.br/...",

    # Esperado: Tier A
    "⚡ OFERTA RELÂMPAGO até meia-noite! iPhone 14 com 45% OFF na Amazon. "
    "De R$3.999 por R$2.199. Link: https://amzn.to/...",

    # Esperado: Tier B
    "Cupom PROMO10 dá 10% de desconto em qualquer compra na Americanas. "
    "Válido até domingo.",

    # Esperado: Tier N
    "Saiu o novo trailer do iPhone 17! O que vocês acharam do design? 🤔",
]

def main():
    api_key = sys.argv[1] if len(sys.argv) > 1 else input("Cole sua API key da Z.ai: ")
    clf = Classifier(api_key=api_key)

    print("\n" + "="*60)
    print("TESTANDO CLASSIFICADOR — GLM-4.7 via Z.ai")
    print("="*60)

    for i, tweet in enumerate(TWEETS_DE_TESTE, 1):
        print(f"\n[Teste {i}]")
        print(f"Tweet: {tweet[:80]}...")
        result = clf.classify(tweet)
        tier = result['tier']
        emoji = {"S": "🔥", "A": "⚡", "B": "💤", "N": "❌"}.get(tier, "?")
        print(f"Tier: {emoji} {tier}  |  Urgência: {result['urgencia']}/10")
        print(f"Produto: {result['produto']}  |  Loja: {result['loja']}")
        print(f"Desconto: {result['desconto_estimado']}%  |  "
              f"Preço: {result['preco_original']} → {result['preco_promocional']}")
        print(f"Motivo: {result['motivo']}")

    print("\n" + "="*60)
    print("Teste concluído!")

if __name__ == "__main__":
    main()
