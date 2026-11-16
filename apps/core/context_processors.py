from functools import lru_cache
from django.conf import settings
from .vendor import vendor_errors


@lru_cache(maxsize=1)
def _vendor_ready(directory):
    return not vendor_errors(directory)


def application(request):
    from django.urls import reverse
    from apps.engagements.permissions import engagement_permissions, Permission
    match = request.resolver_match
    namespace = match.namespace if match else ''
    name = match.url_name if match else ''
    engagement_id = match.kwargs.get('engagement_id') if match else None
    if not engagement_id and namespace == 'engagements':
        engagement_id = match.kwargs.get('pk')
    capabilities = engagement_permissions(request.user, engagement_id) if engagement_id else frozenset()
    sections = {
        'engagements': 'Engagements', 'assets': 'Assets', 'testcases': 'Test cases',
        'findings': 'Findings', 'evidence': 'Evidence', 'reports': 'Reports',
        'audit': 'Audit history', 'system_audit': 'System audit', 'accounts': 'Account',
        'test_templates': 'Test templates', 'finding_templates': 'Finding templates',
        'report_templates': 'Report templates',
    }
    pages = {'dashboard': 'Overview', 'search': 'Search', 'detail': 'Details', 'list': 'List',
             'edit': 'Edit', 'create': 'Create', 'revisions': 'Revision history', 'members': 'Team',
             'profile': 'Your profile', 'password_change': 'Change password', 'users': 'Users'}  # nosec B105
    section = sections.get(namespace, 'Workspace')
    section_url = None
    if namespace in {'assets','testcases','findings','evidence','reports','audit'} and Permission.VIEW in capabilities:
        section_url = reverse(namespace+':list', args=[engagement_id])
    elif namespace in {'engagements','test_templates','finding_templates','report_templates','system_audit'}:
        section_url = reverse(namespace+':list')
    if namespace == 'accounts':
        section_url = reverse('accounts:profile')
    return {
        'can_view_audit': Permission.VIEW_AUDIT in capabilities,
        'can_generate_reports': Permission.GENERATE_REPORTS in capabilities,
        'navigation_section': section,
        'navigation_section_url': section_url,
        'navigation_page': pages.get(name, name.replace('_',' ').capitalize() if name else 'Page'),
        'vendor_ready': _vendor_ready(str(settings.BASE_DIR / 'static' / 'vendor')),
    }
