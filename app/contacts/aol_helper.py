import os
import requests
from flask import Blueprint, url_for, make_response, request, redirect, abort, render_template, session, json, g
from flask_oauth import OAuth

from app import app
from app.models import UserContact


contacts_aol = Blueprint('contacts_aol', __name__)

oa = OAuth()

AOL_CLIENT_ID = app.config['OAUTH_CREDENTIALS']['aol'].get('id')
AOL_CLIENT_SECRET = app.config['OAUTH_CREDENTIALS']['aol'].get('secret')

yh = oa.remote_app('aol',
    base_url='https://api.screenname.aol.com/',
    authorize_url='https://api.screenname.aol.com/auth/authorize',
    request_token_url=None,
    request_token_params={
       'scope': 'profile email addressbook',
       'response_type': 'code',
    },
    access_token_url='https://api.screenname.aol.com/auth/access_token',
    access_token_method='POST',
    access_token_params={
       'grant_type': 'authorization_code'
    },
    consumer_key=AOL_CLIENT_ID,
    consumer_secret=AOL_CLIENT_SECRET
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

                if f.get('type') == 'email':
                    contact['email'] = f.get('value')
                    contacts.append(contact)

    return contacts


@contacts_aol.route('/login')
def login():
    callback = url_for('contacts_aol.auth', _external=True)
    return yh.authorize(callback=callback)


@contacts_aol.route('/auth')
@yh.authorized_handler
def auth(resp, email):
    access_token = resp.get('access_token')
    
    session['CONTACTS_ACCESS_TOKEN'] = access_token

    return render_template('new/oauth/contacts_callback.html')


@contacts_aol.route('/get_contacts')
def get_contacts():
    try:
        access_token = session['CONTACTS_ACCESS_TOKEN']
    except:
        abort(401)

    headers = {"Authorization": 'Bearer %s' % access_token}

    r = requests.get('https://api.screenname.aol.com/auth/getAddressBook',
                     headers=headers)

    contacts = decode_contacts(r.json())

    # Save contacts into our database
    UserContact.save_multiple(g.user.id, contacts)

    return json.jsonify(contacts)

