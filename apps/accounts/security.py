from django.utils.crypto import salted_hmac


def fingerprint(kind, value):
    # Stable legacy namespace preserves throttle buckets and audit correlation.
    return salted_hmac(f"tdt.auth.{kind}", str(value)[:512], algorithm="sha256").hexdigest()


def username_fingerprint(username):
    return fingerprint("account", username.strip().casefold())


def source_fingerprint(request):
    # Trust the WSGI peer address only. Never trust client-supplied forwarded headers.
    return fingerprint("source", request.META.get("REMOTE_ADDR", "unknown") if request else "local")
