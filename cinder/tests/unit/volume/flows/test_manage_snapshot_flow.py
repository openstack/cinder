#   Copyright (c) 2017 Mirantis Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

""" Tests for manage_existing_snapshot TaskFlow."""

# TODO(mdovgal): add tests for other TaskFlow cases

from unittest import mock

import ddt

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume.flows.manager import manage_existing_snapshot as manager


@ddt.ddt
class ManageSnapshotFlowTestCase(test.TestCase):
    def setUp(self):
        super(ManageSnapshotFlowTestCase, self).setUp()
        self.ctxt = context.get_admin_context()

    @mock.patch('cinder.objects.snapshot.Snapshot.get_by_id')
    def test_manage_snapshot_after_volume_extending(self, _get_by_id):
        """Test checks snapshot's volume_size value after it is managed."""
        fake_size = 3
        fake_snap = fake_snapshot.fake_snapshot_obj(self.ctxt,
                                                    volume_size=fake_size)
        fake_snap.save = mock.MagicMock()
        _get_by_id.return_value = fake_snap

        real_size = 1
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        mock_manage_existing_ref = mock.MagicMock()
        mock_driver.manage_existing_snapshot.return_value = {}

        task = manager.ManageExistingTask(mock_db, mock_driver)
        result = task.execute(self.ctxt, fake_snap, mock_manage_existing_ref,
                              real_size)
        snap_after_manage = result['snapshot']
        #  assure value is equal that size, that we want
        self.assertEqual(real_size, snap_after_manage['volume_size'])

    def test_manage_existing_snapshot_with_wrong_volume(self):
        """Test that raise an error when get_by_id fail."""
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        real_size = 1
        manage_existing_ref = None
        fake_snap = fake_snapshot.fake_snapshot_obj(self.ctxt,
                                                    volume_size=real_size)

        task = manager.ManageExistingTask(mock_db, mock_driver)
        self.assertRaises(exception.SnapshotNotFound,
                          task.execute,
                          self.ctxt,
                          fake_snap,
                          manage_existing_ref,
                          real_size)

    @mock.patch('cinder.quota.QuotaEngine.reserve')
    @mock.patch('cinder.db.sqlalchemy.api.volume_type_get')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_quota_reservation_task(self, mock_get_vol_by_id, mock_type_get,
                                    mock_quota_reserve):
        volume_size = 1
        fake_size = '2'
        fake_snap = fake_snapshot.fake_snapshot_obj(self.ctxt,
                                                    volume_size=volume_size)
        fake_snap.save = mock.MagicMock()
        fake_vol = fake_volume.fake_volume_obj(
            self.ctxt, id=fake.VOLUME_ID, volume_type_id=fake.VOLUME_TYPE_ID)
        mock_get_vol_by_id.return_value = fake_vol
        mock_type_get.return_value = {'name': 'fake_type_name'}

        task = manager.QuotaReserveTask()
        task.execute(self.ctxt, fake_size, fake_snap, {})

        reserve_opts = {'gigabytes': 1, 'snapshots': 1,
                        'gigabytes_fake_type_name': 1,
                        'snapshots_fake_type_name': 1}
        mock_quota_reserve.assert_called_once_with(self.ctxt, **reserve_opts)

    @ddt.data(True, False)
    @mock.patch('cinder.quota.QuotaEngine.reserve')
    @mock.patch('cinder.db.sqlalchemy.api.volume_type_get')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_quota_reservation_task_with_update_flag(
            self, need_update, mock_get_vol_by_id,
            mock_type_get, mock_quota_reserve):
        volume_size = 1
        fake_size = '2'
        fake_snap = fake_snapshot.fake_snapshot_obj(self.ctxt,
                                                    volume_size=volume_size)
        fake_snap.save = mock.MagicMock()
        fake_vol = fake_volume.fake_volume_obj(
            self.ctxt, id=fake.VOLUME_ID, volume_type_id=fake.VOLUME_TYPE_ID)
        mock_get_vol_by_id.return_value = fake_vol
        mock_type_get.return_value = {'name': 'fake_type_name'}

        task = manager.QuotaReserveTask()
        task.execute(self.ctxt, fake_size, fake_snap,
                     {'update_size': need_update})

        reserve_opts = {'gigabytes': 1, 'gigabytes_fake_type_name': 1}

        if not need_update:
            reserve_opts.update({'snapshots': 1,
                                 'snapshots_fake_type_name': 1})
        mock_quota_reserve.assert_called_once_with(self.ctxt, **reserve_opts)

    def test_prepare_for_quota_reserveration_task_execute(self):
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        mock_manage_existing_ref = mock.MagicMock()
        mock_get_snapshot_size = self.mock_object(
            mock_driver, 'manage_existing_snapshot_get_size')
        mock_get_snapshot_size.return_value = '5'

        fake_snap = fake_snapshot.fake_snapshot_obj(self.ctxt,
                                                    volume_size=1)
        task = manager.PrepareForQuotaReservationTask(mock_db, mock_driver)

        result = task.execute(self.ctxt, fake_snap, mock_manage_existing_ref)
        self.assertEqual(fake_snap, result['snapshot_properties'])
        self.assertEqual('5', result['size'])
        mock_get_snapshot_size.assert_called_once_with(
            snapshot=fake_snap,
            existing_ref=mock_manage_existing_ref
        )

    @mock.patch('cinder.quota.QuotaEngine.rollback')
    def test_quota_reservation_revert_task(self, mock_quota_rollback):
        """Test checks that we can rollback the snapshot."""
        mock_result = mock.MagicMock()
        optional_args = {}
        optional_args['is_quota_committed'] = False

        task = manager.QuotaReserveTask()
        task.revert(self.ctxt, mock_result, optional_args)
        mock_quota_rollback.assert_called_once_with(self.ctxt,
                                                    mock_result['reservations']
                                                    )

    @mock.patch('cinder.volume.flows.manager.manage_existing_snapshot.'
                'QuotaReserveTask.revert')
    def test_quota_reservation_revert_already_been_committed(self,
                                                             mock_quota_revert
                                                             ):
        """Test reservations can not be rolled back."""
        mock_result = mock.MagicMock()
        optional_args = {}
        optional_args['is_quota_committed'] = True

        task = manager.QuotaReserveTask()
        task.revert(self.ctxt, mock_result, optional_args)
        mock_quota_revert.assert_called_once_with(self.ctxt, mock_result,
                                                  optional_args)

    @mock.patch('cinder.quota.QuotaEngine.commit')
    def test_quota_commit_task(self, mock_quota_commit):
        """Test checks commits the reservation."""
        mock_reservations = mock.MagicMock()
        mock_snapshot_properties = mock.MagicMock()
        mock_optional_args = mock.MagicMock()

        task = manager.QuotaCommitTask()
        task.execute(self.ctxt, mock_reservations, mock_snapshot_properties,
                     mock_optional_args)
        mock_quota_commit.assert_called_once_with(self.ctxt, mock_reservations)

    @mock.patch('cinder.quota.QuotaEngine.reserve')
    def test_quota_commit_revert_task(self, mock_quota_reserve):
        """Test checks commits the reservation."""
        mock_result = mock.MagicMock()
        expected_snapshot = mock_result['snapshot_properties']
        expected_gigabyte = -expected_snapshot['volume_size']

        task = manager.QuotaCommitTask()
        task.revert(self.ctxt, mock_result)
        mock_quota_reserve.assert_called_once_with(self.ctxt,
                                                   gigabytes=expected_gigabyte,
                                                   project_id=None,
                                                   snapshots=-1)

    @mock.patch('cinder.volume.flows.manager.manage_existing_snapshot.'
                'CreateSnapshotOnFinishTask.execute')
    def test_create_snap_on_finish_task(self, mock_snap_create):
        """Test to create snapshot on finish."""
        mock_status = mock.MagicMock()
        mock_db = mock.MagicMock()
        mock_event_suffix = mock.MagicMock()
        mock_host = mock.MagicMock()

        task = manager.CreateSnapshotOnFinishTask(mock_db, mock_event_suffix,
                                                  mock_host)
        task.execute(self.ctxt, fake_snapshot, mock_status)
        mock_snap_create.assert_called_once_with(self.ctxt, fake_snapshot,
                                                 mock_status)

    @mock.patch('cinder.objects.snapshot.Snapshot.get_by_id')
    @mock.patch('cinder.volume.volume_utils.notify_about_snapshot_usage')
    def test_create_snap_on_finish_task_notify(self,
                                               mock_notify_about_usage,
                                               _mock_get_by_id):
        mock_status = mock.MagicMock()
        mock_db = mock.MagicMock()
        mock_event_suffix = mock.MagicMock()
        mock_host = mock.MagicMock()

        fake_snap = fake_snapshot.fake_snapshot_obj(self.ctxt,
                                                    volume_size=1)

        task = manager.CreateSnapshotOnFinishTask(mock_db, mock_event_suffix,
                                                  mock_host)
        task.execute(self.ctxt, fake_snap, mock_status)
        mock_notify_about_usage.assert_called_once_with(
            self.ctxt, fake_snap, mock_event_suffix, host=mock_host)

    @mock.patch('cinder.volume.flows.manager.manage_existing_snapshot.'
                'taskflow.engines.load')
    @mock.patch('cinder.volume.flows.manager.manage_existing_snapshot.'
                'linear_flow.Flow')
    def test_get_flow(self, mock_linear_flow, mock_taskflow_engine):
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        mock_host = mock.MagicMock()
        mock_snapshot_id = mock.MagicMock()
        mock_ref = mock.MagicMock()
        ctxt = context.get_admin_context()

        mock_snapshot_flow = mock.Mock()
        mock_linear_flow.return_value = mock_snapshot_flow

        expected_store = {
            'context': ctxt,
            'snapshot_id': mock_snapshot_id,
            'manage_existing_ref': mock_ref,
            'optional_args': {
                'is_quota_committed': False,
                'update_size': True
            },
        }

        manager.get_flow(ctxt, mock_db, mock_driver, mock_host,
                         mock_snapshot_id, mock_ref)

        mock_linear_flow.assert_called_once_with(
            'snapshot_manage_existing_manager')
        mock_taskflow_engine.assert_called_once_with(mock_snapshot_flow,
                                                     store=expected_store)
