from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from apps.engagements.permissions import get_engagement, Permission
from . import history
from .forms import HistoryFilter
from .redaction import redact_value


def _context(request,engagement_id):
    return {'engagement':get_engagement(request.user,engagement_id,Permission.VIEW_AUDIT) if engagement_id else None}


def _private(response):
    response['Cache-Control']='private, no-store'
    response['X-Content-Type-Options']='nosniff'
    return response


@login_required
@require_GET
def index(request,engagement_id=None):
    queryset=history.events_for(actor=request.user,engagement_id=engagement_id)
    form=HistoryFilter(request.GET)
    if form.is_valid(): queryset=history.filter_events(queryset,request.GET)
    else: queryset=queryset.none()
    page=Paginator(queryset.select_related('actor'),50).get_page(request.GET.get('page'))
    params=request.GET.copy(); params.pop('page',None)
    return _private(render(request,'pages/audit_list.html',{**_context(request,engagement_id),'form':form,'page':page,'query':params.urlencode()},status=200 if form.is_valid() else 400))


@login_required
@require_GET
def detail(request,event_id,engagement_id=None):
    event=get_object_or_404(history.events_for(actor=request.user,engagement_id=engagement_id),pk=event_id)
    before=redact_value(event.before); after=redact_value(event.after)
    changes=[{'field':key,'before':before.get(key,''),'after':after.get(key,''),'changed':before.get(key)!=after.get(key)} for key in sorted(before.keys()|after.keys())]
    return _private(render(request,'pages/audit_detail.html',{**_context(request,engagement_id),'event':event,'changes':changes,'metadata':redact_value(event.metadata)}))


@login_required
@require_GET
def export(request,engagement_id=None):
    try: payload=history.export_history(actor=request.user,engagement_id=engagement_id,filters=request.GET)
    except ValidationError:
        return _private(HttpResponse('Invalid filters or export limit exceeded. Narrow the selection.',status=400))
    response=HttpResponse(payload,content_type='application/json')
    response['Content-Disposition']='attachment; filename="tdt-audit.json"'
    return _private(response)


@login_required
@require_GET
def revisions(request,engagement_id,kind,entity_id):
    entity,rows=history.revisions_for(actor=request.user,engagement_id=engagement_id,kind=kind,entity_id=entity_id)
    page=Paginator(rows,20).get_page(request.GET.get('page'))
    for revision in page: revision.display_values=redact_value(revision.snapshot)
    return _private(render(request,'pages/entity_revisions.html',{'engagement':get_engagement(request.user,engagement_id),'entity':entity,'kind':kind,'page':page}))
