# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack LLC.
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

from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.transfer import api as transfer_api


LOG = logging.getLogger(__name__)


class VolumeTransferTestCase(test.TestCase):
    """Test cases for volume type code."""
    def setUp(self):
        super(VolumeTransferTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id='user_id',
                                           project_id='project_id')

    def _create_volume(self, volume_id, status='available',
                       user_id=None, project_id=None):
        if user_id is None:
            user_id = self.ctxt.user_id
        if project_id is None:
            project_id = self.ctxt.project_id
        vol = {'id': volume_id,
               'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
               'user_id': user_id,
               'project_id': project_id,
               'display_name': 'Display Name',
               'display_description': 'Display Description',
               'size': 1,
               'status': status}
        volume = db.volume_create(self.ctxt, vol)
        return volume

    def test_transfer_volume_create_delete(self):
        tx_api = transfer_api.API()
        volume = self._create_volume('1')
        response = tx_api.create(self.ctxt, '1', 'Description')
        volume = db.volume_get(self.ctxt, '1')
        self.assertEquals('awaiting-transfer', volume['status'],
                          'Unexpected state')

        tx_api.delete(self.ctxt, response['id'])
        volume = db.volume_get(self.ctxt, '1')
        self.assertEquals('available', volume['status'],
                          'Unexpected state')

    def test_transfer_invalid_volume(self):
        tx_api = transfer_api.API()
        volume = self._create_volume('1', status='in-use')
        self.assertRaises(exception.InvalidVolume,
                          tx_api.create,
                          self.ctxt, '1', 'Description')
        volume = db.volume_get(self.ctxt, '1')
        self.assertEquals('in-use', volume['status'],
                          'Unexpected state')

    def test_transfer_accept(self):
        tx_api = transfer_api.API()
        volume = self._create_volume('1')
        transfer = tx_api.create(self.ctxt, '1', 'Description')
        volume = db.volume_get(self.ctxt, '1')
        self.assertEquals('awaiting-transfer', volume['status'],
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
        self.assertEquals(volume['project_id'], 'new_project_id',
                          'Unexpected project id')
        self.assertEquals(volume['user_id'], 'new_user_id',
                          'Unexpected user id')

        self.assertEquals(volume['id'], response['volume_id'],
                          'Unexpected volume id in response.')
        self.assertEquals(transfer['id'], response['id'],
                          'Unexpected transfer id in response.')

    def test_transfer_get(self):
        tx_api = transfer_api.API()
        volume = self._create_volume('1')
        transfer = tx_api.create(self.ctxt, volume['id'], 'Description')
        t = tx_api.get(self.ctxt, transfer['id'])
        self.assertEquals(t['id'], transfer['id'], 'Unexpected transfer id')

        ts = tx_api.get_all(self.ctxt)
        self.assertEquals(len(ts), 1, 'Unexpected number of transfers.')

        nctxt = context.RequestContext(user_id='new_user_id',
                                       project_id='new_project_id')
        self.assertRaises(exception.TransferNotFound,
                          tx_api.get,
                          nctxt,
                          transfer['id'])

        ts = tx_api.get_all(nctxt)
        self.assertEquals(len(ts), 0, 'Unexpected transfers listed.')
