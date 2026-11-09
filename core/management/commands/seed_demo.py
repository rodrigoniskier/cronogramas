"""Carrega dados FICTÍCIOS de demonstração para o piloto técnico.

Uso:  python manage.py seed_demo [--reset]

A senha dos usuários de demonstração NÃO fica no código: é lida da variável
de ambiente CRONOMED_DEMO_PASSWORD ou, na ausência, gerada aleatoriamente e
exibida uma única vez no terminal.
"""
import os
import secrets
from datetime import date, time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Componente, DataBloqueada, Encontro, HorarioSemanal, Semestre, Usuario
from core.services import gerar_encontros, sincronizar_conflitos

DOMINIO = "demo.cronomed.example"
SEMESTRE = "2027.1 (DEMONSTRAÇÃO)"

USUARIOS = [
    ("admin", "Administração Demo (fictício)", "ADMIN"),
    ("coord1", "Helena Duarte (coord. fictícia)", "COORD"),
    ("coord2", "Marcos Teles (coord. fictício)", "COORD"),
    ("coord3", "Lívia Sarmento (coord. fictícia)", "COORD"),
    ("prof1", "Rafael Moura (prof. fictício)", "PROF"),
    ("prof2", "Beatriz Lacerda (profa. fictícia)", "PROF"),
    ("prof3", "Caio Nóbrega (prof. fictício)", "PROF"),
    ("prof4", "Daniela Pires (profa. fictícia)", "PROF"),
    ("prof5", "Eduardo Vilar (prof. fictício)", "PROF"),
    ("prof6", "Fernanda Queiroz (profa. fictícia)", "PROF"),
    ("prof7", "Gustavo Arruda (prof. fictício)", "PROF"),
    ("prof8", "Isabela Monteiro (profa. fictícia)", "PROF"),
]

TEMAS = [
    "Apresentação do componente e pactuação do contrato didático",
    "Anamnese: identificação e queixa principal",
    "História da doença atual",
    "Antecedentes pessoais e familiares",
    "Sinais vitais: técnica e interpretação",
    "Exame físico geral",
    "Raciocínio clínico I",
    "Comunicação médico-paciente",
    "Ética e profissionalismo",
    "Raciocínio clínico II",
    "Discussão de casos integradores",
    "Avaliação formativa",
]
ATIVIDADES = ["Aula expositiva dialogada", "Prática em laboratório", "Discussão em pequenos grupos", "Simulação", "TBL"]


