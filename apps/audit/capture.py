"""Explicit business-field schemas. Never serialize model __dict__, files or requests."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import uuid
from django.apps import apps
from django.core.exceptions import ValidationError
from .redaction import redact_text

SCHEMAS={
 'evidence_quota':('evidence.EvidenceQuota',['limit_bytes','updated_by_id','updated_at','version']),
 'account':('accounts.User',['username','first_name','last_name','email','is_active','is_superuser','version']),
 'engagement':('engagements.Engagement',['name','client','description','objectives','scope_summary','start_date','end_date','status','report_classification','created_by_id','updated_by_id','completed_at','archived_at','version']),
 'membership':('engagements.EngagementMembership',['user_id','role','version']),
 'note':('engagements.EngagementNote',['body','created_by_id','version']),
 'milestone':('engagements.EngagementMilestone',['title','description','due_date','completed','completed_at','created_by_id','version']),
 'asset':('assets.Asset',['name','asset_type','hostname','ip_cidr','url','description','environment','scope_status','owner_id','created_by_id','version']),
 'finding':('findings.Finding',['title','description','severity','cvss_vector','cvss_score','status','technical_details','impact','reproduction_steps','remediation','references','author_id','reviewer_id','reviewed_at','source_template_id','source_template_version','version']),
 'finding_template':('findings.FindingTemplate',['title','description','severity','cvss_vector','cvss_score','technical_details','impact','reproduction_steps','remediation','references','is_active','version']),
 'test_case':('testcases.TestCase',['title','description','category','objective','methodology','procedure','expected_result','actual_result','status','assigned_tester_id','started_at','completed_at','notes','source_template_id','source_template_version','created_by_id','version']),
 'test_template':('testcases.TestCaseTemplate',['name','title','description','category','objective','methodology','procedure','expected_result','is_active','version']),
 'test_note':('testcases.TestCaseNote',['test_case_id','body','created_by_id','version']),
 'test_reference':('testcases.TestCaseReference',['test_case_id','label','url','citation','created_by_id','version']),
 'evidence':('evidence.Evidence',['original_filename','kind','content_type','size','description','uploader_id','deleted_at','deleted_by_id','version']),
 'report':('reports.Report',['title','executive_summary','methodology','recommendations','header','footer','marking','include_images','logo_id','source_template_id','source_template_version','created_by_id','version']),
 'report_template':('reports.ReportTemplate',['name','palette','sections','is_active','version']),
 'report_revision':('reports.ReportRevision',['report_id','number','report_version','status','failure_code','generated_by_id','completed_at','version']),
}
RELATIONS={'finding':['assets','test_cases'],'test_case':['assets'],'evidence':['findings','test_cases'],'report':['additional_evidence']}


@dataclass(frozen=True)
class Snapshot:
    kind:str
    subject_id:str
    engagement_ref:str|None
    values:dict


def _primitive(value):
    if isinstance(value,(date,datetime)): return value.isoformat()
    if isinstance(value,uuid.UUID): return str(value)
    if isinstance(value,Decimal): return str(value)
    if isinstance(value,str): return redact_text(value)
    if isinstance(value,list): return [_primitive(v) for v in value]
    if value is None or isinstance(value,(int,bool)): return value
    raise ValueError('Unsupported audit business value.')


def capture(record):
    kind=next((k for k,(label,_) in SCHEMAS.items() if record._meta.label_lower==label.lower()),None)
    if kind is None: return None
    engagement_ref=getattr(record,'engagement_id',None)
    if kind=='engagement': engagement_ref=record.pk
    if kind in {'test_note','test_reference'}: engagement_ref=record.test_case.engagement_id
    values={field:_primitive(getattr(record,field)) for field in SCHEMAS[kind][1]}
    for field in RELATIONS.get(kind,[]):
        values[field]=sorted(str(pk) for pk in getattr(record,field).values_list('pk',flat=True))
    if kind=='report': values['findings']=[str(pk) for pk in record.finding_links.order_by('position').values_list('finding_id',flat=True)]
    return Snapshot(kind,str(record.pk),str(engagement_ref) if engagement_ref else None,values)


def current_snapshot(kind,subject_id,engagement_ref):
    if kind not in SCHEMAS or not subject_id: return None
    model=apps.get_model(SCHEMAS[kind][0]); queryset=model.objects.all()
    if kind=='engagement': queryset=queryset.filter(pk=engagement_ref)
    elif kind in {'test_note','test_reference'}: queryset=queryset.filter(test_case__engagement_id=engagement_ref)
    elif any(f.name=='engagement' for f in model._meta.fields): queryset=queryset.filter(engagement_id=engagement_ref)
    try: record=queryset.filter(pk=subject_id).first()
    except (ValueError,TypeError,ValidationError): return None
    return capture(record) if record else None


def kind_for_action(action):
    if action.startswith(('login.','logout')): return 'authentication'
    prefix=action.split('.')[0]
    return {'user':'account','test':'test_case','engagement':'engagement','membership':'membership',
            'finding_template':'finding_template','test_template':'test_template','test_note':'test_note','test_reference':'test_reference',
            'report_template':'report_template','report':'report_revision' if action!='report.saved' else 'report'}.get(prefix,prefix if prefix in SCHEMAS else 'system')
