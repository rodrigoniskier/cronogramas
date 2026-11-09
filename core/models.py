from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

DIAS_SEMANA = [
    (0, "Segunda-feira"),
    (1, "Terça-feira"),
    (2, "Quarta-feira"),
    (3, "Quinta-feira"),
    (4, "Sexta-feira"),
    (5, "Sábado"),
    (6, "Domingo"),
]
NOME_DIA = dict(DIAS_SEMANA)


def hora_modelo(t):
    """Formato do cronograma institucional: 15h30, 18h, 08h."""
    return f"{t.hour:02d}h{t.minute:02d}" if t.minute else f"{t.hour:02d}h"


def ch_padrao(inicio, fim):
    """CH sugerida do encontro em horas-aula de 50 minutos (15h30–18h = 3h)."""
    minutos = (fim.hour * 60 + fim.minute) - (inicio.hour * 60 + inicio.minute)
    return f"{max(1, round(minutos / 50))}h"


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _campo_login(self, identificador):
        identificador = identificador.strip().lower()
        campo = self.model.USERNAME_FIELD if "@" in identificador else "username"
        return {campo: identificador}

    def get_by_natural_key(self, username):
        return self.get(**self._campo_login(username))

    async def aget_by_natural_key(self, username):
        return await self.aget(**self._campo_login(username))

    def _criar(self, email, password, **extra):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        usuario = self.model(email=self.normalize_email(email).lower(), **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._criar(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        extra["perfil"] = Usuario.Perfil.ADMIN
        return self._criar(email, password, **extra)


class Usuario(AbstractUser):
    """Cadastro central de pessoas. Docentes são sempre referenciados por ID."""

    class Perfil(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        COORD = "COORD", "Coordenador"
        PROF = "PROF", "Professor"

    username = models.CharField(
        "nome de usuário",
        max_length=150,
        unique=True,
        null=True,
        blank=True,
        help_text="Use letras sem acento, números, ponto, hífen ou sublinhado.",
        validators=[RegexValidator(
            r"\A[a-zA-Z0-9._-]+\Z",
            "Use apenas letras sem acento, números, ponto, hífen ou sublinhado.",
        )],
    )
    first_name = None
    last_name = None
    email = models.EmailField("e-mail", unique=True)
    nome = models.CharField("nome completo", max_length=150)
    perfil = models.CharField(max_length=5, choices=Perfil.choices, default=Perfil.PROF)
    precisa_trocar_senha = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nome"]
    objects = UsuarioManager()

    class Meta:
        ordering = ["nome"]
        verbose_name = "usuário"

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        self.username = (self.username or "").strip().lower() or None
        super().save(*args, **kwargs)

    @property
    def eh_admin(self):
        return self.perfil == self.Perfil.ADMIN

    @property
    def eh_coordenador(self):
        return self.perfil == self.Perfil.COORD

    @property
    def eh_professor(self):
        return self.perfil == self.Perfil.PROF

    @classmethod
    def docentes(cls):
        """Quem pode ser alocado em aulas: professores e coordenadores ativos."""
        return cls.objects.filter(
            is_active=True, perfil__in=[cls.Perfil.PROF, cls.Perfil.COORD]
        )


class Configuracao(models.Model):
    """Configuração institucional (registro único)."""

    instituicao = models.CharField(
        max_length=200, default="Centro Universitário de João Pessoa — UNIPÊ"
    )
    logo = models.FileField(upload_to="branding/", blank=True)

    @classmethod
    def obter(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def caminho_logo(self):
        """Caminho do arquivo da logomarca, ou None se não houver."""
        from pathlib import Path

        if self.logo:
            p = Path(self.logo.path)
            if p.exists():
                return p
        if settings.LOGO_PADRAO.exists():
            return settings.LOGO_PADRAO
        return None


class Semestre(models.Model):
    nome = models.CharField("semestre letivo", max_length=40, unique=True, help_text="Ex.: 2027.1")
    data_inicio = models.DateField("início")
    data_fim = models.DateField("término")
    preenchimento_liberado = models.BooleanField(default=False)
    liberado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-data_inicio"]

    def __str__(self):
        return self.nome

    def clean(self):
        if self.data_inicio and self.data_fim and self.data_fim < self.data_inicio:
            raise ValidationError("O término deve ser posterior ao início.")


class DataBloqueada(models.Model):
    class Tipo(models.TextChoices):
        FERIADO = "FERIADO", "Feriado"
        BLOQUEIO = "BLOQUEIO", "Data bloqueada"

    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, related_name="datas_bloqueadas")
    data = models.DateField()
    descricao = models.CharField("descrição", max_length=120)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.FERIADO)

    class Meta:
        ordering = ["data"]
        constraints = [
            models.UniqueConstraint(fields=["semestre", "data"], name="data_bloqueada_unica")
        ]

    def __str__(self):
        return f"{self.data:%d/%m/%Y} — {self.descricao}"


class Componente(models.Model):
    class Turno(models.TextChoices):
        MANHA = "MANHA", "Manhã"
        TARDE = "TARDE", "Tarde"
        NOITE = "NOITE", "Noite"
        INTEGRAL = "INTEGRAL", "Integral"

    class Situacao(models.TextChoices):
        RASCUNHO = "RASCUNHO", "Em elaboração"
        APROVADO = "APROVADO", "Aprovado"
        PUBLICADO = "PUBLICADO", "Publicado"

    curso = models.CharField(max_length=80, default="Medicina")
    nome = models.CharField("componente curricular", max_length=150)
    periodo = models.CharField("período do curso", max_length=20, blank=True, help_text="Ex.: 4º")
    codigo = models.CharField("código", max_length=30, blank=True)
    turma = models.CharField(max_length=30)
    turno = models.CharField(max_length=10, choices=Turno.choices, default=Turno.TARDE)
    semestre = models.ForeignKey(Semestre, on_delete=models.PROTECT, related_name="componentes")
    carga_horaria = models.PositiveIntegerField("carga horária total (h/a)", default=0)
    ch_teorica = models.PositiveIntegerField("CH teórica (h/a)", default=0)
    ch_pratica = models.PositiveIntegerField("CH prática (h/a)", default=0)
    coordenador = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="componentes_coordenados"
    )
    professores = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="componentes_vinculados", blank=True
    )
    data_inicio = models.DateField("data inicial")
    data_fim = models.DateField("data final")
    local_padrao = models.CharField("local padrão", max_length=120, blank=True)

    situacao = models.CharField(max_length=10, choices=Situacao.choices, default=Situacao.RASCUNHO)
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    aprovado_em = models.DateTimeField(null=True, blank=True)
    publicado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    publicado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome", "turma"]
        constraints = [
            models.UniqueConstraint(
                fields=["nome", "turma", "semestre"], name="componente_turma_semestre_unico"
            )
        ]

    def __str__(self):
        return f"{self.nome} — Turma {self.turma}"

    @property
    def bloqueado(self):
        return self.situacao != self.Situacao.RASCUNHO


