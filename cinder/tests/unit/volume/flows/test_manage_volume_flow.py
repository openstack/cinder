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
""" Tests for manage_existing TaskFlow """

import mock

from cinder import context
from cinder import test
from cinder.tests.unit.volume.flows import fake_volume_api
from cinder.volume.flows.api import manage_existing


class ManageVolumeFlowTestCase(test.TestCase):

    def setUp(self):
        super(ManageVolumeFlowTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.counter = float(0)

    def test_cast_manage_existing(self):

        volume = mock.MagicMock(return_value=None)
        spec = {
            'name': 'name',
            'description': 'description',
            'host': 'host',
            'ref': 'ref',
            'volume_type': 'volume_type',
            'metadata': 'metadata',
            'availability_zone': 'availability_zone',
            'bootable': 'bootable'}

        # Fake objects assert specs
        task = manage_existing.ManageCastTask(
            fake_volume_api.FakeSchedulerRpcAPI(spec, self),
            fake_volume_api.FakeDb())

        create_what = spec.copy()
        create_what.update({'volume': volume})
        task.execute(self.ctxt, **create_what)

        volume = mock.MagicMock(return_value={'id': 1})

        spec = {
            'name': 'name',
            'description': 'description',
            'host': 'host',
            'ref': 'ref',
            'volume_type': 'volume_type',
            'metadata': 'metadata',
            'availability_zone': 'availability_zone',
            'bootable': 'bootable'}

        # Fake objects assert specs
        task = manage_existing.ManageCastTask(
            fake_volume_api.FakeSchedulerRpcAPI(spec, self),
            fake_volume_api.FakeDb())

        create_what = spec.copy()
        create_what.update({'volume': volume})
        task.execute(self.ctxt, **create_what)
