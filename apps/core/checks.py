from django.conf import settings
from django.core.checks import Error, Tags, register
from .vendor import vendor_errors


@register(Tags.staticfiles, deploy=True)
def local_vendor_assets(app_configs, **kwargs):
    if not settings.TRACE_REQUIRE_VENDOR:
        return []
    return [Error(message, hint="Prepare and transfer static/vendor before deploying. Run scripts/vendor_assets.py on the connected build machine.",
                  id="core.E001") for message in vendor_errors(settings.BASE_DIR / "static" / "vendor")]


@register(Tags.security)
def evidence_configuration(app_configs, **kwargs):
    from apps.evidence.storage import root_path, StorageError
    from apps.evidence.validation import TYPES
    errors = []
    try:
        root_path()
    except StorageError:
        errors.append(Error('Evidence storage must be separate from all static storage.', id='evidence.E001'))
    if not set(settings.TRACE_EVIDENCE_ALLOWED_TYPES) <= set(TYPES) or not settings.TRACE_EVIDENCE_ALLOWED_TYPES:
        errors.append(Error('Configure a nonempty allowlist of supported evidence types.', id='evidence.E002'))
    if not 1 <= settings.TRACE_EVIDENCE_MAX_BYTES <= 1024 * 1024 * 1024:
        errors.append(Error('Evidence byte limit must be between 1 byte and 1 GiB.', id='evidence.E003'))
    if not 1 <= settings.TRACE_EVIDENCE_IMAGE_PIXELS <= 20_000_000 or not 1 <= settings.TRACE_EVIDENCE_IMAGE_SIDE <= 16384:
        errors.append(Error('Evidence image limits exceed the supported parser resource budget.', id='evidence.E004'))
    return errors


@register(Tags.security)
def report_configuration(app_configs, **kwargs):
    from apps.reports.storage import root_path, StorageError
    errors=[]
    try: root_path()
    except StorageError:
        errors.append(Error('Report storage must be separate from evidence and public static storage.',id='reports.E001'))
    if not 1 <= settings.TRACE_REPORT_MAX_IMAGES <= 50 or not 1 <= settings.TRACE_REPORT_MAX_IMAGE_BYTES <= 16*1024*1024:
        errors.append(Error('Report image limits exceed the reviewed budget.',id='reports.E002'))
    limits = [(settings.TRACE_REPORT_CONCURRENT_EXPORTS, 8), (settings.TRACE_REPORT_MAX_FINDINGS,500), (settings.TRACE_REPORT_MAX_TESTS,1000),
              (settings.TRACE_REPORT_MAX_EVIDENCE,500), (settings.TRACE_REPORT_MAX_SNAPSHOT_BYTES,16*1024*1024),
              (settings.TRACE_REPORT_MAX_ARTIFACT_BYTES,100*1024*1024), (settings.TRACE_REPORT_RENDER_TIMEOUT,90)]
    if any(not 1 <= value <= maximum for value,maximum in limits):
        errors.append(Error('Report export limits exceed the reviewed renderer budget.',id='reports.E003'))
    return errors


@register(Tags.security)
def storage_configuration(app_configs, **kwargs):
    values = [settings.TRACE_EVIDENCE_TOTAL_QUOTA_BYTES, settings.TRACE_EVIDENCE_ENGAGEMENT_QUOTA_BYTES,
              settings.TRACE_STORAGE_MIN_FREE_BYTES, settings.TRACE_UPLOAD_TEMP_MIN_FREE_BYTES]
    errors = []
    if any(type(value) is not int or not 0 <= value <= 1024**5 for value in values):
        errors.append(Error('Storage quotas/reserves must be nonnegative byte counts up to 1 PiB.', id='evidence.E005'))
    if type(settings.TRACE_STORAGE_WARNING_PERCENT) is not int or not 1 <= settings.TRACE_STORAGE_WARNING_PERCENT <= 99:
        errors.append(Error('Storage warning percentage must be between 1 and 99.', id='evidence.E006'))
    return errors
