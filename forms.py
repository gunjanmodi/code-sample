

# django specific imports
from django import forms

# Third party library specific imports
import pycountry

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Submit, Button, Field
from crispy_forms.bootstrap import FormActions

# project specific imports
from LoadIQWeb.models import Customer, Building

class AddUserForm(forms.Form):
    user_group = forms.CharField(widget=forms.HiddenInput())
    user_username = forms.RegexField(
        label="Username",
        max_length=30,
        regex=r"^[\w.@+-]+$",
        required=True,
    )
    user_first_name = forms.CharField(required=True, max_length=45, label=_("First Name"))
    user_last_name = forms.CharField(required=True, max_length=45, label=_("Last Name"))
    user_email = forms.EmailField(max_length=254, label=_("Email"))
    user_password1 = forms.CharField(widget=forms.PasswordInput, label=_("Password"))
    user_password2 = forms.CharField(widget=forms.PasswordInput, label=_("Confirm Password"))
    user_customer = forms.CharField(widget=forms.HiddenInput())

    helper = FormHelper()

    helper.form_class = 'form-horizontal'
    helper.form_id = 'addUserForm'
    helper.form_action = '/users/add_user/'

    helper.layout = Layout(
        Div(Field('user_username', css_class='form-control'), css_class='form-group'),
        Div(Field('user_first_name', css_class='form-control'), css_class='form-group'),
        Div(Field('user_last_name', css_class='form-control'), css_class='form-group'),
        Div(Field('user_email', css_class='form-control'), css_class='form-group'),
        Div(Field('user_password1', css_class='form-control'), css_class='form-group'),
        Div(Field('user_password2', css_class='form-control'), css_class='form-group'),
        Field('user_customer'),
        Field('user_group'),
        Div(FormActions(
            Button('add-user-submit', 'Submit', css_class="btn btn-shadow btn-danger center-block"),
        ), css_class='form-group')
    )

    def clean_user_username(self):
        """
        Validate that the cp_username is alphanumeric and is not already in use.
        """
        existing = User.objects.filter(username__iexact=self.cleaned_data['user_username'])
        if existing.exists():
            raise forms.ValidationError(_("A user with that username already exists."))
        else:
            return self.cleaned_data['user_username']

    def clean(self):
        """
        Verifiy that the values entered into the two password fields
        match. Note that an error here will end up in
        ``non_field_errors()`` because it doesn't apply to a single
        field.
        """
        if 'user_password1' in self.cleaned_data and 'user_password2' in self.cleaned_data:
            if self.cleaned_data['user_password1'] != self.cleaned_data['user_password2']:
                raise forms.ValidationError(_("The two password fields didn't match."))
        return self.cleaned_data
        

class AddBuildingAdmin(AddUserForm):
    user_building = DynamicChoiceField(required=False, label=_("Building"),
                                       widget=forms.Select(attrs={'id': 'selectBuildingForAdmin'}))

    helper = FormHelper()
    helper.form_class = 'form-horizontal'
    helper.form_id = 'addBuildingAdminForm'
    helper.form_action = '/users/add_building_admin/'

    helper.layout = Layout(
        Div(Field('user_building', css_class='form-control'), css_class='form-group'),
        Div(Field('user_username', css_class='form-control', id='building_admin_user'), css_class='form-group'),
        Div(Field('user_first_name', css_class='form-control', id='building_admin_first_name'), css_class='form-group'),
        Div(Field('user_last_name', css_class='form-control',  id='building_admin_last_name'), css_class='form-group'),
        Div(Field('user_email', css_class='form-control',  id='building_admin_email'), css_class='form-group'),
        Div(Field('user_password1', css_class='form-control', id='building_admin_password1'), css_class='form-group'),
        Div(Field('user_password2', css_class='form-control', id='building_admin_password2'), css_class='form-group'),
        Field('user_customer', id='building_admin_customer'),
        Field('user_group', id='building_admin_user_group'),
        Div(FormActions(
            Button('add-building-admin-submit', 'Submit', css_class="btn btn-shadow btn-danger center-block"),
        ), css_class='form-group')
    )

    def clean_user_username(self):
        """
        Validate that the cp_username is alphanumeric and is not already in use.
        """
        existing = User.objects.filter(username__iexact=self.cleaned_data['user_username'])
        if existing.exists():
            raise forms.ValidationError(_("A user with that username already exists."))
        else:
            return self.cleaned_data['user_username']

    def clean(self):
        """
        Verifiy that the values entered into the two password fields
        match. Note that an error here will end up in
        ``non_field_errors()`` because it doesn't apply to a single
        field.
        """
        if 'user_password1' in self.cleaned_data and 'user_password2' in self.cleaned_data:
            if self.cleaned_data['user_password1'] != self.cleaned_data['user_password2']:
                raise forms.ValidationError(_("The two password fields didn't match."))
        return self.cleaned_data