class Command(BaseCommand):
    help = "Carrega dados fictícios de demonstração (usuários, componentes, conflitos intencionais)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Remove os dados de demonstração existentes antes de recriar.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if Semestre.objects.filter(nome=SEMESTRE).exists():
            if not opts["reset"]:
                raise CommandError("Os dados de demonstração já existem. Use --reset para recriá-los.")
            Componente.objects.filter(semestre__nome=SEMESTRE).delete()
            Semestre.objects.filter(nome=SEMESTRE).delete()

        senha = os.environ.get("CRONOMED_DEMO_PASSWORD")
        gerada = not senha
        if gerada:
            senha = secrets.token_urlsafe(9)

        u = {}
        for login, nome, perfil in USUARIOS:
            email = f"{login}@{DOMINIO}"
            obj, _ = Usuario.objects.get_or_create(email=email, defaults={"nome": nome, "perfil": perfil})
            obj.nome, obj.perfil, obj.is_active = nome, perfil, True
            obj.is_staff = obj.is_superuser = perfil == "ADMIN"
            obj.precisa_trocar_senha = False
            obj.set_password(senha)
            obj.save()
            u[login] = obj

        sem = Semestre.objects.create(
            nome=SEMESTRE, data_inicio=date(2027, 2, 1), data_fim=date(2027, 6, 30),
            preenchimento_liberado=True, liberado_em=timezone.now(),
        )
        DataBloqueada.objects.create(semestre=sem, data=date(2027, 2, 8), descricao="Carnaval (fictício p/ demonstração)")
        DataBloqueada.objects.create(semestre=sem, data=date(2027, 2, 9), descricao="Carnaval (fictício p/ demonstração)")

        ini, fim = date(2027, 2, 1), date(2027, 3, 12)

        def comp(nome, codigo, turma, turno, coord, profs, horarios, local):
            c = Componente.objects.create(
                nome=nome, codigo=codigo, turma=turma, turno=turno, semestre=sem, carga_horaria=60,
                ch_teorica=30, ch_pratica=30, periodo="4º", curso="Medicina",
                coordenador=u[coord], data_inicio=ini, data_fim=fim, local_padrao=local,
            )
            c.professores.set([u[p] for p in profs])
            HorarioSemanal.objects.bulk_create(
                [HorarioSemanal(componente=c, dia_semana=d, hora_inicio=time(*a), hora_fim=time(*b)) for d, a, b in horarios]
            )
            gerar_encontros(c)
            return c

        def preencher(c, rodizio, quantos=None):
            """Preenche os `quantos` primeiros encontros alternando os docentes."""
            encontros = list(c.encontros.all())
            for i, e in enumerate(encontros[: quantos if quantos is not None else len(encontros)]):
                e.conteudo = TEMAS[i % len(TEMAS)]
                e.professor = u[rodizio[i % len(rodizio)]]
                e.atividade = ATIVIDADES[i % len(ATIVIDADES)]
                e.tipo = "P" if i % 2 else "T"
                e.recursos = "Datashow, computador e quadro"
                e.grupos = "TODOS"
                e.atualizado_por, e.atualizado_em = c.coordenador, timezone.now()
                e.save()

        def alocar(c, dia, login):
            e = c.encontros.get(data=dia)
            e.professor = u[login]
            e.conteudo = e.conteudo or "Tema a confirmar"
            e.save()

        # 1) MAPD II — Turma A: seg e qua 13h–15h30 (parcialmente preenchido)
        mapd = comp("MAPD II (DEMO)", "DEMO-01", "A", "TARDE", "coord1", ["prof1", "prof2", "prof3"],
                    [(0, (13, 0), (15, 30)), (2, (13, 0), (15, 30))], "Sala 201 — Bloco D")
        preencher(mapd, ["prof1", "prof3"], quantos=7)
        # 2) Habilidades Clínicas II — Turma B: seg 14h30–17h e qua 15h30–18h (parcial)
        hab = comp("Habilidades Clínicas II (DEMO)", "DEMO-02", "B", "TARDE", "coord2", ["prof1", "prof3", "prof4", "prof5"],
                   [(0, (14, 30), (17, 0)), (2, (15, 30), (18, 0))], "Laboratório de Habilidades")
        preencher(hab, ["prof4", "prof5"], quantos=5)
        # 3) Morfofuncional II — Turma A: ter e sex 8h–10h (completo, sem conflitos)
        morfo = comp("Morfofuncional II (DEMO)", "DEMO-03", "A", "MANHA", "coord3", ["prof6", "prof7"],
                     [(1, (8, 0), (10, 0)), (4, (8, 0), (10, 0))], "Laboratório Morfofuncional")
        preencher(morfo, ["prof6", "prof7"])
        # 4) Saúde Coletiva II — Turma B: qua 15h–17h30 (parcial)
        saude = comp("Saúde Coletiva II (DEMO)", "DEMO-04", "B", "TARDE", "coord2", ["prof2", "prof8"],
                     [(2, (15, 0), (17, 30))], "Sala 105 — Bloco C")
        preencher(saude, ["prof8"], quantos=2)

        # Conflito intencional 1: prof1 em 15/02/2027 — MAPD II 13h–15h30 x Habilidades 14h30–17h
        alocar(mapd, date(2027, 2, 15), "prof1")
        alocar(hab, date(2027, 2, 15), "prof1")
        # Conflito intencional 2: prof2 em 24/02/2027 — MAPD II 13h–15h30 x Saúde Coletiva 15h–17h30
        alocar(mapd, date(2027, 2, 24), "prof2")
        alocar(saude, date(2027, 2, 24), "prof2")
        # Contraexemplo (NÃO é conflito): prof3 em 17/02/2027 — MAPD II 13h–15h30 e Habilidades 15h30–18h
        alocar(mapd, date(2027, 2, 17), "prof3")
        alocar(hab, date(2027, 2, 17), "prof3")

        sincronizar_conflitos()

        w = self.stdout.write
        w(self.style.SUCCESS("\nDados FICTÍCIOS de demonstração carregados."))
        w(f"Semestre: {SEMESTRE} — 4 componentes, {Encontro.objects.filter(componente__semestre=sem).count()} encontros.")
        w("Usuários (login por e-mail):")
        for login, nome, perfil in USUARIOS:
            w(f"  {login}@{DOMINIO:<24} {perfil:<6} {nome}")
        if gerada:
            w(self.style.WARNING(f"\nSenha de demonstração (gerada agora, exibida só desta vez): {senha}"))
        else:
            w("\nSenha de demonstração: valor de CRONOMED_DEMO_PASSWORD.")
        w("Não utilize estes usuários em produção.\n")
