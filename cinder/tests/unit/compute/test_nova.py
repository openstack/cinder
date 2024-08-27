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

from unittest import mock

import ddt
from keystoneauth1 import exceptions as ks_exc
from keystoneauth1 import loading as ks_loading
from novaclient import exceptions as nova_exceptions
from oslo_config import cfg

from cinder.compute import nova
from cinder import context
from cinder.message import message_field
from cinder.tests.unit import test

CONF = cfg.CONF


class NovaClientTestCase(test.TestCase):
    def setUp(self):
        super(NovaClientTestCase, self).setUp()

        # Register the Password auth plugin options,
        # so we can use CONF.set_override
        # reset() first, otherwise already registered CLI options will
        # prevent unregister in tearDown()
        # Use CONF.set_override(), because we'll unregister the opts,
        # no need (and not possible) to cleanup.
        CONF.reset()
        self.password_opts = \
            ks_loading.get_auth_plugin_conf_options('password')
        CONF.register_opts(self.password_opts, group='nova')
        CONF.set_override('auth_url',
                          'http://keystonehost:5000',
                          group='nova')
        CONF.set_override('username', 'adminuser', group='nova')
        CONF.set_override('password', 'strongpassword', group='nova')
        self.ctx = context.RequestContext('regularuser', 'e3f0833dc08b4cea',
                                          auth_token='token', is_admin=False)
        self.ctx.service_catalog = \
            [{'type': 'compute', 'name': 'nova', 'endpoints':
              [{'publicURL': 'http://novahost:8774/v2/e3f0833dc08b4cea'}]},
             {'type': 'identity', 'name': 'keystone', 'endpoints':
              [{'publicURL': 'http://keystonehostfromsc:5000/v3'}]}]

        self.override_config('auth_type', 'password', group='nova')
        self.override_config('cafile', 'my.ca', group='nova')

    def tearDown(self):
        super(NovaClientTestCase, self).tearDown()

        CONF.unregister_opts(self.password_opts, group='nova')

    @mock.patch('novaclient.api_versions.APIVersion')
    @mock.patch('novaclient.client.Client')
    @mock.patch('keystoneauth1.identity.Token')
    @mock.patch('keystoneauth1.session.Session')
    def test_nova_client_regular(self, p_session, p_token_plugin, p_client,
                                 p_api_version):

        self.override_config('token_auth_url',
                             'http://keystonehost:5000',
                             group='nova')
        nova.novaclient(self.ctx)
        p_token_plugin.assert_called_once_with(
            auth_url='http://keystonehost:5000',
            token='token', project_name=None, project_domain_id=None
        )
        p_client.assert_called_once_with(
            p_api_version(nova.NOVA_API_VERSION),
            session=p_session.return_value, region_name=None,
            insecure=False, endpoint_type='public', cacert='my.ca',
            global_request_id=self.ctx.request_id,
            timeout=None, extensions=nova.nova_extensions)

    @mock.patch('novaclient.api_versions.APIVersion')
    @mock.patch('novaclient.client.Client')
    @mock.patch('keystoneauth1.identity.Token')
    @mock.patch('keystoneauth1.session.Session')
    def test_nova_client_regular_service_catalog(self, p_session,
                                                 p_token_plugin, p_client,
                                                 p_api_version):

        nova.novaclient(self.ctx)
        p_token_plugin.assert_called_once_with(
            auth_url='http://keystonehostfromsc:5000/v3',
            token='token', project_name=None, project_domain_id=None
        )
        p_client.assert_called_once_with(
            p_api_version(nova.NOVA_API_VERSION),
            session=p_session.return_value, region_name=None,
            insecure=False, endpoint_type='public', cacert='my.ca',
            global_request_id=self.ctx.request_id,
            timeout=None, extensions=nova.nova_extensions)

    @mock.patch('novaclient.api_versions.APIVersion')
    @mock.patch('novaclient.client.Client')
    @mock.patch('keystoneauth1.identity.Password')
    @mock.patch('keystoneauth1.session.Session')
    def test_nova_client_privileged_user(self, p_session, p_password_plugin,
                                         p_client, p_api_version):

        nova.novaclient(self.ctx, privileged_user=True)
        p_password_plugin.assert_called_once()
        self.assertEqual('adminuser',
                         p_password_plugin.call_args[1]['username'])
        self.assertEqual('http://keystonehost:5000',
                         p_password_plugin.call_args[1]['auth_url'])
        p_client.assert_called_once_with(
            p_api_version(nova.NOVA_API_VERSION),
            session=p_session.return_value, region_name=None,
            insecure=False, endpoint_type='public', cacert='my.ca',
            global_request_id=self.ctx.request_id,
            timeout=None, extensions=nova.nova_extensions)

    @mock.patch('novaclient.api_versions.APIVersion')
    @mock.patch('novaclient.client.Client')
    @mock.patch('keystoneauth1.identity.Password')
    @mock.patch('keystoneauth1.session.Session')
    def test_nova_client_privileged_user_custom_auth_url(self, p_session,
                                                         p_password_plugin,
                                                         p_client,
                                                         p_api_version):

        CONF.set_override('auth_url',
                          'http://privatekeystonehost:5000',
                          group='nova')
        nova.novaclient(self.ctx, privileged_user=True)
        p_password_plugin.assert_called_once()
        self.assertEqual('http://privatekeystonehost:5000',
                         p_password_plugin.call_args[1]['auth_url'])
        self.assertEqual('adminuser',
                         p_password_plugin.call_args[1]['username'])
        p_client.assert_called_once_with(
            p_api_version(nova.NOVA_API_VERSION),
            session=p_session.return_value, region_name=None,
            insecure=False, endpoint_type='public', cacert='my.ca',
            global_request_id=self.ctx.request_id,
            timeout=None, extensions=nova.nova_extensions)

    @mock.patch('novaclient.api_versions.APIVersion')
    @mock.patch('novaclient.client.Client')
    @mock.patch('keystoneauth1.identity.Password')
    @mock.patch('keystoneauth1.session.Session')
    def test_nova_client_custom_region(self, p_session, p_password_plugin,
                                       p_client, p_api_version):

        CONF.set_override('region_name', 'farfaraway', group='nova')
        nova.novaclient(self.ctx, privileged_user=True)
        # This doesn't impact the password plugin, just make sure it was called
        # with expected default values
        p_password_plugin.assert_called_once()
        self.assertEqual('http://keystonehost:5000',
                         p_password_plugin.call_args[1]['auth_url'])
        self.assertEqual('adminuser',
                         p_password_plugin.call_args[1]['username'])
        p_client.assert_called_once_with(
            p_api_version(nova.NOVA_API_VERSION),
            session=p_session.return_value, region_name='farfaraway',
            insecure=False, endpoint_type='public', cacert='my.ca',
            global_request_id=self.ctx.request_id,
            timeout=None, extensions=nova.nova_extensions)

    def test_get_identity_endpoint_from_sc_endpoint_not_found(self):
        ctxt = context.get_admin_context()
        self.assertRaises(ks_exc.EndpointNotFound,
                          nova._get_identity_endpoint_from_sc, ctxt)


