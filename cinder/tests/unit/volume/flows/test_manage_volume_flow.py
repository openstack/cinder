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

import inspect
import mock
import taskflow.engines

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants as fakes
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.flows import fake_volume_api
from cinder.volume.flows.api import manage_existing
from cinder.volume.flows import common as flow_common
from cinder.volume.flows.manager import manage_existing as manager

if hasattr(inspect, 'getfullargspec'):
    getargspec = inspect.getfullargspec
else:
    getargspec = inspect.getargspec


class ManageVolumeFlowTestCase(test.TestCase):

    def setUp(self):
        super(ManageVolumeFlowTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.counter = float(0)

    def test_cast_manage_existing(self):
        volume = fake_volume.fake_volume_obj(self.ctxt)

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

    def test_create_db_entry_task_with_multiattach(self):

        fake_volume_type = fake_volume.fake_volume_type_obj(
            self.ctxt, extra_specs={'multiattach': '<is> True'})

        spec = {
            'name': 'name',
            'description': 'description',
            'host': 'host',
            'ref': 'ref',
            'volume_type': fake_volume_type,
            'metadata': {},
            'availability_zone': 'availability_zone',
            'bootable': 'bootable',
            'volume_type_id': fake_volume_type.id,
            'cluster_name': 'fake_cluster'
        }
        task = manage_existing.EntryCreateTask(fake_volume_api.FakeDb())

        result = task.execute(self.ctxt, **spec)
        self.assertTrue(result['volume_properties']['multiattach'])

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
        mock_error_out.assert_called_once_with(volume_ref,
                                               reason='Volume manage failed.',
                                               status='error_managing')

    def test_prepare_for_quota_reservation_with_wrong_volume(self):
        """Test the class PrepareForQuotaReservationTas with wrong vol."""
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        wrong_volume = mock.MagicMock()
        mock_manage_existing_ref = mock.MagicMock()
        mock_except = exception.CinderException

        mock_driver.manage_existing_get_size.side_effect = mock_except
        task = manager.PrepareForQuotaReservationTask(mock_db, mock_driver)
        self.assertRaises(exception.CinderException,
                          task.execute,
                          self.ctxt,
                          wrong_volume,
                          mock_manage_existing_ref)

    def test_manage_existing_task(self):
        """Test the class ManageExistingTask."""
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        mock_volume = mock.MagicMock()
        mock_manage_existing_ref = mock.MagicMock()
        mock_size = mock.MagicMock()

        task = manager.ManageExistingTask(mock_db, mock_driver)
        rv = task.execute(self.ctxt, mock_volume, mock_manage_existing_ref,
                          mock_size)

        expected_output = {'volume': mock_volume}
        self.assertDictEqual(rv, expected_output)

    def test_manage_existing_task_with_wrong_volume(self):
        """Test the class ManageExistingTask with wrong volume."""
        mock_db = mock.MagicMock()
        mock_driver = mock.MagicMock()
        mock_volume = mock.MagicMock()
        mock_volume.update.side_effect = exception.CinderException
        mock_manage_existing_ref = mock.MagicMock()
        mock_size = mock.MagicMock()

        task = manager.ManageExistingTask(mock_db, mock_driver)
        self.assertRaises(exception.CinderException,
                          task.execute,
                          self.ctxt,
                          mock_volume,
                          mock_manage_existing_ref,
                          mock_size)

    def test_get_flow(self):
        mock_volume_flow = mock.Mock()
        mock_linear_flow = self.mock_object(manager.linear_flow, 'Flow')
        mock_linear_flow.return_value = mock_volume_flow
        mock_taskflow_engine = self.mock_object(taskflow.engines, 'load')
        expected_store = {
            'context': mock.sentinel.context,
            'volume': mock.sentinel.volume,
            'manage_existing_ref': mock.sentinel.ref,
            'group_snapshot': None,
            'optional_args': {'is_quota_committed': False,
                              'update_size': True}
        }

        manager.get_flow(
            mock.sentinel.context, mock.sentinel.db, mock.sentinel.driver,
            mock.sentinel.host, mock.sentinel.volume, mock.sentinel.ref)

        mock_linear_flow.assert_called_once_with(
            'volume_manage_existing_manager')
        mock_taskflow_engine.assert_called_once_with(
            mock_volume_flow, store=expected_store)

    def test_get_flow_volume_flow_tasks(self):
        """Test that all expected parameter names exist for added tasks."""
        mock_taskflow_engine = self.mock_object(taskflow.engines, 'load')
        mock_taskflow_engine.side_effect = self._verify_volume_flow_tasks

        manager.get_flow(
            mock.sentinel.context, mock.sentinel.db, mock.sentinel.driver,
            mock.sentinel.host, mock.sentinel.volume, mock.sentinel.ref)

    def _verify_volume_flow_tasks(self, volume_flow, store=None):
        param_names = [
            'context',
            'volume',
            'manage_existing_ref',
            'group_snapshot',
            'optional_args',
        ]

        provides = {'self'}
        revert_provides = ['self', 'result', 'flow_failures']
        for node in volume_flow.iter_nodes():
            task = node[0]
            # Subsequent tasks may use parameters defined in a previous task's
            # default_provides list. Add these names to the provides set.
            if task.default_provides:
                for p in task.default_provides:
                    provides.add(p)

            execute_args = getargspec(task.execute)[0]
            execute_args = [x for x in execute_args if x not in provides]
            [self.assertIn(arg, param_names) for arg in execute_args]

            revert_args = getargspec(task.revert)[0]
            revert_args = [x for x in revert_args if x not in revert_provides]
            [self.assertIn(arg, param_names) for arg in revert_args]
