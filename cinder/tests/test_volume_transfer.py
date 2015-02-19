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

from oslo_log import log as logging

from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests import utils
from cinder.transfer import api as transfer_api


LOG = logging.getLogger(__name__)


class VolumeTransferTestCase(test.TestCase):
    """Test cases for volume transfer code."""
    def setUp(self):
        super(VolumeTransferTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id='user_id',
                                           project_id='project_id')
        self.updated_at = datetime.datetime(1, 1, 1, 1, 1, 1)

    def test_transfer_volume_create_delete(self):
        tx_api = transfer_api.API()
        utils.create_volume(self.ctxt, id='1',
                            updated_at=self.updated_at)
        response = tx_api.create(self.ctxt, '1', 'Description')
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual('awaiting-transfer', volume['status'],
                         'Unexpected state')

        tx_api.delete(self.ctxt, response['id'])
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual('available', volume['status'], 'Unexpected state')

    def test_transfer_invalid_volume(self):
        tx_api = transfer_api.API()
        utils.create_volume(self.ctxt, id='1', status='in-use',
                            updated_at=self.updated_at)
        self.assertRaises(exception.InvalidVolume,
                          tx_api.create,
                          self.ctxt, '1', 'Description')
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual('in-use', volume['status'], 'Unexpected state')

    def test_transfer_accept(self):
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

        db.volume_update(self.ctxt, '1', {'status': 'wrong'})
        self.assertRaises(exception.InvalidVolume,
                          tx_api.accept,
                          self.ctxt, transfer['id'], transfer['auth_key'])
        db.volume_update(self.ctxt, '1', {'status': 'awaiting-transfer'})

        self.ctxt.user_id = 'new_user_id'
        self.ctxt.project_id = 'new_project_id'
        response = tx_api.accept(self.ctxt,
                                 transfer['id'],
                                 transfer['auth_key'])
        volume = db.volume_get(self.ctxt, '1')
        self.assertEqual(volume['project_id'], 'new_project_id',
                         'Unexpected project id')
        self.assertEqual(volume['user_id'], 'new_user_id',
                         'Unexpected user id')

        self.assertEqual(volume['id'], response['volume_id'],
                         'Unexpected volume id in response.')
        self.assertEqual(transfer['id'], response['id'],
                         'Unexpected transfer id in response.')

        svc.stop()

    def test_transfer_get(self):
        tx_api = transfer_api.API()
        volume = utils.create_volume(self.ctxt, id='1',
                                     updated_at=self.updated_at)
        transfer = tx_api.create(self.ctxt, volume['id'], 'Description')
        t = tx_api.get(self.ctxt, transfer['id'])
        self.assertEqual(t['id'], transfer['id'], 'Unexpected transfer id')

        ts = tx_api.get_all(self.ctxt)
        self.assertEqual(len(ts), 1, 'Unexpected number of transfers.')

        nctxt = context.RequestContext(user_id='new_user_id',
                                       project_id='new_project_id')
        utils.create_volume(nctxt, id='2', updated_at=self.updated_at)
        self.assertRaises(exception.TransferNotFound,
                          tx_api.get,
                          nctxt,
                          transfer['id'])

        ts = tx_api.get_all(nctxt)
        self.assertEqual(len(ts), 0, 'Unexpected transfers listed.')

    def test_delete_transfer_with_deleted_volume(self):
        # create a volume
        volume = utils.create_volume(self.ctxt, id='1',
                                     updated_at=self.updated_at)
        # create a transfer
        tx_api = transfer_api.API()
        transfer = tx_api.create(self.ctxt, volume['id'], 'Description')
        t = tx_api.get(self.ctxt, transfer['id'])
        self.assertEqual(t['id'], transfer['id'], 'Unexpected transfer id')
        # force delete volume
        db.volume_destroy(context.get_admin_context(), volume['id'])
        # Make sure transfer has been deleted.
        self.assertRaises(exception.TransferNotFound,
                          tx_api.get,
                          self.ctxt,
                          transfer['id'])
