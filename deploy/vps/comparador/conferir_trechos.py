"""Confere os trechos do Comparativo no git: cada linha de `antes` existe no `main` do
original e cada linha de `agora` existe no commit do fork (ou na `dev`, sem commit).

Uso, na raiz do repositório e com o remoto `upstream` atualizado:
    python deploy/vps/comparador/conferir_trechos.py
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import trechos  # noqa: E402

ORIGINAL = "upstream/main"


def _linhas(rev, arquivo):
    saida = subprocess.run(["git", "show", f"{rev}:{arquivo}"], capture_output=True,
                           text=True, encoding="utf-8", check=True).stdout
    return set(saida.splitlines())


def _faltando(trecho, rev, arquivo):
    existentes = _linhas(rev, arquivo)
    return [linha for linha in trecho.strip("\n").splitlines()
            if linha.strip() and linha.strip() != "…" and linha not in existentes]


def main():
    erros = 0
    for nome, blocos in vars(trechos).items():
        if not nome.isupper():
            continue
        for bloco in blocos:
            if bloco.get("demo"):
                continue
            lados = [(bloco["agora"], bloco.get("commit", "HEAD"), bloco["arquivo"])]
            if bloco["antes"]:
                lados.append((bloco["antes"], ORIGINAL,
                              bloco.get("arquivo_antes", bloco["arquivo"])))
            for trecho, rev, arquivo in lados:
                for linha in _faltando(trecho, rev, arquivo):
                    erros += 1
                    print(f"{nome} · {rev}:{arquivo}: {linha.strip()}")
    print("tudo confere" if not erros else f"{erros} linha(s) sem par no git")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
