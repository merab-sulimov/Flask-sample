#!/usr/bin/env python

import os
import traceback
from datetime import datetime, timedelta, date
from flask_script import Manager, prompt, prompt_bool
from flask_migrate import Migrate, MigrateCommand
from sqlalchemy import or_
from raven import Client

from scripts import periodic, fixtures, marketing_emails
from app import app, db
from app.models import User, Variable, BitcoinAddress, Transaction, Order, OrderHistory, Category, Product, Dispute, FavoriteSearch, \
    ProductOffer

manager = Manager(app)
migrate = Migrate(app, db)

# Register db commands

manager.add_command('db', MigrateCommand)

# Various helper commands for use from the command-line


PERIOD_MINUTE = 60
PERIOD_HOUR = PERIOD_MINUTE * 60
PERIOD_DAY = PERIOD_HOUR * 24


@manager.command
def runbackground():
    """Command which is responsible to run periodic tasks. To be used with PM2"""

    import subprocess
    import time

    shift = 0

    while True:
        code = subprocess.call(['python', 'manage.py', 'background', '--shift', str(shift)])
        time.sleep(PERIOD_MINUTE)
        shift = shift + PERIOD_MINUTE if shift < PERIOD_DAY else 0


@manager.command
@manager.option('-s', '--shift', help='Shift from start in seconds', required=False)
def background(shift='0'):
    """Periodic script to run with cron/pm2"""

    try:
        shift = int(shift)
    except ValueError:
        shift = 0

    print "***** Running background script. Shift %d minute(s)" % (shift / PERIOD_MINUTE)
    print "***** Time: %s" % datetime.now()

    # Initializing Sentry client
    raven_client = Client(app.config['SENTRY_DSN']) if 'SENTRY_DSN' in app.config else None

    tasks = [
        { 'fn': periodic.check_enquiry_offers_expiration, 'desc': 'Checking enquire offers expiration', 'period': PERIOD_DAY},
        { 'fn': periodic.check_orders, 'desc': 'Checking orders and disputes', 'period': PERIOD_HOUR},
        { 'fn': periodic.check_offers, 'desc': 'Checking active offers', 'period': PERIOD_HOUR },
        { 'fn': periodic.check_pending_transactions, 'desc': 'Checking pending transactions', 'period': PERIOD_HOUR },
        { 'fn': periodic.update_exchange_rate, 'desc': 'Updating BTC exchange rate', 'period': PERIOD_HOUR },
        { 'fn': periodic.check_addresses, 'desc': 'Check BTC addresses', 'period': PERIOD_HOUR },
        { 'fn': periodic.generate_sitemap, 'desc': 'Generate sitemap', 'period': PERIOD_DAY },
        { 'fn': periodic.update_favorite_searches, 'desc': 'Update favorite searches count', 'period': PERIOD_HOUR },
        { 'fn': periodic.check_unread_messages, 'desc': 'Send emails with unread messages', 'period': PERIOD_MINUTE },
        { 'fn': periodic.fake_update_users_time, 'desc': 'Update Last Seen & Response Time with fake data (every 48 hours)', 'period': PERIOD_HOUR },
        { 'fn': periodic.check_product_features, 'desc': 'Remove expired features from products', 'period': PERIOD_HOUR },
        { 'fn': periodic.check_invites, 'desc': 'Send emails with invites', 'period': PERIOD_MINUTE }
    ]

    for idx, task in enumerate(tasks, 1):
        if shift % task['period'] != 0:
            continue

        try:
            print ""
            print "***** Running task #%d: %s" % (idx, task['desc'])
            task['fn']()
        except Exception, e:
            if raven_client:
                raven_client.captureException()

            print "Exception while running task"
            print e

    print
    print "***** End of background script"
    print "***** Time: %s" % datetime.now()
    print


@manager.command
def send_marketing_emails(shift='0'):
    """Marketing emails script to run daily with cron/pm2"""

    print "***** Running marketing email script"
    print "***** Time: %s" % datetime.now()

    # Initializing Sentry client
    raven_client = Client(app.config['SENTRY_DSN']) if 'SENTRY_DSN' in app.config else None

    marketing_emails.send_sellers()

    print
    print "***** End of marketing email script"
    print "***** Time: %s" % datetime.now()
    print


@manager.command
def add_superuser():
    username = prompt("Enter username of user")
    user = User.query.filter_by(username=username).first()
    if not user:
        print "Username %s not found" % username
        return

    user.is_admin = True
    db.session.add(user)
    db.session.commit()
    print "User %s is a new administrator" % username


