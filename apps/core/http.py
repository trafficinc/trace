from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError
from .exceptions import EditConflict
from django.http import HttpResponse
from django.shortcuts import redirect


def saved_redirect(request, url, *, message=None):
    if message:
        from django.contrib import messages
        messages.success(request, message)
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def mutation_error(form, error):
    """Present a failed mutation without echoing database errors or secrets."""
    if isinstance(error, EditConflict):
        form.edit_conflict = True
        form.conflict_current = error.current
        form.add_error(None, "This record changed. Your draft is preserved. Reload the current version before applying changes.")
        return 409
    if isinstance(error, (IntegrityError, OperationalError)):
        form.add_error(None, "The change could not be saved. Reload to check the current record before trying again.")
        return 503
    if isinstance(error, ValidationError):
        form.add_error(None, "; ".join(error.messages))
        return 400
    raise error


def render_page(request, template_name, context=None, *, status=200, **kwargs):
    """Render normal pages or an authorized, draft-preserving conflict review."""
    from django.shortcuts import render
    from django.utils.cache import patch_vary_headers
    from .conflicts import editor_context, conflict_context
    context = dict(context or {})
    try:
        editor = editor_context(request, context)
    except OperationalError:
        form = context.get('form')
        if form is not None and form.is_bound:
            form.add_error(None, 'Current saved values are temporarily unavailable. Your draft is preserved.')
        editor = {'form': form} if status == 409 and form is not None else None
        status = 409 if status == 409 else 503
    if editor:
        context['editor'] = editor
        context['editor_presence_enabled'] = settings.TRACE_EDITOR_PRESENCE_ENABLED
    if editor and (status == 409 or editor.get('stale') or request.POST.get('_prepare_merge')):
        context.update(conflict_context(request, editor))
        status = 200 if context['merge_ready'] else 409
        template_name = 'components/edit_conflict.html' if request.headers.get('HX-Request') == 'true' else 'pages/edit_conflict.html'
    if request.headers.get('HX-Request') == 'true' and request.POST.get('_merge_form') and template_name.startswith('pages/'):
        # A validation/storage failure after manual review still belongs in the
        # submitted form's fragment, rather than nesting a full application page.
        template_name = 'components/edit_failure.html'
    response = render(request, template_name, context, status=status, **kwargs)
    if request.POST.get('_merge_form') and status == 200 and template_name == 'components/engagement_milestones.html':
        response['HX-Retarget'] = '#milestones'
        response['HX-Reswap'] = 'outerHTML'
    patch_vary_headers(response, ['HX-Request'])
    return response
