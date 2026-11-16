from django import forms
from .models import Finding, FindingTemplate, FindingStatus

NARRATIVES = ['description', 'technical_details', 'impact', 'reproduction_steps', 'remediation', 'references']
DEFINITION_FIELDS = ['title', 'severity', 'cvss_vector'] + NARRATIVES
FINDING_FIELDS = DEFINITION_FIELDS + ['assets', 'test_cases']
TEMPLATE_FIELDS = DEFINITION_FIELDS + ['is_active']


class NarrativeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in NARRATIVES:
            self.fields[name].strip = False
            self.fields[name].help_text = 'Formatting: headings (#), **bold**, *emphasis*, lists, fenced code, and [label](https://…) links. HTML is displayed as text.'
        self.fields['cvss_vector'].help_text = 'Optional complete CVSS 3.0/3.1 base vector. Scores are not calculated.'


class FindingForm(NarrativeForm):
    def __init__(self, *args, engagement, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.engagement = engagement
        self.fields['assets'].queryset = engagement.assets.all()
        self.fields['test_cases'].queryset = engagement.test_cases.all()

    class Meta:
        model = Finding
        fields = FINDING_FIELDS


class EditFindingForm(FindingForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class TemplateForm(NarrativeForm):
    class Meta:
        model = FindingTemplate
        fields = TEMPLATE_FIELDS


class EditTemplateForm(TemplateForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class TransitionForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    target = forms.ChoiceField(choices=FindingStatus.choices)


class CopyTemplateForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
