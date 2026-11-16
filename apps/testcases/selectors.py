import uuid
from django.db.models import Count, Q
from .models import TestCaseStatus


def filter_test_cases(engagement, params):
    cases = engagement.test_cases.select_related("assigned_tester").prefetch_related("assets")
    query = params.get("q", "").strip()[:200]
    if query:
        cases = cases.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(category__icontains=query)
                             | Q(objective__icontains=query) | Q(procedure__icontains=query))
    for field in ("status", "category"):
        value = params.get(field, "").strip()[:100]
        if value:
            cases = cases.filter(**{field: value})
    owner = params.get("owner", "")[:32]
    if owner == "unassigned":
        cases = cases.filter(assigned_tester__isnull=True)
    elif owner:
        cases = cases.filter(assigned_tester_id=int(owner)) if owner.isascii() and owner.isdecimal() else cases.none()
    asset = params.get("asset", "")[:64]
    if asset:
        try:
            asset_id = uuid.UUID(asset)
        except ValueError:
            cases = cases.none()
        else:
            cases = cases.filter(assets__pk=asset_id, assets__engagement=engagement)
    sort = params.get("sort", "title")
    if sort not in {"title", "-title", "category", "status", "-updated_at"}:
        sort = "title"
    return cases.order_by(sort, "id"), query, sort


def test_case_progress(cases):
    resolved = Q(status__in=[TestCaseStatus.PASSED, TestCaseStatus.FAILED, TestCaseStatus.NOT_APPLICABLE])
    summary = cases.aggregate(total=Count("pk"), resolved=Count("pk", filter=resolved))
    summary["percent"] = round(summary["resolved"] * 100 / summary["total"]) if summary["total"] else 0
    counts = dict(cases.order_by().values_list("status").annotate(total=Count("pk")))
    summary["statuses"] = [{"value": value, "label": label, "count": counts.get(value, 0)} for value, label in TestCaseStatus.choices]
    summary["categories"] = list(cases.order_by("category").values("category").annotate(total=Count("pk"),
        resolved=Count("pk", filter=resolved), passed=Count("pk", filter=Q(status="passed")), failed=Count("pk", filter=Q(status="failed"))))
    return summary