class HorarioSemanal(models.Model):
    componente = models.ForeignKey(Componente, on_delete=models.CASCADE, related_name="horarios")
    dia_semana = models.PositiveSmallIntegerField(choices=DIAS_SEMANA)
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()

    class Meta:
        ordering = ["dia_semana", "hora_inicio"]

    def __str__(self):
        return f"{self.get_dia_semana_display()} {self.hora_inicio:%H:%M}–{self.hora_fim:%H:%M}"

    @property
    def duracao_minutos(self):
        return (self.hora_fim.hour * 60 + self.hora_fim.minute) - (
            self.hora_inicio.hour * 60 + self.hora_inicio.minute
        )


class Encontro(models.Model):
    componente = models.ForeignKey(Componente, on_delete=models.CASCADE, related_name="encontros")
    data = models.DateField()
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()
    conteudo = models.TextField("conteúdo programático", blank=True)
    professor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="encontros"
    )
    TIPOS = [("", "—"), ("T", "T — Teórica"), ("P", "P — Prática"), ("T/P", "T/P — Teórico-prática"), ("-", "- (sem aula)")]
    tipo = models.CharField(max_length=3, choices=TIPOS, blank=True)
    atividade = models.TextField("atividades", blank=True)
    recursos = models.TextField(blank=True)
    grupos = models.CharField(max_length=300, blank=True)
    ch = models.CharField("CH", max_length=10, blank=True)
    local = models.CharField(max_length=120, blank=True)
    observacoes = models.TextField("observações", blank=True)
    excepcional = models.BooleanField(default=False)

    versao = models.PositiveIntegerField(default=1)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    atualizado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["data", "hora_inicio", "id"]
        # Mais de uma linha no mesmo dia/horário é permitida: o modelo institucional
        # prevê vários docentes (ou grupos) no mesmo encontro, um por linha.
        constraints = [
            models.CheckConstraint(
                condition=models.Q(hora_fim__gt=models.F("hora_inicio")), name="encontro_fim_apos_inicio"
            ),
        ]
        indexes = [models.Index(fields=["professor", "data"])]

    def __str__(self):
        return f"{self.componente} — {self.descricao}"

    @property
    def descricao(self):
        return f"{self.data:%d/%m/%Y} {self.hora_inicio:%H:%M}–{self.hora_fim:%H:%M}"

    @property
    def horario_modelo(self):
        return f"{hora_modelo(self.hora_inicio)}-{hora_modelo(self.hora_fim)}"

    @property
    def dia_semana(self):
        return NOME_DIA[self.data.weekday()]

    @property
    def preenchido(self):
        return bool(self.professor_id and self.conteudo.strip())


class Conflito(models.Model):
    """Sobreposição de horário do mesmo docente em dois encontros distintos."""

    class Status(models.TextChoices):
        ATIVO = "ATIVO", "Ativo"
        RESOLVIDO = "RESOLVIDO", "Resolvido"

    encontro_a = models.ForeignKey(Encontro, on_delete=models.CASCADE, related_name="conflitos_a")
    encontro_b = models.ForeignKey(Encontro, on_delete=models.CASCADE, related_name="conflitos_b")
    professor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conflitos")
    data = models.DateField()
    sobreposicao_inicio = models.TimeField()
    sobreposicao_fim = models.TimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ATIVO)
    detectado_em = models.DateTimeField(auto_now_add=True)
    resolvido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "data", "sobreposicao_inicio"]
        constraints = [
            models.UniqueConstraint(
                fields=["encontro_a", "encontro_b", "professor"], name="conflito_unico_por_par"
            )
        ]

    @property
    def ativo(self):
        return self.status == self.Status.ATIVO


class ObservacaoConflito(models.Model):
    conflito = models.ForeignKey(Conflito, on_delete=models.CASCADE, related_name="observacoes")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["criado_em"]


class HistoricoAlteracao(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    data_hora = models.DateTimeField(auto_now_add=True)
    componente = models.ForeignKey(Componente, on_delete=models.CASCADE, related_name="historico")
    encontro = models.ForeignKey(Encontro, on_delete=models.SET_NULL, null=True, blank=True, related_name="historico")
    encontro_descricao = models.CharField(max_length=60, blank=True)
    campo = models.CharField(max_length=40)
    valor_anterior = models.TextField(blank=True)
    valor_novo = models.TextField(blank=True)

    class Meta:
        ordering = ["-data_hora", "-id"]
