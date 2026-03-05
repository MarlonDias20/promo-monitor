"""
Teste do banco de dados — valida inserção, deduplicação e queries.
Usa SQLite em memória, sem efeito colateral.
Uso: python test_database.py
"""
from datetime import datetime
from dataclasses import dataclass
from database import Database


# Simula a dataclass Tweet do worker sem precisar importar dependências externas
@dataclass
class TweetFake:
    hash: str
    url: str
    conteudo: str
    perfil_origem: str
    publicado_em: datetime


CLASSIFICACAO_S = {
    "tier": "S",
    "produto": "Notebook Lenovo",
    "loja": "Kabum",
    "desconto_estimado": 95.0,
    "preco_original": "R$ 3.999",
    "preco_promocional": "R$ 0,01",
    "urgencia": 10,
    "motivo": "Bug de preço absurdo — produto saindo por R$0,01",
}

CLASSIFICACAO_A = {
    "tier": "A",
    "produto": "iPhone 14",
    "loja": "Amazon",
    "desconto_estimado": 45.0,
    "preco_original": "R$ 3.999",
    "preco_promocional": "R$ 2.199",
    "urgencia": 7,
    "motivo": "Desconto significativo em produto de alta demanda",
}

CLASSIFICACAO_N = {
    "tier": "N",
    "produto": None,
    "loja": None,
    "desconto_estimado": None,
    "preco_original": None,
    "preco_promocional": None,
    "urgencia": 0,
    "motivo": "Não é uma promoção",
}


def main():
    # Banco em memória — não cria arquivo
    db = Database("sqlite:///:memory:")

    print("\n" + "="*60)
    print("TESTANDO DATABASE")
    print("="*60)

    # 1. Inserção básica
    print("\n[1] Inserindo promoções...")
    t1 = TweetFake("abc111", "https://x.com/1", "Bug! Notebook por R$0,01!", "opromocionista", datetime.utcnow())
    t2 = TweetFake("abc222", "https://x.com/2", "iPhone 14 com 45% OFF!", "pelando", datetime.utcnow())
    t3 = TweetFake("abc333", "https://x.com/3", "Novo trailer do iPhone 17", "opromocionista", datetime.utcnow())

    p1 = db.salvar_promocao(t1, CLASSIFICACAO_S)
    p2 = db.salvar_promocao(t2, CLASSIFICACAO_A)
    p3 = db.salvar_promocao(t3, CLASSIFICACAO_N)

    assert p1 is not None, "p1 deveria ter sido salvo"
    assert p2 is not None, "p2 deveria ter sido salvo"
    assert p3 is not None, "p3 deveria ter sido salvo"
    print("  ✅ 3 promoções inseridas")

    # 2. Deduplicação
    print("\n[2] Testando deduplicação...")
    duplicado = db.salvar_promocao(t1, CLASSIFICACAO_S)
    assert duplicado is None, "Duplicata deveria retornar None"
    print("  ✅ Duplicata ignorada corretamente")

    # 3. Stats
    print("\n[3] Stats do banco:")
    s = db.stats()
    assert s["total"] == 3
    assert s["por_tier"]["S"] == 1
    assert s["por_tier"]["A"] == 1
    assert s["por_tier"]["N"] == 1
    print(f"  Total: {s['total']} | S:{s['por_tier']['S']} A:{s['por_tier']['A']} B:{s['por_tier']['B']} N:{s['por_tier']['N']}")
    print("  ✅ Stats corretos")

    # 4. Pendentes de notificação
    print("\n[4] Pendentes de notificação (tiers S e A)...")
    pendentes = db.buscar_pendentes_notificacao({"S", "A"})
    assert len(pendentes) == 2
    print(f"  {len(pendentes)} promoções pendentes (esperado: 2)")
    print("  ✅ Query de pendentes correta")

    # 5. Marcar como notificado
    print("\n[5] Marcando como notificado...")
    db.marcar_notificado(p1.id)
    db.marcar_notificado(p2.id)
    pendentes_apos = db.buscar_pendentes_notificacao({"S", "A"})
    assert len(pendentes_apos) == 0
    print("  ✅ marcar_notificado funcionando")

    # 6. listar_hashes (para sync do worker)
    print("\n[6] Listando hashes para sync do worker...")
    hashes = db.listar_hashes()
    assert set(hashes) == {"abc111", "abc222", "abc333"}
    print(f"  {len(hashes)} hashes recuperados")
    print("  ✅ listar_hashes correto")

    # 7. Sincronizar perfis
    print("\n[7] Sincronizando perfis...")
    db.sincronizar_perfis(["opromocionista", "pelando", "desconto_e_oferta"])
    db.sincronizar_perfis(["opromocionista"])  # não deve duplicar
    print("  ✅ Perfis sincronizados sem duplicata")

    print("\n" + "="*60)
    print("Database OK! Todos os testes passaram.")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
