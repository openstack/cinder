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

import copy
import time
from unittest import mock

import ddt
from oslo_config import cfg

from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as\
    dataontap_fakes
from cinder.tests.unit.volume.drivers.netapp.dataontap.utils import fakes
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap.utils import data_motion
from cinder.volume.drivers.netapp.dataontap.utils import utils
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils


CONF = cfg.CONF


@ddt.ddt
class NetAppCDOTDataMotionMixinTestCase(test.TestCase):

    def setUp(self):
        super(NetAppCDOTDataMotionMixinTestCase, self).setUp()
        self.dm_mixin = data_motion.DataMotionMixin()
        self.src_backend = 'backend1'
        self.dest_backend = 'backend2'
        self.src_vserver = 'source_vserver'
        self.dest_vserver = 'dest_vserver'
        self._setup_mock_config()
        self.mock_cmode_client = self.mock_object(client_cmode, 'Client')
        self.src_flexvol_name = 'volume_c02d497a_236c_4852_812a_0d39373e312a'
        self.dest_flexvol_name = self.src_flexvol_name
        self.mock_src_client = mock.Mock()
        self.mock_dest_client = mock.Mock()
        self.config = fakes.get_fake_cmode_config(self.src_backend)
        self.mock_object(utils, 'get_backend_configuration',
                         side_effect=[self.mock_dest_config,
                                      self.mock_src_config])
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[self.mock_dest_client,
                                      self.mock_src_client])

    def _setup_mock_config(self):
        self.mock_src_config = configuration.Configuration(
            driver.volume_opts, config_group=self.src_backend)
        self.mock_dest_config = configuration.Configuration(
            driver.volume_opts, config_group=self.dest_backend)

        for config in (self.mock_src_config, self.mock_dest_config):
            config.append_config_values(na_opts.netapp_proxy_opts)
            config.append_config_values(na_opts.netapp_connection_opts)
            config.append_config_values(na_opts.netapp_transport_opts)
            config.append_config_values(na_opts.netapp_basicauth_opts)
            config.append_config_values(na_opts.netapp_provisioning_opts)
            config.append_config_values(na_opts.netapp_cluster_opts)
            config.append_config_values(na_opts.netapp_san_opts)
            config.append_config_values(na_opts.netapp_replication_opts)
            config.netapp_snapmirror_quiesce_timeout = 10

        CONF.set_override('netapp_vserver', self.src_vserver,
                          group=self.src_backend)
        CONF.set_override('netapp_vserver', self.dest_vserver,
                          group=self.dest_backend)

    @ddt.data(None, [], [{'some_key': 'some_value'}])
    def test_get_replication_backend_names_none(self, replication_device):
        CONF.set_override('replication_device', replication_device,
                          group=self.src_backend)

        devices = self.dm_mixin.get_replication_backend_names(self.config)

        self.assertEqual(0, len(devices))

    @ddt.data([{'backend_id': 'xyzzy'}, {'backend_id': 'spoon!'}],
              [{'backend_id': 'foobar'}])
    def test_get_replication_backend_names_valid(self, replication_device):
        CONF.set_override('replication_device', replication_device,
                          group=self.src_backend)

        devices = self.dm_mixin.get_replication_backend_names(self.config)

        self.assertEqual(len(replication_device), len(devices))

    def test_get_snapmirrors(self):
        self.mock_object(self.mock_dest_client, 'get_snapmirrors')

        self.dm_mixin.get_snapmirrors(self.src_backend,
                                      self.dest_backend,
                                      self.src_flexvol_name,
                                      self.dest_flexvol_name)

        self.mock_dest_client.get_snapmirrors.assert_called_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name,
            desired_attributes=['relationship-status',
                                'mirror-state',
                                'source-vserver',
                                'source-volume',
                                'destination-vserver',
                                'destination-volume',
                                'last-transfer-end-timestamp',
                                'lag-time'])
        self.assertEqual(1, self.mock_dest_client.get_snapmirrors.call_count)

    @ddt.data([], ['backend1'], ['backend1', 'backend2'])
    def test_get_replication_backend_stats(self, replication_backend_names):
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=replication_backend_names)
        enabled_stats = {
            'replication_count': len(replication_backend_names),
            'replication_targets': replication_backend_names,
            'replication_type': 'async',
        }
        expected_stats = {
            'replication_enabled': len(replication_backend_names) > 0,
        }
        if len(replication_backend_names) > 0:
            expected_stats.update(enabled_stats)

        actual_stats = self.dm_mixin.get_replication_backend_stats(self.config)

        self.assertDictEqual(expected_stats, actual_stats)

    @ddt.data(None, [],
              [{'backend_id': 'replication_backend_2', 'aggr2': 'aggr20'}])
    def test_get_replication_aggregate_map_none(self, replication_aggr_map):

        self.mock_object(utils, 'get_backend_configuration',
                         return_value=self.config)
        CONF.set_override('netapp_replication_aggregate_map',
                          replication_aggr_map,
                          group=self.src_backend)

        aggr_map = self.dm_mixin._get_replication_aggregate_map(
            self.src_backend, 'replication_backend_1')

        self.assertEqual(0, len(aggr_map))

    @ddt.data([{'backend_id': 'replication_backend_1', 'aggr1': 'aggr10'}],
              [{'backend_id': 'replication_backend_1', 'aggr1': 'aggr10'},
               {'backend_id': 'replication_backend_2', 'aggr2': 'aggr20'}])
    def test_get_replication_aggregate_map_valid(self, replication_aggr_map):
        self.mock_object(utils, 'get_backend_configuration',
                         return_value=self.config)
        CONF.set_override('netapp_replication_aggregate_map',
                          replication_aggr_map, group=self.src_backend)

        aggr_map = self.dm_mixin._get_replication_aggregate_map(
            self.src_backend, 'replication_backend_1')

        self.assertDictEqual({'aggr1': 'aggr10'}, aggr_map)

    @ddt.data({'dest_exists': True, 'is_flexgroup': False},
              {'dest_exists': True, 'is_flexgroup': True},
              {'dest_exists': False, 'is_flexgroup': False},
              {'dest_exists': False, 'is_flexgroup': True})
    @ddt.unpack
    def test_create_snapmirror_dest_flexvol_exists(self, dest_exists,
                                                   is_flexgroup):
        mock_dest_client = mock.Mock()
        mock_src_client = mock.Mock()
        self.mock_object(mock_dest_client, 'flexvol_exists',
                         return_value=dest_exists)
        self.mock_object(mock_dest_client, 'get_snapmirrors',
                         return_value=None)
        create_destination_flexvol = self.mock_object(
            self.dm_mixin, 'create_destination_flexvol')
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[mock_dest_client,
                                      mock_src_client])

        mock_provisioning_options = mock.Mock()
        mock_provisioning_options.get.return_value = is_flexgroup

        self.mock_object(mock_src_client,
                         'get_provisioning_options_from_flexvol',
                         return_value=mock_provisioning_options)

        self.dm_mixin.create_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        if not dest_exists:
            create_destination_flexvol.assert_called_once_with(
                self.src_backend, self.dest_backend, self.src_flexvol_name,
                self.dest_flexvol_name, pool_is_flexgroup=is_flexgroup)
        else:
            self.assertFalse(create_destination_flexvol.called)
        mock_dest_client.create_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name,
            schedule='hourly',
            relationship_type=('extended_data_protection'
                               if is_flexgroup
                               else 'data_protection'))
        mock_dest_client.initialize_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)

    def test_create_snapmirror_cleanup_on_geometry_has_changed(self):
        mock_dest_client = mock.Mock()
        mock_src_client = mock.Mock()
        self.mock_object(mock_dest_client, 'flexvol_exists',
                         return_value=True)
        self.mock_object(mock_dest_client, 'get_snapmirrors',
                         return_value=None)
        create_destination_flexvol = self.mock_object(
            self.dm_mixin, 'create_destination_flexvol')
        mock_delete_snapshot = self.mock_object(
            self.dm_mixin, 'delete_snapmirror'
        )
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[mock_dest_client,
                                      mock_src_client])

        geometry_exception_message = ("Geometry of the destination FlexGroup "
                                      "has been changed since the SnapMirror "
                                      "relationship was created.")
        mock_dest_client.initialize_snapmirror.side_effect = [
            netapp_api.NaApiError(code=netapp_api.EAPIERROR,
                                  message=geometry_exception_message),
        ]

        mock_provisioning_options = mock.Mock()
        mock_provisioning_options.get.return_value = False

        self.mock_object(mock_src_client,
                         'get_provisioning_options_from_flexvol',
                         return_value=mock_provisioning_options)

        self.assertRaises(na_utils.GeometryHasChangedOnDestination,
                          self.dm_mixin.create_snapmirror,
                          self.src_backend,
                          self.dest_backend,
                          self.src_flexvol_name,
                          self.dest_flexvol_name)

        self.assertFalse(create_destination_flexvol.called)
        mock_dest_client.create_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, schedule='hourly',
            relationship_type='data_protection')

        mock_dest_client.initialize_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)

        mock_delete_snapshot.assert_called_once_with(
            self.src_backend, self.dest_backend, self.src_flexvol_name,
            self.dest_flexvol_name)

    @ddt.data('uninitialized', 'broken-off', 'snapmirrored')
    def test_create_snapmirror_snapmirror_exists_state(self, mirror_state):
        mock_dest_client = mock.Mock()
        existing_snapmirrors = [{'mirror-state': mirror_state}]
        self.mock_object(self.dm_mixin, 'create_destination_flexvol')
        self.mock_object(utils, 'get_client_for_backend',
                         return_value=mock_dest_client)
        self.mock_object(mock_dest_client, 'flexvol_exists',
                         return_value=True)
        self.mock_object(mock_dest_client, 'get_snapmirrors',
                         return_value=existing_snapmirrors)

        self.dm_mixin.create_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        self.assertFalse(mock_dest_client.create_snapmirror.called)
        self.assertFalse(mock_dest_client.initialize_snapmirror.called)
        self.assertFalse(self.dm_mixin.create_destination_flexvol.called)
        if mirror_state == 'snapmirrored':
            self.assertFalse(mock_dest_client.resume_snapmirror.called)
            self.assertFalse(mock_dest_client.resync_snapmirror.called)
        else:
            mock_dest_client.resume_snapmirror.assert_called_once_with(
                self.src_vserver, self.src_flexvol_name,
                self.dest_vserver, self.dest_flexvol_name)
            mock_dest_client.resync_snapmirror.assert_called_once_with(
                self.src_vserver, self.src_flexvol_name,
                self.dest_vserver, self.dest_flexvol_name)

    @ddt.data('resume_snapmirror', 'resync_snapmirror')
    def test_create_snapmirror_snapmirror_exists_repair_exception(self,
                                                                  failed_call):
        mock_dest_client = mock.Mock()
        mock_exception_log = self.mock_object(data_motion.LOG, 'exception')
        existing_snapmirrors = [{'mirror-state': 'broken-off'}]
        self.mock_object(self.dm_mixin, 'create_destination_flexvol')
        self.mock_object(utils, 'get_client_for_backend',
                         return_value=mock_dest_client)
        self.mock_object(mock_dest_client, 'flexvol_exists',
                         return_value=True)
        self.mock_object(mock_dest_client, 'get_snapmirrors',
                         return_value=existing_snapmirrors)
        self.mock_object(mock_dest_client, failed_call,
                         side_effect=netapp_api.NaApiError)

        self.dm_mixin.create_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        self.assertFalse(mock_dest_client.create_snapmirror.called)
        self.assertFalse(mock_dest_client.initialize_snapmirror.called)
        self.assertFalse(self.dm_mixin.create_destination_flexvol.called)
        mock_dest_client.resume_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name)
        if failed_call == 'resync_snapmirror':
            mock_dest_client.resync_snapmirror.assert_called_once_with(
                self.src_vserver, self.src_flexvol_name,
                self.dest_vserver, self.dest_flexvol_name)
        self.assertEqual(1, mock_exception_log.call_count)

    def test_delete_snapmirror(self):
        mock_src_client = mock.Mock()
        mock_dest_client = mock.Mock()
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[mock_dest_client, mock_src_client])

        self.dm_mixin.delete_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        mock_dest_client.abort_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, clear_checkpoint=False)
        mock_dest_client.delete_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)
        mock_src_client.release_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)

    def test_delete_snapmirror_does_not_exist(self):
        """Ensure delete succeeds when the snapmirror does not exist."""
        mock_src_client = mock.Mock()
        mock_dest_client = mock.Mock()
        mock_dest_client.abort_snapmirror.side_effect = netapp_api.NaApiError(
            code=netapp_api.EAPIERROR)
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[mock_dest_client, mock_src_client])

        self.dm_mixin.delete_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        mock_dest_client.abort_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, clear_checkpoint=False)
        mock_dest_client.delete_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)
        mock_src_client.release_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)

    def test_delete_snapmirror_error_deleting(self):
        """Ensure delete succeeds when the snapmirror does not exist."""
        mock_src_client = mock.Mock()
        mock_dest_client = mock.Mock()
        mock_dest_client.delete_snapmirror.side_effect = netapp_api.NaApiError(
            code=netapp_api.ESOURCE_IS_DIFFERENT
        )
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[mock_dest_client, mock_src_client])

        self.dm_mixin.delete_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        mock_dest_client.abort_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, clear_checkpoint=False)
        mock_dest_client.delete_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)
        mock_src_client.release_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)

    def test_delete_snapmirror_error_releasing(self):
        """Ensure delete succeeds when the snapmirror does not exist."""
        mock_src_client = mock.Mock()
        mock_dest_client = mock.Mock()
        mock_src_client.release_snapmirror.side_effect = (
            netapp_api.NaApiError(code=netapp_api.EOBJECTNOTFOUND))
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[mock_dest_client, mock_src_client])

        self.dm_mixin.delete_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        mock_dest_client.abort_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, clear_checkpoint=False)
        mock_dest_client.delete_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)
        mock_src_client.release_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)

    def test_delete_snapmirror_without_release(self):
        mock_src_client = mock.Mock()
        mock_dest_client = mock.Mock()
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[mock_dest_client, mock_src_client])

        self.dm_mixin.delete_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name,
                                        release=False)

        mock_dest_client.abort_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, clear_checkpoint=False)
        mock_dest_client.delete_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)
        self.assertFalse(mock_src_client.release_snapmirror.called)

    def test_delete_snapmirror_source_unreachable(self):
        mock_src_client = mock.Mock()
        mock_dest_client = mock.Mock()
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[mock_dest_client, Exception])

        self.dm_mixin.delete_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        mock_dest_client.abort_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, clear_checkpoint=False)
        mock_dest_client.delete_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)

        self.assertFalse(mock_src_client.release_snapmirror.called)

    def test_quiesce_then_abort_timeout(self):
        self.mock_object(time, 'sleep')
        mock_get_snapmirrors = mock.Mock(
            return_value=[{'relationship-status': 'transferring'}])
        self.mock_object(self.mock_dest_client, 'get_snapmirrors',
                         mock_get_snapmirrors)

        self.dm_mixin.quiesce_then_abort(self.src_backend,
                                         self.dest_backend,
                                         self.src_flexvol_name,
                                         self.dest_flexvol_name)

        self.mock_dest_client.get_snapmirrors.assert_called_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name,
            desired_attributes=['relationship-status', 'mirror-state'])
        self.assertEqual(2, self.mock_dest_client.get_snapmirrors.call_count)
        self.mock_dest_client.quiesce_snapmirror.assert_called_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name)
        self.mock_dest_client.abort_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, clear_checkpoint=False)

    def test_update_snapmirror(self):
        self.mock_object(self.mock_dest_client, 'get_snapmirrors')

        self.dm_mixin.update_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        self.mock_dest_client.update_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name)

    def test_create_vserver_peer(self):
        mock_get_client_for_backend = self.mock_object(
            utils, 'get_client_for_backend')
        get_vserver_peer_response = []
        mock_get_vserver_peers = mock_get_client_for_backend.return_value.\
            get_vserver_peers
        mock_get_vserver_peers.return_value = get_vserver_peer_response
        mock_create_vserver_peer = mock_get_client_for_backend.return_value.\
            create_vserver_peer
        mock_create_vserver_peer.return_value = None
        peer_applications = ['snapmirror']

        result = self.dm_mixin.create_vserver_peer(
            dataontap_fakes.VSERVER_NAME, self.src_backend,
            dataontap_fakes.DEST_VSERVER_NAME, peer_applications)

        mock_get_vserver_peers.assert_called_once_with(
            dataontap_fakes.VSERVER_NAME, dataontap_fakes.DEST_VSERVER_NAME)
        mock_create_vserver_peer.assert_called_once_with(
            dataontap_fakes.VSERVER_NAME, dataontap_fakes.DEST_VSERVER_NAME,
            vserver_peer_application=peer_applications)
        self.assertIsNone(result)

    def test_create_vserver_peer_already_exists(self):
        mock_get_client_for_backend = self.mock_object(
            utils, 'get_client_for_backend')
        get_vserver_peer_response = [{
            'vserver': dataontap_fakes.VSERVER_NAME,
            'peer-vserver': dataontap_fakes.DEST_VSERVER_NAME,
            'peer-state': 'peered',
            'peer-cluster': dataontap_fakes.CLUSTER_NAME,
            'applications': ['snapmirror']
        }]
        mock_get_vserver_peers = mock_get_client_for_backend.return_value. \
            get_vserver_peers
        mock_get_vserver_peers.return_value = get_vserver_peer_response
        mock_create_vserver_peer = mock_get_client_for_backend.return_value. \
            create_vserver_peer
        mock_create_vserver_peer.return_value = None
        peer_applications = ['snapmirror']

        result = self.dm_mixin.create_vserver_peer(
            dataontap_fakes.VSERVER_NAME, self.src_backend,
            dataontap_fakes.DEST_VSERVER_NAME, peer_applications)

        mock_get_vserver_peers.assert_called_once_with(
            dataontap_fakes.VSERVER_NAME, dataontap_fakes.DEST_VSERVER_NAME)
        mock_create_vserver_peer.assert_not_called()
        self.assertIsNone(result)

    def test_create_vserver_peer_application_not_defined(self):
        mock_get_client_for_backend = self.mock_object(
            utils, 'get_client_for_backend')
        get_vserver_peer_response = [{
            'vserver': dataontap_fakes.VSERVER_NAME,
            'peer-vserver': dataontap_fakes.DEST_VSERVER_NAME,
            'peer-state': 'peered',
            'peer-cluster': dataontap_fakes.CLUSTER_NAME,
            'applications': ['snapmirror']
        }]
        mock_get_vserver_peers = mock_get_client_for_backend.return_value. \
            get_vserver_peers
        mock_get_vserver_peers.return_value = get_vserver_peer_response
        mock_create_vserver_peer = mock_get_client_for_backend.return_value. \
            create_vserver_peer
        mock_create_vserver_peer.return_value = None
        peer_applications = ['not a snapmirror application']

        self.assertRaises(na_utils.NetAppDriverException,
                          self.dm_mixin.create_vserver_peer,
                          dataontap_fakes.VSERVER_NAME,
                          self.src_backend,
                          dataontap_fakes.DEST_VSERVER_NAME,
                          peer_applications)

        mock_get_vserver_peers.assert_called_once_with(
            dataontap_fakes.VSERVER_NAME, dataontap_fakes.DEST_VSERVER_NAME)
        mock_create_vserver_peer.assert_not_called()

    def test_quiesce_then_abort_wait_for_quiesced(self):
        self.mock_object(time, 'sleep')
        self.mock_object(self.mock_dest_client, 'get_snapmirrors',
                         side_effect=[
                             [{'relationship-status': 'transferring'}],
                             [{'relationship-status': 'quiesced'}]])

        self.dm_mixin.quiesce_then_abort(self.src_backend,
                                         self.dest_backend,
                                         self.src_flexvol_name,
                                         self.dest_flexvol_name)

        self.mock_dest_client.get_snapmirrors.assert_called_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name,
            desired_attributes=['relationship-status', 'mirror-state'])
        self.assertEqual(2, self.mock_dest_client.get_snapmirrors.call_count)
        self.mock_dest_client.quiesce_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name)

    def test_break_snapmirror(self):
        self.mock_object(self.dm_mixin, 'quiesce_then_abort')

        self.dm_mixin.break_snapmirror(self.src_backend,
                                       self.dest_backend,
                                       self.src_flexvol_name,
                                       self.dest_flexvol_name)

        self.dm_mixin.quiesce_then_abort.assert_called_once_with(
            self.src_backend, self.dest_backend,
            self.src_flexvol_name, self.dest_flexvol_name)
        self.mock_dest_client.break_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name)
        self.mock_dest_client.mount_flexvol.assert_called_once_with(
            self.dest_flexvol_name)

    def test_break_snapmirror_wait_for_quiesced(self):
        self.mock_object(self.dm_mixin, 'quiesce_then_abort')

        self.dm_mixin.break_snapmirror(self.src_backend,
                                       self.dest_backend,
                                       self.src_flexvol_name,
                                       self.dest_flexvol_name)

        self.dm_mixin.quiesce_then_abort.assert_called_once_with(
            self.src_backend, self.dest_backend,
            self.src_flexvol_name, self.dest_flexvol_name,)
        self.mock_dest_client.break_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name)
        self.mock_dest_client.mount_flexvol.assert_called_once_with(
            self.dest_flexvol_name)

    def test_resync_snapmirror(self):
        self.dm_mixin.resync_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        self.mock_dest_client.resync_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name,
            self.dest_vserver, self.dest_flexvol_name)

    def test_resume_snapmirror(self):
        self.dm_mixin.resume_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name)

        self.mock_dest_client.resume_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name)

    @ddt.data({'size': 1, 'aggr_map': {},
               'is_flexgroup': False},
              {'size': 1, 'aggr_map': {'aggr02': 'aggr20'},
               'is_flexgroup': False},
              {'size': None, 'aggr_map': {'aggr01': 'aggr10'},
               'is_flexgroup': False},
              {'size': 1, 'aggr_map': {'aggr01': 'aggr10'},
               'is_flexgroup': True})
    @ddt.unpack
    def test_create_destination_flexvol_exception(self, size, aggr_map,
                                                  is_flexgroup):
        self.mock_object(
            self.mock_src_client, 'get_provisioning_options_from_flexvol',
            return_value={'size': size, 'aggregate': 'aggr01',
                          'is_flexgroup': is_flexgroup})
        self.mock_object(self.dm_mixin, '_get_replication_aggregate_map',
                         return_value=aggr_map)
        mock_client_call = self.mock_object(
            self.mock_dest_client, 'create_flexvol')

        self.assertRaises(na_utils.NetAppDriverException,
                          self.dm_mixin.create_destination_flexvol,
                          self.src_backend, self.dest_backend,
                          self.src_flexvol_name, self.dest_flexvol_name)

        if size and is_flexgroup is False:
            self.dm_mixin._get_replication_aggregate_map.\
                assert_called_once_with(self.src_backend, self.dest_backend)
        elif is_flexgroup is False:
            self.assertFalse(
                self.dm_mixin._get_replication_aggregate_map.called)
        self.assertFalse(mock_client_call.called)

    @ddt.data('mixed', None)
    def test_create_destination_flexgroup_online_timeout(self, volume_state):
        aggr_map = {
            fakes.PROVISIONING_OPTS['aggregate'][0]: 'aggr01',
            'aggr20': 'aggr02',
        }
        provisioning_opts = copy.deepcopy(fakes.PROVISIONING_OPTS)
        expected_prov_opts = copy.deepcopy(fakes.PROVISIONING_OPTS)
        expected_prov_opts.pop('volume_type', None)
        expected_prov_opts.pop('size', None)
        expected_prov_opts.pop('aggregate', None)
        expected_prov_opts.pop('is_flexgroup', None)

        self.mock_object(
            self.mock_src_client, 'get_provisioning_options_from_flexvol',
            return_value=provisioning_opts)
        self.mock_object(self.dm_mixin, '_get_replication_aggregate_map',
                         return_value=aggr_map)
        self.mock_object(self.dm_mixin,
                         '_get_replication_volume_online_timeout',
                         return_value=2)

        mock_create_volume_async = self.mock_object(self.mock_dest_client,
                                                    'create_volume_async')
        mock_volume_state = self.mock_object(self.mock_dest_client,
                                             'get_volume_state',
                                             return_value=volume_state)
        self.mock_object(self.mock_src_client, 'is_flexvol_encrypted',
                         return_value=False)

        mock_dedupe_enabled = self.mock_object(
            self.mock_dest_client, 'enable_volume_dedupe_async')
        mock_compression_enabled = self.mock_object(
            self.mock_dest_client, 'enable_volume_compression_async')

        self.assertRaises(na_utils.NetAppDriverException,
                          self.dm_mixin.create_destination_flexvol,
                          self.src_backend, self.dest_backend,
                          self.src_flexvol_name, self.dest_flexvol_name,
                          pool_is_flexgroup=True)

        expected_prov_opts.pop('dedupe_enabled')
        expected_prov_opts.pop('compression_enabled')
        mock_create_volume_async.assert_called_once_with(
            self.dest_flexvol_name,
            ['aggr01'],
            fakes.PROVISIONING_OPTS['size'],
            volume_type='dp', **expected_prov_opts)
        mock_volume_state.assert_called_with(
            flexvol_name=self.dest_flexvol_name)
        mock_dedupe_enabled.assert_not_called()
        mock_compression_enabled.assert_not_called()

    @ddt.data('flexvol', 'flexgroup')
    def test_create_destination_flexvol(self, volume_style):
        aggr_map = {
            fakes.PROVISIONING_OPTS['aggregate'][0]: 'aggr01',
            'aggr20': 'aggr02',
        }
        provisioning_opts = copy.deepcopy(fakes.PROVISIONING_OPTS)
        expected_prov_opts = copy.deepcopy(fakes.PROVISIONING_OPTS)
        expected_prov_opts.pop('volume_type', None)
        expected_prov_opts.pop('size', None)
        expected_prov_opts.pop('aggregate', None)
        expected_prov_opts.pop('is_flexgroup', None)
        mock_get_provisioning_opts_call = self.mock_object(
            self.mock_src_client, 'get_provisioning_options_from_flexvol',
            return_value=provisioning_opts)
        mock_is_flexvol_encrypted = self.mock_object(
            self.mock_src_client, 'is_flexvol_encrypted',
            return_value=False)
        self.mock_object(self.dm_mixin, '_get_replication_aggregate_map',
                         return_value=aggr_map)

        pool_is_flexgroup = False
        if volume_style == 'flexgroup':
            pool_is_flexgroup = True
            self.mock_object(self.dm_mixin,
                             '_get_replication_volume_online_timeout',
                             return_value=2)
            mock_create_volume_async = self.mock_object(self.mock_dest_client,
                                                        'create_volume_async')
            mock_volume_state = self.mock_object(self.mock_dest_client,
                                                 'get_volume_state',
                                                 return_value='online')
            mock_dedupe_enabled = self.mock_object(
                self.mock_dest_client, 'enable_volume_dedupe_async')
            mock_compression_enabled = self.mock_object(
                self.mock_dest_client, 'enable_volume_compression_async')
        else:
            mock_create_flexvol = self.mock_object(self.mock_dest_client,
                                                   'create_flexvol')

        retval = self.dm_mixin.create_destination_flexvol(
            self.src_backend, self.dest_backend,
            self.src_flexvol_name, self.dest_flexvol_name,
            pool_is_flexgroup=pool_is_flexgroup)

        self.assertIsNone(retval)
        mock_get_provisioning_opts_call.assert_called_once_with(
            self.src_flexvol_name)
        self.dm_mixin._get_replication_aggregate_map.assert_called_once_with(
            self.src_backend, self.dest_backend)

        if volume_style == 'flexgroup':
            expected_prov_opts.pop('dedupe_enabled')
            expected_prov_opts.pop('compression_enabled')
            mock_create_volume_async.assert_called_once_with(
                self.dest_flexvol_name,
                ['aggr01'],
                fakes.PROVISIONING_OPTS['size'],
                volume_type='dp', **expected_prov_opts)
            mock_volume_state.assert_called_once_with(
                flexvol_name=self.dest_flexvol_name)
            mock_dedupe_enabled.assert_called_once_with(
                self.dest_flexvol_name)
            mock_compression_enabled.assert_called_once_with(
                self.dest_flexvol_name)
        else:
            mock_create_flexvol.assert_called_once_with(
                self.dest_flexvol_name,
                'aggr01',
                fakes.PROVISIONING_OPTS['size'],
                volume_type='dp', **expected_prov_opts)

        mock_is_flexvol_encrypted.assert_called_once_with(
            self.src_flexvol_name, self.src_vserver)

    def test_create_encrypted_destination_flexvol(self):
        aggr_map = {
            fakes.ENCRYPTED_PROVISIONING_OPTS['aggregate'][0]: 'aggr01',
            'aggr20': 'aggr02',
        }
        provisioning_opts = copy.deepcopy(fakes.ENCRYPTED_PROVISIONING_OPTS)
        expected_prov_opts = copy.deepcopy(fakes.ENCRYPTED_PROVISIONING_OPTS)
        expected_prov_opts.pop('volume_type', None)
        expected_prov_opts.pop('size', None)
        expected_prov_opts.pop('aggregate', None)
        expected_prov_opts.pop('is_flexgroup', None)
        mock_get_provisioning_opts_call = self.mock_object(
            self.mock_src_client, 'get_provisioning_options_from_flexvol',
            return_value=provisioning_opts)
        mock_is_flexvol_encrypted = self.mock_object(
            self.mock_src_client, 'is_flexvol_encrypted',
            return_value=True)
        self.mock_object(self.dm_mixin, '_get_replication_aggregate_map',
                         return_value=aggr_map)
        mock_client_call = self.mock_object(
            self.mock_dest_client, 'create_flexvol')

        retval = self.dm_mixin.create_destination_flexvol(
            self.src_backend, self.dest_backend,
            self.src_flexvol_name, self.dest_flexvol_name)

        self.assertIsNone(retval)
        mock_get_provisioning_opts_call.assert_called_once_with(
            self.src_flexvol_name)
        self.dm_mixin._get_replication_aggregate_map.assert_called_once_with(
            self.src_backend, self.dest_backend)
        mock_client_call.assert_called_once_with(
            self.dest_flexvol_name, 'aggr01',
            fakes.ENCRYPTED_PROVISIONING_OPTS['size'],
            volume_type='dp', **expected_prov_opts)
        mock_is_flexvol_encrypted.assert_called_once_with(
            self.src_flexvol_name, self.src_vserver)

    def test_ensure_snapmirrors(self):
        flexvols = ['nvol1', 'nvol2']
        replication_backends = ['fallback1', 'fallback2']
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=replication_backends)
        self.mock_object(self.dm_mixin, 'create_snapmirror')
        expected_calls = [
            mock.call(self.src_backend, replication_backends[0],
                      flexvols[0], flexvols[0]),
            mock.call(self.src_backend, replication_backends[0],
                      flexvols[1], flexvols[1]),
            mock.call(self.src_backend, replication_backends[1],
                      flexvols[0], flexvols[0]),
            mock.call(self.src_backend, replication_backends[1],
                      flexvols[1], flexvols[1]),
        ]

        retval = self.dm_mixin.ensure_snapmirrors(self.mock_src_config,
                                                  self.src_backend,
                                                  flexvols)

        self.assertIsNone(retval)
        self.dm_mixin.get_replication_backend_names.assert_called_once_with(
            self.mock_src_config)
        self.dm_mixin.create_snapmirror.assert_has_calls(expected_calls)

    def test_ensure_snapmirrors_number_of_tries_exceeded(self):
        flexvols = ['nvol1']
        replication_backends = ['fallback1']
        mock_error_log = self.mock_object(data_motion.LOG, 'error')
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=replication_backends)
        self.mock_object(self.dm_mixin, 'create_snapmirror',
                         side_effect=na_utils.GeometryHasChangedOnDestination)

        self.assertRaises(na_utils.GeometryHasChangedOnDestination,
                          self.dm_mixin.ensure_snapmirrors,
                          self.mock_src_config,
                          self.src_backend,
                          flexvols)

        self.dm_mixin.get_replication_backend_names.assert_called_once_with(
            self.mock_src_config)

        excepted_call = mock.call(
            self.src_backend, replication_backends[0],
            flexvols[0], flexvols[0])
        self.dm_mixin.create_snapmirror.assert_has_calls([
            excepted_call, excepted_call, excepted_call
        ])

        mock_error_log.assert_called()

    def test_break_snapmirrors(self):
        flexvols = ['nvol1', 'nvol2']
        replication_backends = ['fallback1', 'fallback2']
        side_effects = [None, netapp_api.NaApiError, None, None]
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=replication_backends)
        self.mock_object(self.dm_mixin, 'break_snapmirror',
                         side_effect=side_effects)
        mock_exc_log = self.mock_object(data_motion.LOG, 'exception')
        expected_calls = [
            mock.call(self.src_backend, replication_backends[0],
                      flexvols[0], flexvols[0]),
            mock.call(self.src_backend, replication_backends[0],
                      flexvols[1], flexvols[1]),
            mock.call(self.src_backend, replication_backends[1],
                      flexvols[0], flexvols[0]),
            mock.call(self.src_backend, replication_backends[1],
                      flexvols[1], flexvols[1]),
        ]

        failed_to_break = self.dm_mixin.break_snapmirrors(
            self.mock_src_config, self.src_backend, flexvols, 'fallback1')

        self.assertEqual(1, len(failed_to_break))
        self.assertEqual(1, mock_exc_log.call_count)
        self.dm_mixin.get_replication_backend_names.assert_called_once_with(
            self.mock_src_config)
        self.dm_mixin.break_snapmirror.assert_has_calls(expected_calls)

    def test_update_snapmirrors(self):
        flexvols = ['nvol1', 'nvol2']
        replication_backends = ['fallback1', 'fallback2']
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=replication_backends)
        side_effects = [None, netapp_api.NaApiError, None, None]
        self.mock_object(self.dm_mixin, 'update_snapmirror',
                         side_effect=side_effects)
        expected_calls = [
            mock.call(self.src_backend, replication_backends[0],
                      flexvols[0], flexvols[0]),
            mock.call(self.src_backend, replication_backends[0],
                      flexvols[1], flexvols[1]),
            mock.call(self.src_backend, replication_backends[1],
                      flexvols[0], flexvols[0]),
            mock.call(self.src_backend, replication_backends[1],
                      flexvols[1], flexvols[1]),
        ]

        retval = self.dm_mixin.update_snapmirrors(self.mock_src_config,
                                                  self.src_backend,
                                                  flexvols)

        self.assertIsNone(retval)
        self.dm_mixin.get_replication_backend_names.assert_called_once_with(
            self.mock_src_config)
        self.dm_mixin.update_snapmirror.assert_has_calls(expected_calls)

    @ddt.data([{'destination-volume': 'nvol3', 'lag-time': '3223'},
               {'destination-volume': 'nvol5', 'lag-time': '32'}],
              [])
    def test__choose_failover_target_no_failover_targets(self, snapmirrors):
        flexvols = ['nvol1', 'nvol2']
        replication_backends = ['fallback1', 'fallback2']
        mock_debug_log = self.mock_object(data_motion.LOG, 'debug')
        self.mock_object(self.dm_mixin, 'get_snapmirrors',
                         return_value=snapmirrors)

        target = self.dm_mixin._choose_failover_target(
            self.src_backend, flexvols, replication_backends)

        self.assertIsNone(target)
        self.assertEqual(2, mock_debug_log.call_count)

    def test__choose_failover_target(self):
        flexvols = ['nvol1', 'nvol2']
        replication_backends = ['fallback1', 'fallback2']
        target_1_snapmirrors = [
            {'destination-volume': 'nvol3', 'lag-time': '12'},
            {'destination-volume': 'nvol1', 'lag-time': '1541'},
            {'destination-volume': 'nvol2', 'lag-time': '16'},
        ]
        target_2_snapmirrors = [
            {'destination-volume': 'nvol2', 'lag-time': '717'},
            {'destination-volume': 'nvol1', 'lag-time': '323'},
            {'destination-volume': 'nvol3', 'lag-time': '720'},
        ]
        mock_debug_log = self.mock_object(data_motion.LOG, 'debug')
        self.mock_object(self.dm_mixin, 'get_snapmirrors',
                         side_effect=[target_1_snapmirrors,
                                      target_2_snapmirrors])

        target = self.dm_mixin._choose_failover_target(
            self.src_backend, flexvols, replication_backends)

        self.assertEqual('fallback2', target)
        self.assertFalse(mock_debug_log.called)

    def test__failover_host_no_suitable_target(self):
        flexvols = ['nvol1', 'nvol2']
        replication_backends = ['fallback1', 'fallback2']
        self.mock_object(self.dm_mixin, '_choose_failover_target',
                         return_value=None)
        self.mock_object(utils, 'get_backend_configuration')
        self.mock_object(self.dm_mixin, 'update_snapmirrors')
        self.mock_object(self.dm_mixin, 'break_snapmirrors')

        self.assertRaises(na_utils.NetAppDriverException,
                          self.dm_mixin._complete_failover,
                          self.src_backend, replication_backends, flexvols,
                          [], failover_target=None)
        self.assertFalse(utils.get_backend_configuration.called)
        self.assertFalse(self.dm_mixin.update_snapmirrors.called)
        self.assertFalse(self.dm_mixin.break_snapmirrors.called)

    @ddt.data('fallback1', None)
    def test__failover_host(self, failover_target):
        flexvols = ['nvol1', 'nvol2', 'nvol3']
        replication_backends = ['fallback1', 'fallback2']
        volumes = [
            {'id': 'xyzzy', 'host': 'openstack@backend1#nvol1'},
            {'id': 'foobar', 'host': 'openstack@backend1#nvol2'},
            {'id': 'waldofred', 'host': 'openstack@backend1#nvol3'},
        ]
        expected_volume_updates = [
            {
                'volume_id': 'xyzzy',
                'updates': {'replication_status': 'failed-over'},
            },
            {
                'volume_id': 'foobar',
                'updates': {'replication_status': 'failed-over'},
            },
            {
                'volume_id': 'waldofred',
                'updates': {'replication_status': 'error'},
            },
        ]
        expected_active_backend_name = failover_target or 'fallback2'
        self.mock_object(self.dm_mixin, '_choose_failover_target',
                         return_value='fallback2')
        self.mock_object(utils, 'get_backend_configuration')
        self.mock_object(self.dm_mixin, 'update_snapmirrors')
        self.mock_object(self.dm_mixin, 'break_snapmirrors',
                         return_value=['nvol3'])

        actual_active_backend_name, actual_volume_updates = (
            self.dm_mixin._complete_failover(
                self.src_backend, replication_backends, flexvols,
                volumes, failover_target=failover_target)
        )

        self.assertEqual(expected_active_backend_name,
                         actual_active_backend_name)
        self.assertEqual(expected_volume_updates, actual_volume_updates)

    def test_migrate_volume_ontap_assisted_is_same_pool(self):
        ctxt = mock.Mock()
        vol_fields = {'id': dataontap_fakes.VOLUME_ID,
                      'host': dataontap_fakes.HOST_STRING}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)
        fake_dest_host = {'host': dataontap_fakes.HOST_STRING}
        self.dm_mixin._migrate_volume_to_pool = mock.Mock()
        mock_migrate_volume_to_pool = self.dm_mixin._migrate_volume_to_pool
        self.dm_mixin._migrate_volume_to_vserver = mock.Mock()
        mock_migrate_volume_to_vserver = (
            self.dm_mixin._migrate_volume_to_vserver)

        migrated, updates = self.dm_mixin.migrate_volume_ontap_assisted(
            fake_vol, fake_dest_host, dataontap_fakes.BACKEND_NAME,
            dataontap_fakes.DEST_VSERVER_NAME)

        mock_migrate_volume_to_pool.assert_not_called()
        mock_migrate_volume_to_vserver.assert_not_called()
        self.assertTrue(migrated)
        self.assertEqual({}, updates)

    def test_migrate_volume_ontap_assisted_same_pool_different_backend(self):
        CONF.set_override('netapp_vserver', dataontap_fakes.DEST_VSERVER_NAME,
                          group=self.dest_backend)
        ctxt = mock.Mock()
        vol_fields = {'id': dataontap_fakes.VOLUME_ID,
                      'host': dataontap_fakes.HOST_STRING}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)
        fake_dest_host = {'host': '%s@%s#%s' % (
            dataontap_fakes.HOST_NAME,
            dataontap_fakes.DEST_BACKEND_NAME,
            dataontap_fakes.POOL_NAME)}
        self.dm_mixin.using_cluster_credentials = True
        self.mock_src_client.get_cluster_name.return_value = (
            dataontap_fakes.CLUSTER_NAME)
        self.mock_dest_client.get_cluster_name.return_value = (
            dataontap_fakes.CLUSTER_NAME)
        self.dm_mixin._migrate_volume_to_pool = mock.Mock()
        mock_migrate_volume_to_pool = self.dm_mixin._migrate_volume_to_pool
        self.dm_mixin._migrate_volume_to_vserver = mock.Mock()
        mock_migrate_volume_to_vserver = (
            self.dm_mixin._migrate_volume_to_vserver)

        migrated, updates = self.dm_mixin.migrate_volume_ontap_assisted(
            fake_vol, fake_dest_host, dataontap_fakes.BACKEND_NAME,
            dataontap_fakes.DEST_VSERVER_NAME)

        utils.get_backend_configuration.assert_called_once_with(
            dataontap_fakes.DEST_BACKEND_NAME)
        utils.get_client_for_backend.has_calls(
            [mock.call(dataontap_fakes.DEST_BACKEND_NAME),
             mock.call(dataontap_fakes.BACKEND_NAME)])
        self.mock_src_client.get_cluster_name.assert_called()
        self.mock_dest_client.get_cluster_name.assert_called()
        mock_migrate_volume_to_pool.assert_not_called()
        mock_migrate_volume_to_vserver.assert_not_called()
        self.assertTrue(migrated)
        self.assertEqual({}, updates)

    def test_migrate_volume_ontap_assisted_invalid_creds(self):
        ctxt = mock.Mock()
        vol_fields = {'id': dataontap_fakes.VOLUME_ID,
                      'host': dataontap_fakes.HOST_STRING}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)
        fake_dest_host = {'host': dataontap_fakes.DEST_HOST_STRING}
        self.dm_mixin.using_cluster_credentials = False
        self.mock_dest_config.netapp_vserver = dataontap_fakes.VSERVER_NAME
        self.dm_mixin._migrate_volume_to_pool = mock.Mock()
        mock_migrate_volume_to_pool = self.dm_mixin._migrate_volume_to_pool
        self.dm_mixin._migrate_volume_to_vserver = mock.Mock()
        mock_migrate_volume_to_vserver = (
            self.dm_mixin._migrate_volume_to_vserver)

        migrated, updates = self.dm_mixin.migrate_volume_ontap_assisted(
            fake_vol, fake_dest_host, dataontap_fakes.BACKEND_NAME,
            dataontap_fakes.DEST_VSERVER_NAME)

        utils.get_backend_configuration.assert_not_called()
        utils.get_client_for_backend.assert_not_called()
        self.mock_src_client.get_cluster_name.assert_not_called()
        self.mock_dest_client.get_cluster_name.assert_not_called()
        mock_migrate_volume_to_pool.assert_not_called()
        mock_migrate_volume_to_vserver.assert_not_called()
        self.assertFalse(migrated)
        self.assertEqual({}, updates)

    def test_migrate_volume_ontap_assisted_dest_pool_not_in_same_cluster(self):
        CONF.set_override('netapp_vserver', dataontap_fakes.DEST_VSERVER_NAME,
                          group=self.dest_backend)
        ctxt = mock.Mock()
        vol_fields = {'id': dataontap_fakes.VOLUME_ID,
                      'host': dataontap_fakes.HOST_STRING}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)
        fake_dest_host = {'host': dataontap_fakes.DEST_HOST_STRING}
        self.dm_mixin.using_cluster_credentials = True
        self.mock_src_client.get_cluster_name.return_value = (
            dataontap_fakes.CLUSTER_NAME)
        self.mock_dest_client.get_cluster_name.return_value = (
            dataontap_fakes.DEST_CLUSTER_NAME)
        self.dm_mixin._migrate_volume_to_pool = mock.Mock()
        mock_migrate_volume_to_pool = self.dm_mixin._migrate_volume_to_pool
        self.dm_mixin._migrate_volume_to_vserver = mock.Mock()
        mock_migrate_volume_to_vserver = (
            self.dm_mixin._migrate_volume_to_vserver)

        migrated, updates = self.dm_mixin.migrate_volume_ontap_assisted(
            fake_vol, fake_dest_host, dataontap_fakes.BACKEND_NAME,
            dataontap_fakes.DEST_VSERVER_NAME)

        utils.get_backend_configuration.assert_called_once_with(
            dataontap_fakes.DEST_BACKEND_NAME)
        utils.get_client_for_backend.has_calls(
            [mock.call(dataontap_fakes.DEST_BACKEND_NAME),
             mock.call(dataontap_fakes.BACKEND_NAME)])
        self.mock_src_client.get_cluster_name.assert_called()
        self.mock_dest_client.get_cluster_name.assert_called()
        mock_migrate_volume_to_pool.assert_not_called()
        mock_migrate_volume_to_vserver.assert_not_called()
        self.assertFalse(migrated)
        self.assertEqual({}, updates)

    @ddt.data((dataontap_fakes.BACKEND_NAME, True),
              (dataontap_fakes.DEST_BACKEND_NAME, False))
    @ddt.unpack
    def test_migrate_volume_ontap_assisted_same_vserver(self,
                                                        dest_backend_name,
                                                        is_same_backend):
        CONF.set_override('netapp_vserver', dataontap_fakes.VSERVER_NAME,
                          group=self.dest_backend)
        ctxt = mock.Mock()
        vol_fields = {'id': dataontap_fakes.VOLUME_ID,
                      'host': dataontap_fakes.HOST_STRING}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)
        fake_dest_host = {'host': '%s@%s#%s' % (
            dataontap_fakes.HOST_NAME,
            dest_backend_name,
            dataontap_fakes.DEST_POOL_NAME)}
        self.dm_mixin.using_cluster_credentials = True
        self.mock_src_client.get_cluster_name.return_value = (
            dataontap_fakes.CLUSTER_NAME)
        self.mock_dest_client.get_cluster_name.return_value = (
            dataontap_fakes.CLUSTER_NAME)
        self.dm_mixin._migrate_volume_to_pool = mock.Mock()
        mock_migrate_volume_to_pool = self.dm_mixin._migrate_volume_to_pool
        mock_migrate_volume_to_pool.return_value = {}
        self.dm_mixin._migrate_volume_to_vserver = mock.Mock()
        mock_migrate_volume_to_vserver = (
            self.dm_mixin._migrate_volume_to_vserver)

        migrated, updates = self.dm_mixin.migrate_volume_ontap_assisted(
            fake_vol, fake_dest_host, dataontap_fakes.BACKEND_NAME,
            dataontap_fakes.VSERVER_NAME)

        if is_same_backend:
            utils.get_backend_configuration.assert_not_called()
            utils.get_client_for_backend.assert_not_called()
            self.mock_src_client.get_cluster_name.assert_not_called()
            self.mock_dest_client.get_cluster_name.assert_not_called()
        else:
            utils.get_backend_configuration.assert_called_once_with(
                dest_backend_name)
            utils.get_client_for_backend.has_calls(
                [mock.call(dest_backend_name),
                 mock.call(dataontap_fakes.BACKEND_NAME)])
            self.mock_src_client.get_cluster_name.assert_called()
            self.mock_dest_client.get_cluster_name.assert_called()

        mock_migrate_volume_to_pool.assert_called_once_with(
            fake_vol, dataontap_fakes.POOL_NAME,
            dataontap_fakes.DEST_POOL_NAME,
            dataontap_fakes.VSERVER_NAME,
            dest_backend_name)
        mock_migrate_volume_to_vserver.assert_not_called()
        self.assertTrue(migrated)
        self.assertEqual({}, updates)

    def test_migrate_volume_different_vserver(self):
        CONF.set_override('netapp_vserver', dataontap_fakes.DEST_VSERVER_NAME,
                          group=self.dest_backend)
        ctxt = mock.Mock()
        vol_fields = {'id': dataontap_fakes.VOLUME_ID,
                      'host': dataontap_fakes.HOST_STRING}
        fake_vol = fake_volume.fake_volume_obj(ctxt, **vol_fields)
        fake_dest_host = {'host': dataontap_fakes.DEST_HOST_STRING}
        self.dm_mixin.using_cluster_credentials = True
        self.mock_src_client.get_cluster_name.return_value = (
            dataontap_fakes.CLUSTER_NAME)
        self.mock_dest_client.get_cluster_name.return_value = (
            dataontap_fakes.CLUSTER_NAME)
        self.dm_mixin._migrate_volume_to_pool = mock.Mock()
        mock_migrate_volume_to_pool = self.dm_mixin._migrate_volume_to_pool
        self.dm_mixin._migrate_volume_to_vserver = mock.Mock()
        mock_migrate_volume_to_vserver = (
            self.dm_mixin._migrate_volume_to_vserver)
        mock_migrate_volume_to_vserver.return_value = {}

        migrated, updates = self.dm_mixin.migrate_volume_ontap_assisted(
            fake_vol, fake_dest_host, dataontap_fakes.BACKEND_NAME,
            dataontap_fakes.VSERVER_NAME)

        utils.get_backend_configuration.assert_called_once_with(
            dataontap_fakes.DEST_BACKEND_NAME)
        utils.get_client_for_backend.has_calls(
            [mock.call(dataontap_fakes.DEST_BACKEND_NAME),
             mock.call(dataontap_fakes.BACKEND_NAME)])
        self.mock_src_client.get_cluster_name.assert_called()
        self.mock_dest_client.get_cluster_name.assert_called()
        mock_migrate_volume_to_pool.assert_not_called()
        mock_migrate_volume_to_vserver.assert_called_once_with(
            fake_vol, dataontap_fakes.POOL_NAME, dataontap_fakes.VSERVER_NAME,
            dataontap_fakes.DEST_POOL_NAME, dataontap_fakes.DEST_VSERVER_NAME,
            dataontap_fakes.DEST_BACKEND_NAME)
        self.assertTrue(migrated)
        self.assertEqual({}, updates)
