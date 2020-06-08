import os
from flask_testing import LiveServerTestCase


from app import app, db


class BaseTestCase(LiveServerTestCase):
    def create_app(self):
        return app

    # def init_data(self):
    #     admin = User(username='admin', password='admin', email='admin@example.com', is_admin=True)
    #     seller = User(username='seller', password='seller', email='seller@example.com')
    #     user = User(username='user', password='user', email='user@example.com')
        
    #     db.session.add_all([admin, seller, user])
    #     db.session.commit()

    def setUp(self):
        db.drop_all()
        db.create_all()

    def tearDown(self):
        pass

    def get_tmp_path(self, filename):
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), 'tmp', filename)
