"""Readiness probes stay on loopback and never follow redirects or environment proxies."""
import os
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


try:
    port = int(os.environ.get('TRACE_BIND_PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid health port.')
    request = urllib.request.Request(f'http://127.0.0.1:{port}/health/', headers={'Host': os.environ.get('TRACE_HEALTH_HOST', 'localhost')})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=4) as response:
        if response.status != 200 or response.read(256) != b'{"status": "ok"}':
            raise SystemExit(1)
except Exception:
    raise SystemExit(1)
