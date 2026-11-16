from django import forms
from .models import Report, ReportTemplate, validate_sections

REPORT_FIELDS = ['title', 'executive_summary', 'methodology', 'recommendations', 'header', 'footer', 'marking', 'include_images', 'logo']
TEMPLATE_FIELDS = ['name', 'palette', 'sections', 'is_active']


class ReportForm(forms.ModelForm):
    def __init__(self, *args, engagement, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.engagement = engagement
        self.fields['logo'].queryset = engagement.evidence.filter(deleted_at__isnull=True, kind__in=['png', 'jpeg'])
        self.fields['additional_evidence'].queryset = engagement.evidence.filter(deleted_at__isnull=True).order_by('original_filename', 'id')
        self.fields['additional_evidence'].label = 'Additional evidence to include'
        self.fields['additional_evidence'].help_text = 'Select evidence directly, including screenshots linked only to test cases. Evidence related to selected findings is included automatically. Hold Ctrl (Windows/Linux) or Command (Mac) to select multiple items.'
        self.fields['include_images'].help_text = 'Embed supported evidence images in Evidence references when generating a new revision. Save this setup first; existing revisions stay unchanged.'
        for field in ['executive_summary', 'methodology', 'recommendations']:
            self.fields[field].strip = False
        self.fields['marking'].help_text = 'Exact supplied marking; blank adds no classification.'
        self.fields['logo'].help_text = 'Uses only a regenerated image from private engagement evidence. Clear or replace a logo if its evidence was removed.'

    class Meta:
        model = Report
        fields = [*REPORT_FIELDS, 'additional_evidence']


class EditReportForm(ReportForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class CreateReportForm(ReportForm):
    source_template = forms.ModelChoiceField(queryset=ReportTemplate.objects.filter(is_active=True), required=False, widget=forms.HiddenInput)
    template_version = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)


class FindingChoiceForm(forms.Form):
    finding = forms.UUIDField(widget=forms.HiddenInput)
    include = forms.BooleanField(required=False)
    position = forms.IntegerField(min_value=1, max_value=500)


FindingChoiceFormSet = forms.formset_factory(FindingChoiceForm, extra=0, max_num=500, validate_max=True, absolute_max=500)


class TemplateForm(forms.ModelForm):
    sections = forms.CharField(widget=forms.Textarea, help_text='List every supported section once, one per line, in report order.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial['sections'] = '\n'.join(self.instance.sections)

    def clean_sections(self):
        values = self.cleaned_data['sections'].split()
        validate_sections(values)
        return values

    class Meta:
        model = ReportTemplate
        fields = TEMPLATE_FIELDS


class EditTemplateForm(TemplateForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class GenerateForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
