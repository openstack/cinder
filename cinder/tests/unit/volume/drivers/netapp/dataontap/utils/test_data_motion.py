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

from cinder import exception
from cinder.objects import fields
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as \
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
        self.src_cg = None
        self.dest_cg = None
        self.active_sync_policy = False
        self.replication_policy = 'MirrorAllSnapshots'
        self.mock_src_client = mock.Mock()
        self.mock_dest_client = mock.Mock()
        self.config = fakes.get_fake_cmode_config(self.src_backend)
        self.mock_object(utils, 'get_backend_configuration',
                         side_effect=[self.mock_dest_config,
                                      self.mock_src_config])
        self.mock_object(utils, 'get_client_for_backend',
                         side_effect=[self.mock_dest_client,
                                      self.mock_src_client])

        # Mock StorageObjectType since it's not defined in na_utils
        storage_object_type_mock = mock.Mock()
        storage_object_type_mock.VOLUME = 'volume'
        self.storage_type_patcher = mock.patch.object(
            na_utils, 'StorageObjectType', storage_object_type_mock,
            create=True)
        self.storage_type_patcher.start()
        self.addCleanup(self.storage_type_patcher.stop)

        # Mock create_cg_path function
        self.cg_path_patcher = mock.patch.object(
            na_utils, 'create_cg_path',
            lambda cg_name: f'/cg/{cg_name}', create=True)
        self.cg_path_patcher.start()
        self.addCleanup(self.cg_path_patcher.stop)

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
            config.append_config_values(na_opts.netapp_certificateauth_opts)
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

    @ddt.data(
        {'backend_names': [], 'active_sync': False},
        {'backend_names': ['backend1'], 'active_sync': False},
        {'backend_names': ['backend1', 'backend2'], 'active_sync': False},
        {'backend_names': ['backend1'], 'active_sync': True},
        {'backend_names': ['backend1', 'backend2'], 'active_sync': True},
    )
    @ddt.unpack
    def test_get_replication_backend_stats(self, backend_names, active_sync):
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=backend_names)
        self.mock_object(self.dm_mixin, 'is_active_sync_configured',
                         return_value=active_sync)
        expected_replication_type = 'sync' if active_sync else 'async'
        enabled_stats = {
            'replication_count': len(backend_names),
            'replication_targets': backend_names,
            'replication_type': expected_replication_type,
        }
        expected_stats = {
            'replication_enabled': len(backend_names) > 0,
        }
        if len(backend_names) > 0:
            expected_stats.update(enabled_stats)

        actual_stats = self.dm_mixin.get_replication_backend_stats(self.config)

        self.assertDictEqual(expected_stats, actual_stats)

    @ddt.data(
        {'configured_policy': 'AutomatedFailOver',
         'expected': 'AutomatedFailOver'},
        {'configured_policy': 'MirrorAllSnapshots',
         'expected': 'MirrorAllSnapshots'},
        {'configured_policy': None, 'expected': 'MirrorAllSnapshots'},
    )
    @ddt.unpack
    def test_get_replication_policy(self, configured_policy, expected):
        CONF.set_override('netapp_replication_policy', configured_policy,
                          group=self.src_backend)
        result = self.dm_mixin.get_replication_policy(self.config)
        self.assertEqual(expected, result)

    @ddt.data(
        {'policy': 'AutomatedFailOver', 'expected': True},
        {'policy': 'AutomatedFailOverDuplex', 'expected': True},
        {'policy': 'Asynchronous', 'expected': False},
        {'policy': 'MirrorAllSnapshots', 'expected': False},
    )
    @ddt.unpack
    def test_is_active_sync_asymmetric_policy(self, policy, expected):
        result = self.dm_mixin.is_active_sync_asymmetric_policy(policy)
        self.assertEqual(expected, result)

    def test_validate_no_conflicting_snapmirrors_no_replication(self):
        """Test validation passes when no replication configured."""
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=[])

        # Should return without error
        self.dm_mixin.validate_no_conflicting_snapmirrors(
            self.config, self.src_backend, ['vol1', 'vol2'])

    def test_validate_no_conflicting_snapmirrors_no_existing_mirrors(self):
        """Test validation passes when no SnapMirrors exist."""
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=[self.dest_backend])
        self.mock_object(utils, 'get_backend_configuration',
                         side_effect=[self.mock_src_config,
                                      self.mock_dest_config])
        self.mock_object(utils, 'get_client_for_backend',
                         return_value=self.mock_src_client)
        self.mock_src_client.get_snapmirrors.return_value = []

        # Should return without error
        self.dm_mixin.validate_no_conflicting_snapmirrors(
            self.config, self.src_backend, ['vol1', 'vol2'])

        self.assertEqual(2, self.mock_src_client.get_snapmirrors.call_count)

    def test_validate_no_conflicting_snapmirrors_cinder_naming_match(self):
        """Test validation passes when existing mirrors match Cinder naming."""
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=[self.dest_backend])
        self.mock_object(utils, 'get_backend_configuration',
                         side_effect=[self.mock_src_config,
                                      self.mock_dest_config])
        self.mock_object(utils, 'get_client_for_backend',
                         return_value=self.mock_src_client)

        # SnapMirror with matching volume names (Cinder convention)
        existing_mirror = [{
            'destination-vserver': self.dest_vserver,
            'destination-volume': 'vol1',  # Same as source
            'mirror-state': 'snapmirrored'
        }]
        self.mock_src_client.get_snapmirrors.return_value = existing_mirror

        # Should return without error
        self.dm_mixin.validate_no_conflicting_snapmirrors(
            self.config, self.src_backend, ['vol1'])

    def test_validate_no_conflicting_snapmirrors_manual_different_name(
            self):
        """Test validation when manual mirrors have different dest names.

        Test validation fails when manual mirrors have different dest names.
        """
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=[self.dest_backend])
        self.mock_object(utils, 'get_backend_configuration',
                         side_effect=[self.mock_src_config,
                                      self.mock_dest_config])
        self.mock_object(utils, 'get_client_for_backend',
                         return_value=self.mock_src_client)

        # SnapMirror with DIFFERENT destination name (manual/brownfield)
        existing_mirror = [{
            'destination-vserver': self.dest_vserver,
            'destination-volume': 'manually_created_dest',  # Different!
            'mirror-state': 'snapmirrored'
        }]
        self.mock_src_client.get_snapmirrors.return_value = existing_mirror

        # Should raise NetAppDriverException
        self.assertRaises(
            na_utils.NetAppDriverException,
            self.dm_mixin.validate_no_conflicting_snapmirrors,
            self.config, self.src_backend, ['vol1'])

    def test_validate_no_conflicting_snapmirrors_api_error_continues(self):
        """Test validation continues when API error occurs querying mirrors."""
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=[self.dest_backend])
        self.mock_object(utils, 'get_backend_configuration',
                         side_effect=[self.mock_src_config,
                                      self.mock_dest_config])
        self.mock_object(utils, 'get_client_for_backend',
                         return_value=self.mock_src_client)

        # API error should not block validation
        self.mock_src_client.get_snapmirrors.side_effect = (
            netapp_api.NaApiError(code=13005, message='Permission denied'))

        # Should return without error (logged as warning)
        self.dm_mixin.validate_no_conflicting_snapmirrors(
            self.config, self.src_backend, ['vol1'])

    def test_validate_no_conflicting_snapmirrors_unconfigured_vserver(self):
        """Test validation handles mirrors to unconfigured vservers."""
        self.mock_object(self.dm_mixin, 'get_replication_backend_names',
                         return_value=[self.dest_backend])
        self.mock_object(utils, 'get_backend_configuration',
                         side_effect=[self.mock_src_config,
                                      self.mock_dest_config])
        self.mock_object(utils, 'get_client_for_backend',
                         return_value=self.mock_src_client)

        # SnapMirror to unconfigured vserver but Cinder naming
        existing_mirror = [{
            'destination-vserver': 'unconfigured_vserver',
            'destination-volume': 'vol1',  # Matches Cinder naming
            'mirror-state': 'snapmirrored'
        }]
        self.mock_src_client.get_snapmirrors.return_value = existing_mirror

        self.dm_mixin.validate_no_conflicting_snapmirrors(
            self.config, self.src_backend, ['vol1'])

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
                                        self.dest_flexvol_name,
                                        self.replication_policy)

        if not dest_exists:
            create_destination_flexvol.assert_called_once_with(
                self.src_backend, self.dest_backend, self.src_flexvol_name,
                self.dest_flexvol_name, pool_is_flexgroup=is_flexgroup)
        else:
            self.assertFalse(create_destination_flexvol.called)
        # With the fix for error 13001, relationship_type is always XDP now
        mock_dest_client.create_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name,
            None,
            None,
            schedule='hourly',
            policy=self.replication_policy,
            relationship_type='extended_data_protection')
        mock_dest_client.initialize_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, self.active_sync_policy)

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
                          self.dest_flexvol_name,
                          self.replication_policy)

        self.assertFalse(create_destination_flexvol.called)
        mock_dest_client.create_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, None, None,
            schedule='hourly', policy=self.replication_policy,
            relationship_type='extended_data_protection')

        mock_dest_client.initialize_snapmirror.assert_called_once_with(
            self.src_vserver, self.src_flexvol_name, self.dest_vserver,
            self.dest_flexvol_name, self.active_sync_policy)

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
                                        self.dest_flexvol_name,
                                        self.replication_policy)

        self.assertFalse(mock_dest_client.create_snapmirror.called)
        self.assertFalse(mock_dest_client.initialize_snapmirror.called)
        self.assertFalse(self.dm_mixin.create_destination_flexvol.called)
        if mirror_state == 'snapmirrored':
            self.assertFalse(mock_dest_client.resume_snapmirror.called)
        else:
            mock_dest_client.resume_snapmirror.assert_called_once_with(
                self.src_vserver, self.src_flexvol_name,
                self.dest_vserver, self.dest_flexvol_name)

    def test_create_snapmirror_snapmirror_exists_repair_exception(self):
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
        self.mock_object(mock_dest_client, 'resume_snapmirror',
                         side_effect=netapp_api.NaApiError)

        self.dm_mixin.create_snapmirror(self.src_backend,
                                        self.dest_backend,
                                        self.src_flexvol_name,
                                        self.dest_flexvol_name,
                                        self.replication_policy)

        self.assertFalse(mock_dest_client.create_snapmirror.called)
        self.assertFalse(mock_dest_client.initialize_snapmirror.called)
        self.assertFalse(self.dm_mixin.create_destination_flexvol.called)
        mock_dest_client.resume_snapmirror.assert_called_once_with(
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
        self.dm_mixin.configuration = self.config
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
        self.dm_mixin.configuration = self.config
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
            return_value={'size': size, 'aggregate': ['aggr1'],
                          'is_flexgroup': is_flexgroup})
        self.mock_object(self.dm_mixin, '_get_replication_aggregate_map',
                         return_value=aggr_map)
        self.mock_object(self.dm_mixin,
                         '_get_replication_volume_online_timeout',
                         return_value=2)
        self.mock_object(self.mock_dest_client,
                         'get_volume_state',
                         return_value='online')
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
    @mock.patch('oslo_service.loopingcall.FixedIntervalWithTimeoutLoopingCall',
                new=test_utils.ZeroIntervalWithTimeoutLoopingCall)
    def test_create_destination_flexgroup_online_timeout(self, volume_state):
        aggr_map = {
            fakes.PROVISIONING_OPTS_FLEXGROUP['aggregate'][0]: 'aggr01',
            'aggr20': 'aggr02',
        }
        provisioning_opts = copy.deepcopy(fakes.PROVISIONING_OPTS_FLEXGROUP)
        expected_prov_opts = copy.deepcopy(fakes.PROVISIONING_OPTS_FLEXGROUP)
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
            fakes.PROVISIONING_OPTS_FLEXGROUP['size'],
            volume_type='dp', **expected_prov_opts)
        mock_volume_state.assert_called_with(
            name=self.dest_flexvol_name)
        mock_dedupe_enabled.assert_not_called()
        mock_compression_enabled.assert_not_called()

    @ddt.data('flexvol', 'flexgroup')
    def test_create_destination_flexvol(self, volume_style):
        provisioning_opts = copy.deepcopy(fakes.PROVISIONING_OPTS)
        aggr_map = {
            provisioning_opts['aggregate'][0]: 'aggr01',
            'aggr20': 'aggr02',
        }
        expected_prov_opts = copy.deepcopy(provisioning_opts)
        expected_prov_opts.pop('volume_type', None)
        expected_prov_opts.pop('size', None)
        expected_prov_opts.pop('aggregate', None)
        expected_prov_opts.pop('is_flexgroup', None)
        mock_is_flexvol_encrypted = self.mock_object(
            self.mock_src_client, 'is_flexvol_encrypted',
            return_value=False)
        self.mock_object(self.dm_mixin, '_get_replication_aggregate_map',
                         return_value=aggr_map)
        self.mock_object(self.dm_mixin,
                         '_get_replication_volume_online_timeout',
                         return_value=2)
        mock_volume_state = self.mock_object(self.mock_dest_client,
                                             'get_volume_state',
                                             return_value='online')

        pool_is_flexgroup = False
        if volume_style == 'flexgroup':
            pool_is_flexgroup = True
            provisioning_opts = copy.deepcopy(
                fakes.PROVISIONING_OPTS_FLEXGROUP)
            self.mock_object(self.dm_mixin,
                             '_get_replication_volume_online_timeout',
                             return_value=2)
            mock_create_volume_async = self.mock_object(self.mock_dest_client,
                                                        'create_volume_async')
            mock_dedupe_enabled = self.mock_object(
                self.mock_dest_client, 'enable_volume_dedupe_async')
            mock_compression_enabled = self.mock_object(
                self.mock_dest_client, 'enable_volume_compression_async')
        else:
            mock_create_flexvol = self.mock_object(self.mock_dest_client,
                                                   'create_flexvol')

        mock_get_provisioning_opts_call = self.mock_object(
            self.mock_src_client, 'get_provisioning_options_from_flexvol',
            return_value=provisioning_opts)

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
                fakes.PROVISIONING_OPTS_FLEXGROUP['size'],
                volume_type='dp', **expected_prov_opts)
            mock_volume_state.assert_called_once_with(
                name=self.dest_flexvol_name)
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
        self.mock_object(self.dm_mixin,
                         '_get_replication_volume_online_timeout',
                         return_value=2)
        self.mock_object(self.mock_dest_client,
                         'get_volume_state',
                         return_value='online')
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
                      flexvols[0], flexvols[0], self.replication_policy),
            mock.call(self.src_backend, replication_backends[0],
                      flexvols[1], flexvols[1], self.replication_policy),
            mock.call(self.src_backend, replication_backends[1],
                      flexvols[0], flexvols[0], self.replication_policy),
            mock.call(self.src_backend, replication_backends[1],
                      flexvols[1], flexvols[1], self.replication_policy),
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
            flexvols[0], flexvols[0], self.replication_policy)
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

    def test__failover_host_to_same_host(self):
        """Tests failover host to same host throws error"""
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend1"
        volumes = []
        # Assert that an exception is raised
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.dm_mixin._failover_host, volumes, secondary_id)

    def test__failover_host_to_default(self):
        """Tests failover host to default sets the old primary as a """
        """new primary"""
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "default"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.dm_mixin._update_zapi_client = mock.Mock()
        self.get_replication_backend_names = mock.Mock(return_value=
                                                       ["backend1"])

        self.dm_mixin.configuration = self.config

        # Call the method
        result = self.dm_mixin._failover_host(volumes, secondary_id)

        # Assert the expected result
        expected_result = ("backend1",
                           [{'volume_id': 'volume1',
                             'updates': {'replication_status': 'enabled'}}],
                           [])
        self.assertEqual(result, expected_result)
        self.assertTrue(self.dm_mixin._update_zapi_client.called)

    def test__failover_host_to_custom_host(self):
        """Tests failover host to custom host sets the secondary """
        """as a new primary"""
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend2"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.dm_mixin._complete_failover = \
            mock.Mock(return_value=
                      ("backend2", [{'volume_id': 'volume1',
                                     'updates':
                                         {'replication_status': 'enabled'}}]))
        self.dm_mixin._update_zapi_client = mock.Mock()
        self.dm_mixin.configuration = self.config
        self.dm_mixin.get_replication_backend_names = \
            mock.Mock(return_value=["backend1", "backend2"])
        self.mock_object(utils, 'get_backend_configuration')
        volume_list = ['pool1', 'vol1', 'vol2']
        self.dm_mixin.ssc_library = mock.Mock()
        self.mock_object(self.dm_mixin.ssc_library,
                         'get_ssc_flexvol_names', return_value=volume_list)

        # Call the method
        result = self.dm_mixin._failover_host(volumes, secondary_id)

        # Assert the expected result
        expected_result = ("backend2",
                           [{'volume_id': 'volume1',
                             'updates': {'replication_status': 'enabled'}}],
                           [])
        self.assertEqual(result, expected_result)
        self.assertTrue(self.dm_mixin._complete_failover.called)
        self.assertTrue(self.dm_mixin._update_zapi_client.called)

    def test__failover_host_without_replication_targets(self):
        """Tests failover host to a target which doenst exist """
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend2"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.dm_mixin._complete_failover = \
            mock.Mock(return_value=("backend2",
                                    [{'volume_id': 'volume1',
                                      'updates':
                                          {'replication_status': 'enabled'}}]))
        self.dm_mixin._update_zapi_client = mock.Mock()
        self.dm_mixin.configuration = self.config
        self.dm_mixin.get_replication_backend_names = \
            mock.Mock(return_value=[])
        self.mock_object(utils, 'get_backend_configuration')
        self.dm_mixin.host = "host1"
        # Assert that an exception is raised
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.dm_mixin._failover_host, volumes, secondary_id)

    def test__failover_host_secondary_id_not_in_replication_target(self):
        """Tests failover host to custom host whose id is not there  """
        """in replication target list"""
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend3"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.dm_mixin._complete_failover = \
            mock.Mock(return_value=("backend2",
                                    [{'volume_id': 'volume1',
                                      'updates':
                                          {'replication_status': 'enabled'}}]))
        self.dm_mixin._update_zapi_client = mock.Mock()
        self.dm_mixin.configuration = self.config
        self.dm_mixin.get_replication_backend_names = \
            mock.Mock(return_value=["backend1", "backend2"])
        self.mock_object(utils, 'get_backend_configuration')
        self.dm_mixin.host = "host1"

        # Assert that an exception is raised
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.dm_mixin._failover_host, volumes, secondary_id)

    def test__failover_host_no_suitable_target(self):
        """Tests failover host to a host which is not a suitable secondary """
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend2"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.mock_object(data_motion.DataMotionMixin, '_complete_failover',
                         side_effect=na_utils.NetAppDriverException)
        self.dm_mixin.configuration = self.config
        self.dm_mixin.get_replication_backend_names = \
            mock.Mock(return_value=["backend1", "backend2"])
        self.mock_object(utils, 'get_backend_configuration')
        volume_list = ['pool1', 'vol1', 'vol2']
        self.dm_mixin.ssc_library = mock.Mock()
        self.mock_object(self.dm_mixin.ssc_library, 'get_ssc_flexvol_names',
                         return_value=volume_list)

        # Assert that an exception is raised
        self.assertRaises(exception.UnableToFailOver,
                          self.dm_mixin._failover_host, volumes, secondary_id)

    def test__failover_to_same_host(self):
        """Tests failover to same host throws error"""
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend1"
        volumes = []

        # Assert that an exception is raised
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.dm_mixin._failover, 'fake_context',
                          volumes, secondary_id)

    def test__failover_to_default(self):
        """Tests failover to default sets the old primary as a new primary"""
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        self.dm_mixin.configuration = self.config

        secondary_id = "default"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.dm_mixin._update_zapi_client = mock.Mock()
        self.get_replication_backend_names = \
            mock.Mock(return_value=["backend1"])
        # Call the method
        result = self.dm_mixin._failover('fake_context', volumes,
                                         secondary_id)
        # Assert the expected result
        expected_result = ("backend1",
                           [{'volume_id': 'volume1',
                             'updates': {'replication_status': 'enabled'}}],
                           [])
        self.assertEqual(result, expected_result)
        self.assertTrue(self.dm_mixin._update_zapi_client.called)

    def test__failover_to_custom_host(self):
        """Tests failover to custom host sets the secondary """
        """as a new primary"""
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend2"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.dm_mixin._complete_failover = \
            mock.Mock(return_value=("backend2",
                                    [{'volume_id': 'volume1',
                                      'updates':
                                          {'replication_status': 'enabled'}}]))
        self.dm_mixin.configuration = self.config
        self.dm_mixin.get_replication_backend_names = \
            mock.Mock(return_value=["backend1", "backend2"])
        self.mock_object(utils, 'get_backend_configuration')
        volume_list = ['pool1', 'vol1', 'vol2']
        self.dm_mixin.ssc_library = mock.Mock()
        self.mock_object(self.dm_mixin.ssc_library,
                         'get_ssc_flexvol_names', return_value=volume_list)

        # Call the method
        result = self.dm_mixin._failover('fake_context', volumes,
                                         secondary_id)
        # Assert the expected result
        expected_result = ("backend2",
                           [{'volume_id': 'volume1',
                             'updates': {'replication_status': 'enabled'}}],
                           [])
        self.assertEqual(result, expected_result)
        self.assertTrue(self.dm_mixin._complete_failover.called)

    def test__failover_without_replication_targets(self):
        """Tests failover to a target which doenst exist """
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend2"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.dm_mixin._complete_failover = \
            mock.Mock(return_value=("backend2",
                                    [{'volume_id': 'volume1',
                                      'updates':
                                          {'replication_status': 'enabled'}}]))
        self.dm_mixin._update_zapi_client = mock.Mock()
        self.dm_mixin.configuration = self.config
        self.dm_mixin.get_replication_backend_names = \
            mock.Mock(return_value=[])
        self.mock_object(utils, 'get_backend_configuration')
        self.dm_mixin.host = "host1"

        # Assert that an exception is raised
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.dm_mixin._failover, 'fake_context',
                          volumes, secondary_id)

    def test__failover_secondary_id_not_in_replication_target(self):
        """Tests failover to custom host whose id is not there  """
        """in replication target list"""
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend3"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]

        # Mock the necessary methods
        self.dm_mixin._complete_failover = \
            mock.Mock(return_value=("backend2",
                                    [{'volume_id': 'volume1',
                                      'updates':
                                          {'replication_status': 'enabled'}}]))
        self.dm_mixin._update_zapi_client = mock.Mock()
        self.dm_mixin.configuration = self.config
        self.dm_mixin.get_replication_backend_names = \
            mock.Mock(return_value=["backend1", "backend2"])
        self.mock_object(utils, 'get_backend_configuration')
        self.dm_mixin.host = "host1"

        # Assert that an exception is raised
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.dm_mixin._failover, 'fake_context',
                          volumes, secondary_id)

    def test__failover_no_suitable_target(self):
        """Tests failover to a host which is not a suitable secondary """
        # Mock the required attributes
        self.dm_mixin.backend_name = "backend1"
        secondary_id = "backend2"
        volumes = [{'id': 'volume1', 'host': 'backend1#pool1'}]
        self.mock_object(data_motion.DataMotionMixin, '_complete_failover',
                         side_effect=na_utils.NetAppDriverException)
        self.dm_mixin.configuration = self.config
        self.dm_mixin.get_replication_backend_names = \
            mock.Mock(return_value=["backend1", "backend2"])
        self.mock_object(utils, 'get_backend_configuration')
        volume_list = ['pool1', 'vol1', 'vol2']
        self.dm_mixin.ssc_library = mock.Mock()
        self.mock_object(self.dm_mixin.ssc_library,
                         'get_ssc_flexvol_names', return_value=volume_list)
        # Assert that an exception is raised
        self.assertRaises(exception.UnableToFailOver,
                          self.dm_mixin._failover, 'fake_context',
                          volumes, secondary_id)

    def test__complete_failover_no_suitable_target(self):
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
    def test__complete_failover(self, failover_target):
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
        utils.get_client_for_backend.assert_has_calls(
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
        utils.get_client_for_backend.assert_has_calls(
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
            utils.get_client_for_backend.assert_has_calls(
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
        utils.get_client_for_backend.assert_has_calls(
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

    @mock.patch.object(data_motion.DataMotionMixin,
                       '_get_create_snapmirror_for_cg_client')
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_create_snapmirror_for_cg_automated_failover(
            self, mock_get_backend_configuration, mock_get_client_for_backend,
            mock_get_create_snapmirror_for_cg_client
    ):

        src_backend = 'src_backend'
        dst_backend = 'dst_backend'
        src_vserver = 'source_vserver'
        dst_vserver = 'dest_vserver'
        src_cg = 'cg_src'
        dst_cg = 'cg_dst'
        policy = 'AutomatedFailOver'

        mock_get_backend_configuration.side_effect = [
            self.mock_dest_config,  # dest
            self.mock_src_config,  # source
        ]

        dest_client = mock.Mock()
        dest_client.get_snapmirrors.return_value = []
        mock_get_client_for_backend.return_value = dest_client

        create_client = mock.Mock()
        mock_get_create_snapmirror_for_cg_client.return_value = create_client

        self.dm_mixin.create_snapmirror_for_cg(
            src_backend_name=src_backend,
            dest_backend_name=dst_backend,
            src_cg_name=src_cg,
            dest_cg_name=dst_cg,
            storage_object_type='volume',
            storage_object_names=['vol1', 'vol2'],
            replication_policy=policy,
        )

        mock_get_backend_configuration.assert_has_calls([
            mock.call(dst_backend),
            mock.call(src_backend),
        ])
        mock_get_client_for_backend.assert_called_once_with(
            dst_backend, vserver_name=dst_vserver, force_rest=True
        )
        dest_client.get_snapmirrors.assert_called_once_with(
            src_vserver, '/cg/' + src_cg, dst_vserver, '/cg/' + dst_cg
        )
        mock_get_create_snapmirror_for_cg_client.assert_called_once_with(
            dest_client, 'volume'
        )

    @mock.patch.object(data_motion.DataMotionMixin,
                       'create_snapmirror_for_cg')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        '_consistent_replication_precheck_for_af_policy')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_policy')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_backend_names')
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.config_utils,
        'get_backend_configuration')
    def test_ensure_consistent_replication_snapmirrors_af_single_cg_used(
            self, mock_get_backend_configuration, mock_get_client_for_backend,
            mock_get_replication_backend_names, mock_get_replication_policy,
            mock_precheck_automated_failover, mock_create_snapmirror_for_cg):

        src_backend = 'src_backend'
        dst_backend = 'dst_backend'
        src_vserver = 'source_vserver'
        policy = 'AutomatedFailOver'
        storage_object_type = na_utils.StorageObjectType.VOLUME
        storage_object_names = ['vol1', 'vol2']
        existing_cg = 'cg_existing'

        mock_get_replication_backend_names.return_value = [dst_backend]
        mock_get_replication_policy.return_value = policy

        mock_get_backend_configuration.return_value = self.mock_src_config

        src_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [
            {'flexvol_name': 'vol1', 'cg_name': existing_cg},
            {'flexvol_name': 'vol2', 'cg_name': existing_cg},
        ]
        src_client.create_ontap_consistency_group = mock.Mock()
        src_client.expand_ontap_consistency_group = mock.Mock()

        mock_get_client_for_backend.return_value = src_client

        config = mock.Mock()

        self.dm_mixin.ensure_consistent_replication_snapmirrors(
            config=config,
            src_backend_name=src_backend,
            storage_object_type=storage_object_type,
            storage_object_names=storage_object_names,
        )

        mock_get_replication_backend_names.assert_called_once_with(config)
        mock_get_replication_policy.assert_called_once_with(config)

        mock_get_backend_configuration.assert_called_with(src_backend)

        mock_get_client_for_backend.assert_called_once_with(
            src_backend, vserver_name=src_vserver, force_rest=True
        )

        src_client.get_flexvols_cg_info.assert_called_once_with(
            storage_object_names)
        src_client.create_ontap_consistency_group.assert_not_called()

        mock_precheck_automated_failover.assert_called_once_with(
            src_backend, [
                dst_backend], storage_object_type, storage_object_names
        )

        mock_create_snapmirror_for_cg.assert_called_once_with(
            src_backend, dst_backend,
            existing_cg, existing_cg,
            storage_object_type, storage_object_names, policy
        )

    @mock.patch.object(
        data_motion.DataMotionMixin,
        'create_snapmirror_for_cg')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        '_consistent_replication_precheck_for_af_policy')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_policy')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_backend_names')
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.config_utils,
        'get_backend_configuration')
    def test_ensure_consistent_replication_snapmirrors_af_new_cg_create(
            self, mock_get_backend_configuration, mock_get_client_for_backend,
            mock_get_replication_backend_names, mock_get_replication_policy,
            mock_precheck_automated_failover, mock_create_snapmirror_for_cg):

        src_backend = 'src_backend'
        dst_backend = 'dst_backend'
        src_vserver = 'source_vserver'
        policy = 'AutomatedFailOver'
        storage_object_type = na_utils.StorageObjectType.VOLUME
        storage_object_names = ['vol1', 'vol2']

        mock_get_replication_backend_names.return_value = [dst_backend]
        mock_get_replication_policy.return_value = policy
        mock_get_backend_configuration.return_value = self.mock_src_config

        src_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [
            {'flexvol_name': 'vol1', 'cg_name': None},
            {'flexvol_name': 'vol2', 'cg_name': None},
        ]
        src_client.create_ontap_consistency_group = mock.Mock()
        src_client.expand_ontap_consistency_group = mock.Mock()
        mock_get_client_for_backend.return_value = src_client

        config = mock.Mock()

        with (mock.patch.object(data_motion, 'timeutils')
              as mock_timeutils):
            mock_now = mock.Mock()
            mock_now.timestamp.return_value = 1234567890
            mock_timeutils.utcnow.return_value = mock_now

            self.dm_mixin.ensure_consistent_replication_snapmirrors(
                config=config,
                src_backend_name=src_backend,
                storage_object_type=storage_object_type,
                storage_object_names=storage_object_names,
            )

        expected_cg = 'cg_cinder_pool_1234567890'

        src_client.create_ontap_consistency_group.assert_called_once_with(
            src_vserver, storage_object_names, expected_cg
        )

        mock_precheck_automated_failover.assert_called_once_with(
            src_backend, [
                dst_backend], storage_object_type, storage_object_names
        )

        mock_create_snapmirror_for_cg.assert_called_once_with(
            src_backend, dst_backend,
            expected_cg, expected_cg,
            storage_object_type, storage_object_names, policy
        )

    @mock.patch.object(
        data_motion.DataMotionMixin,
        'create_snapmirror_for_cg')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_policy')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_backend_names')
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.config_utils,
        'get_backend_configuration')
    def test_ensure_consistent_replication_async_single_cg_multiple_dest(
            self, mock_get_backend_configuration, mock_get_client_for_backend,
            mock_get_replication_backend_names, mock_get_replication_policy,
            mock_create_snapmirror_for_cg):

        src_backend = 'src_backend'
        dst_backend_1 = 'dst_backend_1'
        dst_backend_2 = 'dst_backend_2'
        policy = 'MirrorAllSnapshots'
        storage_object_type = na_utils.StorageObjectType.VOLUME
        storage_object_names = ['vol1', 'vol2']
        existing_cg = 'cg_existing'

        mock_get_replication_backend_names.return_value = [
            dst_backend_1, dst_backend_2]
        mock_get_replication_policy.return_value = policy
        mock_get_backend_configuration.return_value = self.mock_src_config

        src_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [
            {'flexvol_name': 'vol1', 'cg_name': existing_cg},
            {'flexvol_name': 'vol2', 'cg_name': existing_cg},
        ]
        src_client.create_ontap_consistency_group = mock.Mock()
        src_client.expand_ontap_consistency_group = mock.Mock()
        mock_get_client_for_backend.return_value = src_client

        config = mock.Mock()

        self.dm_mixin.ensure_consistent_replication_snapmirrors(
            config=config,
            src_backend_name=src_backend,
            storage_object_type=storage_object_type,
            storage_object_names=storage_object_names,
        )

        src_client.create_ontap_consistency_group.assert_not_called()

        mock_create_snapmirror_for_cg.assert_has_calls([
            mock.call(src_backend, dst_backend_1,
                      existing_cg, existing_cg,
                      storage_object_type, storage_object_names, policy),
            mock.call(src_backend, dst_backend_2,
                      existing_cg, existing_cg,
                      storage_object_type, storage_object_names, policy),
        ])
        self.assertEqual(2, mock_create_snapmirror_for_cg.call_count)

    @mock.patch.object(
        data_motion.DataMotionMixin,
        'create_snapmirror_for_cg')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_policy')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_backend_names')
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.config_utils,
        'get_backend_configuration')
    def test_ensure_consistent_replication_async_create_cg_with_mult_dest(
            self, mock_get_backend_configuration, mock_get_client_for_backend,
            mock_get_replication_backend_names, mock_get_replication_policy,
            mock_create_snapmirror_for_cg):

        src_backend = 'src_backend'
        dst_backend_1 = 'dst_backend_1'
        dst_backend_2 = 'dst_backend_2'
        src_vserver = 'source_vserver'
        policy = 'MirrorAllSnapshots'
        storage_object_type = na_utils.StorageObjectType.VOLUME
        storage_object_names = ['vol1', 'vol2']

        mock_get_replication_backend_names.return_value = [
            dst_backend_1, dst_backend_2]
        mock_get_replication_policy.return_value = policy
        mock_get_backend_configuration.return_value = self.mock_src_config

        src_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [
            {'flexvol_name': 'vol1', 'cg_name': None},
            {'flexvol_name': 'vol2', 'cg_name': None},
        ]
        src_client.create_ontap_consistency_group = mock.Mock()
        src_client.expand_ontap_consistency_group = mock.Mock()
        mock_get_client_for_backend.return_value = src_client

        config = mock.Mock()

        with (mock.patch.object(data_motion, 'timeutils')
              as mock_timeutils):
            mock_now = mock.Mock()
            mock_now.timestamp.return_value = 1234567890
            mock_timeutils.utcnow.return_value = mock_now

            self.dm_mixin.ensure_consistent_replication_snapmirrors(
                config=config,
                src_backend_name=src_backend,
                storage_object_type=storage_object_type,
                storage_object_names=storage_object_names,
            )

        expected_cg = 'cg_cinder_pool_1234567890'

        src_client.create_ontap_consistency_group.assert_called_once_with(
            src_vserver, storage_object_names, expected_cg
        )

        mock_create_snapmirror_for_cg.assert_has_calls([
            mock.call(src_backend, dst_backend_1,
                      expected_cg, expected_cg,
                      storage_object_type, storage_object_names, policy),
            mock.call(src_backend, dst_backend_2,
                      expected_cg, expected_cg,
                      storage_object_type, storage_object_names, policy),
        ])
        self.assertEqual(2, mock_create_snapmirror_for_cg.call_count)

    @mock.patch.object(
        data_motion.DataMotionMixin,
        '_consistent_replication_precheck_for_af_policy'
    )
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_policy')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_backend_names')
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.config_utils,
        'get_backend_configuration')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'create_snapmirror_for_cg')
    def test_ensure_consistent_replication_snapmirrors_af_precheck_error(
            self, mock_create_snapmirror_for_cg,
            mock_get_backend_configuration,
            mock_get_client_for_backend, mock_get_replication_backend_names,
            mock_get_replication_policy, mock_precheck
    ):
        src_backend = 'src_backend'
        dst_backend = 'dst_backend'
        src_vserver = 'source_vserver'
        policy = 'AutomatedFailOver'
        storage_object_type = na_utils.StorageObjectType.VOLUME
        storage_object_names = ['vol1', 'vol2']

        mock_get_replication_backend_names.return_value = [dst_backend]
        mock_get_replication_policy.return_value = policy

        src_backend_conf = mock.Mock()
        src_backend_conf.netapp_vserver = src_vserver
        mock_get_backend_configuration.return_value = src_backend_conf

        src_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [
            {'flexvol_name': 'vol1', 'cg_name': 'cg_1'},
            {'flexvol_name': 'vol2', 'cg_name': 'cg_1'},
        ]
        mock_get_client_for_backend.return_value = src_client

        mock_precheck.side_effect = na_utils.NetAppDriverException(
            message='precheck failed'
        )

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.dm_mixin.ensure_consistent_replication_snapmirrors,
            mock.Mock(), src_backend, storage_object_type, storage_object_names
        )

        mock_precheck.assert_called_once_with(
            src_backend, [
                dst_backend], storage_object_type, storage_object_names
        )
        mock_create_snapmirror_for_cg.assert_not_called()

    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_policy')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'get_replication_backend_names')
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.config_utils,
        'get_backend_configuration')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'create_snapmirror_for_cg')
    def test_ensure_consistent_replication_sm_async_multiple_cgs_error(
            self, mock_create_snapmirror_for_cg,
            mock_get_backend_configuration,
            mock_get_client_for_backend, mock_get_replication_backend_names,
            mock_get_replication_policy
    ):
        src_backend = 'src_backend'
        dst_backend_1 = 'dst_backend_1'
        dst_backend_2 = 'dst_backend_2'
        src_vserver = 'source_vserver'
        policy = 'MirrorAllSnapshots'
        storage_object_type = na_utils.StorageObjectType.VOLUME
        storage_object_names = ['vol1', 'vol2']

        mock_get_replication_backend_names.return_value = [
            dst_backend_1, dst_backend_2]
        mock_get_replication_policy.return_value = policy

        src_backend_conf = mock.Mock()
        src_backend_conf.netapp_vserver = src_vserver
        mock_get_backend_configuration.return_value = src_backend_conf

        src_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [
            {'flexvol_name': 'vol1', 'cg_name': 'cg_A'},
            {'flexvol_name': 'vol2', 'cg_name': 'cg_B'},
        ]
        mock_get_client_for_backend.return_value = src_client

        self.assertRaises(
            na_utils.NetAppDriverException,
            self.dm_mixin.ensure_consistent_replication_snapmirrors,
            mock.Mock(), src_backend,
            storage_object_type, storage_object_names
        )

        src_client.create_ontap_consistency_group.assert_not_called()
        src_client.expand_ontap_consistency_group.assert_not_called()
        mock_create_snapmirror_for_cg.assert_not_called()

    @mock.patch.object(
        data_motion.config_utils,
        'get_backend_configuration')
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'ssc_library', create=True)
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'configuration', create=True)
    def test_complete_failover_active_sync_planned_success(
            self,
            mock_configuration,
            mock_ssc_library,
            mock_get_client_for_backend,
            mock_get_backend_configuration,
    ):
        dm = data_motion.DataMotionMixin()

        mock_configuration.netapp_disaggregated_platform = False
        mock_ssc_library.get_ssc_flexvol_names.return_value = ['flexA']

        src_client = mock.Mock()
        dst_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [{'cg_name': 'cgA'}]
        mock_get_client_for_backend.side_effect = [src_client, dst_client]

        src_cfg = mock.Mock()
        src_cfg.netapp_vserver = 'svm_src'
        dst_cfg = mock.Mock()
        dst_cfg.netapp_vserver = 'svm_dst'
        mock_get_backend_configuration.side_effect = [src_cfg, dst_cfg]

        volumes = [{'id': 'v1'}, {'id': 'v2'}]
        active, updates = dm._complete_failover_active_sync(
            'src_backend',
            'dst_backend', volumes)

        self.assertEqual('dst_backend', active)
        self.assertEqual(2, len(updates))
        for u in updates:
            self.assertEqual(
                fields.ReplicationStatus.FAILED_OVER,
                u['updates']['replication_status']
            )

        mock_ssc_library.get_ssc_flexvol_names.assert_called_once()
        src_client.get_flexvols_cg_info.assert_called_once_with('flexA')
        dst_client.get_flexvols_cg_info.assert_not_called()
        dst_client.failover_snapmirror_active_sync.assert_called_once_with(
            'svm_src', 'cgA', 'svm_dst', 'cgA'
        )
        mock_get_backend_configuration.assert_has_calls([
            mock.call('src_backend'),
            mock.call('dst_backend'),
        ])

    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.DataMotionMixin,
                       'ssc_library', create=True)
    @mock.patch.object(data_motion.DataMotionMixin,
                       'configuration', create=True)
    def test_complete_failover_active_sync_unplanned_success(
            self,
            mock_configuration,
            mock_ssc_library,
            mock_get_client_for_backend,
            mock_get_backend_configuration,
    ):
        dm = data_motion.DataMotionMixin()

        mock_configuration.netapp_disaggregated_platform = False
        mock_ssc_library.get_ssc_flexvol_names.return_value = ['flexB']

        # Source client connect fails, destination succeeds
        dst_client = mock.Mock()
        dst_client.get_flexvols_cg_info.return_value = [{'cg_name': 'cgB'}]
        mock_get_client_for_backend.side_effect = [Exception('src down'),
                                                   dst_client]

        volumes = [{'id': 'v1'}]
        active, updates = dm._complete_failover_active_sync(
            'src_backend',
            'dst_backend', volumes)

        self.assertEqual('dst_backend', active)
        self.assertEqual(1, len(updates))
        self.assertEqual(
            fields.ReplicationStatus.FAILED_OVER,
            updates[0]['updates']['replication_status']
        )

        mock_ssc_library.get_ssc_flexvol_names.assert_called_once()
        # Flexvol name 'flexB' does not have '_dst' suffix, so the code
        # appends it before querying the destination backend.
        dst_client.get_flexvols_cg_info.assert_called_once_with('flexB_dst')
        dst_client.failover_snapmirror_active_sync.assert_not_called()
        mock_get_backend_configuration.assert_not_called()

    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.DataMotionMixin,
                       'ssc_library', create=True)
    @mock.patch.object(data_motion.DataMotionMixin,
                       'configuration', create=True)
    def test_complete_failover_active_sync_unplanned_dst_suffix_present(
            self,
            mock_configuration,
            mock_ssc_library,
            mock_get_client_for_backend,
            mock_get_backend_configuration,
    ):
        """Flexvol already has '_dst' suffix — must not be double-suffixed."""
        dm = data_motion.DataMotionMixin()

        mock_configuration.netapp_disaggregated_platform = False
        mock_ssc_library.get_ssc_flexvol_names.return_value = ['flexC_dst']

        dst_client = mock.Mock()
        dst_client.get_flexvols_cg_info.return_value = [{'cg_name': 'cgC'}]
        mock_get_client_for_backend.side_effect = [Exception('src down'),
                                                   dst_client]

        volumes = [{'id': 'v1'}]
        active, updates = dm._complete_failover_active_sync(
            'src_backend',
            'dst_backend', volumes)

        self.assertEqual('dst_backend', active)
        self.assertEqual(1, len(updates))
        self.assertEqual(
            fields.ReplicationStatus.FAILED_OVER,
            updates[0]['updates']['replication_status']
        )

        mock_ssc_library.get_ssc_flexvol_names.assert_called_once()
        # Flexvol name already has '_dst' suffix — must be used as-is.
        dst_client.get_flexvols_cg_info.assert_called_once_with('flexC_dst')
        dst_client.failover_snapmirror_active_sync.assert_not_called()
        mock_get_backend_configuration.assert_not_called()

    @mock.patch.object(data_motion.LOG, 'error', create=True)
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'ssc_library', create=True)
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'configuration', create=True)
    def test_complete_failover_active_sync_no_destination_backend(
            self,
            mock_configuration,
            mock_ssc_library,
            mock_get_client_for_backend,
            mock_log_error,
    ):
        dm = data_motion.DataMotionMixin()

        with self.assertRaisesRegex(
                na_utils.NetAppDriverException,
                'No suitable host was found to failover.'
        ):
            dm._complete_failover_active_sync(
                'src_backend', None,
                [])

        mock_get_client_for_backend.assert_not_called()
        mock_log_error.assert_called_once()

    @mock.patch.object(data_motion.LOG, 'error', create=True)
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'ssc_library', create=True)
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'configuration', create=True)
    def test_complete_failover_active_sync_destination_client_connect_failure(
            self,
            mock_configuration,
            mock_ssc_library,
            mock_get_client_for_backend,
            mock_log_error,
    ):
        dm = data_motion.DataMotionMixin()

        mock_configuration.netapp_disaggregated_platform = False

        src_client = mock.Mock()
        mock_get_client_for_backend.side_effect = \
            [src_client, Exception('dst')]

        with self.assertRaisesRegex(
                na_utils.NetAppDriverException,
                'Failed to connect to destination '
                'backend client for failover.'
        ):
            dm._complete_failover_active_sync(
                'src_backend',
                'dst_backend', [])

        mock_log_error.assert_called()
        mock_ssc_library.get_ssc_flexvol_names.assert_not_called()

    @mock.patch.object(
        data_motion.config_utils,
        'get_backend_configuration')
    @mock.patch.object(
        data_motion.config_utils,
        'get_client_for_backend')
    @mock.patch.object(
        data_motion.DataMotionMixin,
        'ssc_library', create=True)
    @mock.patch.object(data_motion.DataMotionMixin,
                       'configuration', create=True)
    def test_complete_failover_active_sync_asar2_not_supported(
            self,
            mock_configuration,
            mock_ssc_library,
            mock_get_client_for_backend,
            mock_get_backend_configuration,
    ):
        dm = data_motion.DataMotionMixin()

        mock_configuration.netapp_disaggregated_platform = True

        src_client = mock.Mock()
        dst_client = mock.Mock()
        mock_get_client_for_backend.side_effect = [src_client, dst_client]

        with self.assertRaisesRegex(
                na_utils.NetAppDriverException,
                'ASAr2 platform is not supported for replication'
        ):
            dm._complete_failover_active_sync(
                'src_backend',
                'dst_backend', [])

        mock_ssc_library.get_ssc_flexvol_names.assert_not_called()
        src_client.get_flexvols_cg_info.assert_not_called()
        dst_client.get_flexvols_cg_info.assert_not_called()
        dst_client.failover_snapmirror_active_sync.assert_not_called()

    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.DataMotionMixin,
                       'ssc_library', create=True)
    @mock.patch.object(data_motion.DataMotionMixin,
                       'configuration', create=True)
    def test_complete_failback_active_sync_success(
            self,
            mock_configuration,
            mock_ssc_library,
            mock_get_client_for_backend,
            mock_get_backend_configuration
    ):
        dm = data_motion.DataMotionMixin()
        dm.backend_name = 'active_backend'
        dm.failed_over_backend_name = 'secondary_backend'

        # Platform supported
        mock_configuration.netapp_disaggregated_platform = False

        dm._update_zapi_client = mock.Mock()

        # Clients
        src_client = mock.Mock()
        mock_get_client_for_backend.return_value = src_client

        # Flexvols and CG info
        mock_ssc_library.get_ssc_flexvol_names.return_value = ['poolA']
        src_client.get_flexvols_cg_info.return_value = [{'cg_name': 'cgX'}]

        # Backend configurations
        src_cfg = mock.Mock(netapp_vserver='svm_src')
        dst_cfg = mock.Mock(netapp_vserver='svm_dst')
        mock_get_backend_configuration.side_effect = [src_cfg, dst_cfg]

        # Volumes input
        volumes = [
            {'id': 'v1', 'host': 'host@backend#poolA'},
            {'id': 'v2', 'host': 'host@backend#poolB'},
        ]

        active_backend, volume_updates, extra = (
            dm._complete_failback_active_sync(
                primary_backend_name='active_backend',
                secondary_backend_name='secondary_backend',
                volumes=volumes,
            )
        )

        # Active backend updated and flags set
        self.assertTrue(dm._update_zapi_client.called)
        self.assertEqual('active_backend', active_backend)
        self.assertFalse(dm.failed_over)
        self.assertEqual('active_backend', dm.failed_over_backend_name)

        # Only last volume appended due to function logic
        self.assertEqual(2, len(volume_updates))
        self.assertEqual('v1', volume_updates[0]['volume_id'])
        self.assertEqual(
            fields.ReplicationStatus.ENABLED,
            volume_updates[0]['updates']['replication_status'],
        )
        self.assertEqual([], extra)

        # SnapMirror failback invoked with correct args
        src_client.failover_snapmirror_active_sync.assert_called_once_with(
            'svm_dst', 'cgX', 'svm_src', 'cgX'
        )

    @mock.patch.object(data_motion.DataMotionMixin, 'configuration',
                       create=True)
    def test_complete_failback_active_sync_primary_missing_required_raises(
            self, mock_configuration
    ):
        dm = data_motion.DataMotionMixin()
        with self.assertRaisesRegex(
                na_utils.NetAppDriverException,
                'Primary backend to which the replication '
                'will be failed back to '
                'is required.'
        ):
            dm._complete_failback_active_sync(
                primary_backend_name=None,
                secondary_backend_name='secondaryB',
                volumes=[],
            )

    @mock.patch.object(data_motion.DataMotionMixin,
                       'configuration', create=True)
    def test_complete_failback_active_sync_secondary_missing_required_raises(
            self, mock_configuration
    ):
        dm = data_motion.DataMotionMixin()
        with self.assertRaisesRegex(
                na_utils.NetAppDriverException,
                'Secondary backend to which the replication is failed over is '
                'required.'
        ):
            dm._complete_failback_active_sync(
                primary_backend_name='primaryA',
                secondary_backend_name=None,
                volumes=[],
            )

    @mock.patch.object(data_motion.DataMotionMixin,
                       'configuration', create=True)
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    def test_complete_failback_active_sync_asar2_not_supported_exception(
            self, mock_get_client_for_backend, mock_configuration
    ):
        dm = data_motion.DataMotionMixin()
        # Disaggregated platform triggers unsupported error
        mock_configuration.netapp_disaggregated_platform = True

        # Still create a client to pass initial try block
        mock_get_client_for_backend.return_value = mock.Mock()

        with self.assertRaisesRegex(
                na_utils.NetAppDriverException,
                'ASAr2 platform is not supported for replication'
        ):
            dm._complete_failback_active_sync(
                primary_backend_name='primary_backend',
                secondary_backend_name='secondary_backend',
                volumes=[],
            )

    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_negative_nfs_backend(self, m_get_backend_cfg):
        cfg = mock.Mock()
        cfg.safe_get.return_value = 'nfs'
        m_get_backend_cfg.return_value = cfg
        self.assertRaises(
            na_utils.NetAppDriverException,
            self.dm_mixin.
            _consistent_replication_precheck_for_af_policy,
            self.src_backend,
            ['dest1'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_negative_multiple_destinations(self, m_get_backend_cfg):
        cfg = mock.Mock()
        cfg.safe_get.return_value = 'iscsi'
        m_get_backend_cfg.return_value = cfg
        self.assertRaises(
            na_utils.NetAppDriverException,
            self.dm_mixin.
            _consistent_replication_precheck_for_af_policy,
            self.src_backend,
            ['dest1', 'dest2'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

    @mock.patch.object(data_motion.DataMotionMixin,
                       '_check_cg_name_conflicts')
    @mock.patch.object(data_motion.DataMotionMixin,
                       '_check_flexvol_name_conflicts')
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_positive_no_existing_mirrors_triggers_name_conflicts_checks(
            self, m_get_backend_cfg,
            m_get_client, m_check_flex_conflicts, m_check_cg_conflicts
    ):
        # Source backend config
        src_cfg = mock.Mock()
        src_cfg.safe_get.return_value = 'iscsi'
        src_cfg.netapp_vserver = 'svm-src'
        # Destination backend config
        dest_cfg = mock.Mock()
        dest_cfg.netapp_vserver = 'svm-dest'
        m_get_backend_cfg.side_effect = [src_cfg, src_cfg, dest_cfg]

        # Clients
        src_client = mock.Mock()
        # Flexvols part of a single CG "cgX"
        src_client.get_flexvols_cg_info.return_value = [
            {'cg_name': 'cgX', 'flexvol_name': 'volA'},
            {'cg_name': 'cgX', 'flexvol_name': 'volB'},
        ]
        dest_client = mock.Mock()
        # No existing mirrors
        dest_client.get_snapmirrors.return_value = []
        m_get_client.side_effect = [src_client, dest_client]

        (self.dm_mixin.
            _consistent_replication_precheck_for_af_policy(
                self.src_backend, [self.dest_backend],
                na_utils.StorageObjectType.VOLUME, ['vol1']))

        # Conflict checks invoked with cg and volumes
        m_check_flex_conflicts.assert_called_once_with(
            dest_client, 'svm-dest', ['vol1'], self.dest_backend)
        m_check_cg_conflicts.assert_called_once_with(
            dest_client, 'svm-dest', 'cgX', self.dest_backend)

        # Snapmirrors checked with cg path
        dest_client.get_snapmirrors.assert_called_once()
        args, kwargs = dest_client.get_snapmirrors.call_args
        self.assertEqual(('svm-src', '/cg/cgX', 'svm-dest', '/cg/cgX'), args)

    @mock.patch.object(data_motion.DataMotionMixin,
                       '_check_cg_name_conflicts')
    @mock.patch.object(data_motion.DataMotionMixin,
                       '_check_flexvol_name_conflicts')
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_positive_existing_mirrors_skip_conflict_checks(
            self, m_get_backend_cfg,
            m_get_client, m_check_flex_conflicts, m_check_cg_conflicts
    ):
        src_cfg = mock.Mock()
        src_cfg.safe_get.return_value = 'iscsi'
        src_cfg.netapp_vserver = 'svm-src'
        dest_cfg = mock.Mock()
        dest_cfg.netapp_vserver = 'svm-dest'
        m_get_backend_cfg.side_effect = [src_cfg, src_cfg, dest_cfg]

        src_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [
            {'cg_name': 'cgY', 'flexvol_name': 'volA'},
            {'cg_name': 'cgY', 'flexvol_name': 'volB'},
        ]
        dest_client = mock.Mock()
        # Existing mirrors present
        dest_client.get_snapmirrors.return_value = \
            [{'mirror-state': 'in_sync'}]
        m_get_client.side_effect = [src_client, dest_client]

        (self.dm_mixin.
            _consistent_replication_precheck_for_af_policy(
                self.src_backend, [self.dest_backend],
                na_utils.StorageObjectType.VOLUME,
                ['volA', 'volB']))

        m_check_flex_conflicts.assert_not_called()
        m_check_cg_conflicts.assert_not_called()
        dest_client.get_snapmirrors.assert_called_once()

    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_negative_multiple_cg_names_exception(
            self, m_get_backend_cfg, m_get_client):
        src_cfg = mock.Mock()
        src_cfg.safe_get.return_value = 'iscsi'
        src_cfg.netapp_vserver = 'svm-src'
        dest_cfg = mock.Mock()
        dest_cfg.netapp_vserver = 'svm-dest'
        m_get_backend_cfg.side_effect = [src_cfg, src_cfg, dest_cfg]

        src_client = mock.Mock()
        # Two different CGs found
        src_client.get_flexvols_cg_info.return_value = [
            {'cg_name': 'cg1', 'flexvol_name': 'volA'},
            {'cg_name': 'cg2', 'flexvol_name': 'volB'},
        ]
        dest_client = mock.Mock()
        m_get_client.side_effect = [src_client, dest_client]

        self.assertRaises(
            na_utils.NetAppDriverException,
            (self.dm_mixin.
                _consistent_replication_precheck_for_af_policy),
            self.src_backend,
            [self.dest_backend],
            na_utils.StorageObjectType.VOLUME, ['volA', 'volB'])

    @mock.patch.object(data_motion.DataMotionMixin,
                       '_check_cg_name_conflicts')
    @mock.patch.object(data_motion.DataMotionMixin,
                       '_check_flexvol_name_conflicts')
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_positive_no_cg_names_provided_creates_none_and_checks_conflicts(
            self, m_get_backend_cfg,
            m_get_client, m_check_flex_conflicts, m_check_cg_conflicts
    ):
        # Covers path where cg_names is empty -> cg_name
        # becomes None and conflicts are checked
        src_cfg = mock.Mock()
        src_cfg.safe_get.return_value = 'iscsi'
        src_cfg.netapp_vserver = 'svm-src'
        dest_cfg = mock.Mock()
        dest_cfg.netapp_vserver = 'svm-dest'
        m_get_backend_cfg.side_effect = [src_cfg, src_cfg, dest_cfg]

        src_client = mock.Mock()
        # No CGs on source
        src_client.get_flexvols_cg_info.return_value = [
            {'cg_name': None, 'flexvol_name': 'volA'},
            {'cg_name': None, 'flexvol_name': 'volB'},
        ]
        dest_client = mock.Mock()
        # No existing mirrors
        dest_client.get_snapmirrors.return_value = []
        m_get_client.side_effect = [src_client, dest_client]

        (self.dm_mixin.
            _consistent_replication_precheck_for_af_policy(
                self.src_backend, [self.dest_backend],
                na_utils.StorageObjectType.VOLUME,
                ['volA', 'volB']))

        m_check_flex_conflicts.assert_called_once()
        # cg_name is None still passed to conflict check
        args, _ = m_check_cg_conflicts.call_args
        self.assertIsNone(args[2])
        dest_client.get_snapmirrors.assert_called_once()

    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_afd_precheck_consistent_replication_disabled(
            self, m_get_backend_cfg):
        """Test AFD precheck fails when consistent_replication is disabled."""
        cfg = mock.Mock()
        cfg.safe_get.return_value = False
        m_get_backend_cfg.return_value = cfg
        self.assertRaises(
            na_utils.NetAppDriverException,
            self.dm_mixin.
            _consistent_replication_precheck_for_afd_policy,
            self.src_backend,
            ['dest1'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

    @mock.patch.object(data_motion.DataMotionMixin,
                       '_consistent_replication_precheck_for_active_sync')
    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_afd_precheck_calls_active_sync_precheck(
            self, m_get_backend_cfg, m_active_sync_precheck):
        """Test AFD precheck calls the common active sync precheck."""
        cfg = mock.Mock()
        cfg.safe_get.return_value = True
        m_get_backend_cfg.return_value = cfg

        self.dm_mixin._consistent_replication_precheck_for_afd_policy(
            self.src_backend,
            ['dest1'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

        m_active_sync_precheck.assert_called_once_with(
            self.src_backend,
            ['dest1'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

    @mock.patch.object(data_motion.DataMotionMixin,
                       '_consistent_replication_precheck_for_active_sync')
    def test_af_precheck_calls_active_sync_precheck(
            self, m_active_sync_precheck):
        """Test AF precheck calls the common active sync precheck."""
        self.dm_mixin._consistent_replication_precheck_for_af_policy(
            self.src_backend,
            ['dest1'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

        m_active_sync_precheck.assert_called_once_with(
            self.src_backend,
            ['dest1'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_active_sync_precheck_nfs_backend_error(self, m_get_backend_cfg):
        """Test active sync precheck fails for NFS backends."""
        cfg = mock.Mock()
        cfg.safe_get.return_value = 'nfs'
        m_get_backend_cfg.return_value = cfg
        self.assertRaises(
            na_utils.NetAppDriverException,
            self.dm_mixin.
            _consistent_replication_precheck_for_active_sync,
            self.src_backend,
            ['dest1'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_active_sync_precheck_multiple_destinations_error(
            self, m_get_backend_cfg):
        """Test active sync precheck fails for multiple destinations."""
        cfg = mock.Mock()
        cfg.safe_get.return_value = 'iscsi'
        m_get_backend_cfg.return_value = cfg
        self.assertRaises(
            na_utils.NetAppDriverException,
            self.dm_mixin.
            _consistent_replication_precheck_for_active_sync,
            self.src_backend,
            ['dest1', 'dest2'],
            na_utils.StorageObjectType.VOLUME,
            ['vol1'])

    @mock.patch.object(data_motion.DataMotionMixin,
                       'get_replication_backend_names')
    @mock.patch.object(data_motion.DataMotionMixin,
                       'ssc_library', create=True)
    @mock.patch.object(data_motion.DataMotionMixin,
                       'configuration', create=True)
    @mock.patch.object(data_motion.config_utils,
                       'get_client_for_backend')
    @mock.patch.object(data_motion.config_utils,
                       'get_backend_configuration')
    def test_complete_failover_consistent_rep_async_success(
            self,
            mock_get_backend_configuration,
            mock_get_client_for_backend,
            mock_configuration,
            mock_ssc_library,
            mock_get_replication_backend_names):
        dm = data_motion.DataMotionMixin()
        dm.backend_name = 'src_backend'
        mock_configuration.netapp_disaggregated_platform = False
        mock_get_replication_backend_names.return_value = ['dst_backend']
        mock_ssc_library.get_ssc_flexvol_names.return_value = ['volA', 'volB']

        src_client = mock.Mock()
        dst_client = mock.Mock()
        src_client.get_flexvols_cg_info.return_value = [{'cg_name': 'cg1'}]
        dst_client.get_flexvols_cg_info.return_value = [{'cg_name': 'cg1'}]
        mock_get_client_for_backend.return_value = dst_client

        src_cfg = mock.Mock(netapp_vserver='svm_src')
        src_cfg.netapp_snapmirror_quiesce_timeout = 60
        # mock_get_backend_configuration.side_effect = [src_cfg, dst_cfg]
        mock_get_backend_configuration.return_value = src_cfg

        existing_snapmirrors = [{'relationship-status': 'quiesced'}]
        self.mock_object(dst_client, 'get_snapmirrors',
                         return_value=existing_snapmirrors)

        volumes = [{'id': 'v1'}, {'id': 'v2'}]
        active, updates = dm._complete_failover_consistent_rep_async(
            dm.backend_name,
            ['dst_backend'],
            volumes,
            'dst_backend'
        )

        assert active == 'dst_backend'
        assert len(updates) == 2
        dst_client.update_snapmirror.assert_called_once()
        dst_client.break_snapmirror.assert_called_once()

    @mock.patch.object(data_motion.config_utils, 'get_backend_configuration')
    @mock.patch.object(data_motion.config_utils, 'get_client_for_backend')
    def test_choose_failover_target_of_cg_replication_first_backend_suitable(  # noqa: E501
            self, mock_get_client_for_backend,
            mock_get_backend_configuration):
        # Setup: backend1 has in_sync snapmirror, backend2 does not
        src_cfg = mock.Mock()
        src_cfg.netapp_vserver = 'svm_src'
        mock_get_backend_configuration.side_effect = [
            src_cfg, mock.Mock(), mock.Mock()]
        client1 = mock.Mock()
        client1.get_snapmirrors.return_value = [{'lag-time': '100'}]
        mock_get_client_for_backend.side_effect = [client1]

        result = self.dm_mixin._choose_failover_target_of_cg_replication(
            self.src_backend, 'cg_1', ["backend1"])

        self.assertEqual('backend1', result)
        client1.get_snapmirrors.assert_called_once()
