import os
import requests
from flask import Blueprint, url_for, make_response, request, abort, redirect, render_template, session, json, g
from flask_oauth import OAuth

from app import app
from app.models import UserContact


contacts_google = Blueprint('contacts_google', __name__)

oa = OAuth()

GOOGLE_CLIENT_ID = app.config['OAUTH_CREDENTIALS']['google'].get('id')
GOOGLE_CLIENT_SECRET = app.config['OAUTH_CREDENTIALS']['google'].get('secret')

gg = oa.remote_app(
    'google',
    base_url='https://www.google.com/accounts/',
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    request_token_url=None,
    request_token_params={
       'scope':
           'https://www.googleapis.com/auth/contacts.readonly '
           'https://www.googleapis.com/auth/userinfo.profile',
       'response_type': 'code'
    },
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_method='POST',
    access_token_params={
       'grant_type': 'authorization_code'
    },
    consumer_key=GOOGLE_CLIENT_ID,
    consumer_secret=GOOGLE_CLIENT_SECRET
)


def decode_contact(conn):
    emails = conn.get('emailAddresses')
    names = conn.get('names')
    contact = {}

    if names is not None and len(names) > 0:
        contact['name'] = names[0]['displayName']

    if emails is not None and len(emails) > 0:
        contact['email'] = emails[0]['value']
        if contact.get('name', '') == contact['email']:
            # Do not set name if we've got email instead name
            contact['name'] = ''

    return contact


# This method decodes the data. It is quite unsofisticated, if there are
# multiple names/emails it extracts only the first one, only contacts that
# have emails are added
def decode_contacts(returned_contacts):
    contacts = []
    for conn in returned_contacts['connections']:
            contact = decode_contact(conn)
            if len(contact) > 1:
                contacts.append(contact)

    return contacts


@contacts_google.route('/login')
def login():
    callback = url_for('contacts_google.auth', _external=True)

    # TODO: remove this workaround for dev server:
    if app.config['DEVELOPMENT']:
        callback = callback.replace('//localhost', '//localhost:5002')

    return gg.authorize(callback=callback)


@contacts_google.route('/auth')
@gg.authorized_handler
def auth(resp):
    access_token = resp['access_token']
    
    session['CONTACTS_ACCESS_TOKEN'] = access_token

    return render_template('new/oauth/contacts_callback.html')


@contacts_google.route('/get_contacts')
def get_contacts():
    try:
        access_token = session['CONTACTS_ACCESS_TOKEN']
    except:
        abort(401)

    headers = {"Authorization": 'Bearer %s' % access_token}

    payload = {
        'personFields': 'emailAddresses,names,ageRanges,birthdays,genders,'
                        'locales,phoneNumbers'
    }
    r = requests.get('https://people.googleapis.com/v1/people/me/connections',
                     headers=headers, params=payload)
    contacts = decode_contacts(r.json())

    # Save contacts into our database
    UserContact.save_multiple(g.user.id, contacts)

    return json.jsonify(contacts)

