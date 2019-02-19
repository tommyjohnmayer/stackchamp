import unittest2
from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext import ndb
from google.appengine.ext import testbed
from main import *

class DemoTestCase(unittest2.TestCase):

  def setUp(self):
    # First, create an instance of the Testbed class.
    self.testbed = testbed.Testbed()
    # Then activate the testbed, which prepares the service stubs for use.
    self.testbed.activate()
    # Next, declare which service stubs you want to use.
    self.testbed.init_datastore_v3_stub()
    self.testbed.init_memcache_stub()
	
  def tearDown(self):
    self.testbed.deactivate()

  def testLeague(self):
	a = League(id='test')
	a.name = 'test'
	a.put()
	b = League.get_by_id('test')
	self.assertEqual(a.name, b.name)
	b.name = 'test1'
	b.put()
	c = League(id='test')
	self.assertNotEqual(a.name, c.name)
	c.key.delete()
	self.assertIsNone(c.name)
	
if __name__ == '__main__':
    unittest2.main()