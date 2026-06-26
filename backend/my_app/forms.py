from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User


class SignUpForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "username": "Username",
            "email": "Email",
            "password1": "Password",
            "password2": "Confirm password",
        }
        for field_name, placeholder in placeholders.items():
            self.fields[field_name].widget.attrs.update(
                {"placeholder": placeholder})
            self.fields[field_name].label = ""


class StyledLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "Username"})
        self.fields["username"].label = ""
        self.fields["password"].widget.attrs.update(
            {"placeholder": "Password"})
        self.fields["password"].label = ""


class ChatMessageForm(forms.Form):
    message = forms.CharField(
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "Ask about a destination, trek, or budget..."}),
        max_length=1000,
        label="",
    )
