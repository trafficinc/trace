from apps.core.http import render_page as render
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.vary import vary_on_headers
from django.http import Http404
import uuid

from apps.core.exceptions import EditConflict
from apps.core.http import mutation_error, saved_redirect
from apps.engagements.forms import VersionForm
from apps.engagements.permissions import Permission, get_engagement, has_permission, is_system_admin, require_system_admin
from . import services
from .forms import (BLUEPRINT_FIELDS, CASE_FIELDS, TEMPLATE_FIELDS, CreateTestCaseForm, EditTestCaseForm,
    TemplateSelectionForm, TemplateForm, EditTemplateForm, TestNoteForm, EditTestNoteForm, ReferenceForm, EditReferenceForm)
from .models import TestCaseStatus, TestCaseTemplate
from .selectors import filter_test_cases, test_case_progress

ERRORS = (ValidationError, EditConflict, IntegrityError, OperationalError)


def _scope(request, engagement_id, permission=Permission.VIEW):
    return get_engagement(request.user, engagement_id, permission)


def _case_url(engagement, case):
    return reverse("testcases:detail", args=[engagement.pk, case.pk])


def _detail_context(request, engagement, case, **extra):
    can_write = not engagement.is_read_only and has_permission(request.user, engagement.pk, Permission.WRITE_TESTS)
    can_note = not engagement.is_read_only and has_permission(request.user, engagement.pk, Permission.WRITE_TEST_NOTES)
    notes = Paginator(case.note_entries.select_related("created_by"), 10).get_page(request.GET.get("note_page"))
    lead = has_permission(request.user, engagement.pk, Permission.EDIT_ENGAGEMENT)
    for note in notes:
        note.can_edit = can_note and (note.created_by_id == request.user.pk or lead)
    return {"engagement": engagement, "case": case, "related_evidence": case.evidence.filter(deleted_at__isnull=True, engagement=engagement), "can_write": can_write, "can_note": can_note,
        "note_page": notes, "reference_page": Paginator(case.references.all(), 20).get_page(request.GET.get("reference_page")),
        "note_form": TestNoteForm(), "reference_form": ReferenceForm(), **extra}


def _panel(request, engagement, case, kind, status=200, **extra):
    if request.headers.get("HX-Request") == "true":
        return render(request, f"components/test_{kind}.html", _detail_context(request, engagement, case, **extra), status=status)
    if status != 200:
        return render(request, "pages/test_detail.html", _detail_context(request, engagement, case, **extra), status=status)
    return redirect(_case_url(engagement, case) + f"#test-{kind}")


@login_required
@require_GET
@vary_on_headers("HX-Request")
def test_list(request, engagement_id):
    engagement = _scope(request, engagement_id)
    cases, query, sort = filter_test_cases(engagement, request.GET)
    context = {"engagement": engagement, "page": Paginator(cases, 20).get_page(request.GET.get("page")),
        "query": query, "sort": sort, "statuses": TestCaseStatus.choices, "progress": test_case_progress(cases),
        "owners": get_user_model().objects.filter(pk__in=engagement.test_cases.values("assigned_tester_id")).order_by("username"),
        "categories": engagement.test_cases.order_by("category").values_list("category", flat=True).distinct(),
        "assets": engagement.assets.order_by("name"),
        "can_write": not engagement.is_read_only and has_permission(request.user, engagement_id, Permission.WRITE_TESTS)}
    template = "components/test_results.html" if request.headers.get("HX-Request") == "true" else "pages/test_list.html"
    return render(request, template, context)


@login_required
@require_GET
@vary_on_headers("HX-Request")
def test_detail(request, engagement_id, pk):
    engagement = _scope(request, engagement_id)
    case = get_object_or_404(engagement.test_cases.select_related("assigned_tester", "source_template", "created_by").prefetch_related("assets"), pk=pk)
    panel = request.GET.get("panel")
    template = f"components/test_{panel}.html" if request.headers.get("HX-Request") == "true" and panel in {"notes", "references"} else "pages/test_detail.html"
    return render(request, template, _detail_context(request, engagement, case))


