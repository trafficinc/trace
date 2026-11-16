"""Shared Bootstrap widget classes; preserve Django's labels and ARIA errors."""
from django.forms import CheckboxInput, HiddenInput, Select
from django.forms.boundfield import BoundField
from django.forms.renderers import DjangoTemplates


class BootstrapBoundField(BoundField):
    def as_widget(self, widget=None, attrs=None, only_initial=False):
        widget=widget or self.field.widget
        attrs=dict(attrs or {})
        if not isinstance(widget,HiddenInput):
            css='form-check-input' if isinstance(widget,CheckboxInput) else 'form-select' if isinstance(widget,Select) else 'form-control'
            attrs['class']=' '.join(filter(None,[widget.attrs.get('class',''),attrs.get('class',''),css]))
        return super().as_widget(widget=widget,attrs=attrs,only_initial=only_initial)


class BootstrapFormRenderer(DjangoTemplates):
    bound_field_class=BootstrapBoundField
