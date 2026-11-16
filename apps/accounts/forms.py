from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User


class CreateUserForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "first_name", "last_name", "email"]


class ProfileForm(forms.ModelForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]


class UserStatusForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    is_active = forms.BooleanField(required=False)
