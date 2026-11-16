from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.crypto import salted_hmac


class User(AbstractUser):
    """TRACE identity, established before any application migrations."""
    version = models.PositiveIntegerField(default=1)
    session_version = models.PositiveIntegerField(default=1)

    def _get_session_auth_hash(self, secret=None):
        """Invalidate all sessions on administrative access changes, including reactivation.

        Django's public session/fallback helpers both call this hook, preserving
        password-change invalidation and SECRET_KEY_FALLBACKS behavior.
        """
        # Preserve existing session hashes when changing the product name.
        return salted_hmac("tdt.accounts.User.session_auth", f"{self.password}:{self.session_version}",
                           secret=secret, algorithm="sha256").hexdigest()


class LoginThrottle(models.Model):
    """HMAC bucket identifiers; never store submitted passwords or raw usernames."""
    key = models.CharField(max_length=64, primary_key=True)
    window_started = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
