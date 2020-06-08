from flask_wtf import Form
from wtforms import StringField, BooleanField, SelectField
from wtforms.validators import DataRequired, URL, Optional
from app.models import Report


class ReportAPIForm(Form):
    CTYPES = [
        ('audio', 'AUDIO'),
        ('description', 'DESCRIPTION'),
        ('image', 'IMAGE'),
        ('video', 'VIDEO')
    ]

    reason = SelectField('Reason', choices=Report.REASONS, validators=[DataRequired()])

    # if non_original_content
    content_type = SelectField('contentType', choices=CTYPES, validators=[Optional()])
    url_to_original_content = StringField('Url To Original Content', validators=[Optional(), URL()])
    additional_information = StringField('Additional Information', validators=[Optional()])

    # if inappropriate_gig
    description = StringField('Description', validators=[Optional()])
    reference_url = StringField('Reference URL', validators=[Optional(), URL()])

    # if trademark_violation
    # description = StringField('Description', validators=[Optional()])
    being_infringed = StringField('Being Infringed', validators=[Optional()])
    registration_no = StringField('Registration No', validators=[Optional()])
    class_and_jurisdiction = StringField('Class And Jurisdiction', validators=[Optional()])
    accept = BooleanField('Accept', validators=[Optional()])

    # if copytights_violation
    # url_to_original_content = StringField('Url To Original Content', validators=[Optional(), URL()])
    proof = StringField('Proof', validators=[Optional()])
    # description = StringField('Description', validators=[Optional()])
    # accept = BooleanField('Accept', validators=[Optional()])

    def validate(self):
        is_valid = super(ReportAPIForm, self).validate()
        if is_valid:
            for field in self.get_extra_fields_by_reason():
                getattr(self, field).validators.insert(0, DataRequired())
            is_valid = super(ReportAPIForm, self).validate()
        return is_valid

    def get_extra_fields_by_reason(self):
        reason = self.reason.data
        if reason == 'non_original_content':
            fields = ['content_type', 'url_to_original_content', 'additional_information']
        elif reason == 'inappropriate_gig':
            fields = ['description', 'reference_url']
        elif reason == 'trademark_violation':
            fields = ['description', 'being_infringed', 'registration_no', 'class_and_jurisdiction', 'accept']
        elif reason == 'copyrights_violation':
            fields = ['url_to_original_content', 'proof', 'description', 'accept']
        return fields

    def get_extra_data_as_json(self):
        result = {}
        for field in self.get_extra_fields_by_reason():
            result[field] = getattr(self, field).data
        return result