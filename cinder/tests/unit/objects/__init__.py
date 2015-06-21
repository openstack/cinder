from oslo_versionedobjects.tests import test_objects

from cinder import objects


class BaseObjectsTestCase(test_objects._LocalTest):
    def setUp(self):
        super(BaseObjectsTestCase, self).setUp()
        # Import cinder objects for test cases
        objects.register_all()
