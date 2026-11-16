from django import forms
from django.contrib.auth import get_user_model
from .models import TestCase, TestCaseTemplate, TestCaseNote, TestCaseReference

BLUEPRINT_FIELDS = ["title", "description", "category", "objective", "methodology", "procedure", "expected_result"]
CASE_FIELDS = BLUEPRINT_FIELDS + ["actual_result", "assigned_tester", "notes"]
TEMPLATE_FIELDS = ["name", *BLUEPRINT_FIELDS, "is_active"]


class TestCaseForm(forms.ModelForm):
    def __init__(self, *args, engagement, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.engagement = engagement
        self.fields["assigned_tester"].queryset = get_user_model().objects.filter(is_active=True,
            engagement_memberships__engagement=engagement, engagement_memberships__role__in=["lead", "tester"]).order_by("username")
        self.fields["assigned_tester"].help_text = "Optional active Lead or Tester in this engagement."
        if self.instance.assigned_tester_id and not self.fields["assigned_tester"].queryset.filter(pk=self.instance.assigned_tester_id).exists():
            self.fields["assigned_tester"].help_text = "The previous assignee is no longer eligible. Choose an active engagement Lead/Tester or clear the assignment."
        self.fields["assets"].queryset = engagement.assets.order_by("name")
        self.fields["assets"].help_text = "Optional; select assets from this engagement only."
        self.fields["actual_result"].help_text = "Required when marking a test passed or failed."
        for field in ("description", "objective", "methodology", "procedure", "expected_result", "actual_result", "notes"):
            self.fields[field].strip = False

    class Meta:
        model = TestCase
        fields = CASE_FIELDS + ["assets"]
        widgets = {field: forms.Textarea(attrs={"rows": 5, "class": "work-textarea"}) for field in
                   ["description", "objective", "methodology", "procedure", "expected_result", "actual_result", "notes"]}


class CreateTestCaseForm(TestCaseForm):
    source_template = forms.ModelChoiceField(queryset=TestCaseTemplate.objects.filter(is_active=True), required=False, widget=forms.HiddenInput)
    template_version = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)


class EditTestCaseForm(TestCaseForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].help_text = "Use In progress to start or resume. Resume blocked/finished tests before recording a new outcome."

    class Meta(TestCaseForm.Meta):
        fields = CASE_FIELDS + ["assets", "status"]


class TemplateSelectionForm(forms.Form):
    template = forms.ModelChoiceField(queryset=TestCaseTemplate.objects.filter(is_active=True), required=False, empty_label="Manual test case")


class TemplateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("description", "objective", "methodology", "procedure", "expected_result"):
            self.fields[field].strip = False

    class Meta:
        model = TestCaseTemplate
        fields = TEMPLATE_FIELDS
        widgets = {field: forms.Textarea(attrs={"rows": 5, "class": "work-textarea"}) for field in
                   ["description", "objective", "methodology", "procedure", "expected_result"]}


class EditTemplateForm(TemplateForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class TestNoteForm(forms.ModelForm):
    body = forms.CharField(max_length=20000, strip=False, widget=forms.Textarea(attrs={"rows": 4, "class": "work-textarea"}))

    def clean_body(self):
        value = self.cleaned_data["body"]
        if not value.strip():
            raise forms.ValidationError("Enter a nonempty note.")
        return value

    class Meta:
        model = TestCaseNote
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4, "class": "work-textarea"})}


class EditTestNoteForm(TestNoteForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class ReferenceForm(forms.ModelForm):
    url = forms.URLField(required=False, max_length=2048, assume_scheme="https")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["citation"].strip = False

    class Meta:
        model = TestCaseReference
        fields = ["label", "url", "citation"]
        widgets = {"citation": forms.Textarea(attrs={"rows": 3})}


class EditReferenceForm(ReferenceForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
