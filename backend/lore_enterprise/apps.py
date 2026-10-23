from django.apps import AppConfig


class LoreEnterpriseConfig(AppConfig):
    name = 'lore_enterprise'
    verbose_name = 'LORE Enterprise Core'

    def ready(self):
        # Register system checks
        from . import checks  # noqa: F401
