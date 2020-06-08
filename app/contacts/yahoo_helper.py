import os
import requests
from flask import Blueprint, url_for, make_response, request, redirect, abort, render_template, session, json, g
from flask_oauth import OAuth

from app import app
from app.models import UserContact


contacts_yahoo = Blueprint('contacts_yahoo', __name__)

oa = OAuth()

YAHOO_CLIENT_ID = app.config['OAUTH_CREDENTIALS']['yahoo'].get('id')
YAHOO_CLIENT_SECRET = app.config['OAUTH_CREDENTIALS']['yahoo'].get('secret')

yh = oa.remote_app(
    'yahoo',
    base_url='https://query.yahooapis.com/',
    authorize_url='https://api.login.yahoo.com/oauth2/request_auth',
    request_token_url=None,
    request_token_params={
       'scope': 'sdct-r',
       'response_type': 'code',
    },
    access_token_url='https://api.login.yahoo.com/oauth2/get_token',
    access_token_method='POST',
    access_token_params={
       'grant_type': 'authorization_code'
    },
    consumer_key=YAHOO_CLIENT_ID,
    consumer_secret=YAHOO_CLIENT_SECRET
)


# This method decodes the data. It is quite unsofisticated, if there are
# multiple names/emails it extracts only the first one, only contacts that
# have emails are added
def decode_contacts(returned_contacts):
    contacts = []
    if returned_contacts['contacts']['count'] > 0:
        for c in returned_contacts['contacts']['contact']:
            contact = {}
            for f in c.get('fields'):

                if f.get('type') == 'name':
                    first_name = f.get('givenName', '')
                    middle_name = f.get('middleName', '')
                    last_name = f.get('familyName', '')
                    contact['name'] = '%s %s %s' % (first_name, middle_name,
                                                    last_name)

                    contact['name'] = contact['name'].strip()

                if f.get('type') == 'email':
                    contact['email'] = f.get('value')
                    contacts.append(contact)

    return contacts


@contacts_yahoo.route('/login')
def login():
    callback = url_for('contacts_yahoo.auth', _external=True)
    return yh.authorize(callback=callback)


@contacts_yahoo.route('/auth')
@yh.authorized_handler
def auth(resp):
    access_token = resp.get('access_token')
    guid = resp.get('xoauth_yahoo_guid')

    session['CONTACTS_GUID'] = guid
    session['CONTACTS_ACCESS_TOKEN'] = access_token
    
    return render_template('new/oauth/contacts_callback.html')


@contacts_yahoo.route('/get_contacts')
def get_contacts():
    try:
        access_token = session['CONTACTS_ACCESS_TOKEN']
        guid = session['CONTACTS_GUID']
    except:
        abort(401)

    headers = {"Authorization": 'Bearer %s' % access_token}
    payload = {
        'format': 'json'
    }

    r = requests.get('https://social.yahooapis.com/v1/user/%s/contacts' % guid,
                     headers=headers, params=payload)

    contacts = decode_contacts(r.json())

    # Save contacts into our database
    UserContact.save_multiple(g.user.id, contacts)

    return json.jsonify(contacts)

