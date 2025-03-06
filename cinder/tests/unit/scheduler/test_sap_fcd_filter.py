# Copyright 2020 SAP SE  # All Rights Reserved.
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

from cinder import context
from cinder.tests.unit import fake_constants
from cinder.tests.unit.scheduler import fakes
from cinder.tests.unit.scheduler.test_host_filters \
    import BackendFiltersTestCase

VMWARE_VENDOR = 'VMware'


class SAPFCDFilterTestCase(BackendFiltersTestCase):

    def setUp(self):
        super(SAPFCDFilterTestCase, self).setUp()
        self.filt_cls = self.class_map['SAPFCDFilter']()
        self.props = {
            'request_spec': {
                'volume_properties': {
                    'project_id': 'foo',
                    'host': 'host1@backend1#pool1',
                }
            }
        }
        self.context = context.RequestContext(fake_constants.USER_ID,
                                              fake_constants.PROJECT_ID)

    def test_is_vmware_fcd(self):
        host = fakes.FakeBackendState('host1@backend1#pool1',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        self.assertTrue(self.filt_cls._is_vmware_fcd(host))

    def test_is_not_vmware_fcd(self):
        host = fakes.FakeBackendState('host1@backend1#pool1',
                                      {'capabilities': {},
                                       'vendor_name': 'Not VMware',
                                       'storage_protocol': 'vmdk'})
        self.assertFalse(self.filt_cls._is_vmware_fcd(host))

    def test_passes_not_migrating(self):
        host = fakes.FakeBackendState('host1@backend1#pool1',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        self.assertTrue(self.filt_cls.backend_passes(host, self.props))

    def test_passes_migrating_to_same_backend_no_pool(self):
        """This should pass the pool is the same as the original pool"""
        host = fakes.FakeBackendState('host1@backend1#pool1',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        props = self.props.copy()
        props['request_spec']['destination_host'] = 'host1@backend1'
        props['request_spec']['operation'] = 'migrate_volume'
        self.assertTrue(self.filt_cls.backend_passes(host, props))

    def test_migrating_to_same_backend_different_pool_no_pool(self):
        """This should pass because the destination host provides a pool."""
        host = fakes.FakeBackendState('host1@backend1#pool2',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        props = self.props.copy()
        props['request_spec']['destination_host'] = 'host1@backend1'
        props['request_spec']['operation'] = 'migrate_volume'
        self.assertTrue(self.filt_cls.backend_passes(host, props))

    def test_passes_migrating_to_different_backend_no_pool(self):
        """This should pass the pool is the same as the original pool."""
        host = fakes.FakeBackendState('host1@backend2#pool1',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        props = self.props.copy()
        props['request_spec']['destination_host'] = 'host1@backend2'
        props['request_spec']['operation'] = 'migrate_volume'
        self.assertTrue(self.filt_cls.backend_passes(host, props))

    def test_passes_migrating_to_different_backend_same_pool(self):
        host = fakes.FakeBackendState('host1@backend2#pool1',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        props = self.props.copy()
        props['request_spec']['destination_host'] = 'host1@backend2#pool1'
        props['request_spec']['operation'] = 'migrate_volume'
        self.assertTrue(self.filt_cls.backend_passes(host, props))

    def test_passes_migrating_to_same_backend_different_pool(self):
        host = fakes.FakeBackendState('host1@backend1#pool1',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        props = self.props.copy()
        props['request_spec']['destination_host'] = 'host1@backend1#pool2'
        props['request_spec']['operation'] = 'migrate_volume'
        self.assertTrue(self.filt_cls.backend_passes(host, props))

    def test_passes_migrating_to_different_backend_different_pool(self):
        host = fakes.FakeBackendState('host2@backend2#pool2',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        props = self.props.copy()
        props['request_spec']['destination_host'] = 'host2@backend2#pool2'
        props['request_spec']['operation'] = 'migrate_volume'
        self.assertTrue(self.filt_cls.backend_passes(host, props))

    def test_fails_migrating_to_diff_host_same_backend_different_pool(self):
        host = fakes.FakeBackendState('host2@backend1#pool2',
                                      {'capabilities': {},
                                       'vendor_name': VMWARE_VENDOR,
                                       'storage_protocol': 'vstorageobject'})
        props = self.props.copy()
        props['request_spec']['destination_host'] = 'host2@backend1#pool2'
        props['request_spec']['operation'] = 'migrate_volume'
        self.assertFalse(self.filt_cls.backend_passes(host, props))
