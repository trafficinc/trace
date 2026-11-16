"""Small CAS primitives for already-authorized querysets inside IMMEDIATE transactions."""
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import F
from django.shortcuts import get_object_or_404
from .exceptions import EditConflict


def _version(version):
    if not connection.in_atomic_block:
        raise RuntimeError('Versioned mutations require an explicit transaction.')
    if type(version) is not int or version < 1:
        raise ValidationError('A positive integer version is required.')


def cas_update(queryset, *, version, **values):
    _version(version)
    from .database import mutation_lock
    mutation_lock()
    if 'version' in values:
        raise ValueError('CAS owns the version increment.')
    from apps.audit.capture import capture
    previous = queryset.filter(version=version).first()
    before = capture(previous) if previous else None
    if queryset.filter(version=version).update(**values, version=F('version') + 1) != 1:
        # Only query the same authorized scope. Missing records stay indistinguishable
        # from restricted IDs; a still-visible record is a genuine version conflict.
        raise EditConflict(current=get_object_or_404(queryset))
    return before


def cas_delete(queryset, *, version):
    _version(version)
    from .database import mutation_lock
    mutation_lock()
    from apps.audit.capture import capture
    previous = queryset.filter(version=version).first()
    before = capture(previous) if previous else None
    if queryset.filter(version=version).delete()[0] == 0:
        raise EditConflict(current=get_object_or_404(queryset))
    return before
