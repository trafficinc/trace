from apps.core.http import render_page as render
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash, views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.debug import sensitive_post_parameters
from apps.core.exceptions import EditConflict
from apps.core.http import mutation_error, saved_redirect
from apps.engagements.permissions import require_system_admin
from .forms import CreateUserForm, ProfileForm, UserStatusForm
from .models import User
from . import services
from .throttling import record_unhandled_failure


class LoginView(auth_views.LoginView):
    template_name = "pages/login.html"
    redirect_authenticated_user = False

    def form_invalid(self, form):
        record_unhandled_failure(self.request)
        response = super().form_invalid(form)
        if getattr(self.request, "trace_login_retry_after", 0):
            response.status_code = 429
            response["Retry-After"] = str(self.request.trace_login_retry_after)
        return response


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(request.POST if request.method == "POST" else None, instance=request.user,
                       initial={"version": request.user.version})
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.update_profile(actor=request.user, data=form.cleaned_data, version=form.cleaned_data["version"])
        except (EditConflict, ValidationError, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            messages.success(request, "Profile updated.")
            return saved_redirect(request, reverse("accounts:profile"))
    return render(request, "pages/profile.html", {"form": form}, status=status)


@login_required
@sensitive_post_parameters("old_password", "new_password1", "new_password2")
@require_http_methods(["GET", "POST"])
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST if request.method == "POST" else None)
    version_form = UserStatusForm(request.POST if request.method == "POST" else None,
                                  initial={"version": request.user.version})
    status = 200
    if request.method == "POST" and form.is_valid() and version_form.is_valid():
        try:
            user = services.change_password(actor=request.user, old_password=form.cleaned_data["old_password"],
                new_password=form.cleaned_data["new_password1"], version=version_form.cleaned_data["version"])
        except (EditConflict, ValidationError, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            update_session_auth_hash(request, user)
            messages.success(request, "Password changed.")
            return saved_redirect(request, reverse("accounts:profile"))
    return render(request, "pages/password_change.html", {"form": form, "version_form": version_form}, status=status)


@login_required
@require_GET
def users(request):
    require_system_admin(request.user)
    page = Paginator(User.objects.order_by("username"), 50).get_page(request.GET.get("page"))
    return render(request, "pages/users.html", {"page": page})


@login_required
@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "POST"])
def user_create(request):
    require_system_admin(request.user)
    form = CreateUserForm(request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST" and form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.create_account(actor=request.user, data=request.POST)
        except (ValidationError, IntegrityError, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            messages.success(request, "User created. Share credentials through your approved private channel.")
            return saved_redirect(request, reverse("accounts:users"))
    return render(request, "pages/user_create.html", {"form": form}, status=status)


@login_required
@require_POST
def user_status(request, pk):
    require_system_admin(request.user)
    form = UserStatusForm(request.POST)
    status = 400
    if form.is_valid() and not request.POST.get('_prepare_merge'):
        try:
            services.set_account_active(actor=request.user, user_id=pk,
                active=form.cleaned_data["is_active"], version=form.cleaned_data["version"])
        except (ValidationError, EditConflict, OperationalError) as exc:
            status = mutation_error(form, exc)
        else:
            messages.success(request, "Account access updated.")
            return saved_redirect(request, reverse("accounts:users"))
    return render(request, "pages/action_error.html", {"form": form, "title": "Account update was not saved"}, status=status)
