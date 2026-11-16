from django.db.models import Q


def filter_assets(engagement, params):
    assets = engagement.assets.select_related("owner")
    query = params.get("q", "").strip()[:200]
    if query:
        assets = assets.filter(Q(name__icontains=query) | Q(hostname__icontains=query) | Q(ip_cidr__icontains=query)
            | Q(url__icontains=query) | Q(description__icontains=query))
    for key, field in [("status", "scope_status"), ("type", "asset_type"), ("environment", "environment")]:
        value = params.get(key, "").strip()[:100]
        if value:
            assets = assets.filter(**{field: value})
    owner = params.get("owner", "")[:32]
    if owner == "unassigned":
        assets = assets.filter(owner__isnull=True)
    elif owner:
        assets = assets.filter(owner_id=int(owner)) if owner.isascii() and owner.isdecimal() else assets.none()
    sort = params.get("sort", "name")
    if sort not in {"name", "-name", "asset_type", "environment", "scope_status", "-updated_at"}:
        sort = "name"
    return assets.order_by(sort, "id"), query, sort
