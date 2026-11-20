import os

try:
    from celery import Celery
    app = Celery('lore_enterprise')
    app.config_from_object('django.conf:settings', namespace='CELERY')
    app.autodiscover_tasks()

    app.conf.beat_schedule = {
        'l0-graph-health-drift-check': {
            'task': 'sources.l0_graph_drift_check',
            'schedule': 600.0,  # 10 minutes
        },
        'connector-incremental-sync': {
            'task': 'sources.connector_incremental_sync',
            'schedule': 900.0,  # 15 minutes
        },
        'live-evidence-refresh': {
            'task': 'sources.live_evidence_refresh',
            'schedule': 300.0,  # 5 minutes
        },
    }

    @app.task(bind=True, ignore_result=True)
    def debug_task(self):
        print(f'Request: {self.request!r}')
except ImportError:
    # Graceful fallback when Celery is not installed on lightweight or bare Windows setups
    class _MockCelery:
        def __init__(self, *args, **kwargs):
            self.conf = type('Conf', (), {'beat_schedule': {}})()
        def config_from_object(self, *args, **kwargs):
            pass
        def autodiscover_tasks(self, *args, **kwargs):
            pass
        def task(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    app = _MockCelery('lore_enterprise')
