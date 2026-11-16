from django import forms
from .capture import SCHEMAS
from .models import AuditEvent


class HistoryFilter(forms.Form):
    entity=forms.ChoiceField(required=False,choices=[('','All entities')]+[(k,k.replace('_',' ').title()) for k in SCHEMAS]+[('authentication','Authentication'),('system','System')])
    subject=forms.RegexField(required=False,regex=r'^[0-9a-f\-]{1,64}$',max_length=64,label='Entity ID')
    actor=forms.RegexField(required=False,regex=r'^\d{1,20}$',max_length=20,label='Actor ID')
    action=forms.ChoiceField(required=False,choices=[('','All actions')]+list(AuditEvent.Action.choices))
    date_from=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))
    date_to=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))

    def clean(self):
        data=super().clean()
        if data.get('date_from') and data.get('date_to') and data['date_from']>data['date_to']:
            raise forms.ValidationError('The start date must precede the end date.')
        return data