@login_required
@require_http_methods(["GET", "POST"])
def test_edit(request, engagement_id, pk=None):
    engagement = _scope(request, engagement_id, Permission.WRITE_TESTS)
    if request.method == "GET" and engagement.is_read_only:
        raise PermissionDenied("This engagement is read-only.")
    case = get_object_or_404(engagement.test_cases, pk=pk) if pk else None
    selector = TemplateSelectionForm(request.GET or None)
    initial = {"version": case.version} if case else {}
    status = 200
    if not case and request.method == "GET" and request.GET:
        if selector.is_valid():
            selected = selector.cleaned_data["template"]
            if selected:
                initial = {field: getattr(selected, field) for field in BLUEPRINT_FIELDS}
                initial.update(source_template=selected.pk, template_version=selected.version)
        else:
            status = 400
    form_class = EditTestCaseForm if case else CreateTestCaseForm
    form = form_class(request.POST if request.method == "POST" else None, engagement=engagement, instance=case, initial=initial)
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            data = {field: form.cleaned_data[field] for field in CASE_FIELDS}
            data["assets"] = list(form.cleaned_data["assets"].values_list("pk", flat=True))
            if case:
                saved = services.update_test_case(actor=request.user, engagement_id=engagement_id,
                    test_case_id=pk, data={**data, "status": form.cleaned_data["status"]}, version=form.cleaned_data["version"])
            else:
                selected = form.cleaned_data["source_template"]
                saved = services.create_test_case(actor=request.user, engagement_id=engagement_id,
                    data={**data, "source_template": selected.pk if selected else None, "template_version": form.cleaned_data["template_version"]})
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, _case_url(engagement, saved), message='Changes saved.')
    template = "components/engagement_editor.html" if request.headers.get("HX-Request") == "true" else "pages/test_editor.html"
    return render(request, template, {"engagement": engagement, "case": case, "form": form,
        "title": "Edit test case" if pk else "New test case", "enhance_htmx": True, "template_selector": selector}, status=status)


@login_required
@require_GET
@vary_on_headers("HX-Request")
def template_list(request):
    admin = is_system_admin(request.user)
    templates = TestCaseTemplate.objects.all() if admin else TestCaseTemplate.objects.filter(is_active=True)
    query = request.GET.get("q", "").strip()[:200]
    if query:
        templates = templates.filter(Q(name__icontains=query) | Q(title__icontains=query) | Q(category__icontains=query))
    engagement = None
    if request.GET.get("engagement"):
        try:
            engagement_id = uuid.UUID(request.GET["engagement"])
        except ValueError as exc:
            raise Http404 from exc
        engagement = _scope(request, engagement_id)
    can_use = engagement is not None and not engagement.is_read_only and has_permission(request.user, engagement.pk, Permission.WRITE_TESTS)
    context = {"page": Paginator(templates, 20).get_page(request.GET.get("page")), "query": query,
               "can_manage_templates": admin, "engagement": engagement, "can_use": can_use}
    template = "components/test_template_results.html" if request.headers.get("HX-Request") == "true" else "pages/test_template_list.html"
    return render(request, template, context)


@login_required
@require_GET
def template_detail(request, pk):
    admin = is_system_admin(request.user)
    queryset = TestCaseTemplate.objects.all() if admin else TestCaseTemplate.objects.filter(is_active=True)
    template = get_object_or_404(queryset, pk=pk)
    return render(request, "pages/test_template_detail.html", {"blueprint": template, "can_manage_templates": admin})


@login_required
@require_http_methods(["GET", "POST"])
def template_edit(request, pk=None):
    require_system_admin(request.user)
    template = get_object_or_404(TestCaseTemplate, pk=pk) if pk else None
    form_class = EditTemplateForm if template else TemplateForm
    form = form_class(request.POST if request.method == "POST" else None, instance=template,
                      initial={"version": template.version} if template else {"is_active": True})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            saved = services.save_template(actor=request.user, template_id=pk,
                data={field: form.cleaned_data[field] for field in TEMPLATE_FIELDS}, version=form.cleaned_data.get("version"))
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, reverse("test_templates:detail", args=[saved.pk]), message='Changes saved.')
    page = "components/engagement_editor.html" if request.headers.get("HX-Request") == "true" else "pages/engagement_editor.html"
    return render(request, page, {"form": form, "title": "Edit reusable template" if pk else "New reusable template", "enhance_htmx": True}, status=status)


