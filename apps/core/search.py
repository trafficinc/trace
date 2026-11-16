"""Search one authorized domain at a time; never search auth data or upload bytes."""
from typing import Any
from django import forms
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse
from apps.engagements.permissions import visible_engagements, get_engagement, identity
from apps.assets.models import Asset
from apps.testcases.models import TestCase
from apps.findings.models import Finding
from apps.evidence.models import Evidence

KINDS=[('engagement','Engagements'),('asset','Assets'),('test_case','Test cases'),('finding','Findings'),('evidence','Evidence metadata')]


class SearchForm(forms.Form):
    q=forms.CharField(label='Search terms',max_length=200,required=False,widget=forms.TextInput(attrs={'type':'search','placeholder':'Search your engagements…'}))
    kind=forms.ChoiceField(label='Search in',choices=KINDS,initial='engagement',required=False)
    engagement=forms.UUIDField(required=False,widget=forms.HiddenInput)


def search_records(*,actor,data,page_number=None):
    form=SearchForm(data)
    if not form.is_valid(): return {'search_form':form,'results':None,'search_query':''}
    # A specific parent is authorized even for an empty search; foreign scope
    # never falls back to global results or discloses its existence.
    scope=visible_engagements(actor)
    selected=form.cleaned_data.get('engagement')
    if selected:
        get_engagement(actor,selected)
        scope=scope.filter(pk=selected)
    term=form.cleaned_data['q'].strip()
    kind=form.cleaned_data.get('kind') or 'engagement'
    if kind=='engagement':
        records=scope.filter(Q(name__icontains=term)|Q(client__icontains=term)|Q(scope_summary__icontains=term))
    else:
        models: dict[str, Any] = {'asset':Asset,'test_case':TestCase,'finding':Finding,'evidence':Evidence}
        records=models[kind].objects.filter(engagement_id__in=scope.values('pk')).select_related('engagement')
        if kind=='asset': condition=Q(name__icontains=term)|Q(hostname__icontains=term)|Q(ip_cidr__icontains=term)|Q(description__icontains=term)
        elif kind=='evidence': condition=Q(original_filename__icontains=term)|Q(description__icontains=term)
        else: condition=Q(title__icontains=term)|Q(description__icontains=term)
        records=records.filter(condition)
        if kind=='evidence': records=records.filter(deleted_at__isnull=True)
    if not term or identity(actor) is None: records=records.none()
    page=Paginator(records.order_by('-updated_at','pk'),20).get_page(page_number)
    rows=[]
    namespaces={'asset':'assets','test_case':'testcases','finding':'findings','evidence':'evidence'}
    for record in page:
        engagement=record if kind=='engagement' else record.engagement
        title=record.name if kind in {'engagement','asset'} else record.original_filename if kind=='evidence' else record.title
        url=reverse('engagements:detail',args=[record.pk]) if kind=='engagement' else reverse(namespaces[kind]+':detail',args=[engagement.pk,record.pk])
        rows.append({'title':title,'url':url,'engagement':engagement,'kind':dict(KINDS)[kind],
                     'status':record.get_status_display() if hasattr(record,'get_status_display') else ''})
    return {'search_form':form,'results':page,'search_rows':rows,'search_query':term}
