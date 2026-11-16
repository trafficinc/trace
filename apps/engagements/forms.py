from django import forms
from django.contrib.auth import get_user_model
from .models import Engagement, EngagementMembership, EngagementNote, EngagementMilestone

ENGAGEMENT_FIELDS = ["name", "client", "description", "objectives", "scope_summary", "start_date", "end_date", "report_classification"]


class EngagementForm(forms.ModelForm):
    class Meta:
        model = Engagement
        fields = ENGAGEMENT_FIELDS
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}), "end_date": forms.DateInput(attrs={"type": "date"}),
                   **{name: forms.Textarea(attrs={"rows": 4}) for name in ("description", "objectives", "scope_summary")}}


class CreateEngagementForm(EngagementForm):
    lead = forms.ModelChoiceField(queryset=get_user_model().objects.filter(is_active=True).order_by("username"))


class EditEngagementForm(EngagementForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class NoteForm(forms.ModelForm):
    class Meta:
        model = EngagementNote
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4, "placeholder": "Add context, decisions or a team update…"})}


class EditNoteForm(NoteForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = EngagementMilestone
        fields = ["title", "description", "due_date"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "due_date": forms.DateInput(attrs={"type": "date"})}


class EditMilestoneForm(MilestoneForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class MilestoneCompletionForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    completed = forms.BooleanField(required=False)


class GrantMembershipForm(forms.Form):
    user = forms.ModelChoiceField(queryset=get_user_model().objects.filter(is_active=True).order_by("username"))
    role = forms.ChoiceField(choices=EngagementMembership.Role.choices)


class ChangeMembershipForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    role = forms.ChoiceField(choices=EngagementMembership.Role.choices)


class VersionForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
