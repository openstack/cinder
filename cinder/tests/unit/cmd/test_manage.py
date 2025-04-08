import uuid
import random

from sqlalchemy import insert
from sqlalchemy import and_
from oslo_db.sqlalchemy import utils as sqlalchemyutils
from oslo_utils import timeutils

from cinder.cmd.manage import SapCommands
from cinder.db.sqlalchemy import api as db_api
from cinder.tests.unit import test
from cinder.tests.unit import fake_volume
from cinder import context
from cinder.db.sqlalchemy import models
from cinder.db.sqlalchemy import api as db_api


class SapCommandsTests(test.TestCase):
    def setUp(self):
        super(SapCommandsTests, self).setUp()
        self.context = context.get_admin_context()
        self.session = db_api.get_session()
    
    def test_mark_deleted_by_ids_volume(self):
        n_volumes = 10
        mark_as_deleted_ids, ids = [], []
        already_deleted_idx = [0, 1, 2]
        should_be_deleted_idx = [3, 4, 5]
        with self.session.begin():
            for i in range(n_volumes):
                id = str(uuid.uuid4())
                volume_type_id = str(uuid.uuid4())
                ids.append(id)
                if i in should_be_deleted_idx:
                    mark_as_deleted_ids.append(id)
                deleted = 1 if i in already_deleted_idx else 0
                self.session.execute(insert(models.Volume).values(
                    id=id, status="available", volume_type_id=volume_type_id,
                    deleted=deleted))
        count_total_volumes = self.session.query(models.Volume).count()
        self.assertEqual(n_volumes, count_total_volumes)
        count_already_deleted_volumes = self.session.query(models.Volume).\
            filter_by(deleted=1).count()
        self.assertEqual(len(already_deleted_idx),
                         count_already_deleted_volumes)
        sap_commands = SapCommands()
        now = timeutils.utcnow()
        sap_commands._mark_deleted_by_ids(self.session,
                                          models.Volume,
                                          mark_as_deleted_ids,
                                          now = now)
        count_by_date = self.session.query(models.Volume).\
            filter_by(updated_at=now, deleted_at=now).\
            count()
        self.assertEqual(len(should_be_deleted_idx), count_by_date)
        count_deleted_volumes = self.session.query(models.Volume).\
            filter_by(deleted=1).count()
        self.assertEqual(len(already_deleted_idx) + len(should_be_deleted_idx),
                         count_deleted_volumes)
        # Nothing should be changed
        sap_commands._mark_deleted_by_ids(self.session,
                                          models.Volume,
                                          [],
                                          now = now)
        count_deleted_volumes = self.session.query(models.Volume).\
            filter_by(deleted=1).count()
        self.assertEqual(len(already_deleted_idx) + len(should_be_deleted_idx),
                         count_deleted_volumes)

    def test_mark_deleted_by_ids_volume_metadata(self):
        n_volumes = 10
        mark_as_deleted_ids, ids = [], []
        already_deleted_idx = [0, 1, 2]
        should_be_deleted_idx = [3, 4, 5]
        with self.session.begin():
            for i in range(n_volumes):
                id = random.randint(1, 100000)
                volume_id = str(uuid.uuid4())
                ids.append(id)
                if i in should_be_deleted_idx:
                    mark_as_deleted_ids.append(id)
                deleted = 1 if i in already_deleted_idx else 0
                self.session.execute(insert(models.VolumeMetadata).values(
                    id=id, volume_id=volume_id, deleted=deleted))
        count_total_volumes = self.session.query(models.VolumeMetadata).count()
        self.assertEqual(n_volumes, count_total_volumes)
        count_already_deleted_volumes = self.session.query(
            models.VolumeMetadata).\
            filter_by(deleted=1).count()
        self.assertEqual(len(already_deleted_idx),
                         count_already_deleted_volumes)
        sap_commands = SapCommands()
        now = timeutils.utcnow()
        sap_commands._mark_deleted_by_ids(self.session,
                                          models.VolumeMetadata,
                                          mark_as_deleted_ids,
                                          now = now)
        count_by_date = self.session.query(models.VolumeMetadata).\
            filter_by(updated_at=now, deleted_at=now).\
            count()
        self.assertEqual(len(should_be_deleted_idx), count_by_date)
        count_deleted_volumes = self.session.query(models.VolumeMetadata).\
            filter_by(deleted=1).count()
        self.assertEqual(len(already_deleted_idx) + len(should_be_deleted_idx),
                         count_deleted_volumes)
