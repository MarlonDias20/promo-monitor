"""
conftest.py — coloca a raiz do projeto no sys.path para que os testes
importem os módulos (database, worker, classifier) direto, como os scripts
originais faziam ao rodar da raiz.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