@login_required
@require_POST
def note_create(request, engagement_id, pk):
    engagement = _scope(request, engagement_id, Permission.WRITE_TEST_NOTES)
    case = get_object_or_404(engagement.test_cases, pk=pk)
    form = TestNoteForm(request.POST)
    status = 400
    if form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.save_test_note(actor=request.user, engagement_id=engagement_id, test_case_id=pk, body=form.cleaned_data["body"])
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return _panel(request, engagement, case, "notes")
    return _panel(request, engagement, case, "notes", status, note_form=form)


@login_required
@require_http_methods(["GET", "POST"])
def note_edit(request, engagement_id, pk, child_id):
    engagement = _scope(request, engagement_id, Permission.WRITE_TEST_NOTES)
    case = get_object_or_404(engagement.test_cases, pk=pk)
    note = get_object_or_404(case.note_entries, pk=child_id)
    if not services.can_edit_test_note(request.user, engagement, note) or (request.method == "GET" and engagement.is_read_only):
        raise PermissionDenied
    form = EditTestNoteForm(request.POST if request.method == "POST" else None, instance=note, initial={"version": note.version})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.save_test_note(actor=request.user, engagement_id=engagement_id, test_case_id=pk,
                note_id=child_id, body=form.cleaned_data["body"], version=form.cleaned_data["version"])
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, _case_url(engagement, case) + "#test-notes", message='Changes saved.')
    page = "components/engagement_editor.html" if request.headers.get("HX-Request") == "true" else "pages/engagement_editor.html"
    return render(request, page, {"engagement": engagement, "form": form, "title": "Edit test-case note", "enhance_htmx": True}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def reference_edit(request, engagement_id, pk, child_id=None):
    engagement = _scope(request, engagement_id, Permission.WRITE_TESTS)
    case = get_object_or_404(engagement.test_cases, pk=pk)
    if request.method == "GET" and engagement.is_read_only:
        raise PermissionDenied
    reference = get_object_or_404(case.references, pk=child_id) if child_id else None
    form_class = EditReferenceForm if reference else ReferenceForm
    form = form_class(request.POST if request.method == "POST" else None, instance=reference,
                      initial={"version": reference.version} if reference else {})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.save_reference(actor=request.user, engagement_id=engagement_id, test_case_id=pk,
                reference_id=child_id, data={field: form.cleaned_data[field] for field in ("label", "url", "citation")}, version=form.cleaned_data.get("version"))
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            if not child_id:
                return _panel(request, engagement, case, "references")
            return saved_redirect(request, _case_url(engagement, case) + "#test-references", message='Changes saved.')
    if not child_id and request.method == "POST":
        return _panel(request, engagement, case, "references", status if status != 200 else 400, reference_form=form)
    page = "components/engagement_editor.html" if request.headers.get("HX-Request") == "true" else "pages/engagement_editor.html"
    return render(request, page, {"engagement": engagement, "form": form, "title": "Edit reference" if child_id else "Add reference", "enhance_htmx": True}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def child_delete(request, engagement_id, pk, child_id, kind):
    permission = Permission.WRITE_TEST_NOTES if kind == "note" else Permission.WRITE_TESTS
    engagement = _scope(request, engagement_id, permission)
    case = get_object_or_404(engagement.test_cases, pk=pk)
    child = get_object_or_404(case.note_entries if kind == "note" else case.references, pk=child_id)
    if kind == "note" and not services.can_edit_test_note(request.user, engagement, child):
        raise PermissionDenied
    if request.method == "GET" and engagement.is_read_only:
        raise PermissionDenied
    form = VersionForm(request.POST if request.method == "POST" else None, initial={"version": child.version})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.delete_test_child(actor=request.user, engagement_id=engagement_id, test_case_id=pk,
                child_id=child_id, kind=kind, version=form.cleaned_data["version"])
        except ERRORS as exc:
            status = mutation_error(form, exc)
        else:
            return saved_redirect(request, _case_url(engagement, case), message='Record removed.')
    return render(request, "pages/test_child_confirm.html", {"engagement": engagement, "case": case,
        "child": child, "kind": kind, "form": form}, status=status)
