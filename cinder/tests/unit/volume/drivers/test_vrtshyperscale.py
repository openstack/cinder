# Copyright (c) 2017 Veritas Technologies LLC.  All rights reserved.
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

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers.veritas import vrtshyperscale as vrts


class FakeDb(object):
    def volume_metadata_get(self, *a, **kw):
        return {}

    def volume_metadata_update(self, *a, **kw):
        return None


def _stub_volume(*args, **kwargs):
    updates = {'provider_location': 'hyperscale-sv:/hyperscale'}
    return fake_volume.fake_db_volume(**updates)


def _stub_snapshot(*args, **kwargs):
    updates = {'volume': _stub_volume(), 'name': 'vrts'}
    return fake_snapshot.fake_db_snapshot(**updates)


def _stub_stats():
    data = {}
    data["volume_backend_name"] = 'Veritas_HyperScale'
    data["vendor_name"] = 'Veritas Technologies LLC'
    data["driver_version"] = '1.0'
    data["storage_protocol"] = 'nfs'
    data['total_capacity_gb'] = 0.0
    data['free_capacity_gb'] = 0.0
    data['reserved_percentage'] = 0
    data['QoS_support'] = False
    return data


class VRTSHyperScaleDriverTestCase(test.TestCase):
    """Test case for Veritas HyperScale VolumeDriver."""

    driver_name = "cinder.volume.drivers.veritas.vrtshyperscale"

    @staticmethod
    def gvmv_side_effect(arg1, arg2):
        """Mock side effect for _get_volume_metadata_value."""
        # mock the return of get_volume_metadata_value
        # for different arguments
        if arg2 == 'Secondary_datanode_key':
            return '{9876}'
        elif arg2 == 'Secondary_datanode_ip':
            return '192.0.2.2'
        elif arg2 == 'current_dn_ip':
            return '192.0.2.1'
        elif arg2 == 'vsa_ip':
            return '192.0.2.1'

    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._fetch_config_for_compute')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._fetch_config_for_datanode')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._fetch_config_for_controller')
    def setUp(self, mock_fcfcntr, mock_fcfd, mock_fcfc):
        mock_fcfcntr.return_value = None
        mock_fcfd.return_value = None
        mock_fcfc.return_value = None

        # Initialise a test seup
        super(VRTSHyperScaleDriverTestCase, self).setUp()

        self.configuration = mock.Mock(conf.Configuration(None))
        self.configuration.reserved_percentage = 0
        self.context = context.get_admin_context()
        self.driver = vrts.HyperScaleDriver(
            db=FakeDb(), configuration=self.configuration)
        self.driver.dn_routing_key = '{1234}'
        self.driver.datanode_ip = '192.0.2.1'
        self.volume = _stub_volume()
        self.snapshot = _stub_snapshot()

    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_replicas')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_details_for_create_volume')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    @mock.patch('cinder.volume.api.API.update_volume_metadata')
    def test_create_volume_single_replicas(self, mock_uvm, mock_mdp,
                                           mock_gvdfcv, mock_get_replicas,
                                           mock_gvm):
        """Test single volume replica. Happy path test case."""
        # Mock volume meatadata
        mock_gvm.return_value = _stub_volume()

        # Mock number of replicas to 1
        mock_get_replicas.return_value = 1
        # assume volume details are populated correctly
        mock_gvdfcv.return_value = _stub_volume()

        # assume volume message is sent to data node successfully
        mock_mdp.return_value = ("", None)
        # assume that the volume metadata gets updated correctly
        mock_uvm.return_value = {}

        # declare the expected result
        expected_result = {
            'provider_location': 'hyperscale-sv:/hyperscale',
            'metadata': mock_gvm.return_value
        }

        # call create volume and get the result
        actual_result = self.driver.create_volume(self.volume)

        # Test if the return value matched the expected results
        self.assertDictEqual(actual_result, expected_result)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.get_hyperscale_version')
    def test_check_for_setup_error(self, mock_ghv):
        """Test check for setup errors in Veritas HyperScale driver.

        The test case checks happy path execution when driver version 1.0.0
        is installed.
        """
        mock_ghv.return_value = "1.0.0"

        # check the driver for setup errors
        self.driver.check_for_setup_error()

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.get_hyperscale_version')
    def test_check_for_setup_error_unsupported_version(self, mock_ghv):
        """Test check for setup errors in Veritas HyperScale driver.

        The test case checks happy path execution when driver version 1.0.0
        is installed.
        """
        mock_ghv.return_value = "1.0.0.1"

        # check the driver for setup errors
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.get_hyperscale_version')
    def test_check_for_setup_error_exception(self, mock_ghv):
        """Test check for setup errors in Veritas HyperScale driver.

        The test case checks happy path execution when driver version 1.0.0
        is installed.
        """
        mock_ghv.side_effect = exception.ErrorInHyperScaleVersion(
            cmd_error="mock error")

        # check the driver for setup errors
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_delete_volume_no_replica(self, mock_mdp, mock_gvmv):
        """Test happy path for delete_volume one data nodes."""
        mock_gvmv.return_value = None
        self.driver.delete_volume(self.volume)

        message_body = {'display_name': self.volume['name']}

        mock_mdp.assert_called_with(self.driver.dn_routing_key,
                                    'hyperscale.storage.dm.volume.delete',
                                    **message_body)

    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_delete_volume_more_than_one_replica(self, mock_mdp, mock_gvmv):
        """Test happy path for delete_volume with more than one data nodes."""
        mock_gvmv.side_effect = VRTSHyperScaleDriverTestCase.gvmv_side_effect

        message_body = {'display_name': self.volume['name']}

        # make the delete call
        self.driver.delete_volume(self.volume)

        # check if delete volume sent to reflection target on data node
        # check if mq message sent with 'Secondary_datanode_key'
        mock_mdp.assert_any_call(
            '{9876}', 'hyperscale.storage.dm.volume.delete', **message_body)

        # check if the delete is sent to primary data node as well
        mock_mdp.assert_any_call(self.driver.dn_routing_key,
                                 'hyperscale.storage.dm.volume.delete',
                                 **message_body)

    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_delete_volume_no_replica_failure(self, mock_mdp, mock_gvmv):
        """Failure case for delete_volume one node in data plane."""
        mock_gvmv.side_effect = None
        self.driver.delete_volume(self.volume)
        mock_mdp.side_effect = exception.UnableToProcessHyperScaleCmdOutput(
            cmd_out='mock error')
        self.assertRaises(exception.VolumeIsBusy, self.driver.delete_volume,
                          self.volume)

    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_delete_volume_more_than_one_replica_failure(self, mock_mdp,
                                                         mock_gvmv):
        """failure case for delete_volume with more than one data nodes."""
        mock_gvmv.side_effect = VRTSHyperScaleDriverTestCase.gvmv_side_effect

        mock_mdp.side_effect = exception.UnableToProcessHyperScaleCmdOutput(
            cmd_out='mock error')

        self.assertRaises(exception.VolumeIsBusy, self.driver.delete_volume,
                          self.volume)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.get_guid_with_curly_brackets')
    def test_delete_snapshot_force_flag(self, mock_ggwcb):
        """Test snapshot deletion does not happen if force flag is set."""
        # get a mock snapshot object
        snapshot = fake_snapshot.fake_db_snapshot()
        # set the force in metadata of snapshot
        snapshot['metadata'] = {"force": "force"}

        # call the delete volume
        self.driver.delete_snapshot(snapshot)

        # if snapshot has force set in metadata then
        # get_guid_with_curly_brackets() will not be called because we
        # return as soon as we see force
        mock_ggwcb.assert_not_called()

    def test_delete_snapshot_isbusy_flag(self):
        """Test snapshot deletion throws exception if snapshot is busy."""
        # get a mock snapshot object
        snapshot = fake_snapshot.fake_db_snapshot()
        # set the force in metadata of snapshot
        snapshot['metadata'] = {"is_busy": "is_busy"}

        # call the delete volume to check if it raises Busy Exception
        self.assertRaises(exception.SnapshotIsBusy,
                          self.driver.delete_snapshot, snapshot)

    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata')
    @mock.patch('cinder.volume.api.API.get_volume')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_delete_snapshot_from_primary_dn(self, mock_mdp, mock_gv,
                                             mock_gvm):
        """Test snapshot deletion from primary DN."""
        # get mock volume
        mock_gv.return_value = None
        mock_gvm.return_value = {'current_dn_ip': self.driver.datanode_ip}

        message_body = {}
        message_body['volume_guid'] = '{' + self.volume['id'] + '}'
        message_body['snapshot_id'] = '{' + self.snapshot['id'] + '}'

        # call delete snapshot
        self.driver.delete_snapshot(self.snapshot)

        # assert msg is sent over mq with primary DN routing key
        mock_mdp.assert_called_with(self.driver.dn_routing_key,
                                    'hyperscale.storage.dm.version.delete',
                                    **message_body)

    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata')
    @mock.patch('cinder.volume.api.API.get_volume')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    def test_delete_snapshot_from_current_dn(self, mock_gvmv, mock_mdp,
                                             mock_gv, mock_gvm):
        """Test snapshot deletion DN value from volume."""
        # get a mock volume
        mock_gv.return_value = _stub_volume()

        # get a mock value of DN from volume
        mock_gvmv.return_value = '{9876}'

        message_body = {}
        message_body['volume_guid'] = '{' + self.volume['id'] + '}'
        message_body['snapshot_id'] = '{' + self.snapshot['id'] + '}'

        # call delete snapshot
        self.driver.delete_snapshot(self.snapshot)

        # assert msg is sent over mq with key from volume's current_dn_owner
        mock_mdp.assert_called_with(
            '{9876}', 'hyperscale.storage.dm.version.delete', **message_body)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_fetch_volume_stats_failure(self, mock_mdp):
        """Test case checking failure of pool for fetching stats."""
        # since we have initialised the pool to None in setup()
        # the function will return only the stub without populating
        # any free and used stats
        mock_obj = {'payload': {}}

        mock_mdp.return_value = (mock_obj, None)
        self.assertDictEqual(_stub_stats(), self.driver._fetch_volume_status())

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_create_cloned_volume_with_exception(self, mock_mdp):
        """Test case throws exception when command failed to execute."""
        vol_a = _stub_volume()
        vol_b = _stub_volume()
        mock_mdp.side_effect = exception.UnableToExecuteHyperScaleCmd(
            command='mock error')
        self.assertRaises(exception.UnableToExecuteHyperScaleCmd,
                          self.driver.create_cloned_volume, vol_b, vol_a)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale'
                '.HyperScaleDriver._select_rt')
    def test_create_cloned_volume_with_no_replica(self, mock_srt, mock_mdp):
        """Test case clone volume when there is no replica."""
        mock_obj = {'payload': {}}
        mock_mdp.return_value = (mock_obj, None)
        mock_srt.return_value = (None, None)
        vol_a = _stub_volume()
        vol_b = _stub_volume()
        self.assertDictContainsSubset({
            'provider_location': 'hyperscale-sv:/hyperscale'
        }, self.driver.create_cloned_volume(vol_b, vol_a))

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale'
                '.HyperScaleDriver._select_rt')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    def test_create_cloned_volume_with_replica(self, mock_gvmv, mock_srt,
                                               mock_mdp):
        """Test case clone volume when there is replica."""
        mock_gvmv.side_effect = VRTSHyperScaleDriverTestCase.gvmv_side_effect
        mock_obj = {'payload': {}}
        mock_mdp.return_value = (mock_obj, None)
        mock_srt.return_value = ('{1234}', '192.0.2.2')
        vol_a = _stub_volume()
        vol_b = _stub_volume()
        metadata = {
            'current_dn_owner': '{1234}',
            'Potential_secondary_key': '{1234}',
            'Primary_datanode_ip': '192.0.2.1',
            'Potential_secondary_ip': '192.0.2.2',
            'current_dn_ip': '192.0.2.1',
            'source_volid': vol_a['id'],
            'size': vol_a['size']
        }
        self.assertDictContainsSubset({
            'provider_location': 'hyperscale-sv:/hyperscale',
            'metadata': metadata
        }, self.driver.create_cloned_volume(vol_b, vol_a))

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_extend_volume_with_exception(self, mock_mdp):
        """Test case extend volume to the given size in GB."""
        mock_mdp.side_effect = exception.UnableToProcessHyperScaleCmdOutput(
            cmd_out='mock error')
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume, _stub_volume(), 256)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_extend_volume_no_exception(self, mock_mdp):
        """Test case extend volume thorws exception."""
        mock_mdp.return_value = (None, None)
        self.driver.extend_volume(_stub_volume(), 256)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    def test_create_volume_from_snapshot_with_exception(self, mock_mdp):
        """Test case create volume from snapshot thorws exception."""
        fake_volume, fake_snapshot = _stub_volume(), _stub_snapshot()
        mock_mdp.side_effect = exception.UnableToExecuteHyperScaleCmd(
            command='mock error')
        self.assertRaises(exception.UnableToExecuteHyperScaleCmd,
                          self.driver.create_volume_from_snapshot, fake_volume,
                          fake_snapshot)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale'
                '.HyperScaleDriver._select_rt')
    def test_create_volume_from_snapshot_with_no_replica(self, mock_srt,
                                                         mock_mdp):
        """Test case create volume from snapshot when there is no replica."""
        mock_obj = {'payload': {}}
        mock_mdp.return_value = (mock_obj, None)
        mock_srt.return_value = (None, None)
        fake_volume, fake_snapshot = _stub_volume(), _stub_snapshot()
        self.assertDictContainsSubset({
            'provider_location': 'hyperscale-sv:/hyperscale'
        }, self.driver.create_volume_from_snapshot(fake_volume, fake_snapshot))

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale'
                '.HyperScaleDriver._select_rt')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    def test_create_volume_from_snapshot_with_replica(self, mock_gvmv,
                                                      mock_srt, mock_mdp):
        """Test case create volume from snapshot when there is replica."""
        mock_gvmv.side_effect = VRTSHyperScaleDriverTestCase.gvmv_side_effect
        mock_obj = {'payload': {}}
        mock_mdp.return_value = (mock_obj, None)
        mock_srt.return_value = ('{1234}', '192.0.2.2')
        fake_volume, fake_snapshot = _stub_volume(), _stub_snapshot()
        metadata = {
            'current_dn_owner': '{1234}',
            'Potential_secondary_key': '{1234}',
            'Primary_datanode_ip': '192.0.2.1',
            'Potential_secondary_ip': '192.0.2.2',
            'current_dn_ip': '192.0.2.1',
            'snapshot_id': fake_snapshot['id'],
            'parent_volume_guid': '{' + fake_snapshot['volume']['id'] + '}'
        }
        self.assertDictContainsSubset({
            'provider_location': 'hyperscale-sv:/hyperscale',
            'metadata': metadata
        }, self.driver.create_volume_from_snapshot(fake_volume, fake_snapshot))

    def test_initialize_connection(self):
        """Test case intialize_connection."""
        fake_volume = _stub_volume()
        expected_data = {
            'driver_volume_type': 'veritas_hyperscale',
            'data': {
                'export': fake_volume['provider_location'],
                'name': fake_volume['name']
            }
        }
        self.assertEqual(expected_data,
                         self.driver.initialize_connection(fake_volume, None))

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_compute_plane')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.episodic_snap')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    def test_create_snapshot_with_exception(
            self, mock_gvmv, mock_es, mock_mcp):
        """Test case create snapshot throws exception."""
        mock_gvmv.side_effect = VRTSHyperScaleDriverTestCase.gvmv_side_effect
        mock_es_obj = {'payload': {'update': False}}
        mock_es.return_value = mock_es_obj
        mock_mcp.side_effect = exception.UnableToExecuteHyperScaleCmd(
            command='mock error')
        fake_snapshot = _stub_snapshot()
        self.assertRaises(exception.UnableToExecuteHyperScaleCmd,
                          self.driver.create_snapshot, fake_snapshot)

    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_controller')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_data_plane')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.episodic_snap')
    @mock.patch('cinder.volume.drivers.veritas.vrtshyperscale.HyperScaleDriver'
                '._get_volume_metadata_value')
    @mock.patch('cinder.volume.drivers.veritas.utils'
                '.message_compute_plane')
    def test_create_snapshot_user(
            self, mock_cdp, mock_gvmv, mock_es, mock_mdp, mock_mc):
        """Test case user snapshot."""
        mock_gvmv.side_effect = VRTSHyperScaleDriverTestCase.gvmv_side_effect
        mock_es_obj = {'payload': {'update': False}}
        mock_es.return_value = mock_es_obj
        mock_obj = {'payload': {}}
        mock_mdp.return_value = ("", None)
        mock_mc.return_value = ("", None)
        mock_cdp.return_value = (mock_obj, None)
        fake_snapshot = _stub_snapshot()
        expected = {
            'metadata': {
                'status': 'creating',
                'datanode_ip': '192.0.2.1',
                'TYPE': vrts.TYPE_USER_SNAP
            }
        }
        self.assertEqual(expected, self.driver.create_snapshot(fake_snapshot))
