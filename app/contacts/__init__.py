from app import app
from app.models import db, UserContact

from .aol_helper import contacts_aol
from .google_helper import contacts_google
from .yahoo_helper import contacts_yahoo
from .outlook_helper import contacts_outlook


app.register_blueprint(contacts_aol, url_prefix='/contacts/aol')
app.register_blueprint(contacts_google, url_prefix='/contacts/google')
app.register_blueprint(contacts_yahoo, url_prefix='/contacts/yh')
app.register_blueprint(contacts_outlook, url_prefix='/contacts/outlook')
