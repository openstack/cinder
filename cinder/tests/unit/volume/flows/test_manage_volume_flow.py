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
from cinder.tests.unit import fake_constants as fakes
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.flows import fake_volume_api
from cinder.volume.flows.api import manage_existing
from cinder.volume.flows import common as flow_common
from cinder.volume.flows.manager import manage_existing as manager


class ManageVolumeFlowTestCase(test.TestCase):

    def setUp(self):
        super(ManageVolumeFlowTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.counter = float(0)

    def test_cast_manage_existing(self):
        volume = fake_volume.fake_volume_type_obj(self.ctxt)

        spec = {
            'name': 'name',
            'description': 'description',
            'host': 'host',
            'ref': 'ref',
            'volume_type': 'volume_type',
            'metadata': 'metadata',
            'availability_zone': 'availability_zone',
            'bootable': 'bootable',
            'volume_id': volume.id,
        }

        # Fake objects assert specs
        task = manage_existing.ManageCastTask(
            fake_volume_api.FakeSchedulerRpcAPI(spec, self),
            fake_volume_api.FakeDb())

        create_what = spec.copy()
        create_what.update({'volume': volume})
        create_what.pop('volume_id')
        task.execute(self.ctxt, **create_what)

    @staticmethod
    def _stub_volume_object_get(self):
        volume = {
            'id': fakes.VOLUME_ID,
            'volume_type_id': fakes.VOLUME_TYPE_ID,
            'status': 'creating',
            'name': fakes.VOLUME_NAME,
        }
        return fake_volume.fake_volume_obj(self.ctxt, **volume)

    def test_prepare_for_quota_reserveration_task_execute(self):
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        mock_manage_existing_ref = mock.MagicMock()
        mock_get_size = self.mock_object(
            mock_driver, 'manage_existing_get_size')
        mock_get_size.return_value = '5'

        volume_ref = self._stub_volume_object_get(self)
        task = manager.PrepareForQuotaReservationTask(mock_db, mock_driver)

        result = task.execute(self.ctxt, volume_ref, mock_manage_existing_ref)

        self.assertEqual(volume_ref, result['volume_properties'])
        self.assertEqual('5', result['size'])
        self.assertEqual(volume_ref.id, result['volume_spec']['volume_id'])
        mock_get_size.assert_called_once_with(
            volume_ref, mock_manage_existing_ref)

    def test_prepare_for_quota_reservation_task_revert(self):
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        mock_result = mock.MagicMock()
        mock_flow_failures = mock.MagicMock()
        mock_error_out = self.mock_object(flow_common, 'error_out')
        volume_ref = self._stub_volume_object_get(self)
        task = manager.PrepareForQuotaReservationTask(mock_db, mock_driver)

        task.revert(self.ctxt, mock_result, mock_flow_failures, volume_ref)
        mock_error_out.assert_called_once_with(volume_ref, reason=mock.ANY)
