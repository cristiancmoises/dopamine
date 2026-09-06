#!/usr/bin/env python3
import http.client
import json
import os
import sys
from urllib.parse import urlsplit
try:
    host=urlsplit(os.environ.get('SITE_URL','https://dopamine.securityops.co')).netloc
    conn=http.client.HTTPConnection('127.0.0.1',8000,timeout=4)
    conn.request('GET','/healthz',headers={'Host':host})
    response=conn.getresponse()
    payload=json.loads(response.read(512))
    conn.close()
    sys.exit(0 if response.status==200 and payload.get('status')=='ok' and payload.get('service')=='dopamine' else 1)
except Exception:sys.exit(1)
