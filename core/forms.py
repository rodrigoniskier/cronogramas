from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Componente, Configuracao, DataBloqueada, Semestre, Usuario


class _Bootstrap:
    """Aplica classes do Bootstrap aos widgets."""

    def _estilizar(self):
        for campo in self.fields.values():
            w = campo.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")


class LoginForm(_Bootstrap, AuthenticationForm):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["username"].label = "E-mail"
        self.fields["username"].widget = forms.EmailInput(attrs={"autofocus": True, "autocomplete": "username"})
        self._estilizar()

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class UsuarioForm(_Bootstrap, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["nome", "email", "perfil", "is_active"]
        labels = {"is_active": "Usuário ativo"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._estilizar()

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class SemestreForm(_Bootstrap, forms.ModelForm):
    class Meta:
        model = Semestre
        fields = ["nome", "data_inicio", "data_fim"]
        widgets = {
            "data_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_fim": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._estilizar()


class DataBloqueadaForm(_Bootstrap, forms.ModelForm):
    class Meta:
        model = DataBloqueada
        fields = ["data", "descricao", "tipo"]
        widgets = {"data": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *a, semestre=None, **kw):
        super().__init__(*a, **kw)
        self.semestre = semestre
        self._estilizar()

    def clean_data(self):
        d = self.cleaned_data["data"]
        s = self.semestre
        if s and not (s.data_inicio <= d <= s.data_fim):
            raise forms.ValidationError("A data deve estar dentro do semestre.")
        if s and DataBloqueada.objects.filter(semestre=s, data=d).exists():
            raise forms.ValidationError("Esta data já está bloqueada.")
        return d


class ComponenteForm(_Bootstrap, forms.ModelForm):
    class Meta:
        model = Componente
        fields = [
            "curso", "nome", "codigo", "periodo", "turma", "turno", "semestre",
            "carga_horaria", "ch_teorica", "ch_pratica",
            "coordenador", "professores", "data_inicio", "data_fim", "local_padrao",
        ]
        widgets = {
            "data_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_fim": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *a, usuario=None, **kw):
        super().__init__(*a, **kw)
        self.usuario = usuario
        self.fields["coordenador"].queryset = Usuario.objects.filter(
            is_active=True, perfil=Usuario.Perfil.COORD
        )
        self.fields["professores"].queryset = Usuario.docentes()
        self.fields["professores"].label = "Professores vinculados"
        if usuario and not usuario.eh_admin:
            # Coordenador cadastra apenas componentes sob sua responsabilidade.
            del self.fields["coordenador"]
        self._estilizar()

    def clean(self):
        dados = super().clean()
        ini, fim, sem = dados.get("data_inicio"), dados.get("data_fim"), dados.get("semestre")
        if ini and fim and fim < ini:
            self.add_error("data_fim", "A data final deve ser posterior à inicial.")
        if ini and fim and sem and (ini < sem.data_inicio or fim > sem.data_fim):
            self.add_error(
                "data_inicio",
                f"O período deve estar dentro do semestre ({sem.data_inicio:%d/%m/%Y} a {sem.data_fim:%d/%m/%Y}).",
            )
        return dados


class ConfiguracaoForm(_Bootstrap, forms.ModelForm):
    class Meta:
        model = Configuracao
        fields = ["instituicao", "logo"]
        labels = {"instituicao": "Identificação institucional", "logo": "Logomarca (PNG ou JPG)"}
        widgets = {"logo": forms.FileInput(attrs={"accept": ".png,.jpg,.jpeg"})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._estilizar()

    def clean_logo(self):
        arq = self.cleaned_data.get("logo")
        if arq and hasattr(arq, "content_type"):
            from PIL import Image

            if arq.size > 3 * 1024 * 1024:
                raise forms.ValidationError("A imagem deve ter no máximo 3 MB.")
            try:
                img = Image.open(arq)
                img.verify()
                if img.format not in ("PNG", "JPEG"):
                    raise ValueError
            except Exception:
                raise forms.ValidationError("Envie uma imagem PNG ou JPG válida.")
            arq.seek(0)
        return arq
