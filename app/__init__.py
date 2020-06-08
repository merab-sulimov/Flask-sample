import os
import jinja2
from redis import Redis
from pyelasticsearch import ElasticSearch
from flask import Flask, g, request, send_from_directory
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from raven.contrib.flask import Sentry
import stripe

from app.session import RedisSessionInterface


db = SQLAlchemy()
login_manager = LoginManager()
app = Flask(__name__)


try:
    app.config.from_object(os.environ['SIMPLEFLASK_CONFIG'])
except:
    print 'WARNING: running with config.DevelopmentConfig since SIMPLEFLASK_CONFIG variable is not set'
    app.config.from_object('config.DevelopmentConfig')


# Check out versions of applications. Version is basically a git commit
# For now, only frontend version is used to prevent caching of assets after update

app_versions = dict()

try:
    with open(os.path.join(app.config['FRONTEND_BUILD_LOCATION'], 'VERSION'), 'rt') as f:
        app_versions['frontend'] = f.read()

    if app.config['LOCAL_DEVELOPMENT']:
        # For local development environment, serve static assets from their custom path
        @app.route('/static/assets/<path:filename>')
        def custom_static_asset(filename):
            return send_from_directory(app.config['FRONTEND_BUILD_LOCATION'], filename)
except IOError:
    pass

print 'Application versions:', app_versions

# Set up custom template folder

app.template_folder = app.config['CUSTOM_TEMPLATE_FOLDER']

# Initialise redis and elasticsearch

redis = Redis()

es = ElasticSearch(app.config['ELASTICSEARCH_URI'])
import search

try:
    search.create_index()
except:
    # This almost always means that index already exists
    pass

# Set up sessions

app.session_interface = RedisSessionInterface(redis=redis)

# Initialise extensions with the app instance

db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

# Init statistic layer

import statistic

# Init sentry

if not app.config['DEVELOPMENT'] and not app.config['LOCAL_DEVELOPMENT']:
    sentry = Sentry(app, dsn=app.config.get('SENTRY_DSN'))
else:
    print 'WARNING: Sentry is not active in DEVELOPMENT/LOCAL_DEVELOPMENT modes'
    sentry = Sentry(app, dsn=None)

# Init stripe

stripe.api_key = app.config['STRIPE_SECRET_KEY']

# Import main views and register blueprints

import frontend
import helpers
import webhooks

from .auth import auth as auth_blueprint
app.register_blueprint(auth_blueprint)

from .account import account as account_blueprint
app.register_blueprint(account_blueprint)

from .admin import admin as admin_blueprint
app.register_blueprint(admin_blueprint)

import contacts


# Enable developer API, only if config option is set

if app.config['DEVELOPMENT']:
    print 'WARNING: DEVELOPMENT mode is ON which means that developer API is enabled'
    import developer
    app._template_folder = app.template_folder = developer.create_template_directory()
    app.jinja_loader = jinja2.FileSystemLoader(app.template_folder)
    developer.copy_templates(app.config['CUSTOM_TEMPLATE_FOLDER'], app.template_folder)

# LoginManager user loader

from models import User


@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))


# Before/After request hooks go here

import cache


@app.before_request
def before_request():
    g.user = current_user
    g.ip = request.headers.get('X-Real-IP', '127.0.0.1')
    g.debug = app.config['DEBUG']

    if g.user.is_authenticated and not request.is_xhr:
        # Trigger last_logged_on date update
        g.user.action('online')

        if g.user.seller_fee_paid:
            # For seller, update ES index with last logged on date (not every request, only if cache item is expired)
            if not cache.is_user_online(g.user.id):
                cache.set_user_online(g.user.id)
                search.seller_online.send(seller=g.user)

    if app.config['DEVELOPMENT']:
        if 'X-Dev-API-Key' in request.headers:
            key = request.headers['X-Dev-API-Key']
            g.developer = next((item for item in app.config['DEVELOPER_API_KEYS'] if item['key'] == key), None)

            if g.developer and 'username' in g.developer:
                new_template_folder = os.path.join(app._template_folder, g.developer['username'])
                if app.template_folder != new_template_folder:
                    app.template_folder = new_template_folder
                    app.jinja_loader = jinja2.FileSystemLoader(app.template_folder)
                    app.jinja_env.cache.clear()
                    print "Changed template folder to %s" % app.template_folder
        else:
            print "Restoring template folder to %s" % app._template_folder
            app.template_folder = app._template_folder
            app.jinja_loader = jinja2.FileSystemLoader(app.template_folder)
            app.jinja_env.cache.clear()

    if not g.user.is_authenticated and not request.is_xhr:
        referer = request.args.get('referer', request.args.get('agent', None))
        referer_set = request.cookies.get(User.REFERER_COOKIE, None)
        invitation = request.args.get('invitation')

        if referer and not referer_set and not invitation:
            # Inject affiliate script
            g.inject_affiliate_script = True
            g.inject_affiliate_script_options = dict(
                url=request.url,
                referer_url=request.headers.get('Referer', None)
            )


@app.after_request
def after_request(response):
    if not g.user.is_authenticated and not request.is_xhr:
        referer = request.args.get('referer', request.args.get('agent', None))
        referer_set = request.cookies.get(User.REFERER_COOKIE, None)
        invitation = request.args.get('invitation')

        if invitation:
            # Invitation has higher priority over affiliate cookie
            response.set_cookie(User.INVITATION_COOKIE, invitation, User.INVITATION_COOKIE_MAXAGE)
        elif referer and not referer_set:
            referer_user = User.query.filter(
                User.username == referer,
                User.is_deleted != True
            ).first()

            if referer_user:
                response.set_cookie(User.REFERER_COOKIE, str(referer_user.id), User.REFERER_COOKIE_MAXAGE)

    return response
