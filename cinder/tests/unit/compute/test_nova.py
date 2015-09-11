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

import mock

from cinder.compute import nova
from cinder import context
from cinder import test


class NovaClientTestCase(test.TestCase):
    def setUp(self):
        super(NovaClientTestCase, self).setUp()

        self.ctx = context.RequestContext('regularuser', 'e3f0833dc08b4cea',
                                          auth_token='token', is_admin=False)
        self.ctx.service_catalog = \
            [{'type': 'compute', 'name': 'nova', 'endpoints':
              [{'publicURL': 'http://novahost:8774/v2/e3f0833dc08b4cea'}]},
             {'type': 'identity', 'name': 'keystone', 'endpoints':
              [{'publicURL': 'http://keystonehost:5000/v2.0'}]}]

        self.override_config('nova_endpoint_template',
                             'http://novahost:8774/v2/%(project_id)s')
        self.override_config('nova_endpoint_admin_template',
                             'http://novaadmhost:4778/v2/%(project_id)s')
        self.override_config('os_privileged_user_name', 'adminuser')
        self.override_config('os_privileged_user_password', 'strongpassword')

    @mock.patch('novaclient.client.Client')
    def test_nova_client_regular(self, p_client):
        nova.novaclient(self.ctx)
        p_client.assert_called_once_with(
            nova.NOVA_API_VERSION,
            'regularuser', 'token', None, region_name=None,
            auth_url='http://novahost:8774/v2/e3f0833dc08b4cea',
            insecure=False, endpoint_type='publicURL', cacert=None,
            timeout=None, extensions=nova.nova_extensions)

    @mock.patch('novaclient.client.Client')
    def test_nova_client_admin_endpoint(self, p_client):
        nova.novaclient(self.ctx, admin_endpoint=True)
        p_client.assert_called_once_with(
            nova.NOVA_API_VERSION,
            'regularuser', 'token', None, region_name=None,
            auth_url='http://novaadmhost:4778/v2/e3f0833dc08b4cea',
            insecure=False, endpoint_type='adminURL', cacert=None,
            timeout=None, extensions=nova.nova_extensions)

    @mock.patch('novaclient.client.Client')
    def test_nova_client_privileged_user(self, p_client):
        nova.novaclient(self.ctx, privileged_user=True)
        p_client.assert_called_once_with(
            nova.NOVA_API_VERSION,
            'adminuser', 'strongpassword', None, region_name=None,
            auth_url='http://keystonehost:5000/v2.0',
            insecure=False, endpoint_type='publicURL', cacert=None,
            timeout=None, extensions=nova.nova_extensions)

    @mock.patch('novaclient.client.Client')
    def test_nova_client_privileged_user_custom_auth_url(self, p_client):
        self.override_config('os_privileged_user_auth_url',
                             'http://privatekeystonehost:5000/v2.0')
        nova.novaclient(self.ctx, privileged_user=True)
        p_client.assert_called_once_with(
            nova.NOVA_API_VERSION,
            'adminuser', 'strongpassword', None, region_name=None,
            auth_url='http://privatekeystonehost:5000/v2.0',
            insecure=False, endpoint_type='publicURL', cacert=None,
            timeout=None, extensions=nova.nova_extensions)

    @mock.patch('novaclient.client.Client')
    def test_nova_client_custom_region(self, p_client):
        self.override_config('os_region_name', 'farfaraway')
        nova.novaclient(self.ctx)
        p_client.assert_called_once_with(
            nova.NOVA_API_VERSION,
            'regularuser', 'token', None, region_name='farfaraway',
            auth_url='http://novahost:8774/v2/e3f0833dc08b4cea',
            insecure=False, endpoint_type='publicURL', cacert=None,
            timeout=None, extensions=nova.nova_extensions)


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
        with mock.patch.object(nova, 'novaclient') as mock_novaclient, \
                mock.patch.object(self.novaclient.volumes,
                                  'update_server_volume') as \
                mock_update_server_volume:
            mock_novaclient.return_value = self.novaclient

            self.api.update_server_volume(self.ctx, 'server_id',
                                          'attach_id', 'new_volume_id')

        mock_novaclient.assert_called_once_with(self.ctx)
        mock_update_server_volume.assert_called_once_with(
            'server_id',
            'attach_id',
            'new_volume_id'
        )
