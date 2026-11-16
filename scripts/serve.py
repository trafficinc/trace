#!/usr/bin/env python3
"""Supported native/container WSGI entry point. No migrations or accounts on boot."""
import argparse
import ipaddress
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default=os.environ.get('TRACE_BIND_HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('TRACE_BIND_PORT','8000')))
    parser.add_argument('--allow-lan',action='store_true',default=os.environ.get('TRACE_ALLOW_LAN')=='1')
    parser.add_argument('--development',action='store_true',help='Local HTTP developer settings; never use behind a public listener.')
    args=parser.parse_args()
    try: address=ipaddress.ip_address(args.host)
    except ValueError: parser.error('Use an explicit IP bind address.')
    if not address.is_loopback and (not args.allow_lan or args.development): parser.error('Non-loopback binding requires --allow-lan and production settings.')
    if not 1<=args.port<=65535: parser.error('Port must be between 1 and 65535.')
    os.environ['DJANGO_SETTINGS_MODULE']='config.settings.development' if args.development else 'config.settings.production'
    os.umask(0o077)
    from config.wsgi import application
    if args.development:
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        application = StaticFilesHandler(application)
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    call_command('check',deploy=not args.development,fail_level='WARNING',verbosity=0)
    executor=MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()): parser.error('Apply migrations during maintenance before starting workers.')
    from waitress import serve
    proxy=settings.TRACE_PROXY_IP if settings.TRACE_TRUST_PROXY else None
    serve(application,host=args.host,port=args.port,threads=4,
          connection_limit=32, channel_timeout=30, cleanup_interval=5,
          max_request_header_size=16*1024, expose_tracebacks=False,
          trusted_proxy=proxy,trusted_proxy_headers={'x-forwarded-proto'} if proxy else set(),
          clear_untrusted_proxy_headers=True,
          max_request_body_size=settings.TRACE_EVIDENCE_MAX_BYTES+4*1024*1024)


if __name__=='__main__':
    try: main()
    except Exception:
        import json
        print(json.dumps({'event':'startup_failed','level':'ERROR','message':'Startup refused. Run the documented configuration/migration checks during maintenance.'}),file=sys.stderr)
        raise SystemExit(1) from None
