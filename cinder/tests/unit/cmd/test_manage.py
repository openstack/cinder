from oslo_db.sqlalchemy import utils as sqlalchemyutils

from cinder.cmd.manage import SapCommands
from cinder.db.sqlalchemy import api as db_api
from cinder.tests.unit import test
from cinder import context


class SapCommandsTests(test.TestCase):
    def setUp(self):
        super(SapCommandsTests, self).setUp()
        self.context = context.get_admin_context()
        self.engine = db_api.get_engine()
        self.session = db_api.get_session()
        self.conn = self.engine.connect()
        self.volumes = sqlalchemyutils.get_table(self.engine, "volumes")

    def test_remove_volumes_in_state_error_deleting(self):
        import pdb;pdb.set_trace()
        sap_commands = SapCommands()
        sap_commands._remove_volumes_in_state_error_deleting(self.context,
                                                             dry_run=False)
        
