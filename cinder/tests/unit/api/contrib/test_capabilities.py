# Copyright (c) 2015 Hitachi Data Systems, Inc.
# All Rights Reserved.
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

import oslo_messaging

from cinder.api.contrib import capabilities
from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


def rpcapi_get_capabilities(self, context, host, discover):
    capabilities = dict(
        vendor_name='OpenStack',
        volume_backend_name='lvm',
        pool_name='pool',
        driver_version='2.0.0',
        storage_protocol='iSCSI',
        display_name='Capabilities of Cinder LVM driver',
        description='These are volume type options provided by '
                    'Cinder LVM driver, blah, blah.',
        replication_targets=[],
        visibility='public',
        properties=dict(
            compression=dict(
                title='Compression',
                description='Enables compression.',
                type='boolean'),
            qos=dict(
                title='QoS',
                description='Enables QoS.',
                type='boolean'),
            replication=dict(
                title='Replication',
                description='Enables replication.',
                type='boolean'),
            thin_provisioning=dict(
                title='Thin Provisioning',
                description='Sets thin provisioning.',
                type='boolean'),
        )
    )
    return capabilities


class CapabilitiesAPITest(test.TestCase):
    def setUp(self):
        super(CapabilitiesAPITest, self).setUp()
        self.flags(host='fake')
        self.controller = capabilities.CapabilitiesController()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_capabilities',
                rpcapi_get_capabilities)
    def test_capabilities_summary(self, mock_services):
        mock_services.return_value = [{'name': 'fake', 'host': 'fake_host'}]
        req = fakes.HTTPRequest.blank('/fake/capabilities/fake')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.show(req, 'fake')

        expected = {
            'namespace': 'OS::Storage::Capabilities::fake_host',
            'vendor_name': 'OpenStack',
            'volume_backend_name': 'lvm',
            'pool_name': 'pool',
            'driver_version': '2.0.0',
            'storage_protocol': 'iSCSI',
            'display_name': 'Capabilities of Cinder LVM driver',
            'description': 'These are volume type options provided by '
                           'Cinder LVM driver, blah, blah.',
            'visibility': 'public',
            'replication_targets': [],
            'properties': {
                'compression': {
                    'title': 'Compression',
                    'description': 'Enables compression.',
                    'type': 'boolean'},
                'qos': {
                    'title': 'QoS',
                    'description': 'Enables QoS.',
                    'type': 'boolean'},
                'replication': {
                    'title': 'Replication',
                    'description': 'Enables replication.',
                    'type': 'boolean'},
                'thin_provisioning': {
                    'title': 'Thin Provisioning',
                    'description': 'Sets thin provisioning.',
                    'type': 'boolean'},
            }
        }

        self.assertDictEqual(expected, res)

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.get_capabilities')
    def test_get_capabilities_rpc_timeout(self, mock_rpc, mock_services):
        mock_rpc.side_effect = oslo_messaging.MessagingTimeout
        mock_services.return_value = [{'name': 'fake'}]

        req = fakes.HTTPRequest.blank('/fake/capabilities/fake')
        req.environ['cinder.context'] = self.ctxt
        self.assertRaises(exception.RPCTimeout,
                          self.controller.show, req, 'fake')

    @mock.patch('cinder.db.service_get_all')
    def test_get_capabilities_service_not_found(self, mock_services):
        mock_services.return_value = []

        req = fakes.HTTPRequest.blank('/fake/capabilities/fake')
        req.environ['cinder.context'] = self.ctxt
        self.assertRaises(exception.NotFound,
                          self.controller.show, req, 'fake')
