import os
bind = '0.0.0.0:' + os.getenv('PORT', '5000')
workers = 1
threads = 2
worker_class = 'gthread'
timeout = 180
graceful_timeout = 30
max_requests = 500
max_requests_jitter = 50
accesslog = '-'
errorlog = '-'
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(L)s'
