from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "CronoMed UNIPÊ"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        def _marcar(sender, request, user, **kwargs):
            request.session["avisar_pendencias"] = True

        user_logged_in.connect(_marcar, dispatch_uid="cronomed_avisar_pendencias", weak=False)
