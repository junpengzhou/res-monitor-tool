import os

bind = "0.0.0.0:5000"
workers = int(os.environ.get("GUNICORN_WORKERS", "6"))
worker_class = "sync"
timeout = 120
