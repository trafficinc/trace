import logging
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, OperationalError, connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.vary import vary_on_headers

logger = logging.getLogger(__name__)


@login_required
@require_GET
@vary_on_headers('HX-Request')
def dashboard(request):
    template = 'components/dashboard_engagements.html' if request.headers.get('HX-Request') == 'true' else 'pages/dashboard.html'
    from .dashboards import workspace_summary
    return render(request, template, workspace_summary(actor=request.user, page_number=request.GET.get("page")))


@require_GET
def health(request):
    """Readiness probe with no version, filesystem, user or exception disclosure."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.warning("health_database_unavailable")
        response = JsonResponse({"status": "unavailable"}, status=503)
    else:
        response = JsonResponse({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
@vary_on_headers('HX-Request')
def editor_status(request, kind, object_id, engagement_id=None):
    from .editing import resolve_editor
    try:
        record, engagement = resolve_editor(actor=request.user, kind=kind, object_id=object_id, engagement_id=engagement_id)
    except OperationalError:
        return HttpResponse('<p role="status">Saved status is temporarily unavailable. Your draft is unchanged.</p>', status=503)
    try:
        loaded = int(request.GET.get('version', ''))
        if loaded < 1:
            raise ValueError
    except ValueError:
        return HttpResponse('A loaded version is required.', status=400)
    return render(request, 'components/editor_status.html', {'record': record, 'loaded_version': loaded,
                  'changed': loaded != record.version, 'poll_url': request.path, 'engagement': engagement})


@login_required
@require_http_methods(['GET', 'POST'])
@vary_on_headers('HX-Request')
def editor_presence(request, kind, object_id, engagement_id=None):
    from .presence import heartbeat, editors
    active = False
    try:
        if request.method == 'POST':
            active = request.POST.get('leave') != '1'
            heartbeat(actor=request.user, kind=kind, object_id=object_id, engagement_id=engagement_id, leave=not active)
        names = editors(actor=request.user, kind=kind, object_id=object_id, engagement_id=engagement_id)
    except OperationalError:
        return HttpResponse('<p role="status">Presence is temporarily unavailable. Your draft is unchanged.</p>', status=503)
    return render(request, 'components/editor_presence.html' if request.headers.get('HX-Request') == 'true' else 'pages/editor_presence.html',
                  {'presence_active': active, 'presence_names': names, 'presence_url': request.path})


@login_required
@require_GET
@vary_on_headers('HX-Request')
def search(request):
    from .search import search_records
    context=search_records(actor=request.user,data=request.GET,page_number=request.GET.get('page'))
    params=request.GET.copy(); params.pop('page',None)
    context['search_params']=params.urlencode()
    template='components/search_results.html' if request.headers.get('HX-Request')=='true' else 'pages/search.html'
    return render(request,template,context,status=200 if not context['search_form'].errors else 400)


@vary_on_headers("HX-Request")
def permission_denied(request,exception):
    template='components/access_error.html' if request.headers.get('HX-Request')=='true' else 'pages/access_error.html'
    return render(request,template,{'error_title':'Access unavailable','error_message':'Your current role does not allow this action. Your submitted changes were not saved. Contact your engagement Lead if you need access.'},status=403)


@vary_on_headers("HX-Request")
def page_not_found(request,exception):
    template='components/access_error.html' if request.headers.get('HX-Request')=='true' else 'pages/access_error.html'
    return render(request,template,{'error_title':'Page unavailable','error_message':'This page is unavailable with your current access. Return to your workspace to choose an available engagement.'},status=404)


@login_required
@require_GET
@vary_on_headers('HX-Request')
def storage_status(request):
    from apps.evidence.quotas import system_status
    context = {'storage_status': system_status(actor=request.user)}
    template = 'components/storage_status.html' if request.headers.get('HX-Request') == 'true' else 'pages/storage_status.html'
    return render(request, template, context)
