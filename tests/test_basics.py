import time
import urllib2
from flask import url_for
from selenium import webdriver

from . import BaseTestCase


class TestViews(BaseTestCase):
    def test_index_view(self):
        """
        Test that index view is accessible without login
        """
        response = urllib2.urlopen(self.get_server_url())
        self.assertEqual(response.code, 200)


class TestFrontend(BaseTestCase):
    def setUp(self):
        self.driver = webdriver.PhantomJS()
        self.driver.set_window_size(1200, 800)
        self.driver.get(self.get_server_url())

    def tearDown(self):
        self.driver.quit()

    def test_login(self):
        self.driver.find_element_by_css_selector('.link.login').click()
        assert self.driver.find_element_by_css_selector('.dialog.login').is_displayed()

        self.driver.find_element_by_css_selector('.dialog.login input[type="text"]').send_keys('admin')
        self.driver.find_element_by_css_selector('.dialog.login input[type="password"]').send_keys('admin')

        self.driver.save_screenshot(self.get_tmp_path('test.png'))
