import webapp2
import webtest
import unittest2
from main import *

class AppTest(unittest2.TestCase):
	def setUp(self):

		app = webapp2.WSGIApplication([('/hello', HelloWorldHandler)])

		self.testapp = webtest.TestApp(app)


	def testHelloWorldHandler(self):
		response = self.testapp.get('/hello')
		self.assertEqual(response.status_int, 200)
		self.assertEqual(response.normal_body, 'Hello World!')
		self.assertEqual(response.content_type, 'text/plain')