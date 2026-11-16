from django import forms
from django.contrib.auth import get_user_model
from .models import Asset

ASSET_FIELDS = ["name", "asset_type", "hostname", "ip_cidr", "url", "description", "environment", "scope_status", "owner"]


class AssetForm(forms.ModelForm):
    url = forms.URLField(label="URL", required=False, max_length=2048, assume_scheme="https")

    def __init__(self, *args, engagement, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.engagement = engagement
        self.fields["owner"].queryset = get_user_model().objects.filter(is_active=True, engagement_memberships__engagement=engagement).order_by("username")
        self.fields["owner"].help_text = "Optional active member of this engagement."
        if self.instance.owner_id and not self.fields["owner"].queryset.filter(pk=self.instance.owner_id).exists():
            self.fields["owner"].help_text = "The previous owner is no longer eligible. Choose an active engagement member or clear the owner."
        self.fields["description"].strip = False

    class Meta:
        model = Asset
        fields = ASSET_FIELDS
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}


class EditAssetForm(AssetForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
