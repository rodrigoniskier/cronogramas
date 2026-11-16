"""Gera as planilhas de exemplo da importação (dados FICTÍCIOS).

Uso:  python manage.py gerar_exemplos [--destino exemplos]

As planilhas referenciam os usuários e o semestre criados por `seed_demo`.
"""
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

from core.importacao import gerar_planilha

D = "demo.cronomed.example"
NOME = "Farmacologia Básica (DEMO)"
TEMAS = (
    "Introdução à farmacologia", "Farmacocinética: absorção e distribuição", "Farmacocinética: metabolismo e excreção",
    "Farmacodinâmica: receptores", "Sistema nervoso autônomo", "Avaliação formativa",
)
QUINTAS = (date(2027, 2, 4), date(2027, 2, 11), date(2027, 2, 18), date(2027, 2, 25), date(2027, 3, 4), date(2027, 3, 11))


def _linha(turma, dia, horario, tema, docente, tipo="T", local="Sala 302 — Bloco D"):
    return (NOME, "DEMO-05", "4º", turma, "Manhã", dia, horario, tema, tipo,
            "Aula expositiva dialogada", "Datashow e quadro", "TODOS", f"{docente}@{D}" if docente else "", "", local)


def linhas_validas():
    """15 encontros em 2 componentes novos, com três conflitos intencionais."""
    linhas = [_linha("A", dia, "08h-10h", tema, "prof8") for dia, tema in zip(QUINTAS, TEMAS)]
    linhas += [_linha("B", dia, "10h-12h", tema, "prof4") for dia, tema in zip(QUINTAS, TEMAS)]
    linhas += [
        # CALENDÁRIO: 08/02/2027 é data bloqueada (Carnaval) no semestre de demonstração.
        _linha("A", date(2027, 2, 8), "08h-10h", "Aula de revisão", "prof8"),
        # TURMA: a Turma A (4º período) já tem MAPD II na quarta, 13h–15h30.
        _linha("A", date(2027, 3, 3), "13h-15h30", "Seminário integrador", "prof7", "P"),
        # DOCENTE: prof7 já leciona Morfofuncional II na terça 23/02, 08h–10h.
        _linha("B", date(2027, 2, 23), "08h-10h", "Aula de reposição", "prof7"),
    ]
    return linhas


def linhas_com_erros():
    """As mesmas colunas, com os erros de preenchimento mais comuns."""
    ok = _linha("A", date(2027, 2, 4), "08h-10h", TEMAS[0], "prof8")
    return [
        ok,
        ok,                                                                       # linha repetida
        ("",) + _linha("A", date(2027, 2, 11), "08h-10h", TEMAS[1], "prof8")[1:],  # sem componente
        _linha("A", "31/02/2027", "08h-10h", TEMAS[2], "prof8"),                  # data inexistente
        _linha("A", date(2027, 2, 25), "10h-08h", TEMAS[3], "prof8"),             # término antes do início
        _linha("A", date(2027, 3, 4), "08h-10h", TEMAS[4], "nao.cadastrado"),     # docente desconhecido
        _linha("A", date(2027, 3, 11), "08h-10h", TEMAS[5], "prof8", tipo="X"),   # tipo inválido
        _linha("A", date(2027, 8, 12), "08h-10h", "Aula extra", "prof8"),         # fora do semestre
    ]


class Command(BaseCommand):
    help = "Gera as planilhas de exemplo da importação em exemplos/ (dados fictícios)."

    def add_arguments(self, parser):
        parser.add_argument("--destino", default="exemplos")

    def handle(self, *args, **opts):
        destino = Path(opts["destino"])
        destino.mkdir(parents=True, exist_ok=True)
        titulo = "CRONOGRAMA DE AULAS — 2027.1 (DEMONSTRAÇÃO) — dados fictícios"
        for nome, linhas in (("cronograma_exemplo.xlsx", linhas_validas()), ("cronograma_exemplo_com_erros.xlsx", linhas_com_erros())):
            (destino / nome).write_bytes(gerar_planilha(linhas, titulo=titulo))
            self.stdout.write(f"{destino / nome}: {len(linhas)} linhas")
