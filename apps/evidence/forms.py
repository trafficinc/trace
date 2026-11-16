from django import forms
from .models import Evidence

FIELDS = ['description', 'test_cases', 'findings']


class EvidenceForm(forms.ModelForm):
    def __init__(self, *args, engagement, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.engagement = engagement
        self.fields['test_cases'].queryset = engagement.test_cases.all()
        self.fields['findings'].queryset = engagement.findings.all()
        self.fields['description'].strip = False

    def clean(self):
        values = super().clean()
        if not values.get('test_cases') and not values.get('findings'):
            raise forms.ValidationError('Link evidence to at least one test case or finding.')
        return values

    class Meta:
        model = Evidence
        fields = FIELDS


class UploadEvidenceForm(EvidenceForm):
    file = forms.FileField(label='Evidence file', allow_empty_file=False)


class EditEvidenceForm(EvidenceForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class VersionForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class QuotaForm(forms.Form):
    limit_bytes = forms.IntegerField(required=False, min_value=0, max_value=1024**5,
        label='Engagement evidence quota (bytes)',
        help_text='Blank uses the configured default. 1 GiB = 1,073,741,824 bytes. Zero blocks new evidence; existing files stay intact.')
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
