#    Copyright 2013 IBM Corp.
#
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

import contextlib

import mock

from cinder.compute import nova
from cinder import context
from cinder import test


class FakeNovaClient(object):
    class Volumes(object):
        def __getattr__(self, item):
            return None

    def __init__(self):
        self.volumes = self.Volumes()

    def create_volume_snapshot(self, *args, **kwargs):
        pass

    def delete_volume_snapshot(self, *args, **kwargs):
        pass


class NovaApiTestCase(test.TestCase):
    def setUp(self):
        super(NovaApiTestCase, self).setUp()

        self.api = nova.API()
        self.novaclient = FakeNovaClient()
        self.ctx = context.get_admin_context()

    def test_update_server_volume(self):
        with contextlib.nested(
                mock.patch.object(nova, 'novaclient'),
                mock.patch.object(self.novaclient.volumes,
                                  'update_server_volume')
        ) as (mock_novaclient, mock_update_server_volume):
            mock_novaclient.return_value = self.novaclient

            self.api.update_server_volume(self.ctx, 'server_id',
                                          'attach_id', 'new_volume_id')

        mock_novaclient.assert_called_once_with(self.ctx)
        mock_update_server_volume.assert_called_once_with(
            'server_id',
            'attach_id',
            'new_volume_id'
        )
