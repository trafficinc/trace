# Install TRACE on a private host

Use **Python 3.13** and local disk outside network/synchronized folders. Keep the complete source release, including templates, static assets, scripts and dependency locks. SQLite is the default; [PostgreSQL](postgresql.md) is optional.

## Linux native installation

Example for **Debian 13**. Other distributions need supported Python 3.13 and matching native packages.

```sh
sudo apt-get update
sudo apt-get install python3.13 python3.13-venv libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core nginx
# Unpack the reviewed release into a directory you own, then enter it.
umask 077
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements/runtime.txt
python scripts/vendor_assets.py --check
python manage.py migrate --noinput
python manage.py configure_sqlite
python manage.py createsuperuser
python scripts/serve.py --development
```

Open `http://127.0.0.1:8000` and sign in with the administrator you created. Startup generates no credentials. Create ordinary users and engagement memberships in the application. This development launcher serves local assets over loopback HTTP.

Development commands default to development settings; WSGI/ASGI and production startup default to production. Native commands do **not** load `.env` automatically. Use the protected shell/service environment; [.env.example](../.env.example) lists variables.

## macOS

Use a local APFS directory outside cloud-synchronized folders. With Homebrew available:

```sh
brew install python@3.13 pango libffi
umask 077
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements/runtime.txt
python scripts/vendor_assets.py --check
python manage.py migrate --noinput
python manage.py configure_sqlite
python manage.py createsuperuser
python scripts/serve.py --development
```