class FakeNovaClient(object):
    class ServerExternalEvents(object):
        def __getattr__(self, item):
            return None

    class Volumes(object):
        def __getattr__(self, item):
            return None

    def __init__(self):
        self.server_external_events = self.ServerExternalEvents()
        self.volumes = self.Volumes()

    def create_volume_snapshot(self, *args, **kwargs):
        pass

    def delete_volume_snapshot(self, *args, **kwargs):
        pass


@ddt.ddt
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

        mock_novaclient.assert_called_once_with(self.ctx,
                                                privileged_user=True,
                                                api_version='2.85')
        mock_update_server_volume.assert_called_once_with(
            'server_id',
            'attach_id',
            'new_volume_id'
        )

    def test_extend_volume(self):
        server_ids = ['server-id-1', 'server-id-2']
        with mock.patch.object(nova, 'novaclient') as mock_novaclient, \
                mock.patch.object(self.novaclient.server_external_events,
                                  'create') as mock_create_event:
            mock_novaclient.return_value = self.novaclient
            mock_create_event.return_value = []

            result = self.api.extend_volume(self.ctx, server_ids, 'volume_id')
            self.assertTrue(result)

        mock_novaclient.assert_called_once_with(self.ctx,
                                                privileged_user=True,
                                                api_version='2.51')
        mock_create_event.assert_called_once_with([
            {'name': 'volume-extended',
             'server_uuid': 'server-id-1',
             'tag': 'volume_id'},
            {'name': 'volume-extended',
             'server_uuid': 'server-id-2',
             'tag': 'volume_id'},
        ])

    @ddt.data(nova_exceptions.NotFound,
              Exception,
              'illegal_list',
              [{'code': None}])
    @mock.patch('cinder.message.api.API.create')
    def test_extend_volume_failed(self, nova_result, mock_create):
        server_ids = ['server-id-1', 'server-id-2']
        with mock.patch.object(nova, 'novaclient') as mock_novaclient, \
                mock.patch.object(self.novaclient.server_external_events,
                                  'create') as mock_create_event:
            mock_novaclient.return_value = self.novaclient
            mock_create_event.side_effect = [nova_result]

            result = self.api.extend_volume(self.ctx, server_ids, 'volume_id')
            self.assertFalse(result)

        mock_novaclient.assert_called_once_with(self.ctx,
                                                privileged_user=True,
                                                api_version='2.51')
        mock_create.assert_called_once_with(
            self.ctx,
            message_field.Action.EXTEND_VOLUME,
            resource_uuid='volume_id',
            detail=message_field.Detail.NOTIFY_COMPUTE_SERVICE_FAILED)
        mock_create_event.assert_called_once_with([
            {'name': 'volume-extended',
             'server_uuid': 'server-id-1',
             'tag': 'volume_id'},
            {'name': 'volume-extended',
             'server_uuid': 'server-id-2',
             'tag': 'volume_id'},
        ])