@manager.command
def update_exchange_rate():
    periodic.update_exchange_rate()


@manager.command
def rebuild_search_index():
    from app import search

    if prompt_bool("Drop index and recreate again (only do this if you are sure)?"):
        print "Dropping index..."
        search.delete_index()

        print "Creating index..."
        search.create_index()

    sellers_query = User.query.filter(User.is_deleted != True, User.seller_fee_paid == True)
    products_query = Product.query_active(include_private=True)

    if not prompt_bool("Total count of the sellers/products to be indexed: {0}/{1}.\nPlease confirm operation".format(sellers_query.count(), products_query.count())):
        print "Cancelled"
        return
    
    counter = 0
    for seller in sellers_query:
        search.add_seller_to_index(seller)
        counter += 1

    print "Successfully added to index {0} sellers".format(counter)
    
    counter = 0
    for product in products_query:
        search.add_product_to_index(product)
        counter += 1

    print "Successfully added to index {0} products".format(counter)


@manager.command
def add_test_users():
    admin = User(id=1, username='admin', password='admin', email='admin@example.com', is_admin=True, country='RU', is_verified=True)
    seller1 = User(id=2, username='seller1', password='seller1', email='seller1@example.com', country='FI', is_verified=True, seller_fee_paid=True)
    seller2 = User(id=3, username='seller2', password='seller2', email='seller2@example.com', country='IT', is_verified=True, seller_fee_paid=True)
    user1 = User(id=4, username='user1', password='user1', email='user1@example.com', country='BE', is_verified=True)

    db.session.add_all([admin, seller1, seller2, user1])
    db.session.commit()


@manager.command
def add_test_categories():
    import json

    fixtures = json.load(open('tests/fixtures/categories.json', 'r'))

    categories = [Category(id=c['id'], title=c['title'], parent_id=c['parent_id']) for c in fixtures]
    db.session.add_all(categories)
    db.session.commit()
    print "Added {0} categories".format(len(categories))


@manager.command
def add_fake_products():
    fixtures.add_fake_products()


@manager.command
@manager.option('-s', '--start', help='Start date, YYYY-MM-DD', required=False)
@manager.option('-e', '--end', help='End date, YYYY-MM-DD', required=False)
def add_fake_reviews(start='', end=''):
    if not start:
        start = datetime.today()
    else:
        start = datetime.strptime(start, '%Y-%m-%d')

    if not end:
        end = datetime.today()
    else:
        end = datetime.strptime(end, '%Y-%m-%d')

    if start > datetime.today() or end > datetime.today():
        print "Start/end dates can't be greater than today"
        return

    if start > end:
        print "Start date can't be greater than end date"
        return

    fixtures.add_fake_reviews(start, end)


@manager.command
def convert(operation):
    from scripts import convert

    if operation not in convert.operations:
        print "Available operations are:", ",".join(convert.operations)
        return

    convert.operations[operation]()


@manager.command
def generate_rsa_keys():
    import rsa

    print "Creating 2048-bit RSA keypair..."
    print

    (pub_key, priv_key) = rsa.newkeys(2048)

    print pub_key.save_pkcs1()
    print

    print priv_key.save_pkcs1()
    print


@manager.command
def decode_rsa_password(priv_key_pkcs1_file):
    import rsa

    try:
        with open(priv_key_pkcs1_file) as f:
            priv_key_pkcs1 = f.read()
        
        priv_key = rsa.PrivateKey.load_pkcs1(priv_key_pkcs1)
    except:
        print "Expecting valid 2048-bit RSA private key"
        return

    print "Input data to decode (BASE64-encoded encrypted string)"
    print "End your input with empty line to proceed:"
    encoded = []

    while True:
        line = raw_input('')
        if not line:
            break

        encoded.append(line)

    encoded = ''.join(encoded)

    if not encoded:
        return

    encrypted = encoded.decode('base64')

    try:
        decrypted = rsa.decrypt(encrypted, priv_key)
        print decrypted
    except:
        print "Unable to decode data"


