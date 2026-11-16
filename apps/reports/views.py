from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.views.decorators.vary import vary_on_headers
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from apps.core.exceptions import EditConflict
from apps.core.http import mutation_error, saved_redirect, render_page
from apps.engagements.permissions import Permission as P, get_engagement, require_system_admin, is_system_admin
from apps.findings.models import FindingStatus
from . import services, storage
from .forms import CreateReportForm, EditReportForm, FindingChoiceFormSet, TemplateForm, EditTemplateForm, GenerateForm, REPORT_FIELDS, TEMPLATE_FIELDS
from .models import ReportTemplate
from .rendering import RenderError

ERRORS=(ValidationError,EditConflict,IntegrityError,OperationalError)


def _selection(engagement, report, post):
    choices=list(engagement.findings.order_by('title','id')[:501])
    if len(choices)>500: raise ValidationError('The report editor supports up to 500 available findings per engagement.')
    selected={str(link.finding_id):link.position for link in report.finding_links.all()} if report else {}
    initial=[]
    for i,finding in enumerate(choices):
        pk=str(finding.pk)
        initial.append({'finding':finding.pk,'include':pk in selected if report else finding.status==FindingStatus.CONFIRMED,
                        'position':selected.get(pk,i+1) if report else i+1})
    formset=FindingChoiceFormSet(post,initial=initial,prefix='findings')
    labels={str(f.pk):f'{f.title} · {f.get_severity_display()} · {f.get_status_display()}' for f in choices}
    rows=[{'form':form,'label':labels.get(str(form['finding'].value()),'Unavailable selection')} for form in formset]
    return formset,rows


def _selected(formset):
    rows=[f.cleaned_data for f in formset if f.cleaned_data.get('include')]
    if len({r['position'] for r in rows})!=len(rows): raise ValidationError('Use a different report position for each included finding.')
    return [r['finding'] for r in sorted(rows,key=lambda r:r['position'])]


@login_required
@require_GET
@vary_on_headers("HX-Request")
def report_list(request,engagement_id):
    engagement=get_engagement(request.user,engagement_id,P.GENERATE_REPORTS)
    query=request.GET.get('q','').strip()[:200]
    sort=request.GET.get('sort','-updated_at')
    if sort not in {'title','-title','-updated_at'}: sort='-updated_at'
    records=engagement.reports.all()
    if query: records=records.filter(title__icontains=query)
    page=Paginator(records.order_by(sort,'id'),20).get_page(request.GET.get('page'))
    params=request.GET.copy(); params.pop('page',None)
    template='reports/components/report_results.html' if request.headers.get('HX-Request')=='true' else 'reports/list.html'
    return render(request,template,{'engagement':engagement,'reports':page,'page':page,'query':query,'sort':sort,'pagination_query':params.urlencode(),'can_edit':not engagement.is_read_only})


@login_required
@require_http_methods(['GET','POST'])
def report_edit(request,engagement_id,pk=None):
    engagement=get_engagement(request.user,engagement_id,P.GENERATE_REPORTS)
    if request.method=='GET' and engagement.is_read_only: raise PermissionDenied('This engagement is read-only.')
    report=get_object_or_404(engagement.reports,pk=pk) if pk else None
    template=None
    initial={'version':report.version} if report else {'title':engagement.name+' — Assessment report','marking':engagement.report_classification,'include_images':True}
    if not report and request.method=='GET' and request.GET.get('template'):
        template=get_object_or_404(ReportTemplate.objects.filter(is_active=True),pk=request.GET['template'])
        initial.update(source_template=template.pk,template_version=template.version)
    cls=EditReportForm if report else CreateReportForm
    form=cls(request.POST if request.method=='POST' else None,instance=report,engagement=engagement,initial=initial)
    status=200
    try: selection,rows=_selection(engagement,report,request.POST if request.method=='POST' else None)
    except ValidationError as exc:
        return render(request,'reports/error.html',{'engagement':engagement,'message':exc.messages[0]},status=400)
    if request.method=='POST' and form.is_valid() and selection.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            source=form.cleaned_data.get('source_template')
            saved=services.save_report(actor=request.user,engagement_id=engagement_id,report_id=pk,version=form.cleaned_data.get('version'),
                data={f:form.cleaned_data[f] for f in REPORT_FIELDS},finding_ids=_selected(selection),
                evidence_ids=list(form.cleaned_data['additional_evidence'].values_list('pk', flat=True)),
                template_id=source.pk if source else None,template_version=form.cleaned_data.get('template_version'))
        except ERRORS as exc: status=mutation_error(form,exc)
        else: return saved_redirect(request,reverse('reports:detail',args=[engagement_id,saved.pk]), message='Changes saved.')
    return render_page(request,'reports/editor.html',{'engagement':engagement,'report':report,'form':form,
        'title':'Edit report setup' if report else 'New report','selection_formset':selection,'report_selection_rows':rows,
        'saved_selection':report.finding_links.select_related('finding').all() if report else [],
        'conflict_extra_template':'reports/components/finding_selection.html','templates':ReportTemplate.objects.filter(is_active=True),'source':template},status=status)