Apple Silicon detects `/opt/homebrew/lib`; Intel hosts can set `TRACE_REPORT_WEASYPRINT_DLL_DIRECTORIES=/usr/local/lib`. See [report dependencies](reports.md#offline-pdf-dependencies) for library/font details.

## Windows developer computer

Use **WSL2**; native Windows Python lacks the required POSIX storage safeguards.

From an administrator PowerShell terminal:

```powershell
wsl --install -d Debian
wsl --set-default-version 2
wsl -d Debian
```

Inside WSL Debian 13, follow the Linux commands. Keep files under the Linux home directory (for example `~/trace`), outside `/mnt/c`, OneDrive and network drives. Open `http://localhost:8000` from Windows. Docker Desktop with WSL2 integration is also supported below.

## Native production service and HTTPS

Run on a private machine/LAN/VPN behind a trusted HTTPS proxy. Keep Waitress on loopback and expose only intended proxy listeners/networks. Do not publish directly to the internet.

1. Create a dedicated unprivileged `trace` OS account. On Debian, an administrator can prepare ownership with:

```sh
sudo useradd --system --home-dir /var/lib/trace --shell /usr/sbin/nologin trace
sudo install -d -o trace -g trace -m 0700 /var/lib/trace /var/lib/trace-recovery /etc/trace
sudo install -d -o trace -g trace -m 0750 /opt/trace/releases
```

Keep releases under `/opt/trace/releases`, private storage under `/var/lib/trace` and protected configuration under `/etc/trace`. Point `/opt/trace/current` at the selected release.

2. Prepare the release and protected environment file below. Fill in the real hostname/origin, storage path and random secret before continuing. Generate a secret for private entry with `python -c "import secrets; print(secrets.token_urlsafe(64))"`; never commit it or pass credentials as command arguments.
After unpacking the reviewed release at `/opt/trace/releases/0.1.0`, prepare its virtualenv and initial configuration (adjust the version directory for each release):

```sh
sudo ln -s /opt/trace/releases/0.1.0 /opt/trace/current
sudo -u trace python3.13 -m venv /opt/trace/current/.venv
sudo -u trace /opt/trace/current/.venv/bin/python -m pip install -r /opt/trace/current/requirements/runtime.txt
sudo install -o trace -g trace -m 0600 deploy/trace.env.example /etc/trace/trace.env
```

Fill in the protected environment file before continuing; do not overwrite an existing installation's configuration or secret during updates.

3. As `trace`, load that environment explicitly and initialize the stopped service:

```sh
cd /opt/trace/current
set -a
. /etc/trace/trace.env
set +a
umask 077
. .venv/bin/activate
python manage.py migrate --noinput --settings=config.settings.production
python manage.py configure_sqlite --settings=config.settings.production
python manage.py collectstatic --noinput --settings=config.settings.production
python manage.py createsuperuser --settings=config.settings.production
python manage.py check --deploy --fail-level WARNING --settings=config.settings.production
```

4. Install a trusted private-CA certificate/key; clients must trust the CA. Adapt `deploy/nginx.conf` in nginx's `http` context and disable unwanted default sites. For LAN use, bind nginx to a specific private interface and restrict firewall/DNS access. Keep Waitress on loopback.
5. Install `deploy/trace.service` as `/etc/systemd/system/trace.service`, then run:

```sh
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl daemon-reload
sudo systemctl enable --now trace
sudo systemctl status trace
```

Startup enforces production checks and refuses pending migrations; it never migrates or creates accounts. `TRACE_BIND_HOST`/`TRACE_BIND_PORT` default to `127.0.0.1:8000`. Keep the backend reachable only by the proxy. Waitress accepts `X-Forwarded-Proto` only from `TRACE_PROXY_IP`; nginx must overwrite forwarded headers. Throttling uses the WSGI peer. Do not disguise plain HTTP with `--url-scheme=https`.

Production requires secure cookies, explicit hosts/origins, a private secret and HTTPS. HSTS covers the configured host for one year; W005/W021 are silenced because unrelated subdomains/preload are excluded. Only minimal `/health/` readiness is exempt from HTTPS redirects.

## Docker Compose, still SQLite-first

Default Compose starts one application container using the private `tdt-data` volume. Host publication is `127.0.0.1:8000`; place a trusted HTTPS proxy in front.

Create a private Compose environment file from `deploy/compose.env.example`, fill in its secret and real hostname, then:

```sh
docker compose --env-file /private/path/trace-compose.env build
docker compose --env-file /private/path/trace-compose.env run --rm trace python manage.py migrate --noinput
docker compose --env-file /private/path/trace-compose.env run --rm trace python manage.py configure_sqlite
docker compose --env-file /private/path/trace-compose.env run --rm trace python manage.py createsuperuser
docker compose --env-file /private/path/trace-compose.env run --rm trace python manage.py check --deploy --fail-level WARNING
docker compose --env-file /private/path/trace-compose.env up -d --no-build
docker compose --env-file /private/path/trace-compose.env ps
```

The image includes PDF dependencies/static assets and runs as UID 10001 with capabilities dropped. Bind mounts must match that ownership. Keep runtime data/secrets outside images. Never run `down --volumes` on a real installation.

The bridge uses `172.30.86.0/29`, gateway/proxy `.1` and application `.2`. Resolve subnet conflicts by adjusting IPAM and `TRACE_PROXY_IP` together. Verify the actual proxy peer and HTTPS redirects; never trust `*`. `TRACE_PUBLISH_IP`/`TRACE_PUBLISH_PORT` control publication and default to loopback/8000.

### Self-contained Compose HTTPS option

To use a local proxy container instead of host nginx, copy `deploy/compose-https.env.example` to your protected environment file. Supply the real hostname/origin, secret, and an absolute private TLS directory containing `trace.crt` and `trace.key`; keep its private key mode `0600`. Clients must trust the issuing private CA. Set `TRACE_PROXY_IP=172.30.86.3` for this profile, rather than the host gateway used by the host-proxy option.

After the one-time migration/administrator commands above:

```sh
docker compose --env-file PRIVATE_ENV --profile https up -d --no-build
```

HTTPS defaults to `https://localhost:8443`. Coordinate DNS/certificate, `TRACE_PROXY_SERVER_NAME`, allowed hosts and HTTPS origin for a private hostname. Set `TRACE_HTTPS_PUBLISH_IP` explicitly for LAN access. The proxy shares the bridge, mounts certificates/configuration read-only and has no private-data volume.

Keep `--profile https` on proxy lifecycle commands. For offline use, prepare and transfer both application and verified nginx images before `--pull never`. Deployment certificates remain operator-supplied.

## Offline installation

Prepare on a connected machine matching the target **Python 3.13, operating system, CPU architecture and Linux ABI**:

```sh
python3.13 -m venv prep-venv
. prep-venv/bin/activate
python scripts/prepare_offline.py --directory wheelhouse
# Add --postgres and/or --test when those optional dependencies are needed.
python scripts/vendor_assets.py --check
python scripts/verify_wheels.py wheelhouse
```

Transfer the reviewed release, binary wheelhouse, Python runtime and matching signed OS PDF/font packages. Wheels do not include Python or Pango. Keep `SHA256SUMS.json` separately trusted; hashes are not signatures. For Debian, use `apt-get --download-only install` on a matching Debian 13 host and transfer packages/dependencies or an approved offline repository. Do not mix releases/architectures.

On the isolated target, with those OS prerequisites installed:

```sh
umask 077
python3.13 -m venv .venv
. .venv/bin/activate
python scripts/verify_wheels.py /media/transfer/wheelhouse
python -m pip install --no-index --find-links /media/transfer/wheelhouse -r requirements/runtime.txt
python -m pip check
python scripts/vendor_assets.py --check
```

Then use the native initialization/production commands above. No package downloads, font services or runtime network access are required. For optional PostgreSQL use `requirements/postgres.txt` and a wheelhouse prepared with `--postgres`; for tests use `requirements/test.txt` and `--test`.

For offline Docker, build and test the image on a connected compatible host, then transfer the completed image rather than trying to run `apt` or `pip` on the isolated server:

```sh
docker save trace-local:0.1.0 -o trace-image.tar
# If using the HTTPS profile, also pull/save/load its reviewed nginx image.
# Transfer the image plus a separately verified checksum and release configuration.
docker load -i trace-image.tar
docker compose --env-file /private/path/trace-compose.env up -d --no-build --pull never
```

Run one-time migration/admin setup before startup. Pin verified image digests or retain immutable image IDs; review and retest rebuilt images.

See [operations and recovery](operations.md) for backups, restore, health, restart and updates, and [PostgreSQL](postgresql.md) for the optional database path.

## Release tooling and resource defaults

Optional `requirements/quality.txt` pins lint/type/security tools; it is not needed at runtime. Prepare its wheels with `python scripts/prepare_offline.py --quality --directory NEW_WHEEL_DIRECTORY` on a matching connected machine. Advisory queries need internet access; ordinary tests, rendering and local assets do not.

Tune Waitress/nginx connections, body/header/time limits and temporary space together with upload/report limits. Defaults include 32 Waitress connections, 16 KiB headers and bounded Compose temporary mounts. Use [storage controls](storage-controls.md), host quotas and monitoring for evidence, reports, backups and proxy buffers.

Production serves collected static assets through WhiteNoise. Private storage must never be published.
