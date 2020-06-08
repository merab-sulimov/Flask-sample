from flask import session
from flask_wtf import Form
from wtforms import StringField, PasswordField, SubmitField, ValidationError, SelectField
from wtforms.validators import Email, DataRequired, Length, Regexp, EqualTo

from app.utils.country import COUNTRIES
from ..models import User


COUNTRIES_MODIFIED = map(lambda item: item[:2], COUNTRIES)


class RegisterForm(Form):
    username = StringField('Username', validators=[
        DataRequired(),
        Length(3, 20),
        Regexp('^[A-Za-z][A-Za-z0-9_.]*$', 0,
               'Usernames must contain only letters, '
               'numbers, dots or underscores')])

    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(8, 20),
        EqualTo('password2', message='Passwords must match.')])
    password2 = PasswordField('Confirm password', validators=[DataRequired()])

    email = StringField('E-mail', validators=[DataRequired(), Email()])

    country = SelectField('Country', choices=([(u'', 'Select country',),] + COUNTRIES_MODIFIED), coerce=unicode, validators=[DataRequired()])

    invite = StringField('Invite code')
    page = StringField('Page')

    captcha = StringField('Captcha')
    submit = SubmitField('Sign Up')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('Email already registered.')

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('Username already in use.')


class LoginForm(Form):
    username = StringField('Username', validators=[DataRequired(), Length(3, 50)])
    password = PasswordField('Password', validators=[DataRequired()])

    captcha = StringField('Captcha')
    submit = SubmitField('Sign In')

    def validate_captcha(self, field):
        if session.get('login_attempts', 0) < 500: # TODO: once captcha is back, change back to 5
            return

        if field.data != session.get('captcha'):
            raise ValidationError('Wrong captcha value')


class RecoveryForm(Form):
    username = StringField('Username', validators=[DataRequired(), Length(3, 50)])


class RecoveryCompleteForm(Form):
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(8, 20),
        EqualTo('password2', message='Passwords must match.')])
    password2 = PasswordField('Confirm password', validators=[DataRequired()])

    token = StringField('token', validators=[DataRequired()])
