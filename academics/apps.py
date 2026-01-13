from django.apps import AppConfig


class AcademicsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "academics"
    
    def ready(self):
        # Import signals to register them when the app is ready
        import academics.signals  # noqa: F401