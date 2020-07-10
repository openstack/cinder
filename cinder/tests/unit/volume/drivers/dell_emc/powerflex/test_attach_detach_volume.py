# Copyright (c) 2016 EMC Corporation.
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

from cinder import context
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex


class TestAttachDetachVolume(powerflex.TestPowerFlexDriver):

    def setUp(self):
        super(TestAttachDetachVolume, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)
        self.fake_path = '/fake/path/vol-xx'
        self.volume = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': fake.PROVIDER_ID})
        self.driver.connector = FakeConnector()

    def test_attach_volume(self):
        path = self.driver._sio_attach_volume(self.volume)
        self.assertEqual(self.fake_path, path)

    def test_detach_volume(self):
        self.driver._sio_detach_volume(self.volume)


class FakeConnector(object):
    def connect_volume(self, connection_properties):
        return {'path': '/fake/path/vol-xx'}

    def disconnect_volume(self, connection_properties, volume):
        return None
