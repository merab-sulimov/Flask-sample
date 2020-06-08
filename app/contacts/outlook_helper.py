import os
import requests
from flask import Blueprint, url_for, make_response, request, redirect, abort, render_template, session, json, g
from flask_oauth import OAuth
import urllib
import base64

from app import app
from app.models import UserContact


contacts_outlook = Blueprint('contacts_outlook', __name__)

oa = OAuth()

HOTMAIL_CLIENT_ID = app.config['OAUTH_CREDENTIALS']['outlook'].get('id')
HOTMAIL_PASSWORD = app.config['OAUTH_CREDENTIALS']['outlook'].get('secret')

ou = oa.remote_app(
    'hotmail',
    base_url='https://apis.live.net/v5.0/',
    authorize_url='https://login.live.com/oauth20_authorize.srf',
    request_token_url=None,
    request_token_params={
       'scope': 'wl.basic wl.emails',
       'response_type': 'code',
    },
    access_token_url='https://login.live.com/oauth20_token.srf',
    access_token_method='POST',
    access_token_params={
       'grant_type': 'authorization_code'
    },
    consumer_key=HOTMAIL_CLIENT_ID,
    consumer_secret=HOTMAIL_PASSWORD
)


# This method decodes the data. It is quite unsofisticated, if there are
# multiple names/emails it extracts only the first one, only contacts that
# have emails are added
def decode_contacts(returned_contacts):
    contacts = []
    if len(returned_contacts['data']) > 0:
        for f in returned_contacts['data']:
            contact = {}
            if f.get('first_name') is not None:
                first_name = f.get('first_name', '')
                last_name = f.get('last_name', '')
                contact['name'] = '%s %s' % (first_name, last_name)
                contact['name'] = contact['name'].strip()

            if f.get('emails') is not None:
                contact['email'] = f.get('emails').get('preferred')
                contacts.append(contact)

    return contacts


@contacts_outlook.route('/login')
def login():
    callback = url_for('contacts_outlook.auth', _external=True)
    return ou.authorize(callback=callback)


@contacts_outlook.route('/auth')
@ou.authorized_handler
def auth(resp):
    access_token = resp.get('access_token')
    
    session['CONTACTS_ACCESS_TOKEN'] = access_token

    return render_template('new/oauth/contacts_callback.html')


@contacts_outlook.route('/get_contacts')
def get_contacts():
    try:
        access_token = session['CONTACTS_ACCESS_TOKEN'].replace(' ', '+')
    except:
        abort(401)

    headers = {"Authorization": 'Bearer %s' % access_token}

    r = requests.get('https://apis.live.net/v5.0/me/contacts', headers=headers)

    contacts = decode_contacts(r.json())

    # Save contacts into our database
    UserContact.save_multiple(g.user.id, contacts)

    return json.jsonify(contacts)

