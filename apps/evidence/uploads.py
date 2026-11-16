"""Stream directly into leased private files, bounded before any disk write."""
from typing import NoReturn
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.files.uploadhandler import FileUploadHandler, StopUpload, SkipFile
from apps.engagements.permissions import get_engagement, Permission
from . import storage, quotas
import logging

logger = logging.getLogger('trace.evidence')


class PrivateUploadedFile(UploadedFile):
    def __init__(self, file, *, engagement_id, key, reservation, **kwargs):
        super().__init__(file=file, **kwargs)
        self.engagement_id, self.key = engagement_id, key
        self.reservation = reservation
        self._cleaned = False

    def close(self):
        super().close()
        if self._cleaned:
            return
        self._cleaned = True
        try:
            storage.remove_file(self.engagement_id, self.key)
        except (OSError, storage.StorageError):
            logger.warning('evidence_cleanup_deferred')
        finally:
            self.reservation.close()


class BoundedUploadHandler(FileUploadHandler):
    chunk_size = 64 * 1024

    def __init__(self, request=None):
        super().__init__(request)
        self.total = 0
        self.files = 0
        self.file: PrivateUploadedFile

    def _abort(self, message, status=413, *, preserve_fields=False) -> NoReturn:
        self.request.evidence_upload_error = message
        self.request.evidence_upload_status = status
        if getattr(self, "file", None):
            self.file.close()
        if preserve_fields:
            raise SkipFile()
        raise StopUpload(connection_reset=True)

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.files += 1
        if getattr(self.request, "evidence_upload_error", None):
            raise SkipFile()
        match = self.request.resolver_match
        if not match or match.namespace != 'evidence':
            self._abort('This endpoint does not accept files.', 400)
        engagement = get_engagement(self.request.user, match.kwargs['engagement_id'], Permission.ATTACH_EVIDENCE)
        if engagement.is_read_only:
            self._abort('This engagement is read-only.', 400)
        if self.files > 1:
            self._abort('Upload one evidence file at a time.')
        reservation = None
        file = None
        try:
            reservation = quotas.begin(actor=self.request.user, engagement_id=engagement.pk)
            key, file = storage.create_file(engagement.pk)
            reservation.attach("staging_key", key)
        except quotas.CapacityError as error:
            if file is not None:
                file.close()
            if reservation is not None:
                reservation.close()
            self._abort(error.messages[0], error.status, preserve_fields=True)
        except (OSError, storage.StorageError):
            if file is not None:
                file.close()
            if reservation is not None:
                reservation.close()
            self._abort('Private upload storage is unavailable.', 503, preserve_fields=True)
        self.file = PrivateUploadedFile(file, engagement_id=engagement.pk, key=key, name=self.file_name, reservation=reservation,
                                        content_type=self.content_type, size=0, charset=self.charset)

    def receive_data_chunk(self, raw_data, start):
        if not getattr(self, "file", None):
            self._abort("No evidence upload was initialized.", 400)
        self.total += len(raw_data)
        if self.total > settings.TRACE_EVIDENCE_MAX_BYTES:
            self._abort('Evidence exceeds the configured upload limit.', preserve_fields=True)
        try:
            self.file.reservation.reserve(self.total)
            self.file.write(raw_data)
        except quotas.CapacityError as error:
            self._abort(error.messages[0], error.status, preserve_fields=True)
        except ValidationError as error:
            self._abort(error.messages[0], 400, preserve_fields=True)
        except OSError:
            self._abort('Private upload storage is unavailable.', 503, preserve_fields=True)
        return None

    def file_complete(self, file_size):
        if not getattr(self, "file", None):
            self._abort("No evidence upload was initialized.", 400)
        try:
            self.file.flush()
            self.file.seek(0)
        except OSError:
            self._abort('Private upload storage is unavailable.', 503)
        self.file.size = self.total
        return self.file

    def upload_interrupted(self):
        if getattr(self, "file", None):
            self.file.close()
