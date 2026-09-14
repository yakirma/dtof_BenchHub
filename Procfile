redis:  redis-server --port 6379 --save "" --appendonly no
worker: celery -A app.celery worker --loglevel=info
web:    python run.py
