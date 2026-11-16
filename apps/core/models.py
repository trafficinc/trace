from django.conf import settings
from django.db import models


class EditorPresence(models.Model):
    """Expiring server-generated hints; never an editing lock or user draft store."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kind = models.CharField(max_length=24)
    object_id = models.CharField(max_length=36)
    engagement_ref = models.UUIDField(null=True, blank=True)
    seen_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['actor', 'kind', 'object_id'], name='unique_editor_presence')]
        indexes = [models.Index(fields=['engagement_ref', 'kind', 'object_id', 'seen_at'])]
