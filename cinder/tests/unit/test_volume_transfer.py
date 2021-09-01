# Copyright (c) 2013 OpenStack Foundation
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""Unit Tests for volume transfers."""

from unittest import mock

import ddt
from oslo_utils import timeutils

from cinder import context
from cinder import db
from cinder.db.sqlalchemy import api as db_api
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import objects
from cinder import quota
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.tests.unit import utils
from cinder.transfer import api as transfer_api


QUOTAS = quota.QUOTAS


@ddt.ddt
class VolumeTransferTestCase(test.TestCase):
    """Test cases for volume transfer code."""
    def setUp(self):
        super(VolumeTransferTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID)
        self.updated_at = timeutils.utcnow()

    def test_transfer_volume_create_delete(self):
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            response = tx_api.create(self.ctxt, volume.id, 'Description')
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                     mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
            mock_notify.assert_has_calls(calls)
            self.assertEqual(2, mock_notify.call_count)

        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('awaiting-transfer', volume['status'],
                         'Unexpected state')

        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            tx_api.delete(self.ctxt, response['id'])
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.delete.start"),
                     mock.call(self.ctxt, mock.ANY, "transfer.delete.end")]
            mock_notify.assert_has_calls(calls)
            self.assertEqual(2, mock_notify.call_count)

        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('available', volume['status'], 'Unexpected state')

    def test_transfer_invalid_volume(self):
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, status='in-use',
                                     updated_at=self.updated_at)
        self.assertRaises(exception.InvalidVolume,
                          tx_api.create,
                          self.ctxt, volume.id, 'Description')
        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('in-use', volume['status'], 'Unexpected state')

    def test_transfer_invalid_encrypted_volume(self):
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)
        db.volume_update(self.ctxt,
                         volume.id,
                         {'encryption_key_id': fake.ENCRYPTION_KEY_ID})
        self.assertRaises(exception.InvalidVolume,
                          tx_api.create,
                          self.ctxt, volume.id, 'Description')

    def test_transfer_accept_invalid_authkey(self):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, volume.id, 'Description')
        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('awaiting-transfer', volume['status'],
                         'Unexpected state')

        self.assertRaises(exception.TransferNotFound,
                          tx_api.accept,
                          self.ctxt, '2', transfer['auth_key'])

        self.assertRaises(exception.InvalidAuthKey,
                          tx_api.accept,
                          self.ctxt, transfer['id'], 'wrong')

    def test_transfer_accept_invalid_volume(self):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at,
                                     volume_type_id=self.vt['id'])
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            transfer = tx_api.create(self.ctxt, volume.id, 'Description')
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                     mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
            mock_notify.assert_has_calls(calls)
            self.assertEqual(2, mock_notify.call_count)

        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('awaiting-transfer', volume['status'],
                         'Unexpected state')

        volume.status = 'wrong'
        volume.save()
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            self.assertRaises(exception.InvalidVolume,
                              tx_api.accept,
                              self.ctxt, transfer['id'], transfer['auth_key'])
            # Because the InvalidVolume exception is raised in tx_api, so
            # there is only transfer.accept.start called and missing
            # transfer.accept.end.
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.accept.start")]
            mock_notify.assert_has_calls(calls)
            self.assertEqual(1, mock_notify.call_count)

        volume.status = 'awaiting-transfer'
        volume.save()

    def test_transfer_accept_volume_in_consistencygroup(self):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        consistencygroup = utils.create_consistencygroup(self.ctxt)
        volume = utils.create_volume(self.ctxt,
                                     updated_at=self.updated_at,
                                     consistencygroup_id=
                                     consistencygroup.id)
        transfer = tx_api.create(self.ctxt, volume.id, 'Description')

        self.assertRaises(exception.InvalidVolume,
                          tx_api.accept,
                          self.ctxt, transfer['id'], transfer['auth_key'])

    @mock.patch.object(QUOTAS, "limit_check")
    @mock.patch.object(QUOTAS, "reserve")
    @mock.patch.object(QUOTAS, "add_volume_type_opts")
    def test_transfer_accept(self, mock_quota_voltype,
                             mock_quota_reserve, mock_quota_limit):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt,
                                     volume_type_id=fake.VOLUME_TYPE_ID,
                                     updated_at=self.updated_at)
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            transfer = tx_api.create(self.ctxt, volume.id, 'Description')
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                     mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
            mock_notify.assert_has_calls(calls)
            self.assertEqual(2, mock_notify.call_count)

        self.ctxt.user_id = fake.USER2_ID
        self.ctxt.project_id = fake.PROJECT2_ID
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            response = tx_api.accept(self.ctxt,
                                     transfer['id'],
                                     transfer['auth_key'])
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.accept.start"),
                     mock.call(self.ctxt, mock.ANY, "transfer.accept.end")]
            mock_notify.assert_has_calls(calls)
            self.assertEqual(2, mock_notify.call_count)

        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual(fake.PROJECT2_ID, volume.project_id)
        self.assertEqual(fake.USER2_ID, volume.user_id)

        self.assertEqual(response['volume_id'], volume.id,
                         'Unexpected volume id in response.')
        self.assertEqual(response['id'], transfer['id'],
                         'Unexpected transfer id in response.')

        # Check QUOTAS reservation calls
        # QUOTAS.add_volume_type_opts
        reserve_opt = {'volumes': 1, 'gigabytes': 1}
        release_opt = {'volumes': -1, 'gigabytes': -1}
        calls = [mock.call(self.ctxt, reserve_opt, fake.VOLUME_TYPE_ID),
                 mock.call(self.ctxt, release_opt, fake.VOLUME_TYPE_ID)]
        mock_quota_voltype.assert_has_calls(calls)

        # QUOTAS.reserve
        calls = [mock.call(mock.ANY, **reserve_opt),
                 mock.call(mock.ANY, project_id=fake.PROJECT_ID,
                           **release_opt)]
        mock_quota_reserve.assert_has_calls(calls)

        # QUOTAS.limit_check
        values = {'per_volume_gigabytes': 1}
        mock_quota_limit.assert_called_once_with(self.ctxt,
                                                 project_id=fake.PROJECT2_ID,
                                                 **values)

    @mock.patch.object(QUOTAS, "reserve")
    @mock.patch.object(QUOTAS, "add_volume_type_opts")
    def test_transfer_accept_over_quota(self, mock_quota_voltype,
                                        mock_quota_reserve):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt,
                                     volume_type_id=fake.VOLUME_TYPE_ID,
                                     updated_at=self.updated_at)
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            transfer = tx_api.create(self.ctxt, volume.id, 'Description')
            self.assertEqual(2, mock_notify.call_count)

        fake_overs = ['volumes_lvmdriver-3']
        fake_quotas = {'gigabytes_lvmdriver-3': 1,
                       'volumes_lvmdriver-3': 10}
        fake_usages = {'gigabytes_lvmdriver-3': {'reserved': 0, 'in_use': 1},
                       'volumes_lvmdriver-3': {'reserved': 0, 'in_use': 1}}

        mock_quota_reserve.side_effect = exception.OverQuota(
            overs=fake_overs,
            quotas=fake_quotas,
            usages=fake_usages)

        self.ctxt.user_id = fake.USER2_ID
        self.ctxt.project_id = fake.PROJECT2_ID
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            self.assertRaises(exception.VolumeLimitExceeded,
                              tx_api.accept,
                              self.ctxt,
                              transfer['id'],
                              transfer['auth_key'])
            # notification of transfer.accept is sent only after quota check
            # passes
            self.assertEqual(0, mock_notify.call_count)

    @mock.patch.object(QUOTAS, "limit_check")
    def test_transfer_accept_over_quota_check_limit(self, mock_quota_limit):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt,
                                     volume_type_id=fake.VOLUME_TYPE_ID,
                                     updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, volume.id, 'Description')
        fake_overs = ['per_volume_gigabytes']
        fake_quotas = {'per_volume_gigabytes': 1}
        fake_usages = {}

        mock_quota_limit.side_effect = exception.OverQuota(
            overs=fake_overs,
            quotas=fake_quotas,
            usages=fake_usages)

        self.ctxt.user_id = fake.USER2_ID
        self.ctxt.project_id = fake.PROJECT2_ID
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            self.assertRaises(exception.VolumeSizeExceedsLimit,
                              tx_api.accept,
                              self.ctxt,
                              transfer['id'],
                              transfer['auth_key'])
            # notification of transfer.accept is sent only after quota check
            # passes
            self.assertEqual(0, mock_notify.call_count)

    def test_transfer_get(self):
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, volume['id'], 'Description')
        t = tx_api.get(self.ctxt, transfer['id'])
        self.assertEqual(t['id'], transfer['id'], 'Unexpected transfer id')

        ts = tx_api.get_all(self.ctxt)
        self.assertEqual(1, len(ts), 'Unexpected number of transfers.')

        nctxt = context.RequestContext(user_id=fake.USER2_ID,
                                       project_id=fake.PROJECT2_ID)
        utils.create_volume(nctxt, updated_at=self.updated_at)
        self.assertRaises(exception.TransferNotFound,
                          tx_api.get,
                          nctxt,
                          transfer['id'])

        ts = tx_api.get_all(nctxt)
        self.assertEqual(0, len(ts), 'Unexpected transfers listed.')

    @ddt.data({'all_tenants': '1', 'name': 'transfer1'},
              {'all_tenants': 'true', 'name': 'transfer1'},
              {'all_tenants': 'false', 'name': 'transfer1'},
              {'all_tenants': '0', 'name': 'transfer1'},
              {'name': 'transfer1'})
    @mock.patch.object(context.RequestContext, 'authorize')
    @mock.patch('cinder.db.transfer_get_all')
    @mock.patch('cinder.db.transfer_get_all_by_project')
    def test_get_all_transfers_non_admin(self, search_opts, get_all_by_project,
                                         get_all, auth_mock):
        ctxt = context.RequestContext(user_id=None, is_admin=False,
                                      project_id=mock.sentinel.project_id,
                                      read_deleted='no', overwrite=False)
        tx_api = transfer_api.API()
        res = tx_api.get_all(ctxt, mock.sentinel.marker,
                             mock.sentinel.limit, mock.sentinel.sort_keys,
                             mock.sentinel.sort_dirs,
                             search_opts, mock.sentinel.offset)

        auth_mock.assert_called_once_with(transfer_api.policy.GET_ALL_POLICY)
        get_all.assert_not_called()
        get_all_by_project.assert_called_once_with(
            ctxt,
            mock.sentinel.project_id,
            filters={'name': 'transfer1'},
            limit=mock.sentinel.limit,
            marker=mock.sentinel.marker,
            offset=mock.sentinel.offset,
            sort_dirs=mock.sentinel.sort_dirs,
            sort_keys=mock.sentinel.sort_keys)
        self.assertEqual(get_all_by_project.return_value, res)

    def test_delete_transfer_with_deleted_volume(self):
        # create a volume
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)
        # create a transfer
        tx_api = transfer_api.API()
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            transfer = tx_api.create(self.ctxt, volume['id'], 'Description')
            t = tx_api.get(self.ctxt, transfer['id'])
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                     mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
            mock_notify.assert_has_calls(calls)
            self.assertEqual(2, mock_notify.call_count)

        self.assertEqual(t['id'], transfer['id'], 'Unexpected transfer id')

        # force delete volume
        volume.destroy()
        # Make sure transfer has been deleted.
        self.assertRaises(exception.TransferNotFound,
                          tx_api.get,
                          self.ctxt,
                          transfer['id'])

    def test_transfer_accept_with_snapshots(self):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt,
                                     volume_type_id=fake.VOLUME_TYPE_ID,
                                     updated_at=self.updated_at)
        utils.create_volume_type(self.ctxt.elevated(),
                                 id=fake.VOLUME_TYPE_ID, name="test_type")
        utils.create_snapshot(self.ctxt, volume.id, status='available')
        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            transfer = tx_api.create(self.ctxt, volume.id, 'Description')
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                     mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
            mock_notify.assert_has_calls(calls)
            # The notify_about_volume_usage is called twice at create().
            self.assertEqual(2, mock_notify.call_count)

        # Get volume and snapshot quota before accept
        self.ctxt.user_id = fake.USER2_ID
        self.ctxt.project_id = fake.PROJECT2_ID
        usages = db.quota_usage_get_all_by_project(self.ctxt,
                                                   self.ctxt.project_id)
        self.assertEqual(0, usages.get('volumes', {}).get('in_use', 0))
        self.assertEqual(0, usages.get('snapshots', {}).get('in_use', 0))

        with mock.patch('cinder.volume.volume_utils.notify_about_volume_usage'
                        ) as mock_notify:
            tx_api.accept(self.ctxt, transfer['id'], transfer['auth_key'])
            calls = [mock.call(self.ctxt, mock.ANY, "transfer.accept.start"),
                     mock.call(self.ctxt, mock.ANY, "transfer.accept.end")]
            mock_notify.assert_has_calls(calls)
            # The notify_about_volume_usage is called twice at accept().
            self.assertEqual(2, mock_notify.call_count)

        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual(fake.PROJECT2_ID, volume.project_id)
        self.assertEqual(fake.USER2_ID, volume.user_id)

        # Get volume and snapshot quota after accept
        self.ctxt.user_id = fake.USER2_ID
        self.ctxt.project_id = fake.PROJECT2_ID
        usages = db.quota_usage_get_all_by_project(self.ctxt,
                                                   self.ctxt.project_id)
        self.assertEqual(1, usages.get('volumes', {}).get('in_use', 0))
        self.assertEqual(1, usages.get('snapshots', {}).get('in_use', 0))

    def test_transfer_accept_with_snapshots_invalid(self):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt,
                                     volume_type_id=fake.VOLUME_TYPE_ID,
                                     updated_at=self.updated_at)
        utils.create_volume_type(self.ctxt.elevated(),
                                 id=fake.VOLUME_TYPE_ID, name="test_type")
        utils.create_snapshot(self.ctxt, volume.id, status='deleting')
        self.assertRaises(exception.InvalidSnapshot,
                          tx_api.create, self.ctxt, volume.id, 'Description')

    @mock.patch('cinder.volume.volume_utils.notify_about_volume_usage')
    @mock.patch.object(db, 'volume_type_get', v2_fakes.fake_volume_type_get)
    @mock.patch.object(quota.QUOTAS, 'reserve')
    def test_transfer_accept_with_detail_records(self, mock_notify,
                                                 mock_type_get):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)

        transfer = tx_api.create(self.ctxt, volume.id, 'Description')
        self.assertEqual(volume.project_id, transfer['source_project_id'])
        self.assertIsNone(transfer['destination_project_id'])
        self.assertFalse(transfer['accepted'])

        # Get volume and snapshot quota before accept
        self.ctxt.user_id = fake.USER2_ID
        self.ctxt.project_id = fake.PROJECT2_ID

        tx_api.accept(self.ctxt, transfer['id'], transfer['auth_key'])

        xfer = db_api.model_query(self.ctxt, models.Transfer,
                                  read_deleted='yes'
                                  ).filter_by(id=transfer['id']).first()
        self.assertEqual(volume.project_id, xfer['source_project_id'])
        self.assertTrue(xfer['accepted'])
        self.assertEqual(fake.PROJECT2_ID, xfer['destination_project_id'])
