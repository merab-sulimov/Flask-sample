import os
import nose2

os.environ['SIMPLEFLASK_CONFIG'] = 'config.TestingConfig'
nose2.discover()
