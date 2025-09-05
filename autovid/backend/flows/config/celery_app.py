from celery import Celery

app = Celery(
    'tasks',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    result_backend='redis://localhost:6379/0',
    task_queues={
        'low_priority': {
            'exchange': 'low_priority',
            'exchange_type': 'direct',
            'binding_key': 'low_priority',
        },
        'medium_priority': {
            'exchange': 'medium_priority',
            'exchange_type': 'direct',
            'binding_key': 'medium_priority',
        },
        'high_priority': {
            'exchange': 'high_priority',
            'exchange_type': 'direct',
            'binding_key': 'high_priority',
        },
    },
    task_default_queue='medium_priority',
    task_default_exchange='medium_priority',
    task_default_routing_key='medium_priority',
)
