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


import mock
from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder import objects
from cinder import quota
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils
from cinder.transfer import api as transfer_api


QUOTAS = quota.QUOTAS


class VolumeTransferTestCase(test.TestCase):
    """Test cases for volume transfer code."""
    def setUp(self):
        super(VolumeTransferTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID)
        self.updated_at = timeutils.utcnow()

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_volume_create_delete(self, mock_notify):
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)
        response = tx_api.create(self.ctxt, volume.id, 'Description')
        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('awaiting-transfer', volume['status'],
                         'Unexpected state')
        calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(2, mock_notify.call_count)

        tx_api.delete(self.ctxt, response['id'])
        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('available', volume['status'], 'Unexpected state')
        calls = [mock.call(self.ctxt, mock.ANY, "transfer.delete.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.delete.end")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(4, mock_notify.call_count)

    def test_transfer_invalid_volume(self):
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, status='in-use',
                                     updated_at=self.updated_at)
        self.assertRaises(exception.InvalidVolume,
                          tx_api.create,
                          self.ctxt, volume.id, 'Description')
        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('in-use', volume['status'], 'Unexpected state')

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_accept_invalid_authkey(self, mock_notify):
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

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_accept_invalid_volume(self, mock_notify):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, volume.id, 'Description')
        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual('awaiting-transfer', volume['status'],
                         'Unexpected state')

        calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(2, mock_notify.call_count)

        volume.status = 'wrong'
        volume.save()
        self.assertRaises(exception.InvalidVolume,
                          tx_api.accept,
                          self.ctxt, transfer['id'], transfer['auth_key'])
        volume.status = 'awaiting-transfer'
        volume.save()

        # Because the InvalidVolume exception is raised in tx_api, so there is
        # only transfer.accept.start called and missing transfer.accept.end.
        calls = [mock.call(self.ctxt, mock.ANY, "transfer.accept.start")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(3, mock_notify.call_count)

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_accept_volume_in_consistencygroup(self, mock_notify):
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
    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_accept(self, mock_notify, mock_quota_voltype,
                             mock_quota_reserve, mock_quota_limit):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt,
                                     volume_type_id=fake.VOLUME_TYPE_ID,
                                     updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, volume.id, 'Description')

        self.ctxt.user_id = fake.USER2_ID
        self.ctxt.project_id = fake.PROJECT2_ID
        response = tx_api.accept(self.ctxt,
                                 transfer['id'],
                                 transfer['auth_key'])
        volume = objects.Volume.get_by_id(self.ctxt, volume.id)
        self.assertEqual(fake.PROJECT2_ID, volume.project_id)
        self.assertEqual(fake.USER2_ID, volume.user_id)

        self.assertEqual(response['volume_id'], volume.id,
                         'Unexpected volume id in response.')
        self.assertEqual(response['id'], transfer['id'],
                         'Unexpected transfer id in response.')

        calls = [mock.call(self.ctxt, mock.ANY, "transfer.accept.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.accept.end")]
        mock_notify.assert_has_calls(calls)
        # The notify_about_volume_usage is called twice at create(),
        # and twice at accept().
        self.assertEqual(4, mock_notify.call_count)

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
    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_accept_over_quota(self, mock_notify, mock_quota_voltype,
                                        mock_quota_reserve):
        svc = self.start_service('volume', host='test_host')
        self.addCleanup(svc.stop)
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt,
                                     volume_type_id=fake.VOLUME_TYPE_ID,
                                     updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, volume.id, 'Description')
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
        self.assertRaises(exception.VolumeLimitExceeded,
                          tx_api.accept,
                          self.ctxt,
                          transfer['id'],
                          transfer['auth_key'])
        # notification of transfer.accept is sent only after quota check
        # passes
        self.assertEqual(2, mock_notify.call_count)

    @mock.patch.object(QUOTAS, "limit_check")
    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_accept_over_quota_check_limit(self, mock_notify,
                                                    mock_quota_limit):
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
        self.assertRaises(exception.VolumeSizeExceedsLimit,
                          tx_api.accept,
                          self.ctxt,
                          transfer['id'],
                          transfer['auth_key'])
        # notification of transfer.accept is sent only after quota check
        # passes
        self.assertEqual(2, mock_notify.call_count)

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

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_delete_transfer_with_deleted_volume(self, mock_notify):
        # create a volume
        volume = utils.create_volume(self.ctxt, updated_at=self.updated_at)
        # create a transfer
        tx_api = transfer_api.API()
        transfer = tx_api.create(self.ctxt, volume['id'], 'Description')
        t = tx_api.get(self.ctxt, transfer['id'])
        self.assertEqual(t['id'], transfer['id'], 'Unexpected transfer id')

        calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(2, mock_notify.call_count)
        # force delete volume
        volume.destroy()
        # Make sure transfer has been deleted.
        self.assertRaises(exception.TransferNotFound,
                          tx_api.get,
                          self.ctxt,
                          transfer['id'])