@login_required
@require_http_methods(['GET','POST'])
def report_detail(request,engagement_id,pk):
    engagement=get_engagement(request.user,engagement_id,P.GENERATE_REPORTS)
    report=get_object_or_404(engagement.reports,pk=pk)
    form=GenerateForm(request.POST if request.method=='POST' else None,initial={'version':report.version})
    status=200
    if request.method=='POST' and form.is_valid() and not request.POST.get('_prepare_merge'):
        try: services.generate_report(actor=request.user,engagement_id=engagement_id,report_id=pk,version=form.cleaned_data['version'])
        except ERRORS as exc: status=mutation_error(form,exc)
        except (RenderError,OSError,storage.StorageError):
            form.add_error(None,'Generation failed. Check offline dependencies, source file integrity and export limits. The failed revision is retained.')
            status=503
        else: return saved_redirect(request,reverse('reports:detail',args=[engagement_id,pk]), message='Report revision generated.')
    return render_page(request,'reports/detail.html',{'engagement':engagement,'report':report,'form':form,'revision_page':Paginator(report.revisions.select_related('generated_by').order_by('-number','id'),20).get_page(request.GET.get('page')),'can_edit':not engagement.is_read_only},status=status)


@login_required
@require_GET
def download(request,engagement_id,revision_id,format,preview=False):
    try: artifact,file=services.open_artifact(actor=request.user,engagement_id=engagement_id,revision_id=revision_id,format=format)
    except (OSError,storage.StorageError,IntegrityError,OperationalError):
        return render(request,'reports/error.html',{'message':'The private report is unavailable or failed integrity verification.'},status=409)
    types={'html':'text/html; charset=utf-8','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','pdf':'application/pdf'}
    response=FileResponse(file,as_attachment=not preview,filename=f'report-{revision_id}.{format}',content_type=types[format])
    response['Content-Security-Policy']="sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
    response['X-Frame-Options']='SAMEORIGIN' if preview else 'DENY'
    response['X-Content-Type-Options']='nosniff'; response['Cache-Control']='no-store, private'
    response['Cross-Origin-Resource-Policy']='same-origin'
    return response


@login_required
@require_GET
def template_list(request):
    records=ReportTemplate.objects.all() if is_system_admin(request.user) else ReportTemplate.objects.filter(is_active=True)
    query=request.GET.get('q','').strip()[:200]
    if query: records=records.filter(name__icontains=query)
    page=Paginator(records.order_by('name','pk'),20).get_page(request.GET.get('page'))
    return render(request,'reports/templates.html',{'templates':page,'page':page,'query':query,'can_manage':is_system_admin(request.user)})


@login_required
@require_http_methods(['GET','POST'])
def template_edit(request,pk=None):
    require_system_admin(request.user)
    record=get_object_or_404(ReportTemplate,pk=pk) if pk else None
    cls=EditTemplateForm if record else TemplateForm
    form=cls(request.POST if request.method=='POST' else None,instance=record,initial={'version':record.version} if record else {})
    status=200
    if request.method=='POST' and form.is_valid() and not request.POST.get('_prepare_merge'):
        try: services.save_template(actor=request.user,template_id=pk,version=form.cleaned_data.get('version'),data={f:form.cleaned_data[f] for f in TEMPLATE_FIELDS})
        except ERRORS as exc: status=mutation_error(form,exc)
        else: return saved_redirect(request,reverse('report_templates:list'), message='Changes saved.')
    return render_page(request,'pages/engagement_editor.html',{'form':form,'title':'Report template'},status=status)
