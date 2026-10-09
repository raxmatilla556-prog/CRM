from django import forms

from core.models import User


class StyledFormMixin:
    """Bootstrap klasslarini avtomatik qo'shadi."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class UserForm(StyledFormMixin, forms.ModelForm):
    password = forms.CharField(label='Parol', required=False, widget=forms.PasswordInput, min_length=6)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'phone', 'role', 'language', 'is_active']
        labels = {
            'username': 'Login', 'first_name': 'Ism', 'last_name': 'Familiya',
            'phone': 'Telefon', 'role': 'Rol', 'language': 'Til', 'is_active': 'Faol',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].help_text = ''
        if not self.instance.pk:
            self.fields['password'].required = True

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('password'):
            user.set_password(self.cleaned_data['password'])
            # Ega bergan parol vaqtinchalik: xodim birinchi kirishda o'zinikiga almashtiradi
            user.must_change_password = True
        if commit:
            user.save()
        return user
