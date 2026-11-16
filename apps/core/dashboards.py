"""Bounded, read-only operational summaries; scope before aggregating or slicing."""
from datetime import timedelta
from django.db.models import Count, Q
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.engagements.models import EngagementStatus
from apps.engagements.permissions import visible_engagements, get_engagement
from apps.findings.models import Finding, Severity
from apps.testcases.models import TestCase

OPEN_FINDINGS = ('draft', 'under_review', 'confirmed')
ACTIVE_TESTS = ('not_started', 'in_progress', 'blocked')
# Coarse activity summaries disclose no audit bodies, workflow metadata, files,
# authentication or report exports. Full audit history keeps VIEW_AUDIT policy.
ACTIVITY_ACTIONS = tuple(value for value in AuditEvent.Action.values if value.split('.')[0] in {
    'engagement', 'membership', 'note', 'milestone', 'asset', 'test', 'test_note',
    'test_reference', 'test_child', 'finding', 'evidence'
} and value not in {'engagement.purged', 'evidence.downloaded', 'evidence.verified'})


def activity_for(engagements):
    return AuditEvent.objects.filter(engagement_id__in=engagements.values('pk'), action__in=ACTIVITY_ACTIONS)


def recent_activity(events):
    labels=dict(AuditEvent.Action.choices)
    rows=list(events.order_by('-created_at', '-id').values(
        'action', 'created_at', 'actor__username', 'actor_ref', 'engagement__name', 'engagement__report_classification', 'engagement_id'
    )[:12])
    for row in rows:
        row['label']=labels[row['action']]
    return rows


def workspace_summary(*, actor, page_number=None):
    from django.core.paginator import Paginator
    engagements=visible_engagements(actor)
    open_engagements=engagements.exclude(status__in=[EngagementStatus.COMPLETED, EngagementStatus.ARCHIVED])
    tests=TestCase.objects.filter(engagement_id__in=open_engagements.values('pk'), status__in=ACTIVE_TESTS)
    findings=Finding.objects.filter(engagement_id__in=engagements.values('pk'), status__in=OPEN_FINDINGS)
    # Separate aggregates prevent multiplication across independent child joins.
    counts={
        'engagements':engagements.count(),
        'active_engagements':engagements.filter(status='active').count(),
        'tests':tests.count(),
        'findings':findings.count(),
    }
    records=engagements.only('id','name','client','status','report_classification','updated_at').annotate(
        milestone_total=Count('milestones'),
        milestone_done=Count('milestones', filter=Q(milestones__completed=True)),
    ).order_by('-updated_at','id')
    page=Paginator(records,10).get_page(page_number)
    from apps.engagements.permissions import is_system_admin
    from apps.evidence.quotas import system_status
    storage_status = system_status(actor=actor) if is_system_admin(actor) else None
    return {
        'storage_status': storage_status,
        'engagements':page, 'engagement_page':page, 'summary':counts,
        'active_tests':list(tests.select_related('engagement','assigned_tester').only('id','title','status','engagement__id','engagement__name','engagement__report_classification','assigned_tester__id','assigned_tester__username').order_by('-updated_at','id')[:10]),
        'open_findings':list(findings.select_related('engagement').only('id','title','severity','status','engagement__id','engagement__name','engagement__report_classification').order_by('-updated_at','id')[:10]),
        'recent_activity':recent_activity(activity_for(engagements)),
    }


def engagement_summary(*, actor, engagement_id):
    engagement=get_engagement(actor,engagement_id)
    tests=engagement.test_cases.aggregate(
        total=Count('pk'), finished=Count('pk', filter=Q(status__in=['passed','failed','not_applicable'])),
        passed=Count('pk',filter=Q(status='passed')), failed=Count('pk',filter=Q(status='failed')),
        blocked=Count('pk',filter=Q(status='blocked')),
    )
    tests['percent']=round(100*tests['finished']/tests['total']) if tests['total'] else 0
    grouped=dict(engagement.findings.filter(status__in=OPEN_FINDINGS).values('severity').annotate(total=Count('pk')).values_list('severity','total'))
    severities=[{'value':value,'label':label,'count':grouped.get(value,0)} for value,label in Severity.choices]
    events=AuditEvent.objects.filter(engagement=engagement,action__in=ACTIVITY_ACTIONS)
    members=list(events.filter(created_at__gte=timezone.now()-timedelta(days=7)).values('actor_ref','actor__username').annotate(total=Count('pk')).order_by('-total','actor_ref')[:10])
    return {'test_progress':tests,'severity_summary':severities,'member_activity':members,'recent_activity':recent_activity(events)}
