from apps.core.http import render_page as render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import OperationalError
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.vary import vary_on_headers

from apps.core.exceptions import EditConflict
from apps.core.http import mutation_error, saved_redirect
from . import services
from .forms import (
    ENGAGEMENT_FIELDS, ChangeMembershipForm, GrantMembershipForm, VersionForm,
    CreateEngagementForm, EditEngagementForm, NoteForm, EditNoteForm,
    MilestoneForm, EditMilestoneForm, MilestoneCompletionForm,
)
from .models import EngagementStatus, EngagementMembership
from .permissions import (
    Permission, get_engagement, has_permission, visible_engagements,
    is_system_admin, require_system_admin,
)

@login_required
@require_GET
@vary_on_headers("HX-Request")
def detail(request, pk):
    engagement = get_engagement(request.user, pk)
    panel = request.GET.get("panel")
    template = f"components/engagement_{panel}.html" if request.headers.get("HX-Request") == "true" and panel in {"notes", "milestones", "overview_status"} else "pages/engagement_overview.html"
    if panel == "overview_status" and request.headers.get("HX-Request") == "true":
        from apps.core.dashboards import engagement_summary
        return render(request, template, {"engagement": engagement, **engagement_summary(actor=request.user, engagement_id=pk)})
    return render(request, template, _overview_context(request, engagement))


