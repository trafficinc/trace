import ipaddress
import re
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models


def validate_hostname(value):
    hostname = value.rstrip(".")
    if len(hostname) > 253 or not all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", part) for part in hostname.split(".")):
        raise ValidationError("Enter a valid hostname, such as app01 or app01.internal.")


def validate_ip_cidr(value):
    try:
        ipaddress.ip_interface(value) if "/" in value else ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValidationError("Enter a valid IPv4/IPv6 address or CIDR.") from exc


class Asset(models.Model):
    class Type(models.TextChoices):
        HOST = "host", "Host"
        APPLICATION = "application", "Application"
        NETWORK = "network", "Network"
        SERVICE = "service", "Service"
        OTHER = "other", "Other"

    class ScopeStatus(models.TextChoices):
        IN_SCOPE = "in_scope", "In scope"
        OUT_OF_SCOPE = "out_of_scope", "Out of scope"
        PENDING = "pending", "Pending confirmation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey("engagements.Engagement", on_delete=models.PROTECT, related_name="assets")
    name = models.CharField(max_length=200)
    asset_type = models.CharField(max_length=12, choices=Type.choices, default=Type.HOST)
    hostname = models.CharField(max_length=253, blank=True, validators=[validate_hostname])
    ip_cidr = models.CharField("IP address / CIDR", max_length=64, blank=True, validators=[validate_ip_cidr])
    url = models.URLField("URL", max_length=2048, blank=True, validators=[URLValidator(schemes=["http", "https"])])
    description = models.TextField(max_length=20000, blank=True)
    environment = models.CharField(max_length=100, blank=True)
    scope_status = models.CharField(max_length=12, choices=ScopeStatus.choices, default=ScopeStatus.PENDING)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_assets")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="created_assets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["engagement", field]) for field in ("name", "owner", "scope_status", "asset_type", "environment")]
        constraints = [
            models.CheckConstraint(condition=models.Q(asset_type__in=["host", "application", "network", "service", "other"]), name="valid_asset_type"),
            models.CheckConstraint(condition=models.Q(scope_status__in=["in_scope", "out_of_scope", "pending"]), name="valid_asset_scope"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        errors = {}
        if self.asset_type == self.Type.HOST and not (self.hostname or self.ip_cidr):
            errors["hostname"] = "Hosts need a hostname or IP address."
        if self.asset_type == self.Type.APPLICATION and not self.url:
            errors["url"] = "Applications need an HTTP or HTTPS URL."
        if self.asset_type == self.Type.NETWORK and not self.ip_cidr:
            errors["ip_cidr"] = "Networks need an IP address or CIDR."
        if self.asset_type == self.Type.SERVICE and not (self.hostname or self.ip_cidr or self.url):
            errors["hostname"] = "Services need a hostname, IP address or URL."
        if self.owner_id and self.engagement_id:
            if not self.engagement.memberships.filter(user_id=self.owner_id, user__is_active=True).exists():
                errors["owner"] = "The owner must be an active engagement member."
        if errors:
            raise ValidationError(errors)
