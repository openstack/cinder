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


import datetime
import mock

from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.unit import utils
from cinder.transfer import api as transfer_api


class VolumeTransferTestCase(test.TestCase):
    """Test cases for volume transfer code."""
    def setUp(self):
        super(VolumeTransferTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id='user_id',
                                           project_id='project_id')
        self.updated_at = datetime.datetime(1, 1, 1, 1, 1, 1)

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_volume_create_delete(self, mock_notify):
        tx_api = transfer_api.API()
        utils.create_volume(self.ctxt, id='1',
                            updated_at=self.updated_at)
        response = tx_api.create(self.ctxt, '1', 'Description')
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual('awaiting-transfer', volume['status'],
                         'Unexpected state')
        calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(2, mock_notify.call_count)

        tx_api.delete(self.ctxt, response['id'])
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual('available', volume['status'], 'Unexpected state')
        calls = [mock.call(self.ctxt, mock.ANY, "transfer.delete.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.delete.end")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(4, mock_notify.call_count)

    def test_transfer_invalid_volume(self):
        tx_api = transfer_api.API()
        utils.create_volume(self.ctxt, id='1', status='in-use',
                            updated_at=self.updated_at)
        self.assertRaises(exception.InvalidVolume,
                          tx_api.create,
                          self.ctxt, '1', 'Description')
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual('in-use', volume['status'], 'Unexpected state')

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_transfer_accept(self, mock_notify):
        svc = self.start_service('volume', host='test_host')
        tx_api = transfer_api.API()
        utils.create_volume(self.ctxt, id='1',
                            updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, '1', 'Description')
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual('awaiting-transfer', volume['status'],
                         'Unexpected state')

        self.assertRaises(exception.TransferNotFound,
                          tx_api.accept,
                          self.ctxt, '2', transfer['auth_key'])

        self.assertRaises(exception.InvalidAuthKey,
                          tx_api.accept,
                          self.ctxt, transfer['id'], 'wrong')

        calls = [mock.call(self.ctxt, mock.ANY, "transfer.create.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.create.end")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(2, mock_notify.call_count)

        db.volume_update(self.ctxt, '1', {'status': 'wrong'})
        self.assertRaises(exception.InvalidVolume,
                          tx_api.accept,
                          self.ctxt, transfer['id'], transfer['auth_key'])
        db.volume_update(self.ctxt, '1', {'status': 'awaiting-transfer'})

        # Because the InvalidVolume exception is raised in tx_api, so there is
        # only transfer.accept.start called and missing transfer.accept.end.
        calls = [mock.call(self.ctxt, mock.ANY, "transfer.accept.start")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(3, mock_notify.call_count)

        self.ctxt.user_id = 'new_user_id'
        self.ctxt.project_id = 'new_project_id'
        response = tx_api.accept(self.ctxt,
                                 transfer['id'],
                                 transfer['auth_key'])
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual('new_project_id', volume['project_id'],
                         'Unexpected project id')
        self.assertEqual('new_user_id', volume['user_id'],
                         'Unexpected user id')

        self.assertEqual(volume['id'], response['volume_id'],
                         'Unexpected volume id in response.')
        self.assertEqual(transfer['id'], response['id'],
                         'Unexpected transfer id in response.')

        calls = [mock.call(self.ctxt, mock.ANY, "transfer.accept.start"),
                 mock.call(self.ctxt, mock.ANY, "transfer.accept.end")]
        mock_notify.assert_has_calls(calls)
        self.assertEqual(5, mock_notify.call_count)

        svc.stop()

    def test_transfer_get(self):
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, id='1',
                                     updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, volume['id'], 'Description')
        t = tx_api.get(self.ctxt, transfer['id'])
        self.assertEqual(t['id'], transfer['id'], 'Unexpected transfer id')

        ts = tx_api.get_all(self.ctxt)
        self.assertEqual(1, len(ts), 'Unexpected number of transfers.')

        nctxt = context.RequestContext(user_id='new_user_id',
                                       project_id='new_project_id')
        utils.create_volume(nctxt, id='2', updated_at=self.updated_at)
        self.assertRaises(exception.TransferNotFound,
                          tx_api.get,
                          nctxt,
                          transfer['id'])

        ts = tx_api.get_all(nctxt)
        self.assertEqual(0, len(ts), 'Unexpected transfers listed.')

    @mock.patch('cinder.volume.utils.notify_about_volume_usage')
    def test_delete_transfer_with_deleted_volume(self, mock_notify):
        # create a volume
        volume = utils.create_volume(self.ctxt, id='1',
                                     updated_at=self.updated_at)
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
        db.volume_destroy(context.get_admin_context(), volume['id'])
        # Make sure transfer has been deleted.
        self.assertRaises(exception.TransferNotFound,
                          tx_api.get,
                          self.ctxt,
                          transfer['id'])