@login_required
@require_http_methods(["GET", "POST"])
def members(request, pk):
    engagement = get_engagement(request.user, pk, Permission.MANAGE_MEMBERS)
    form = GrantMembershipForm(request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.grant_membership(actor=request.user, engagement_id=pk,
                user_id=form.cleaned_data["user"].pk, role=form.cleaned_data["role"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            messages.success(request, "Membership granted.")
            return saved_redirect(request, reverse("engagements:members", args=[pk]))
    template = "components/membership_table.html" if request.method == "GET" and request.headers.get("HX-Request") == "true" else "pages/memberships.html"
    return render(request, template, {"engagement": engagement, "form": form,
        "memberships": engagement.memberships.select_related("user"), "roles": EngagementMembership.Role.choices}, status=status)


@login_required
@require_POST
def member_change(request, pk, membership_id):
    engagement = get_engagement(request.user, pk, Permission.MANAGE_MEMBERS)
    form = ChangeMembershipForm(request.POST)
    status = 400
    if form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.change_membership(actor=request.user, engagement_id=pk, membership_id=membership_id,
                role=form.cleaned_data["role"], version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse("engagements:members", args=[pk]))
    return render(request, "pages/action_error.html", {"engagement": engagement, "form": form, "title": "Membership was not saved"}, status=status)


@login_required
@require_POST
def member_revoke(request, pk, membership_id):
    engagement = get_engagement(request.user, pk, Permission.MANAGE_MEMBERS)
    form = VersionForm(request.POST)
    status = 400
    if form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.revoke_membership(actor=request.user, engagement_id=pk, membership_id=membership_id,
                                       version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse("engagements:members", args=[pk]))
    return render(request, "pages/action_error.html", {"engagement": engagement, "form": form, "title": "Membership was not revoked"}, status=status)



def _overview_context(request, engagement, **extra):
    from apps.core.dashboards import engagement_summary
    dashboard = engagement_summary(actor=request.user, engagement_id=engagement.pk)
    editable = not engagement.is_read_only
    manage = has_permission(request.user, engagement.pk, Permission.EDIT_ENGAGEMENT)
    notes = engagement.notes.select_related("created_by")
    note_page = Paginator(notes, 10).get_page(request.GET.get("note_page"))
    for note in note_page:
        note.can_edit = editable and (manage or (note.created_by_id == request.user.pk and has_permission(request.user, engagement.pk, Permission.WRITE_NOTES)))
    milestones = engagement.milestones.all()
    progress = milestones.aggregate(total=Count("pk"), done=Count("pk", filter=Q(completed=True)))
    progress["percent"] = round(progress["done"] * 100 / progress["total"]) if progress["total"] else 0
    return {**dashboard, "engagement": engagement, "team": engagement.memberships.select_related("user"),
        "note_page": note_page, "milestone_page": Paginator(milestones, 20).get_page(request.GET.get("milestone_page")),
        "progress": progress, "today": timezone.localdate(), "can_edit": editable and manage,
        "can_manage": has_permission(request.user, engagement.pk, Permission.MANAGE_MEMBERS),
        "can_write_notes": editable and has_permission(request.user, engagement.pk, Permission.WRITE_NOTES),
        "can_manage_milestones": editable and has_permission(request.user, engagement.pk, Permission.MANAGE_MILESTONES),
        "transitions": [{"value": str(target), "label": EngagementStatus(target).label} for target in EngagementStatus.values if target in services.TRANSITIONS.get(engagement.status, set())] if manage else [],
        "note_form": NoteForm(), "milestone_form": MilestoneForm(), **extra}


def _panel_response(request, engagement, panel, *, status=200, **extra):
    if request.headers.get("HX-Request") == "true":
        return render(request, f"components/engagement_{panel}.html", _overview_context(request, engagement, **extra), status=status)
    if status != 200:
        return render(request, "pages/engagement_overview.html", _overview_context(request, engagement, **extra), status=status)
    return redirect(reverse("engagements:detail", args=[engagement.pk]) + f"#{panel}")


def _saved_redirect(request, engagement):
    url = reverse("engagements:detail", args=[engagement.pk])
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


@login_required
@require_GET
@vary_on_headers("HX-Request")
def engagement_list(request):
    queryset = visible_engagements(request.user)
    query = request.GET.get("q", "").strip()[:200]
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(client__icontains=query) | Q(scope_summary__icontains=query))
    status_filter = request.GET.get("status", "")
    if status_filter in EngagementStatus.values:
        queryset = queryset.filter(status=status_filter)
    sort = request.GET.get("sort", "-updated_at")
    if sort not in {"name", "-name", "client", "start_date", "-updated_at", "status"}:
        sort = "-updated_at"
    queryset = queryset.annotate(milestone_total=Count("milestones", distinct=True),
        milestone_done=Count("milestones", filter=Q(milestones__completed=True), distinct=True)).order_by(sort, "id")
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))
    # Resolve this user's roles in one scoped query rather than fetching each row's team.
    roles = set(EngagementMembership.objects.filter(user=request.user, engagement_id__in=[item.pk for item in page.object_list], role="lead").values_list("engagement_id", flat=True))
    admin = is_system_admin(request.user)
    for engagement in page:
        engagement.can_edit = not engagement.is_read_only and (admin or engagement.pk in roles)
    context = {"page": page, "query": query, "selected_status": status_filter, "sort": sort,
               "statuses": EngagementStatus.choices, "can_create": admin}
    template = "components/engagement_list.html" if request.headers.get("HX-Request") == "true" else "pages/engagement_list.html"
    return render(request, template, context)


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    require_system_admin(request.user)
    form = CreateEngagementForm(request.POST if request.method == "POST" else None, initial={"lead": request.user.pk})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            engagement = services.create_engagement(actor=request.user, name=form.cleaned_data["name"],
                lead_id=form.cleaned_data["lead"].pk, data={key: form.cleaned_data[key] for key in ENGAGEMENT_FIELDS if key != "name"})
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _saved_redirect(request, engagement)
    return render(request, "pages/engagement_editor.html", {"form": form, "title": "New engagement"}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    engagement = get_engagement(request.user, pk, Permission.EDIT_ENGAGEMENT)
    if request.method == "GET" and engagement.is_read_only:
        raise PermissionDenied("This engagement is read-only.")
    form = EditEngagementForm(request.POST if request.method == "POST" else None, instance=engagement, initial={"version": engagement.version})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            saved = services.update_engagement(actor=request.user, engagement_id=pk,
                data={key: form.cleaned_data[key] for key in ENGAGEMENT_FIELDS}, version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _saved_redirect(request, saved)
    template = "components/engagement_editor.html" if request.headers.get("HX-Request") == "true" else "pages/engagement_editor.html"
    if request.method == "POST":
        engagement.refresh_from_db()  # Bound ModelForm drafts must not replace the saved handling marking.
    return render(request, template, {"engagement": engagement, "form": form, "title": "Edit engagement"}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def lifecycle(request, pk, target):
    engagement = get_engagement(request.user, pk, Permission.EDIT_ENGAGEMENT)
    form = VersionForm(request.POST if request.method == "POST" else None, initial={"version": engagement.version})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            saved = services.transition_engagement(actor=request.user, engagement_id=pk, target=target, version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _saved_redirect(request, saved)
    return render(request, "pages/engagement_confirm.html", {"engagement": engagement, "form": form,
        "title": f"Mark engagement {EngagementStatus(target).label.lower()}", "target": target}, status=status)


@login_required
@require_POST
def note_create(request, pk):
    engagement = get_engagement(request.user, pk, Permission.WRITE_NOTES)
    form = NoteForm(request.POST)
    status = 400
    if form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.save_note(actor=request.user, engagement_id=pk, body=form.cleaned_data["body"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _panel_response(request, engagement, "notes")
    return _panel_response(request, engagement, "notes", status=status, note_form=form)


@login_required
@require_http_methods(["GET", "POST"])
def note_edit(request, pk, note_id):
    engagement = get_engagement(request.user, pk, Permission.WRITE_NOTES)
    note = get_object_or_404(engagement.notes, pk=note_id)
    if not services.can_edit_note(request.user, note):
        raise PermissionDenied
    if request.method == "GET" and engagement.is_read_only:
        raise PermissionDenied
    form = EditNoteForm(request.POST if request.method == "POST" else None, instance=note, initial={"version": note.version})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.save_note(actor=request.user, engagement_id=pk, note_id=note_id, body=form.cleaned_data["body"], version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _saved_redirect(request, engagement)
    return render(request, "pages/engagement_editor.html", {"engagement": engagement, "form": form, "title": "Edit note"}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def child_delete(request, pk, child_id, kind):
    permission = Permission.WRITE_NOTES if kind == "note" else Permission.MANAGE_MILESTONES
    engagement = get_engagement(request.user, pk, permission)
    child = get_object_or_404(engagement.notes if kind == "note" else engagement.milestones, pk=child_id)
    if kind == "note" and not services.can_edit_note(request.user, child):
        raise PermissionDenied
    if request.method == "GET" and engagement.is_read_only:
        raise PermissionDenied("This engagement is read-only.")
    form = VersionForm(request.POST if request.method == "POST" else None, initial={"version": child.version})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            if kind == "note":
                services.delete_note(actor=request.user, engagement_id=pk, note_id=child_id, version=form.cleaned_data["version"])
            else:
                services.delete_milestone(actor=request.user, engagement_id=pk, milestone_id=child_id, version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _saved_redirect(request, engagement)
    return render(request, "pages/engagement_confirm.html", {"engagement": engagement, "form": form,
        "title": f"Delete {kind}", "child": child, "delete": True}, status=status)


@login_required
@require_POST
def milestone_create(request, pk):
    engagement = get_engagement(request.user, pk, Permission.MANAGE_MILESTONES)
    form = MilestoneForm(request.POST)
    status = 400
    if form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.save_milestone(actor=request.user, engagement_id=pk, data=form.cleaned_data)
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _panel_response(request, engagement, "milestones")
    return _panel_response(request, engagement, "milestones", status=status, milestone_form=form)


@login_required
@require_http_methods(["GET", "POST"])
def milestone_edit(request, pk, milestone_id):
    engagement = get_engagement(request.user, pk, Permission.MANAGE_MILESTONES)
    milestone = get_object_or_404(engagement.milestones, pk=milestone_id)
    if request.method == "GET" and engagement.is_read_only:
        raise PermissionDenied
    form = EditMilestoneForm(request.POST if request.method == "POST" else None, instance=milestone, initial={"version": milestone.version})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.save_milestone(actor=request.user, engagement_id=pk, milestone_id=milestone_id,
                data={key: form.cleaned_data[key] for key in ("title", "description", "due_date")}, version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _saved_redirect(request, engagement)
    return render(request, "pages/engagement_editor.html", {"engagement": engagement, "form": form, "title": "Edit milestone"}, status=status)


@login_required
@require_POST
def milestone_complete(request, pk, milestone_id):
    engagement = get_engagement(request.user, pk, Permission.MANAGE_MILESTONES)
    form = MilestoneCompletionForm(request.POST)
    status = 400
    if form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.set_milestone_completed(actor=request.user, engagement_id=pk, milestone_id=milestone_id,
                completed=form.cleaned_data["completed"], version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            return _panel_response(request, engagement, "milestones")
    return _panel_response(request, engagement, "milestones", status=status, milestone_action_form=form)
