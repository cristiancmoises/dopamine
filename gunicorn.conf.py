"""HTTP has no published host port. Trust only exact NPM peers on the shared bridge."""
import os
bind='0.0.0.0:8000'
workers=int(os.environ.get('WEB_WORKERS','2'))
threads=2
worker_class='gthread'
worker_connections=64
preload_app=True
max_requests=1200
max_requests_jitter=100
timeout=30
graceful_timeout=30
keepalive=3
backlog=128
limit_request_line=2048
limit_request_fields=32
limit_request_field_size=8190
worker_tmp_dir='/tmp'
umask=0o077
accesslog='-'
errorlog='-'
loglevel='info'
# Deliberately omit IP, query string, cookies, passwords, referrer and user agent.
access_log_format='%(m)s %(U)s %(s)s %(D)s'
# Trust is enforced once by the application, against the exact NPM peer IP.
# Never trust arbitrary SCRIPT_NAME/PATH_INFO or forwarded TLS headers here.
secure_scheme_headers={}
forwarded_allow_ips=''
forwarder_headers=""
proxy_protocol=False
permit_obsolete_folding=False
strip_header_spaces=False
permit_unconventional_http_method=False
permit_unconventional_http_version=False
header_map='refuse'
