"""
Teste do worker RSS — valida coleta e deduplicação sem precisar do banco.
Uso: python test_worker.py
"""
import logging
import sys
from worker import RSSWorker

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")

PERFIS_TESTE = [
    "@opromocionista",   # troque por perfis reais que você monitora
]

def main():
    print("\n" + "="*60)
    print("TESTANDO WORKER RSS")
    print("="*60)

    # Verifica quais instâncias do Nitter estão no ar
    worker = RSSWorker(perfis=PERFIS_TESTE)
    print("\n[1] Health check das instâncias Nitter:")
    status = worker.health_check()
    for url, ok in status.items():
        print(f"  {'✅' if ok else '❌'} {url}")

    # Busca tweets reais
    print("\n[2] Buscando tweets...")
    tweets = worker.fetch_new_tweets()

    if not tweets:
        print("Nenhum tweet encontrado. Verifique se os perfis existem e o Nitter está acessível.")
        sys.exit(1)

    print(f"\n{len(tweets)} tweets encontrados:\n")
    for t in tweets:
        print(f"  @{t.perfil_origem} | {t.publicado_em.strftime('%d/%m %H:%M')}")
        print(f"  {t.conteudo[:120]}...")
        print(f"  Hash: {t.hash} | URL: {t.url}")
        print()

    # Testa deduplicação — segundo fetch não deve retornar nada
    print("[3] Testando deduplicação (segundo fetch deve retornar 0 tweets)...")
    duplicatas = worker.fetch_new_tweets()
    assert len(duplicatas) == 0, f"Esperado 0, veio {len(duplicatas)}"
    print("  ✅ Deduplicação funcionando corretamente\n")

    print("="*60)
    print("Worker OK!")

if __name__ == "__main__":
    main()
