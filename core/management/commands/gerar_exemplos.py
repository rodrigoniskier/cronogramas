"""Gera os arquivos de exemplo da importação (dados FICTÍCIOS).

Uso:  python manage.py gerar_exemplos [--destino exemplos]

Os arquivos referenciam os usuários e o semestre criados por `seed_demo`. As
planilhas são geradas sempre; os cronogramas em DOCX e PDF do conjunto
"cruzamento" são produzidos pelas próprias rotinas de exportação do sistema
e exigem que `seed_demo` já tenha sido executado (nada fica gravado no banco).
"""
from datetime import date, time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from core import exports
from core.importacao import gerar_planilha
from core.models import Componente, Encontro, Semestre, Usuario, ch_padrao

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


# ---------------------------------------------------------------- cruzamento
# Cinco cronogramas do 2º período, em três formatos, com quatro conflitos que só
# aparecem quando os arquivos são cruzados entre si.

SEGUNDAS = (date(2027, 3, 1), date(2027, 3, 8), date(2027, 3, 15), date(2027, 3, 22))
T4 = ("Introdução", "Fundamentos", "Aplicações clínicas", "Síntese e avaliação")


def _encontros(datas, horario, docente):
    return [(dia, horario, tema, docente) for dia, tema in zip(datas, T4)]


def cronogramas_para_cruzamento():
    anatomia = _encontros(SEGUNDAS, (8, 10), "prof6")
    fisiologia = _encontros(SEGUNDAS, (10, 12), "prof7")
    fisiologia[2] = (date(2027, 3, 15), (9, 11), T4[2], "prof7")          # TURMA × Anatomia (08h–10h)
    bioquimica = _encontros((date(2027, 3, 2), date(2027, 3, 9), date(2027, 3, 16), date(2027, 3, 23)), (13, 15), "prof8")
    histologia = _encontros((date(2027, 3, 4), date(2027, 3, 11), date(2027, 3, 18)), (8, 10), "prof6")
    histologia.append((date(2027, 3, 22), (8, 10), T4[3], "prof6"))       # DOCENTE × Anatomia (prof6, 22/03)
    familia = _encontros((date(2027, 3, 5), date(2027, 3, 12), date(2027, 3, 19), date(2027, 3, 26)), (13, 15), "prof5")
    familia.append((date(2027, 3, 16), (14, 16), "Visita técnica", "prof5"))   # TURMA × Bioquímica (13h–15h)
    familia.append((date(2027, 2, 9), (13, 15), "Aula inaugural", "prof5"))    # CALENDÁRIO: Carnaval
    return [
        ("cruzamento_1_anatomia.docx", "Anatomia Humana II (DEMO)", "A", "Laboratório de Anatomia", anatomia),
        ("cruzamento_2_fisiologia.pdf", "Fisiologia II (DEMO)", "A", "Sala 110 — Bloco B", fisiologia),
        ("cruzamento_3_bioquimica.xlsx", "Bioquímica II (DEMO)", "B", "Sala 112 — Bloco B", bioquimica),
        ("cruzamento_4_histologia.pdf", "Histologia II (DEMO)", "B", "Laboratório de Microscopia", histologia),
        ("cruzamento_5_saude_da_familia.docx", "Saúde da Família II (DEMO)", "B", "Sala 105 — Bloco C", familia),
    ]


def gerar_cruzamento(semestre, coordenador, dominio=D):
    """{nome do arquivo: bytes}. Cria os componentes dentro de uma transação que é desfeita."""
    arquivos = {}
    docentes = {u.email.split("@")[0]: u for u in Usuario.objects.filter(email__endswith="@" + dominio)}
    with transaction.atomic():
        for arquivo, nome, turma, local, encontros in cronogramas_para_cruzamento():
            if arquivo.endswith(".xlsx"):
                arquivos[arquivo] = gerar_planilha(
                    [(nome, "", "2º", turma, "Tarde", dia, f"{i:02d}h-{f:02d}h", tema, "T", "Aula expositiva dialogada",
                      "Datashow e quadro", "TODOS", f"{login}@{dominio}", "", local) for dia, (i, f), tema, login in encontros],
                    titulo=f"CRONOGRAMA DE AULAS — {semestre.nome} — dados fictícios",
                )
                continue
            comp = Componente.objects.create(
                nome=nome, turma=turma, periodo="2º", semestre=semestre, coordenador=coordenador, carga_horaria=40,
                ch_teorica=40, data_inicio=min(e[0] for e in encontros), data_fim=max(e[0] for e in encontros), local_padrao=local,
            )
            for dia, (i, f), tema, login in encontros:
                Encontro.objects.create(
                    componente=comp, data=dia, hora_inicio=time(i), hora_fim=time(f), conteudo=tema, tipo="T",
                    atividade="Aula expositiva dialogada", recursos="Datashow e quadro", grupos="TODOS",
                    professor=docentes[login], ch=ch_padrao(time(i), time(f)), local=local,
                )
            linhas = exports.linhas_cronograma(comp)
            gerar = exports.gerar_docx if arquivo.endswith(".docx") else exports.gerar_pdf
            arquivos[arquivo] = gerar(comp, linhas, False)
        transaction.set_rollback(True)
    return arquivos


class Command(BaseCommand):
    help = "Gera os arquivos de exemplo da importação em exemplos/ (dados fictícios)."

    def add_arguments(self, parser):
        parser.add_argument("--destino", default="exemplos")

    def handle(self, *args, **opts):
        destino = Path(opts["destino"])
        destino.mkdir(parents=True, exist_ok=True)
        titulo = "CRONOGRAMA DE AULAS — 2027.1 (DEMONSTRAÇÃO) — dados fictícios"
        for nome, linhas in (("cronograma_exemplo.xlsx", linhas_validas()), ("cronograma_exemplo_com_erros.xlsx", linhas_com_erros())):
            (destino / nome).write_bytes(gerar_planilha(linhas, titulo=titulo))
            self.stdout.write(f"{destino / nome}: {len(linhas)} linhas")

        semestre = Semestre.objects.filter(nome__startswith="2027.1 (DEMO").first()
        coordenador = Usuario.objects.filter(email=f"coord2@{D}").first()
        if not (semestre and coordenador):
            self.stdout.write(self.style.WARNING(
                "Exemplos de cruzamento (DOCX/PDF) não gerados: execute antes \"python manage.py seed_demo\"."
            ))
            return
        for nome, dados in gerar_cruzamento(semestre, coordenador).items():
            (destino / nome).write_bytes(dados)
            self.stdout.write(f"{destino / nome}: {len(dados) // 1024} KB")