@manager.command
def update_categories(csv_file):
    import csv

    data = list()

    try:
        with open(csv_file) as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) != 3:
                    print "Skipping row '%s' as it contains %d columns instead of 3" % (', '.join(row), len(row))
                    continue

                data.append(dict(title=row[0], seo_description=row[1], description=row[2]))
    except IOError:
        print "Expecting CSV file"
        return

    if not data:
        print "No data extracted from CSV file"
        return

    notfound_titles = list()

    for item in data:
        category = Category.query.filter_by(title=item['title']).first()
        if not category:
            notfound_titles.append(item['title'])
            continue

        item['category'] = category

    print "Total rows in the file: %d" % len(data)

    if notfound_titles:
        print "Not found associations for the following categories: %s" % ', '.join(notfound_titles)

    print "Categories to update: %d" % (len(data) - len(notfound_titles))

    if prompt_bool("Proceed?"):
        for item in data:
            if 'category' not in item:
                continue

            item['category'].description = item['description']
            item['category'].seo_description = item['seo_description']

            db.session.add(item['category'])

        db.session.commit()
        print "Done"


@manager.command
def create_pdf(directory):
    from xhtml2pdf import pisa
    from flask import render_template, Markup
    from app.utils import render_markdown
    from app.utils.storage import Storage
    from tempfile import mktemp
    from hashlib import md5
    import json
    import requests

    if not os.path.isdir(directory):
        print "Please specify existing directory where to save PDF files"
        return

    checksums = dict()

    try:
        with open(os.path.join(directory, 'checksums.json'), 'r+t') as f:
            checksums = json.loads(f.read())
    except:
        pass

    for product in Product.query_active():
        custom_id = product.get_custom_id()
        print "Processing service %s..." % custom_id

        output = os.path.join(directory, '%s-%s.pdf' % (product.get_title_seofied(), custom_id)).encode('utf-8')

        product_photos = map(
            lambda photo_dict: Storage.get_product_photo_url(photo_dict, 'c_pad,g_center,w_670'),
            product.get_data('photos') or list()
        )

        source = render_template(
            'service-pdf-source.html',
            product=product,
            product_description=Markup(render_markdown(product.description)),
            product_photos=product_photos,
            product_tags=product.get_tags()
        )

        m = md5()
        m.update(source.encode('utf-8'))
        checksum = m.hexdigest()

        if custom_id in checksums and checksums[custom_id] == checksum:
            print "Skipping service %s as checksum was not changed" % custom_id
            continue

        def link_callback(name, rel):
            if name.startswith('http'):
                resp = requests.get(name)
                temp_file_name = mktemp(suffix='.jpg')

                with open(temp_file_name, 'w+b') as temp_file:
                    temp_file.write(resp.content)

                return temp_file_name

        with open(output, 'w+b') as f:
            exc = None
            status = None

            try:
                status = pisa.CreatePDF(source, link_callback=link_callback, dest=f)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                print "Exception: %s" % exc.message
                exc = exc

            if (status and status.err) or exc:
                print "Error converting PDF for service %s" % custom_id
            else:
                checksums[custom_id] = checksum

        # Write checksum file after each convertation
        with open(os.path.join(directory, 'checksums.json'), 'w+t') as f:
            f.write(json.dumps(checksums))


@manager.command
def create_services_dump(dump_file):
    from app.utils.storage import Storage, ImagePresets
    from app.utils.data import skills
    from app.utils import render_markdown
    import json
    import re

    TAGS_RE = re.compile(r'(<!--.*?-->|<[^>]*>)')

    if os.path.exists(dump_file):
        if not prompt_bool("Output file already exists. Overwrite it?"):
            return

    dump = list()

    for service in Product.query_active():
        custom_id = service.get_custom_id()
        print "Processing service %s..." % custom_id

        photos = map(
            lambda photo_dict: Storage.get_product_photo_url(photo_dict, ImagePresets.SERVICE_PRIMARY),
            service.get_data('photos') or list()
        )

        seller_skills = map(lambda s: skills.resolve(s['id'], s['level_id'])[0], service.seller.get_meta_data('skills') or list())

        dump.append(dict(
            id=service.id,
            photos=photos,
            title=service.title.capitalize(),
            tags=service.get_approved_tags(),
            description=TAGS_RE.sub('', render_markdown(service.description)),
            url=service.get_url(_external=True),
            seller_photo=service.seller.get_photo_url('h_150,w_150,c_thumb,g_face'),
            seller_display_name=service.seller.profile_display_name,
            seller_username=service.seller.username,
            seller_headline=service.seller.profile_headline,
            seller_skills=seller_skills
        ))

    with open(dump_file, 'w+t') as f:
        json.dump(dump, f)


if __name__ == "__main__":
    manager.run()
