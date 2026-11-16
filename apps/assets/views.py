from apps.core.http import render_page as render
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.vary import vary_on_headers
from apps.core.exceptions import EditConflict
from apps.core.http import mutation_error, saved_redirect
from apps.engagements.permissions import Permission, get_engagement, has_permission
from .models import Asset
from .forms import AssetForm, EditAssetForm, ASSET_FIELDS
from .selectors import filter_assets
from .services import save_asset


@login_required
@require_GET
@vary_on_headers("HX-Request")
def asset_list(request, engagement_id):
    engagement = get_engagement(request.user, engagement_id)
    assets, query, sort = filter_assets(engagement, request.GET)
    context = {"engagement": engagement, "page": Paginator(assets, 20).get_page(request.GET.get("page")),
        "query": query, "sort": sort, "types": Asset.Type.choices, "scope_statuses": Asset.ScopeStatus.choices,
        "environments": engagement.assets.exclude(environment="").order_by("environment").values_list("environment", flat=True).distinct(),
        "owners": get_user_model().objects.filter(pk__in=engagement.assets.values("owner_id")).order_by("username"),
        "can_write": not engagement.is_read_only and has_permission(request.user, engagement_id, Permission.MANAGE_ASSETS)}
    template = "components/asset_results.html" if request.headers.get("HX-Request") == "true" else "pages/asset_list.html"
    return render(request, template, context)


@login_required
@require_GET
def asset_detail(request, engagement_id, pk):
    engagement = get_engagement(request.user, engagement_id)
    asset = get_object_or_404(engagement.assets.select_related("owner", "created_by"), pk=pk)
    return render(request, "pages/asset_detail.html", {"engagement": engagement, "asset": asset,
        "test_cases": asset.test_cases.filter(engagement=engagement).select_related("assigned_tester"),
        "can_write": not engagement.is_read_only and has_permission(request.user, engagement_id, Permission.MANAGE_ASSETS)})


@login_required
@require_http_methods(["GET", "POST"])
def asset_edit(request, engagement_id, pk=None):
    engagement = get_engagement(request.user, engagement_id, Permission.MANAGE_ASSETS)
    if request.method == "GET" and engagement.is_read_only:
        raise PermissionDenied("This engagement is read-only.")
    asset = get_object_or_404(engagement.assets, pk=pk) if pk else None
    form_class = EditAssetForm if asset else AssetForm
    kwargs = {"initial": {"version": asset.version}} if asset else {}
    form = form_class(request.POST if request.method == "POST" else None, instance=asset, engagement=engagement, **kwargs)
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            saved = save_asset(actor=request.user, engagement_id=engagement_id, asset_id=pk,
                data={field: form.cleaned_data[field] for field in ASSET_FIELDS}, version=form.cleaned_data.get("version"))
        except (ValidationError, EditConflict, IntegrityError, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse("assets:detail", args=[engagement_id, saved.pk]), message='Changes saved.')
    template = "components/engagement_editor.html" if request.headers.get("HX-Request") == "true" else "pages/engagement_editor.html"
    return render(request, template, {"engagement": engagement, "form": form, "title": "Edit asset" if pk else "New asset",
                                    "enhance_htmx": True}, status=status)
