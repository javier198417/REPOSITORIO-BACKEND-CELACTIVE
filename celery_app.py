from celery import Celery

celery = Celery(
    'celery_app',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

# Agrega esta línea para forzar una compatibilidad mayor
celery.conf.broker_transport_options = {'fanout_patterns': True, 'fanout_prefix': True}
celery.conf.redis_max_connections = 20