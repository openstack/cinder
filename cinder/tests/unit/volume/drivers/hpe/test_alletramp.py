#    (c) Copyright 2025 Hewlett Packard Enterprise Development LP
#    All Rights Reserved.
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
"""Unit tests for OpenStack Cinder volume driver"""

from unittest import mock

from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_group_snapshot
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.hpe \
    import fake_hpe_storage_flowkit as hpe_storage_flowkit
from cinder.volume import configuration as conf
from cinder.volume.drivers.hpe import alletramp_driver as alletramp
from cinder.volume.drivers.hpe import alletramp_service
from cinder.volume import qos_specs
from cinder.volume import volume_types

HPE3PAR_CPG = 'OpenStackCPG'
HPE3PAR_CPG2 = 'fakepool'
HPE3PAR_CPG_QOS = 'qospool'
HPE3PAR_CPG_SNAP = 'OpenStackCPGSnap'
HPE3PAR_USER_NAME = 'testUser'
HPE3PAR_USER_PASS = 'testPassword'
HPE3PAR_SAN_IP = '2.2.2.2'

ALLETRAMP_VLUN_WORKFLOW = (
    'cinder.volume.drivers.hpe.alletramp_service.VLUNWorkflow')
ALLETRAMP_VOLUME_WORKFLOW = (
    'cinder.volume.drivers.hpe.alletramp_service.VolumeWorkflow')
ALLETRAMP_HOST_WORKFLOW = (
    'cinder.volume.drivers.hpe.alletramp_service.HostWorkflow')

VOLUME_ID = 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'
VOLUME_NAME = 'volume-' + VOLUME_ID

FAKE_HOST = 'fakehost'
FAKE_CINDER_HOST = 'fakehost@foo#' + HPE3PAR_CPG


class TestAlletraMPServiceImports(test.TestCase):

    def test_check_for_setup_error_reports_missing_flowkit(self):
        driver = alletramp.HPEAlletraMPDriverBase(configuration=mock.Mock())

        with mock.patch.object(alletramp_service, 'flowkit', None):
            self.assertRaises(exception.VolumeDriverException,
                              driver.check_for_setup_error)

    def test_service_init_raises_only_when_instantiated_without_flowkit(self):
        with mock.patch.object(alletramp_service, 'flowkit', None):
            self.assertRaises(exception.InvalidInput,
                              alletramp_service.AlletraMPService,
                              mock.Mock())


def _apply_common_backend_config(configuration):
    configuration.san_ssh_port = 22
    configuration.ssh_conn_timeout = 30
    configuration.san_private_key = None
    configuration.hpe_api_url_v3 = 'https://1.1.1.1/api/v3'
    configuration.hpe3par_iscsi_ips = []
    configuration.hpe3par_iscsi_chap_enabled = False
    configuration.hpe3par_hostseesvlun = False
    configuration.target_ip_address = None
    configuration.target_port = 3260
    configuration.hpe3par_nvme_ips = []


def _fake_volume_type(*args, **kwargs):
    ctxt = context.get_admin_context()
    type_ref = volume_types.create(ctxt, "qos_extra_specs", {})
    qos_ref = qos_specs.create(ctxt, 'qos-specs', {})
    qos_specs.associate_qos_with_type(ctxt, qos_ref['id'],
                                      type_ref['id'])
    qos_type = volume_types.get_volume_type(ctxt, type_ref['id'])
    return qos_type


def _fake_volume(*args, **kwargs):
    volume = fake_volume.fake_volume_obj(
        context.get_admin_context(),
        name=VOLUME_NAME,
        id=VOLUME_ID,
        display_name='Foo Volume',
        size=2,
        host=FAKE_CINDER_HOST,
        volume_type=None,
        volume_type_id=None,
        multiattach=False)

    return volume


def _fake_group(*args, **kwargs):
    group = fake_group.fake_group_obj(mock.MagicMock())
    return group


def _fake_group_snapshot(*args, **kwargs):
    group_snap = fake_group_snapshot.fake_group_snapshot_obj(
        mock.MagicMock())
    return group_snap


class TestHPEAlletraMPServiceLogic(test.TestCase):

    def setUp(self):
        super(TestHPEAlletraMPServiceLogic, self).setUp()
        self.context = context.get_admin_context()
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.hpe3par_debug = False
        self.configuration.hpe3par_username = HPE3PAR_USER_NAME
        self.configuration.hpe3par_password = HPE3PAR_USER_PASS
        self.configuration.hpe3par_api_url = 'https://1.1.1.1/api/v1'
        self.configuration.hpe3par_cpg = [HPE3PAR_CPG, HPE3PAR_CPG2]
        self.configuration.hpe3par_cpg_snap = HPE3PAR_CPG_SNAP
        self.configuration.san_ip = HPE3PAR_SAN_IP
        self.configuration.san_login = HPE3PAR_USER_NAME
        self.configuration.san_password = HPE3PAR_USER_PASS
        self.configuration.replication_device = None
        _apply_common_backend_config(self.configuration)

        self.service = alletramp_service.AlletraMPService(self.configuration)
        self.service.do_setup(None)

    def test_get_existing_volume_ref_name_uses_source_name(self):
        name = self.service._get_existing_volume_ref_name(
            {'source-name': 'my-existing-volume'})
        self.assertEqual('my-existing-volume', name)

    def test_get_existing_volume_ref_name_uses_source_id(self):
        ref = {'source-id': VOLUME_ID}
        expected = self.service._get_alletramp_unm_name(VOLUME_ID)

        name = self.service._get_existing_volume_ref_name(ref)

        self.assertEqual(expected, name)

    def test_get_existing_snapshot_ref_name_uses_source_id(self):
        ref = {'source-id': VOLUME_ID}
        expected = self.service._get_alletramp_ums_name(VOLUME_ID)

        name = self.service._get_existing_volume_ref_name(
            ref, is_snapshot=True)

        self.assertEqual(expected, name)

    def test_get_existing_volume_ref_name_requires_source_key(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.service._get_existing_volume_ref_name,
                          {'invalid': 'ref'})

    def test_require_connector_fields_raises_for_missing_fields(self):
        connector = {'host': 'host1'}

        with self.assertRaises(exception.InvalidInput) as ex:
            self.service._require_connector_fields(
                connector, ['host', 'initiator'])

        self.assertIn('initiator', str(ex.exception))

    def test_get_normalized_extra_specs_handles_vendor_prefix(self):
        volume_type = {
            'extra_specs': {
                'HPE:AlletraMP:hpe3par:provisioning': 'THIN',
                'HPE:AlletraMP:minIOPS': '2000',
                'HPE:AlletraMP:replication:mode': 'periodic',
            }
        }

        specs = self.service._get_normalized_extra_specs(volume_type)

        self.assertEqual('thin', specs['provisioning'])
        self.assertEqual('2000', specs['minIOPS'])
        extra_spec_rep_mode = (
            alletramp_service.constants.EXTRA_SPEC_REP_MODE)
        self.assertEqual('periodic', specs[extra_spec_rep_mode])

    def test_validate_persona_rejects_invalid_value(self):
        self.assertRaises(exception.InvalidInput,
                          self.service.validate_persona,
                          'invalid persona')

    def test_get_persona_type_defaults_to_generic_alua(self):
        volume = {'id': VOLUME_ID, 'volume_type_id': None}

        persona_id = self.service.get_persona_type(volume, hpe3par_keys={})

        self.assertEqual('2', persona_id)

    def test_get_volume_settings_from_type_id_rejects_bad_provisioning(self):
        with mock.patch.object(
                self.service,
                'get_type_info',
                return_value=({'provisioning': 'invalid-provisioning'},
                              {}, None, None)):
            self.assertRaises(exception.InvalidInput,
                              self.service.get_volume_settings_from_type_id,
                              None,
                              HPE3PAR_CPG)

    def test_ensure_failover_replication_enabled_raises_when_disabled(self):
        self.service._replication_enabled = False

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.service._ensure_failover_replication_enabled)

    def test_resolve_host_failover_request_returns_failback_tuple(self):
        failover, target, backend_id = (
            self.service._resolve_host_failover_request(
                alletramp_service.constants.FAILBACK_VALUE))

        self.assertFalse(failover)
        self.assertIsNone(target)
        self.assertEqual(alletramp_service.constants.FAILBACK_VALUE,
                         backend_id)

    def test_resolve_host_failover_request_returns_target(self):
        self.service._replication_targets = [
            {'backend_id': 'secondary-a', 'id': 'array-a'}
        ]

        failover, target, backend_id = (
            self.service._resolve_host_failover_request(
                'secondary-a'))

        self.assertTrue(failover)
        self.assertEqual('secondary-a', backend_id)
        self.assertEqual('array-a', target['id'])

    def test_build_failover_volume_updates_host_shape(self):
        volumes = [{'id': 'vol-1', 'provider_location': 'loc-1'}]

        updates = (
            self.service._build_failover_volume_updates(
                volumes,
                'failed-over',
                'target-id',
                host=True))

        self.assertEqual(1, len(updates))
        self.assertEqual('vol-1', updates[0]['volume_id'])
        self.assertEqual('failed-over',
                         updates[0]['updates']['replication_status'])
        self.assertEqual('target-id',
                         updates[0]['updates']['replication_driver_data'])

    def test_extend_volume_retries_after_api_error_150(self):
        volume = {'id': VOLUME_ID, 'size': 1}
        vol_name = self.service._get_alletramp_vol_name(volume)
        first_error = (
            alletramp_service.flowkit_exceptions.HTTPForbidden(
                str(alletramp_service.constants.API_ERROR_150)))

        with mock.patch.object(self.service,
                               '_convert_to_base_volume',
                               return_value={'converted': True}) as \
                mock_convert, \
                mock.patch.object(alletramp_service.VolumeWorkflow,
                                  'grow_volume',
                                  side_effect=[first_error, None]) as \
                mock_grow:
            model_update = self.service._extend_volume(
                volume, vol_name, units.Ki)

            self.assertEqual({'converted': True}, model_update)
            self.assertEqual(2, mock_grow.call_count)
            mock_convert.assert_called_once_with(volume)

    def test_handle_delete_snapshot_conflict_returns_false_for_other_error(
            self):
        snap_name = self.service._get_alletramp_snap_name(VOLUME_ID)

        with mock.patch.object(
                self.service,
                '_delete_temp_snapshot_children') as mock_delete_children, \
                mock.patch.object(
                    self.service,
                    '_convert_snapshot_child_volumes_to_base') as \
                mock_convert_children:
            handled = (
                self.service._handle_delete_snapshot_conflict(
                    {'id': VOLUME_ID},
                    snap_name,
                    'some unrelated conflict'))

            self.assertFalse(handled)
            mock_delete_children.assert_not_called()
            mock_convert_children.assert_not_called()

    def test_handle_delete_snapshot_conflict_deletes_after_cleanup(self):
        snap_name = self.service._get_alletramp_snap_name(VOLUME_ID)
        conflict = str(alletramp_service.constants.API_ERROR_32)

        with mock.patch.object(
                self.service,
                '_delete_temp_snapshot_children') as mock_delete_children, \
                mock.patch.object(
                    self.service,
                    '_convert_snapshot_child_volumes_to_base') as \
                mock_convert_children, \
                mock.patch.object(alletramp_service.SnapshotWorkflow,
                                  'delete_snapshot') as mock_delete_snapshot:
            handled = self.service._handle_delete_snapshot_conflict(
                {'id': VOLUME_ID},
                snap_name,
                conflict)

            self.assertTrue(handled)
            mock_delete_children.assert_called_once_with(snap_name)
            mock_convert_children.assert_called_once_with(snap_name)
            mock_delete_snapshot.assert_called_once_with(snap_name)

    def test_handle_delete_snapshot_conflict_raises_busy_if_delete_fails(self):
        snap_name = self.service._get_alletramp_snap_name(VOLUME_ID)
        conflict = str(alletramp_service.constants.API_ERROR_32)

        with mock.patch.object(self.service,
                               '_delete_temp_snapshot_children'), \
                mock.patch.object(self.service,
                                  '_convert_snapshot_child_volumes_to_base'), \
                mock.patch.object(
                    alletramp_service.SnapshotWorkflow,
                    'delete_snapshot',
                    side_effect=Exception('still has children')):
            self.assertRaises(exception.SnapshotIsBusy,
                              self.service._handle_delete_snapshot_conflict,
                              {'id': VOLUME_ID},
                              snap_name,
                              conflict)

    def test_split_group_volumes_returns_grouped_and_remaining(self):
        volumes = [
            {'id': 'v1', 'group_id': 'g1'},
            {'id': 'v2', 'group_id': 'g2'},
            {'id': 'v3', 'group_id': 'g1'},
            {'id': 'v4', 'group_id': None},
        ]

        grouped, remaining = self.service._split_group_volumes(volumes, 'g1')

        self.assertEqual(['v1', 'v3'], [v['id'] for v in grouped])
        self.assertEqual(['v2', 'v4'], [v['id'] for v in remaining])

    def test_failover_grouped_host_volumes_partitions_and_collects_updates(
            self):
        group1 = mock.Mock(id='g1')
        group2 = mock.Mock(id='g2')
        volumes = [
            {'id': 'v1', 'group_id': 'g1'},
            {'id': 'v2', 'group_id': 'g2'},
            {'id': 'v3', 'group_id': None},
        ]

        with mock.patch.object(
                self.service,
                'failover_replication',
                side_effect=[
                    ({'replication_status': 'failed-over'},
                     [{'volume_id': 'v1',
                       'updates': {'replication_status': 'failed-over'}}]),
                    ({'replication_status': 'failed-over'},
                     [{'volume_id': 'v2',
                       'updates': {'replication_status': 'failed-over'}}]),
                ]) as mock_failover_replication:
            remaining, group_updates, volume_updates = (
                self.service._failover_grouped_host_volumes(
                    [group1, group2], volumes,
                    'secondary-a'))

            self.assertEqual(['v3'], [v['id'] for v in remaining])
            self.assertEqual(2, len(group_updates))
            self.assertEqual('g1', group_updates[0]['group_id'])
            self.assertEqual('g2', group_updates[1]['group_id'])
            self.assertEqual(['v1', 'v2'],
                             [u['volume_id'] for u in volume_updates])
            self.assertEqual(2, mock_failover_replication.call_count)

    def test_failover_grouped_host_volumes_handles_none_groups(self):
        volumes = [{'id': 'v1', 'group_id': 'g1'}]

        remaining, group_updates, volume_updates = (
            self.service._failover_grouped_host_volumes(
                None, volumes, 'secondary-a'))

        self.assertEqual(volumes, remaining)
        self.assertEqual([], group_updates)
        self.assertEqual([], volume_updates)

    def test_capacity_from_size_zero_and_nonzero(self):
        self.assertEqual(1024, self.service._capacity_from_size(0))
        self.assertEqual(2048, self.service._capacity_from_size(2))

    def test_encode_name_removes_unsupported_characters(self):
        encoded_uuid = self.service._encode_name(VOLUME_ID)
        encoded_text = self.service._encode_name('name/with+chars==')

        self.assertNotIn('+', encoded_uuid)
        self.assertNotIn('/', encoded_uuid)
        self.assertNotIn('=', encoded_uuid)
        self.assertNotIn('+', encoded_text)
        self.assertNotIn('/', encoded_text)
        self.assertNotIn('=', encoded_text)

    def test_get_boolean_key_value_parses_string_values(self):
        self.assertTrue(self.service._get_boolean_key_value(
            {'convert_to_base': 'True'}, 'convert_to_base'))
        self.assertFalse(self.service._get_boolean_key_value(
            {'convert_to_base': 'false'}, 'convert_to_base', default=True))
        self.assertTrue(self.service._get_boolean_key_value(
            {'convert_to_base': True}, 'convert_to_base'))

    def test_is_alletra_mp_uses_api_version_threshold(self):
        api_ver_r5 = alletramp_service.constants.API_VERSION_R5
        self.service.API_VERSION = api_ver_r5
        self.assertTrue(self.service._is_alletra_mp())

        self.service.API_VERSION = api_ver_r5 - 1
        self.assertFalse(self.service._is_alletra_mp())

    def test_get_qos_value_returns_default_when_missing(self):
        qos = {'maxIOPS': 4000}

        self.assertEqual(4000, self.service._get_qos_value(qos, 'maxIOPS'))
        self.assertEqual('x', self.service._get_qos_value(qos, 'missing', 'x'))

    def test_get_remote_copy_mode_num(self):
        self.assertEqual(alletramp_service.constants.SYNC,
                         self.service._get_remote_copy_mode_num('sync'))
        self.assertEqual(alletramp_service.constants.PERIODIC,
                         self.service._get_remote_copy_mode_num('periodic'))
        self.assertIsNone(self.service._get_remote_copy_mode_num('invalid'))

    def test_is_replication_mode_correct_valid_and_invalid(self):
        self.assertTrue(self.service._is_replication_mode_correct('sync', 900))
        self.assertTrue(self.service._is_replication_mode_correct(
            'periodic', 900))
        self.assertFalse(self.service._is_replication_mode_correct(
            'periodic', 299))
        self.assertFalse(self.service._is_replication_mode_correct(
            'periodic', 31622401))
        self.assertFalse(self.service._is_replication_mode_correct(
            'bad-mode', 900))

    def test_is_volume_type_replicated(self):
        vol_type_true = {
            'extra_specs': {'replication_enabled': '<is> True'}}
        vol_type_false = {
            'extra_specs': {'replication_enabled': '<is> False'}}

        is_vol_type_replicated = (
            self.service._is_volume_type_replicated)
        self.assertTrue(is_vol_type_replicated(vol_type_true))
        self.assertFalse(is_vol_type_replicated(vol_type_false))

    def test_is_volume_group_snap_type(self):
        vol_type_true = {
            'extra_specs': {'consistent_group_snapshot_enabled': '<is> True'}
        }
        vol_type_false = {
            'extra_specs': {'consistent_group_snapshot_enabled': '<is> False'}
        }

        is_vol_group_snap = (
            self.service.is_volume_group_snap_type)
        self.assertTrue(is_vol_group_snap(vol_type_true))
        self.assertFalse(is_vol_group_snap(vol_type_false))
        self.assertFalse(is_vol_group_snap(None))

    def test_get_cpg_map_helpers(self):
        cpg_map = 'src1:dst1 src2:dst2 src3:dst3'

        self.assertEqual('dst2',
                         self.service._get_cpg_from_cpg_map(cpg_map, 'src2'))
        self.assertIsNone(self.service._get_cpg_from_cpg_map(cpg_map, 'src9'))
        self.assertEqual(['dst1', 'dst2', 'dst3'],
                         self.service._generate_alletramp_cpgs(cpg_map))

    def test_get_replication_target_or_raise(self):
        self.service._replication_targets = [
            {'backend_id': 'secondary-a', 'id': 'arr-a'}
        ]

        target = self.service._get_replication_target_or_raise(
            'backend_id', 'secondary-a', 'missing target')
        self.assertEqual('arr-a', target['id'])

        self.assertRaises(exception.InvalidReplicationTarget,
                          self.service._get_replication_target_or_raise,
                          'backend_id',
                          'secondary-b',
                          'missing target')

    def test_build_nonreplicated_failover_host_update(self):
        update = self.service._build_nonreplicated_failover_host_update(
            {'id': 'v1'})

        self.assertEqual('v1', update['volume_id'])
        self.assertEqual('error', update['updates']['status'])

    def test_build_alletramp_config_from_primary_config(self):
        self.service._build_alletramp_config()

        self.assertEqual(self.configuration.hpe3par_cpg,
                         self.service._client_conf['hpe3par_cpg'])
        self.assertEqual(self.configuration.hpe3par_api_url,
                         self.service._client_conf['hpe3par_api_url'])
        self.assertEqual(self.configuration.hpe3par_nvme_ips,
                         self.service._client_conf['hpe3par_nvme_ips'])

    def test_build_alletramp_config_from_replication_target(self):
        conf = {
            'cpg_map': 'srcA:dstA srcB:dstB',
            'hpe3par_username': 'u2',
            'hpe3par_password': 'p2',
            'san_ip': '3.3.3.3',
            'san_login': 's2',
            'san_password': 'sp2',
            'san_ssh_port': 2222,
            'ssh_conn_timeout': 44,
            'san_private_key': 'key',
            'hpe3par_api_url': 'https://2.2.2.2/api/v1',
            'hpe_api_url_v3': 'https://2.2.2.2/api/v3',
            'hpe3par_iscsi_ips': ['10.1.1.1'],
            'hpe3par_iscsi_chap_enabled': True,
            'hpe3par_hostseesvlun': 'hostsees_key',
            'hostsees_key': False,
            'target_ip_address': '10.1.1.1',
            'iscsi_port': 3260,
        }

        self.service._build_alletramp_config(conf)

        self.assertEqual(['dstA', 'dstB'],
                         self.service._client_conf['hpe3par_cpg'])
        self.assertEqual('u2', self.service._client_conf['hpe3par_username'])
        self.assertEqual('https://2.2.2.2/api/v1',
                         self.service._client_conf['hpe3par_api_url'])
        self.assertEqual(['10.1.1.1'],
                         self.service._client_conf['hpe3par_iscsi_ips'])

    def test_get_alletramp_config_chooses_active_replication_target(self):
        self.service._replication_enabled = True
        self.service._active_backend_id = 'secondary-b'
        self.service._replication_targets = [
            {'backend_id': 'secondary-a'},
            {'backend_id': 'secondary-b'},
        ]

        with mock.patch.object(self.service,
                               '_do_replication_setup') as mock_setup, \
                mock.patch.object(self.service,
                                  '_build_alletramp_config') as mock_build:
            self.service._get_alletramp_config(array_id='array-id')

            mock_setup.assert_called_once_with(array_id='array-id')
            mock_build.assert_called_once_with(
                {'backend_id': 'secondary-b'})

    def test_set_qos_rule_alletra_requires_max_limit(self):
        with mock.patch.object(self.service, '_is_alletra_mp',
                               return_value=True):
            self.assertRaises(exception.InvalidInput,
                              self.service._set_qos_rule,
                              {'minIOPS': '1000'},
                              'vvs-test')

    def test_set_qos_rule_alletra_creates_qos_with_max_limits(self):
        qos = {'maxIOPS': '4000', 'maxBWS': '10'}

        with mock.patch.object(self.service, '_is_alletra_mp',
                               return_value=True), \
                mock.patch.object(alletramp_service.QOSWorkflow,
                                  'create_qos') as mock_create_qos:
            self.service._set_qos_rule(qos, 'vvs-test')

            created_rule = mock_create_qos.call_args[0][0]
            self.assertEqual('vvs-test', created_rule['name'])
            self.assertEqual(4000, created_rule['ioMaxLimit'])
            self.assertEqual(10 * units.k, created_rule['bwMaxLimitKB'])
            self.assertEqual(1, created_rule['type'])

    def test_set_qos_rule_existing_vvset_falls_back_to_create(self):
        qos = {'maxIOPS': '5000'}

        with mock.patch.object(self.service, '_is_alletra_mp',
                               return_value=True), \
                mock.patch.object(
                    alletramp_service.QOSWorkflow,
                    'modify_qos',
                    side_effect=alletramp_service.flowkit_exceptions.
                    HTTPNotFound('missing qos')) as mock_modify_qos, \
                mock.patch.object(alletramp_service.QOSWorkflow,
                                  'create_qos') as mock_create_qos:
            self.service._set_qos_rule(
                qos, 'vvs-existing', existing_vvset=True)

            mock_modify_qos.assert_called_once()
            mock_create_qos.assert_called_once()

    def test_is_volume_in_remote_copy_group_true_and_false(self):
        vol = {'id': VOLUME_ID, 'migration_status': None}

        with mock.patch.object(
                alletramp_service.RemoteCopyGroupWorkflow,
                'get_remote_copy_group',
                return_value={'name': 'rcg'}) as mock_get_rcg:
            self.assertTrue(self.service._is_volume_in_remote_copy_group(vol))
            mock_get_rcg.assert_called_once()

        with mock.patch.object(
                alletramp_service.RemoteCopyGroupWorkflow,
                'get_remote_copy_group',
                side_effect=alletramp_service.flowkit_exceptions.
                HPEStorageException('not found')):
            self.assertFalse(self.service._is_volume_in_remote_copy_group(vol))


class TestHPEAlletraMPDriverBase(test.TestCase):

    def setUp(self):
        super(TestHPEAlletraMPDriverBase, self).setUp()
        self.context = context.get_admin_context()
        self.assertIsNotNone(hpe_storage_flowkit)
        self._create_fake_config()
        self.assertIsNone(self.driver.do_setup(None))
        self.service = self.driver.alletra_mp_service

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)

        self.configuration.hpe3par_debug = False
        self.configuration.hpe3par_username = HPE3PAR_USER_NAME
        self.configuration.hpe3par_password = HPE3PAR_USER_PASS
        self.configuration.hpe3par_api_url = 'https://1.1.1.1/api/v1'
        self.configuration.hpe3par_cpg = [HPE3PAR_CPG, HPE3PAR_CPG2]
        self.configuration.hpe3par_cpg_snap = HPE3PAR_CPG_SNAP

        self.configuration.san_ip = HPE3PAR_SAN_IP
        self.configuration.san_login = HPE3PAR_USER_NAME
        self.configuration.san_password = HPE3PAR_USER_PASS
        self.configuration.replication_device = None
        _apply_common_backend_config(self.configuration)

        self.ctxt = context.get_admin_context()
        self.vol = fake_volume.fake_volume_obj(self.context)
        self.vol.volume_type = fake_volume.fake_volume_type_obj(self.context)
        self.snap = fake_snapshot.fake_snapshot_obj(self.context)
        self.snap.volume = self.vol
        self.driver = alletramp.HPEAlletraMPDriverBase(
            configuration=self.configuration)
        self.vol_other = fake_volume.fake_volume_obj(self.context)
        self.group = fake_group.fake_group_obj(self.context)
        self.group_other = fake_group.fake_group_obj(self.context)
        self.group_snap = fake_group_snapshot.fake_group_snapshot_obj(
            self.context)

    def test_get_volume_stats(self, *args, **kwargs):
        with mock.patch.object(self.service, 'get_volume_stats') as \
                mock_get_vol_stats:
            expected_result = self.driver._stats

            result = self.driver.get_volume_stats(False)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_get_vol_stats.assert_not_called()

    def test_create_volume(self, *args, **kwargs):
        with mock.patch.object(self.service, 'create_volume') as \
                mock_create:
            mock_create.return_value = mock.Mock()
            expected_result = mock_create.return_value

            result = self.driver.create_volume(self.vol)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_create.assert_called_once_with(self.vol)

    def test_delete_volume(self, *args, **kwargs):
        with mock.patch.object(self.service, 'delete_volume') as \
                mock_delete:
            mock_delete.return_value = mock.Mock()
            expected_result = mock_delete.return_value

            result = self.driver.delete_volume(self.vol)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_delete.assert_called_once_with(self.vol)

    def test_extend_volume(self, *args, **kwargs):
        new_size = self.vol.size + 10
        with mock.patch.object(self.service, 'extend_volume') as \
                mock_extend:
            mock_extend.return_value = mock.Mock()
            expected_result = mock_extend.return_value

            result = self.driver.extend_volume(self.vol, new_size)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_extend.assert_called_once_with(self.vol, new_size)

    def test_create_volume_from_snapshot(self, *args, **kwargs):
        with mock.patch.object(self.service,
                               'create_volume_from_snapshot') as \
                mock_create_vol_from_snap:
            mock_create_vol_from_snap.return_value = mock.Mock()
            expected_result = mock_create_vol_from_snap.return_value

            result = self.driver.create_volume_from_snapshot(
                self.vol, self.snap)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_create_vol_from_snap.assert_called_once_with(
                self.vol, self.snap)

    def test_create_snapshot(self, *args, **kwargs):
        with mock.patch.object(self.service, 'create_snapshot') as \
                mock_create_snap:
            mock_create_snap.return_value = mock.Mock()
            expected_result = mock_create_snap.return_value

            result = self.driver.create_snapshot(self.snap)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_create_snap.assert_called_once_with(self.snap)

    def test_delete_snapshot(self, *args, **kwargs):
        with mock.patch.object(self.service, 'delete_snapshot') as \
                mock_delete_snap:
            mock_delete_snap.return_value = mock.Mock()
            expected_result = mock_delete_snap.return_value

            result = self.driver.delete_snapshot(self.snap)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_delete_snap.assert_called_once_with(self.snap)

    def test_revert_to_snapshot(self, *args, **kwargs):
        with mock.patch.object(self.service,
                               'revert_to_snapshot') as \
                mock_revert_to_snap:
            mock_revert_to_snap.return_value = mock.Mock()
            expected_result = mock_revert_to_snap.return_value

            result = self.driver.revert_to_snapshot(
                self.ctxt, self.vol, self.snap)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_revert_to_snap.assert_called_once_with(
                self.vol, self.snap)

    def test_get_pool(self, *args, **kwargs):
        with mock.patch.object(self.service, 'get_cpg') as \
                mock_get_pool:
            mock_get_pool.return_value = mock.Mock()
            expected_result = mock_get_pool.return_value

            result = self.driver.get_pool(self.vol)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_get_pool.assert_called_once_with(self.vol)

    def test_create_group(self, *args, **kwargs):
        with mock.patch.object(self.service, 'create_group') as \
                mock_create_group:
            mock_create_group.return_value = mock.Mock()
            expected_result = mock_create_group.return_value

            result = self.driver.create_group(self.ctxt, self.group)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_create_group.assert_called_once_with(self.ctxt, self.group)

    def test_update_group(self, *args, **kwargs):
        with mock.patch.object(self.service, 'update_group') as \
                mock_update_group:
            mock_update_group.return_value = mock.Mock()
            expected_result = mock_update_group.return_value

            result = self.driver.update_group(
                self.ctxt, self.group, [self.vol],
                [self.vol_other])
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_update_group.assert_called_once_with(
                self.ctxt, self.group, [self.vol],
                [self.vol_other])

    def test_delete_group(self, *args, **kwargs):
        with mock.patch.object(self.service, 'delete_group') as \
                mock_delete_group:
            mock_delete_group.return_value = mock.Mock()
            expected_result = mock_delete_group.return_value

            vols = [self.vol, self.vol_other]
            result = self.driver.delete_group(self.ctxt, self.group, vols)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_delete_group.assert_called_once_with(
                self.ctxt, self.group, vols)

    def test_create_group_from_src(self, *args, **kwargs):
        with mock.patch.object(self.service, 'create_group_from_src') \
                as mock_create_group_from_src:
            mock_create_group_from_src.return_value = mock.Mock()
            expected_result = mock_create_group_from_src.return_value

            volumes = [self.vol]
            snapshots = [self.snap]
            source_vols = [self.vol_other]
            result = self.driver.create_group_from_src(
                self.ctxt, self.group, volumes, self.group_snap, snapshots,
                self.group_other, source_vols)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_create_group_from_src.assert_called_once_with(
                self.ctxt, self.group, volumes, self.group_snap, snapshots,
                self.group_other, source_vols)

    def test_create_group_snapshot(self, *args, **kwargs):
        with mock.patch.object(self.service, 'create_group_snapshot') \
                as mock_create_group_snapshot:
            mock_create_group_snapshot.return_value = mock.Mock()
            expected_result = mock_create_group_snapshot.return_value

            snaps = [self.snap]
            result = self.driver.create_group_snapshot(
                self.ctxt, self.group_snap, snaps)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_create_group_snapshot.assert_called_once_with(
                self.ctxt, self.group_snap, snaps)

    def test_delete_group_snapshot(self, *args, **kwargs):
        with mock.patch.object(self.service, 'delete_group_snapshot') \
                as mock_delete_group_snapshot:
            mock_delete_group_snapshot.return_value = mock.Mock()
            expected_result = mock_delete_group_snapshot.return_value

            snaps = [self.snap]
            result = self.driver.delete_group_snapshot(
                self.ctxt, self.group_snap, snaps)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_delete_group_snapshot.assert_called_once_with(
                self.ctxt, self.group_snap, snaps)

    def test_create_cloned_volume(self, *args, **kwargs):
        with mock.patch.object(self.service,
                               'create_cloned_volume') as \
                mock_create:
            mock_create.return_value = mock.Mock()
            expected_result = mock_create.return_value

            result = self.driver.create_cloned_volume(self.vol,
                                                      self.vol_other)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_create.assert_called_once_with(self.vol, self.vol_other)

    def test_create_cloned_volume_cleans_up_created_dest_volume(self):
        self.vol.size = 5
        self.vol_other.size = 2

        with mock.patch.object(self.service,
                               '_can_do_online_clone',
                               return_value=False), \
                mock.patch.object(self.service,
                                  'create_volume',
                                  return_value={
                                      'provider_location': 'id'}) as \
                mock_create_volume, \
                mock.patch.object(
                    self.service,
                    '_copy_cloned_volume_and_wait',
                    side_effect=(
                        alletramp_service.flowkit_exceptions.HTTPNotFound(
                            'Resource could not be found.'))) as \
                mock_copy_wait, \
                mock.patch.object(self.service, 'delete_volume') as \
                mock_delete_volume, \
                mock.patch.object(self.service,
                                  '_update_clone_replication') as \
                mock_update_clone_replication:
            self.assertRaises(exception.NotFound,
                              self.service.create_cloned_volume,
                              self.vol,
                              self.vol_other)

            mock_create_volume.assert_called_once_with(
                self.vol, perform_replica=False)
            mock_copy_wait.assert_called_once()
            mock_delete_volume.assert_called_once_with(self.vol)
            mock_update_clone_replication.assert_not_called()

    def test_create_cloned_volume_skips_cleanup_when_dest_not_created(self):
        self.vol.size = 5
        self.vol_other.size = 2

        with mock.patch.object(self.service,
                               '_can_do_online_clone',
                               return_value=False), \
                mock.patch.object(self.service,
                                  'create_volume',
                                  side_effect=RuntimeError(
                                      'create failed')) as \
                mock_create_volume, \
                mock.patch.object(self.service,
                                  '_copy_cloned_volume_and_wait') as \
                mock_copy_wait, \
                mock.patch.object(self.service, 'delete_volume') as \
                mock_delete_volume:
            self.assertRaises(
                exception.CinderException,
                self.service.create_cloned_volume,
                self.vol,
                self.vol_other)

            mock_create_volume.assert_called_once_with(
                self.vol, perform_replica=False)
            mock_copy_wait.assert_not_called()
            mock_delete_volume.assert_not_called()

    def test_manage_existing(self, *args, **kwargs):
        with mock.patch.object(self.service,
                               'manage_existing') as \
                mock_manage_existing:
            mock_manage_existing.return_value = mock.Mock()
            expected_result = mock_manage_existing.return_value

            existing_ref = {'source-name': 'vol_name'}
            result = self.driver.manage_existing(
                self.vol, existing_ref)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_manage_existing.assert_called_once_with(
                self.vol, existing_ref)

    def test_manage_existing_get_size(self, *args, **kwargs):
        with mock.patch.object(self.service,
                               'manage_existing_get_size') as \
                mock_manage_existing_get_size:
            mock_manage_existing_get_size.return_value = mock.Mock()
            expected_result = mock_manage_existing_get_size.return_value

            existing_ref = {'source-name': 'vol_name'}
            result = self.driver.manage_existing_get_size(
                self.vol, existing_ref)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_manage_existing_get_size.assert_called_once_with(
                self.vol, existing_ref)

    def test_unmanage(self, *args, **kwargs):
        with mock.patch.object(self.service, 'unmanage') as \
                mock_unmanage:
            mock_unmanage.return_value = mock.Mock()
            expected_result = mock_unmanage.return_value

            result = self.driver.unmanage(self.vol)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_unmanage.assert_called_once_with(self.vol)

    def test_manage_existing_snapshot(self, *args, **kwargs):
        with mock.patch.object(self.service,
                               'manage_existing_snapshot') as \
                mock_manage_existing_snapshot:
            mock_manage_existing_snapshot.return_value = mock.Mock()
            expected_result = mock_manage_existing_snapshot.return_value

            existing_ref = {'source-name': 'snap_name'}
            result = self.driver.manage_existing_snapshot(
                self.snap, existing_ref)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_manage_existing_snapshot.assert_called_once_with(
                self.snap, existing_ref)

    def test_manage_existing_snapshot_get_size(self, *args, **kwargs):
        with mock.patch.object(self.service,
                               'manage_existing_snapshot_get_size') as \
                mock_manage_existing_snap_get_size:
            mock_manage_existing_snap_get_size.return_value = mock.Mock()
            expected_result = mock_manage_existing_snap_get_size.return_value

            existing_ref = {'source-name': 'snap_name'}
            result = self.driver.manage_existing_snapshot_get_size(
                self.snap, existing_ref)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_manage_existing_snap_get_size.assert_called_once_with(
                self.snap, existing_ref)

    def test_unmanage_snapshot(self, *args, **kwargs):
        with mock.patch.object(self.service, 'unmanage_snapshot') as \
                mock_unmanage_snapshot:
            mock_unmanage_snapshot.return_value = mock.Mock()
            expected_result = mock_unmanage_snapshot.return_value

            result = self.driver.unmanage_snapshot(self.snap)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_unmanage_snapshot.assert_called_once_with(self.snap)

    def test_get_manageable_volumes(self, *args, **kwargs):
        with mock.patch.object(
                self.service, 'get_manageable_volumes') as \
                mock_get_manageable_volumes:
            mock_get_manageable_volumes.return_value = mock.Mock()
            expected_result = mock_get_manageable_volumes.return_value

            vols = [self.vol]
            marker = None
            limit = 1000
            offset = 0
            sort_keys = ['reference']
            sort_dirs = ['desc']

            result = self.driver.get_manageable_volumes(
                vols, marker, limit, offset, sort_keys, sort_dirs)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_get_manageable_volumes.assert_called_once_with(
                vols, marker, limit, offset, sort_keys, sort_dirs)

    def test_get_manageable_snapshots(self, *args, **kwargs):
        with mock.patch.object(
                self.service, 'get_manageable_snapshots') as \
                mock_get_manageable_snapshots:
            mock_get_manageable_snapshots.return_value = mock.Mock()
            expected_result = mock_get_manageable_snapshots.return_value

            snaps = [self.snap]
            marker = None
            limit = 1000
            offset = 0
            sort_keys = ['reference']
            sort_dirs = ['desc']

            result = self.driver.get_manageable_snapshots(
                snaps, marker, limit, offset, sort_keys, sort_dirs)
            self.assertIsNotNone(result)
            self.assertEqual(result, expected_result)
            mock_get_manageable_snapshots.assert_called_once_with(
                snaps, marker, limit, offset, sort_keys, sort_dirs)

    def test_failover_host(self, *args, **kwargs):
        """Test failover_host method."""
        with mock.patch.object(
                self.service, 'failover_host') as \
                mock_failover_host:
            # Setup mock return values
            active_backend_id = 'secondary_backend_id'
            volume_updates = [{'volume_id': VOLUME_ID,
                               'updates': {'replication_status':
                                           'failed-over'}}]
            group_update_list = []
            mock_failover_host.return_value = (
                active_backend_id, volume_updates, group_update_list)

            vols = [self.vol]
            secondary_id = 'secondary_backend_id'
            groups = [self.group]

            result_backend_id, result_vol_updates, result_group_updates = \
                self.driver.failover_host(
                    self.ctxt, vols, secondary_id, groups)

            self.assertEqual(result_backend_id, active_backend_id)
            self.assertEqual(result_vol_updates, volume_updates)
            self.assertEqual(result_group_updates, group_update_list)
            self.assertEqual(self.driver._active_backend_id, active_backend_id)
            mock_failover_host.assert_called_once_with(
                self.ctxt, vols, secondary_id, groups)

    def test_failover_replication(self, *args, **kwargs):
        """Test failover_replication method."""
        with mock.patch.object(
                self.service, 'failover_replication') as \
                mock_failover_replication:
            # Setup mock return values
            model_update = {'replication_status': 'failed-over'}
            vol_model_updates = [{'id': VOLUME_ID,
                                 'replication_status': 'failed-over'}]
            mock_failover_replication.return_value = (
                model_update, vol_model_updates)

            vols = [self.vol]
            secondary_backend_id = 'secondary_backend_id'

            result_model_update, result_vol_updates = \
                self.driver.failover_replication(
                    self.ctxt, self.group, vols, secondary_backend_id)

            self.assertEqual(result_model_update, model_update)
            self.assertEqual(result_vol_updates, vol_model_updates)
            mock_failover_replication.assert_called_once_with(
                self.ctxt, self.group, vols, secondary_backend_id)

    def test_retype(self, *args, **kwargs):
        """Test retype method."""
        with mock.patch.object(
                self.service, 'retype') as \
                mock_retype:
            mock_retype.return_value = True
            expected_result = mock_retype.return_value

            new_type = _fake_volume_type()
            diff = {'encryption': {}, 'qos_specs': {},
                    'extra_specs': {}}
            host = {'host': FAKE_HOST, 'capabilities': {}}

            result = self.driver.retype(
                self.ctxt, self.vol, new_type, diff, host)

            self.assertEqual(result, expected_result)
            mock_retype.assert_called_once_with(
                self.vol, new_type, diff, host)

    def test_migrate_volume(self, *args, **kwargs):
        """Test migrate_volume method."""
        with mock.patch.object(
                self.service, 'migrate_volume') as \
                mock_migrate_volume:
            mock_migrate_volume.return_value = (True, None)
            expected_result = mock_migrate_volume.return_value

            host = {
                'host': FAKE_HOST,
                'capabilities': {
                    'storage_protocol': self.driver.protocol
                }
            }

            result = self.driver.migrate_volume(
                self.ctxt, self.vol, host)

            self.assertEqual(result, expected_result)
            mock_migrate_volume.assert_called_once_with(
                self.vol, host)

    def test_update_migrated_volume(self, *args, **kwargs):
        """Test update_migrated_volume method."""
        with mock.patch.object(
                self.service, 'update_migrated_volume') as \
                mock_update_migrated_volume:
            mock_update_migrated_volume.return_value = {'_name_id': None}
            expected_result = mock_update_migrated_volume.return_value

            original_volume_status = 'available'

            result = self.driver.update_migrated_volume(
                self.ctxt, self.vol, self.vol_other, original_volume_status)

            self.assertEqual(result, expected_result)
            mock_update_migrated_volume.assert_called_once_with(
                self.ctxt, self.vol, self.vol_other, original_volume_status)


class TestHPEAlletraMPFCDriver(test.TestCase):

    def setUp(self):
        super(TestHPEAlletraMPFCDriver, self).setUp()
        self.context = context.get_admin_context()
        self.assertIsNotNone(hpe_storage_flowkit)
        self._create_fake_config()
        self.assertIsNone(self.driver.do_setup(None))
        self.service = self.driver.alletra_mp_service

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)

        self.configuration.hpe3par_debug = False
        self.configuration.hpe3par_username = HPE3PAR_USER_NAME
        self.configuration.hpe3par_password = HPE3PAR_USER_PASS
        self.configuration.hpe3par_api_url = 'https://1.1.1.1/api/v1'
        self.configuration.hpe3par_cpg = [HPE3PAR_CPG, HPE3PAR_CPG2]
        self.configuration.hpe3par_cpg_snap = HPE3PAR_CPG_SNAP

        self.configuration.san_ip = HPE3PAR_SAN_IP
        self.configuration.san_login = HPE3PAR_USER_NAME
        self.configuration.san_password = HPE3PAR_USER_PASS
        self.configuration.replication_device = None
        _apply_common_backend_config(self.configuration)

        self.ctxt = context.get_admin_context()
        self.vol = fake_volume.fake_volume_obj(self.context)
        self.vol.volume_type = fake_volume.fake_volume_type_obj(self.context)
        self.snap = fake_snapshot.fake_snapshot_obj(self.context)
        self.snap.volume = self.vol
        self.driver = alletramp.HPEAlletraMPFCDriver(
            configuration=self.configuration)
        self.vol_other = fake_volume.fake_volume_obj(self.context)

    def test_initialize_connection_without_multipath(self, *args, **kwargs):
        """Test FC initialize_connection without multipath."""
        connector = {
            'wwpns': ['1234567890123456'],
            'multipath': False
        }

        host = {'name': 'test-host'}
        cpg = 'test-cpg'
        target_wwns = ['5001234567890ABC']
        init_targ_map = {
            '1234567890123456': ['5001234567890ABC']
        }
        numPaths = 1
        vlun = {'lun': 1}

        with mock.patch.object(
                self.service, '_create_host_fc') as mock_create_host, \
                mock.patch.object(
                    self.service, '_build_initiator_target_map') as \
                mock_build_map, \
                mock.patch.object(
                    self.service, 'find_existing_vlun') as \
                mock_find_vlun, \
                mock.patch.object(
                    self.service, 'create_vlun') as mock_create_vlun, \
                mock.patch.object(
                    self.service, '_get_user_target') as \
                mock_get_user_target:

            mock_create_host.return_value = (host, cpg)
            mock_build_map.return_value = (target_wwns, init_targ_map,
                                           numPaths)
            mock_find_vlun.return_value = None
            mock_create_vlun.return_value = vlun
            mock_get_user_target.return_value = None

            result = self.driver.initialize_connection(self.vol, connector)

            self.assertIsNotNone(result)
            self.assertEqual(result['driver_volume_type'], 'fibre_channel')
            self.assertEqual(result['data']['target_lun'], 1)
            self.assertEqual(result['data']['encrypted'], False)
            mock_create_host.assert_called_once()
            mock_build_map.assert_called_once()
            mock_create_vlun.assert_called_once()

    def test_initialize_connection_with_multipath(self, *args, **kwargs):
        """Test FC initialize_connection with multipath."""
        connector = {
            'wwpns': ['1234567890123456', '1234567890123457'],
            'multipath': True
        }

        host = {'name': 'test-host'}
        cpg = 'test-cpg'
        target_wwns = ['5001234567890ABC', '5001234567890ABD']
        init_targ_map = {
            '1234567890123456': ['5001234567890ABC', '5001234567890ABD'],
            '1234567890123457': ['5001234567890ABC', '5001234567890ABD']
        }
        numPaths = 4
        vlun = {'lun': 1}

        with mock.patch.object(
                self.service, '_create_host_fc') as mock_create_host, \
                mock.patch.object(
                    self.service, '_build_initiator_target_map') as \
                mock_build_map, \
                mock.patch.object(
                    self.service, 'find_existing_vlun') as \
                mock_find_vlun, \
                mock.patch.object(
                    self.service, 'create_vlun') as mock_create_vlun:

            mock_create_host.return_value = (host, cpg)
            mock_build_map.return_value = (target_wwns, init_targ_map,
                                           numPaths)
            mock_find_vlun.return_value = None
            mock_create_vlun.return_value = vlun

            result = self.driver.initialize_connection(self.vol, connector)

            self.assertIsNotNone(result)
            self.assertEqual(result['driver_volume_type'], 'fibre_channel')
            self.assertEqual(result['data']['target_lun'], 1)
            self.assertEqual(result['data']['target_wwn'], target_wwns)
            self.assertEqual(result['data']['encrypted'], False)
            mock_create_host.assert_called_once()
            mock_build_map.assert_called_once()
            mock_create_vlun.assert_called_once()

    def test_initialize_connection_with_existing_vlun(self, *args, **kwargs):
        """Test FC initialize_connection with existing VLUN."""
        connector = {
            'wwpns': ['1234567890123456'],
            'multipath': True
        }

        host = {'name': 'test-host'}
        cpg = 'test-cpg'
        target_wwns = ['5001234567890ABC']
        init_targ_map = {
            '1234567890123456': ['5001234567890ABC']
        }
        numPaths = 1
        existing_vlun = {'lun': 2, 'active': True}

        with mock.patch.object(
                self.service, '_create_host_fc') as mock_create_host, \
                mock.patch.object(
                    self.service, '_build_initiator_target_map') as \
                mock_build_map, \
                mock.patch.object(
                    self.service, 'find_existing_vlun') as \
                mock_find_vlun, \
                mock.patch.object(
                    self.service, 'create_vlun') as mock_create_vlun:

            mock_create_host.return_value = (host, cpg)
            mock_build_map.return_value = (target_wwns, init_targ_map,
                                           numPaths)
            mock_find_vlun.return_value = existing_vlun

            result = self.driver.initialize_connection(self.vol, connector)

            self.assertIsNotNone(result)
            self.assertEqual(result['driver_volume_type'], 'fibre_channel')
            self.assertEqual(result['data']['target_lun'], 2)
            mock_create_host.assert_called_once()
            mock_build_map.assert_called_once()
            # create_vlun should NOT be called when existing VLUN is found
            mock_create_vlun.assert_not_called()

    def test_terminate_connection_force_detach(self, *args, **kwargs):
        """Test FC terminate_connection with force detach."""
        connector = None  # Force detach scenario

        with mock.patch.object(
                self.service, 'terminate_connection') as \
                mock_terminate:

            result = self.driver.terminate_connection(
                self.vol, connector)

            self.assertIsNotNone(result)
            self.assertEqual(result['driver_volume_type'], 'fibre_channel')
            self.assertIn('data', result)
            mock_terminate.assert_called_once_with(
                self.vol, None, None)

    def test_terminate_connection_with_zone_removal(self, *args, **kwargs):
        """Test FC terminate_connection with FC zone removal."""
        connector = {
            'wwpns': ['1234567890123456'],
            'multipath': True
        }

        hostname = 'test-host'
        target_wwns = ['5001234567890ABC']
        init_targ_map = {
            '1234567890123456': ['5001234567890ABC']
        }

        with mock.patch.object(
                self.service, '_safe_hostname') as mock_safe_hostname:
            with mock.patch.object(
                    self.driver, '_is_multiattach') as mock_multiattach:
                with mock.patch.object(
                        self.service, 'terminate_connection') as \
                        mock_terminate:
                    with mock.patch.object(
                            self.service,
                            '_build_initiator_target_map') as mock_build_map:
                        with mock.patch(ALLETRAMP_VLUN_WORKFLOW) as \
                                mock_vlun_workflow:

                            mock_safe_hostname.return_value = hostname
                            mock_multiattach.return_value = False
                            mock_build_map.return_value = (
                                target_wwns, init_targ_map, 1)

                            # Mock VLUNWorkflow instance to raise exception.
                            mock_vlun_wf_instance = mock.Mock()
                            mock_vlun_wf_instance.getHostVLUNs.side_effect = (
                                hpe_storage_flowkit.flowkit_exceptions.
                                HPEStorageException())
                            mock_vlun_workflow.return_value = (
                                mock_vlun_wf_instance)

                            result = self.driver.terminate_connection(
                                self.vol, connector)

                            self.assertIsNotNone(result)
                            self.assertEqual(
                                result['driver_volume_type'],
                                'fibre_channel')
                            self.assertIn('target_wwn', result['data'])
                            self.assertEqual(
                                result['data']['target_wwn'], target_wwns)
                            self.assertIn(
                                'initiator_target_map', result['data'])
                            mock_terminate.assert_called_once()
                            mock_build_map.assert_called_once()

    def test_terminate_connection_without_zone_removal(self, *args, **kwargs):
        """Test FC terminate_connection without FC zone removal."""
        connector = {
            'wwpns': ['1234567890123456'],
            'multipath': True
        }

        hostname = 'test-host'
        vluns = [
            {
                'active': True,
                'remoteName': '1234567890123456'
            }
        ]

        with mock.patch.object(
                self.service, '_safe_hostname') as mock_safe_hostname:
            with mock.patch.object(
                    self.driver, '_is_multiattach') as mock_multiattach:
                with mock.patch.object(
                        self.service, 'terminate_connection') as \
                        mock_terminate:
                    with mock.patch(ALLETRAMP_VLUN_WORKFLOW) as \
                            mock_vlun_workflow:

                        mock_safe_hostname.return_value = hostname
                        mock_multiattach.return_value = False

                        # Mock VLUNWorkflow instance to return existing VLUNs.
                        mock_vlun_wf_instance = mock.Mock()
                        mock_vlun_wf_instance.getHostVLUNs.return_value = vluns
                        mock_vlun_workflow.return_value = mock_vlun_wf_instance

                        result = self.driver.terminate_connection(
                            self.vol, connector)

                        self.assertIsNotNone(result)
                        self.assertEqual(
                            result['driver_volume_type'], 'fibre_channel')
                        self.assertEqual(result['data'], {})
                        mock_terminate.assert_called_once()

    def test_terminate_connection_multiattach(self, *args, **kwargs):
        """Test FC terminate_connection with multiattach volume."""
        connector = {
            'wwpns': ['1234567890123456'],
            'multipath': True
        }

        hostname = 'test-host'
        vluns = [
            {
                'active': True,
                'remoteName': '1234567890123456'
            }
        ]

        with mock.patch.object(
                self.service, '_safe_hostname') as mock_safe_hostname:
            with mock.patch.object(
                    self.driver, '_is_multiattach') as mock_multiattach:
                with mock.patch.object(
                        self.service, 'terminate_connection') as \
                        mock_terminate:
                    with mock.patch(ALLETRAMP_VLUN_WORKFLOW) as \
                            mock_vlun_workflow:

                        mock_safe_hostname.return_value = hostname
                        mock_multiattach.return_value = True

                        # Mock VLUNWorkflow instance to return existing VLUNs.
                        mock_vlun_wf_instance = mock.Mock()
                        mock_vlun_wf_instance.getHostVLUNs.return_value = vluns
                        mock_vlun_workflow.return_value = mock_vlun_wf_instance

                        result = self.driver.terminate_connection(
                            self.vol, connector)

                        self.assertIsNotNone(result)
                        self.assertEqual(
                            result['driver_volume_type'], 'fibre_channel')
                        self.assertEqual(result['data'], {})
                        mock_terminate.assert_not_called()


class TestHPEAlletraMPISCSIDriver(test.TestCase):

    def setUp(self):
        super(TestHPEAlletraMPISCSIDriver, self).setUp()
        self.context = context.get_admin_context()
        self.assertIsNotNone(hpe_storage_flowkit)
        self._create_fake_config()

        with mock.patch.object(
                alletramp.HPEAlletraMPISCSIDriver,
                'initialize_iscsi_ports'):
            self.assertIsNone(self.driver.do_setup(None))
        self.service = self.driver.alletra_mp_service

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)

        self.configuration.hpe3par_debug = False
        self.configuration.hpe3par_username = HPE3PAR_USER_NAME
        self.configuration.hpe3par_password = HPE3PAR_USER_PASS
        self.configuration.hpe3par_api_url = 'https://1.1.1.1/api/v1'
        self.configuration.hpe3par_cpg = [HPE3PAR_CPG, HPE3PAR_CPG2]
        self.configuration.hpe3par_cpg_snap = HPE3PAR_CPG_SNAP
        self.configuration.hpe3par_iscsi_ips = ['10.10.10.10', '10.10.10.11']
        self.configuration.hpe3par_iscsi_chap_enabled = False

        self.configuration.san_ip = HPE3PAR_SAN_IP
        self.configuration.san_login = HPE3PAR_USER_NAME
        self.configuration.san_password = HPE3PAR_USER_PASS
        self.configuration.replication_device = None
        _apply_common_backend_config(self.configuration)

        self.ctxt = context.get_admin_context()
        self.vol = fake_volume.fake_volume_obj(self.context)
        self.vol.volume_type = fake_volume.fake_volume_type_obj(self.context)
        self.snap = fake_snapshot.fake_snapshot_obj(self.context)
        self.snap.volume = self.vol
        self.driver = alletramp.HPEAlletraMPISCSIDriver(
            configuration=self.configuration)
        self.vol_other = fake_volume.fake_volume_obj(self.context)

    def test_initialize_connection_single_path(self, *args, **kwargs):
        """Test iSCSI initialize_connection without multipath (single path)."""
        connector = {
            'initiator': 'iqn.1993-08.org.debian:01:222',
            'multipath': False
        }

        host = {'name': 'test-host'}
        username = 'test-user'
        password = 'test-password'
        cpg = 'test-cpg'
        vlun = {'lun': 1}
        iscsi_ips = {
            '10.10.10.10': {
                'ip_port': '3260',
                'iqn': 'iqn.2000-05.com.3pardata:21210002ac00383d',
                'nsp': '0:2:1'
            }
        }

        with mock.patch.object(
                self.service, '_create_host_iscsi') as \
                mock_create_host, \
                mock.patch.object(
                    self.service, 'find_existing_vlun') as \
                mock_find_vlun, \
                mock.patch.object(
                    self.service, 'create_vlun') as mock_create_vlun, \
                mock.patch.object(
                    self.service, '_get_least_used_nsp_for_host') as \
                mock_least_nsp, \
                mock.patch.object(
                    self.service, '_get_ip_using_nsp') as \
                mock_get_ip:

            mock_create_host.return_value = (host, username, password, cpg)
            mock_find_vlun.return_value = None
            mock_create_vlun.return_value = vlun
            mock_least_nsp.return_value = '0:2:1'
            mock_get_ip.return_value = '10.10.10.10'
            self.driver.iscsi_ips = {
                self.configuration.hpe3par_api_url: iscsi_ips
            }

            result = self.driver.initialize_connection(self.vol, connector)

            self.assertIsNotNone(result)
            self.assertEqual(result['driver_volume_type'], 'iscsi')
            self.assertEqual(result['data']['target_lun'], 1)
            self.assertEqual(result['data']['target_discovered'], True)
            self.assertIn('target_portal', result['data'])
            self.assertIn('target_iqn', result['data'])
            self.assertEqual(result['data']['encrypted'], False)
            mock_create_host.assert_called_once()
            mock_create_vlun.assert_called_once()

    def test_initialize_connection_multipath(self, *args, **kwargs):
        """Test iSCSI initialize_connection with multipath."""
        connector = {
            'initiator': 'iqn.1993-08.org.debian:01:222',
            'multipath': True
        }

        host = {'name': 'test-host'}
        username = 'test-user'
        password = 'test-password'
        cpg = 'test-cpg'
        iscsi_ips = {
            '10.10.10.10': {
                'ip_port': '3260',
                'iqn': 'iqn.2000-05.com.3pardata:21210002ac00383d',
                'nsp': '0:2:1'
            },
            '10.10.10.11': {
                'ip_port': '3260',
                'iqn': 'iqn.2000-05.com.3pardata:21210002ac00383e',
                'nsp': '1:2:1'
            }
        }
        connection_targets = {
            'target_portals': ['10.10.10.10:3260', '10.10.10.11:3260'],
            'target_iqns': [
                'iqn.2000-05.com.3pardata:21210002ac00383d',
                'iqn.2000-05.com.3pardata:21210002ac00383e'
            ],
            'target_luns': [1, 1]
        }

        with mock.patch.object(
                self.service, '_create_host_iscsi') as \
                mock_create_host, \
                mock.patch.object(
                    self.service,
                    'initialize_iscsi_multipath_targets') as \
                mock_init_targets:

            mock_create_host.return_value = (host, username, password, cpg)
            mock_init_targets.return_value = connection_targets
            self.driver.iscsi_ips = {
                self.configuration.hpe3par_api_url: iscsi_ips
            }

            result = self.driver.initialize_connection(self.vol, connector)

            self.assertIsNotNone(result)
            self.assertEqual(result['driver_volume_type'], 'iscsi')
            self.assertEqual(result['data']['target_discovered'], True)
            self.assertIn('target_portals', result['data'])
            self.assertIn('target_iqns', result['data'])
            self.assertIn('target_luns', result['data'])
            self.assertEqual(len(result['data']['target_portals']), 2)
            self.assertEqual(len(result['data']['target_iqns']), 2)
            self.assertEqual(len(result['data']['target_luns']), 2)
            self.assertEqual(result['data']['encrypted'], False)
            mock_create_host.assert_called_once()
            mock_init_targets.assert_called_once_with(
                self.vol, connector, host, iscsi_ips, cpg)

    def test_initialize_connection_multipath_with_chap(self, *args, **kwargs):
        """Test iSCSI initialize_connection with multipath and CHAP enabled."""
        connector = {
            'initiator': 'iqn.1993-08.org.debian:01:222',
            'multipath': True
        }

        host = {'name': 'test-host'}
        username = 'chap-user'
        password = 'chap-password'
        cpg = 'test-cpg'
        iscsi_ips = {
            '10.10.10.10': {
                'ip_port': '3260',
                'iqn': 'iqn.2000-05.com.3pardata:21210002ac00383d',
                'nsp': '0:2:1'
            }
        }
        connection_targets = {
            'target_portals': ['10.10.10.10:3260'],
            'target_iqns': ['iqn.2000-05.com.3pardata:21210002ac00383d'],
            'target_luns': [1]
        }

        # Enable CHAP in the driver's internal client configuration
        self.service._client_conf['hpe3par_iscsi_chap_enabled'] = True

        with mock.patch.object(self.service, '_create_host_iscsi') as \
                mock_create_host:
            with mock.patch.object(
                    self.service,
                    'initialize_iscsi_multipath_targets') as \
                    mock_init_targets:

                mock_create_host.return_value = (
                    host, username, password, cpg)
                mock_init_targets.return_value = connection_targets
                self.driver.iscsi_ips = {
                    self.configuration.hpe3par_api_url: iscsi_ips
                }

                result = self.driver.initialize_connection(
                    self.vol, connector)

            self.assertIsNotNone(result)
            self.assertEqual(result['driver_volume_type'], 'iscsi')
            self.assertEqual(result['data']['auth_method'], 'CHAP')
            self.assertEqual(result['data']['auth_username'], username)
            self.assertEqual(result['data']['auth_password'], password)
            mock_create_host.assert_called_once()
            mock_init_targets.assert_called_once_with(
                self.vol, connector, host, iscsi_ips, cpg)

    def test_set_alletramp_chaps_uses_constants(self):
        self.service._client_conf['hpe3par_iscsi_chap_enabled'] = True

        with mock.patch(ALLETRAMP_HOST_WORKFLOW) as mock_host_workflow:
            host_wf_instance = mock.Mock()
            mock_host_workflow.return_value = host_wf_instance

            self.service._set_alletramp_chaps(
                'test-host', self.vol, 'chap-user', 'chap-password')

            host_wf_instance.modify_host.assert_called_once_with(
                'test-host',
                {'chapOperation': alletramp_service.constants.HOST_EDIT_ADD,
                 'chapOperationMode': (
                     alletramp_service.constants.CHAP_INITIATOR),
                 'chapName': 'chap-user',
                 'chapSecret': 'chap-password'})

    def test_modify_alletramp_iscsi_host_uses_constants(self):
        with mock.patch(ALLETRAMP_HOST_WORKFLOW) as mock_host_workflow:
            host_wf_instance = mock.Mock()
            mock_host_workflow.return_value = host_wf_instance

            self.service._modify_alletramp_iscsi_host(
                'test-host', 'iqn.1993-08.org.debian:01:222')

            host_wf_instance.modify_host.assert_called_once_with(
                'test-host',
                {'pathOperation': alletramp_service.constants.HOST_EDIT_ADD,
                 'iSCSINames': ['iqn.1993-08.org.debian:01:222']})

    def test_terminate_connection_force_detach(self, *args, **kwargs):
        """Test iSCSI terminate_connection with force detach."""
        connector = None  # Force detach scenario

        with mock.patch.object(
                self.service,
                'terminate_iscsi_connection') as mock_terminate:
            self.driver.terminate_connection(self.vol, connector)

            mock_terminate.assert_called_once_with(self.vol, connector)

    def test_terminate_connection_multipath(self, *args, **kwargs):
        """Test iSCSI terminate_connection with multipath."""
        connector = {
            'initiator': 'iqn.1993-08.org.debian:01:222',
            'multipath': True
        }

        with mock.patch.object(
                self.service,
                'terminate_iscsi_connection') as mock_terminate:

            self.driver.terminate_connection(self.vol, connector)

            mock_terminate.assert_called_once_with(self.vol, connector)

    def test_terminate_connection_multiattach(self, *args, **kwargs):
        """Test iSCSI terminate_connection with multiattach volume."""
        connector = {
            'initiator': 'iqn.1993-08.org.debian:01:222',
            'multipath': True,
            'host': 'test-host'
        }

        with mock.patch.object(
                self.service,
                'terminate_iscsi_connection') as mock_terminate:

            self.driver.terminate_connection(self.vol, connector)

            mock_terminate.assert_called_once_with(self.vol, connector)


class TestHPEAlletraMPNVMETCPDriver(test.TestCase):

    def setUp(self):
        super(TestHPEAlletraMPNVMETCPDriver, self).setUp()
        self.context = context.get_admin_context()
        self.assertIsNotNone(hpe_storage_flowkit)
        self._create_fake_config()
        # Mock initialize_nvme_ips_and_ports to avoid initialization issues
        with mock.patch.object(
                alletramp.HPEAlletraMPNVMETCPDriver,
                'initialize_nvme_ips_and_ports'):
            self.assertIsNone(self.driver.do_setup(None))
        self.service = self.driver.alletra_mp_service

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)

        self.configuration.hpe3par_debug = False
        self.configuration.hpe3par_username = HPE3PAR_USER_NAME
        self.configuration.hpe3par_password = HPE3PAR_USER_PASS
        self.configuration.hpe3par_api_url = 'https://1.1.1.1/api/v1'
        self.configuration.hpe3par_cpg = [HPE3PAR_CPG, HPE3PAR_CPG2]
        self.configuration.hpe3par_cpg_snap = HPE3PAR_CPG_SNAP

        self.configuration.san_ip = HPE3PAR_SAN_IP
        self.configuration.san_login = HPE3PAR_USER_NAME
        self.configuration.san_password = HPE3PAR_USER_PASS
        self.configuration.replication_device = None
        _apply_common_backend_config(self.configuration)

        self.ctxt = context.get_admin_context()
        self.vol = fake_volume.fake_volume_obj(self.context)
        self.vol.volume_type = fake_volume.fake_volume_type_obj(self.context)
        self.snap = fake_snapshot.fake_snapshot_obj(self.context)
        self.snap.volume = self.vol
        self.driver = alletramp.HPEAlletraMPNVMETCPDriver(
            configuration=self.configuration)
        self.vol_other = fake_volume.fake_volume_obj(self.context)
        self.nqn = 'nqn.2014-08.org.nvmexpress:uuid:12345678-1234-123456789abc'

    def test_initialize_connection(self, *args, **kwargs):
        """Test NVMe-oF TCP initialize_connection."""
        connector = {
            'nqn': self.nqn,
            'host': 'test-host'
        }

        host = {
            'name': 'test-host',
            'id': 1
        }
        vlun = {
            'lun': 1,
            'active': True
        }
        storage_volume = {
            'nguid': '00112233445566778899aabbccddeeff',
            'name': 'volume-' + VOLUME_ID
        }
        portals = [
            '10.10.10.10:4420',
            '10.10.10.11:4420'
        ]
        target_nqns = [
            'nqn.2000-05.com.3pardata:21210002ac00383d'
        ]
        nvme_ips = {
            '10.10.10.10': {
                'ip_port': '4420',
                'nsp': '0:2:1'
            },
            '10.10.10.11': {
                'ip_port': '4420',
                'nsp': '1:2:1'
            }
        }

        with mock.patch(ALLETRAMP_VLUN_WORKFLOW) as mock_vlun_workflow:
            with mock.patch(ALLETRAMP_VOLUME_WORKFLOW) as \
                    mock_vol_workflow:

                # Mock VLUNWorkflow instance
                mock_vlun_wf_instance = mock.Mock()
                mock_vlun_wf_instance.getHostByNqn.return_value = host
                mock_vlun_wf_instance.create_vlun_nvme.return_value = (
                    portals, target_nqns)
                mock_vlun_wf_instance.getVLUN.return_value = vlun
                mock_vlun_workflow.return_value = mock_vlun_wf_instance

                # Mock VolumeWorkflow instance
                mock_vol_wf_instance = mock.Mock()
                mock_vol_wf_instance.get_volume.return_value = storage_volume
                mock_vol_workflow.return_value = mock_vol_wf_instance

                # Setup nvme_ips on driver
                self.driver.nvme_ips = {
                    self.configuration.hpe3par_api_url: nvme_ips
                }

                result = self.driver.initialize_connection(
                    self.vol, connector)

                self.assertIsNotNone(result)
                self.assertEqual(result['driver_volume_type'], 'nvmeof')
                self.assertEqual(result['data']['target_lun'], 1)
                self.assertEqual(
                    result['data']['host_nqn'], connector['nqn'])
                self.assertEqual(
                    result['data']['target_nqn'], target_nqns[0])
                self.assertEqual(result['data']['vol_uuid'],
                                 storage_volume['nguid'])
                self.assertEqual(result['data']['access_mode'], 'rw')
                self.assertIn('portals', result['data'])
                self.assertEqual(len(result['data']['portals']), 2)
                mock_vlun_wf_instance.getHostByNqn.assert_called_once_with(
                    connector['nqn'])
                mock_vlun_wf_instance.create_vlun_nvme.assert_called_once()

    def test_initialize_connection_host_not_found(self, *args, **kwargs):
        """Test NVMe-oF TCP initialize_connection when host not found."""
        connector = {
            'nqn': self.nqn,
            'host': 'test-host'
        }

        nvme_ips = {
            '10.10.10.10': {
                'ip_port': '4420',
                'nsp': '0:2:1'
            }
        }

        with mock.patch(ALLETRAMP_VLUN_WORKFLOW) as mock_vlun_workflow:
            with mock.patch(ALLETRAMP_VOLUME_WORKFLOW) as \
                    mock_vol_workflow:

                # Mock VLUNWorkflow instance - host not found
                mock_vlun_wf_instance = mock.Mock()
                mock_vlun_wf_instance.getHostByNqn.return_value = None
                mock_vlun_workflow.return_value = mock_vlun_wf_instance

                # Mock VolumeWorkflow instance
                mock_vol_wf_instance = mock.Mock()
                mock_vol_workflow.return_value = mock_vol_wf_instance

                # Setup nvme_ips on driver
                self.driver.nvme_ips = {
                    self.configuration.hpe3par_api_url: nvme_ips
                }

                # Should raise exception when host not found
                self.assertRaisesRegex(
                    Exception,
                    "Host not found with nqn",
                    self.driver.initialize_connection,
                    self.vol,
                    connector)

    def test_terminate_connection(self, *args, **kwargs):
        """Test NVMe-oF TCP terminate_connection."""
        connector = {
            'nqn': self.nqn,
            'host': 'test-host'
        }

        host = {
            'name': 'test-host',
            'id': 1
        }

        with mock.patch(ALLETRAMP_VLUN_WORKFLOW) \
                as mock_vlun_workflow, \
                mock.patch.object(
                    self.driver, '_is_multiattach') as mock_multiattach:

            # Mock VLUNWorkflow instance
            mock_vlun_wf_instance = mock.Mock()
            mock_vlun_wf_instance.getHostByNqn.return_value = host
            mock_vlun_workflow.return_value = mock_vlun_wf_instance

            mock_multiattach.return_value = False

            self.driver.terminate_connection(self.vol, connector)

            mock_vlun_wf_instance.getHostByNqn.assert_called_once_with(
                connector['nqn'])
            mock_vlun_wf_instance.remove_vlun_nvme.assert_called_once()

    def test_terminate_connection_multiattach(self, *args, **kwargs):
        """Test NVMe-oF TCP terminate_connection with multiattach volume."""
        connector = {
            'nqn': self.nqn,
            'host': 'test-host'
        }

        with mock.patch(ALLETRAMP_VLUN_WORKFLOW) \
                as mock_vlun_workflow, \
                mock.patch.object(
                    self.driver, '_is_multiattach') as mock_multiattach:

            # Mock VLUNWorkflow instance
            mock_vlun_wf_instance = mock.Mock()
            mock_vlun_workflow.return_value = mock_vlun_wf_instance

            # Multiattach returns True, skip termination
            mock_multiattach.return_value = True

            self.driver.terminate_connection(self.vol, connector)

            # When multiattach is True, terminate should return early
            # without calling remove_vlun_nvme
            mock_vlun_wf_instance.remove_vlun_nvme.assert_not_called()

    def test_terminate_connection_force_detach(self, *args, **kwargs):
        """Test NVMe-oF TCP terminate_connection with force detach."""
        connector = None  # Force detach scenario

        with mock.patch(ALLETRAMP_VLUN_WORKFLOW) \
                as mock_vlun_workflow:

            # Mock VLUNWorkflow instance
            mock_vlun_wf_instance = mock.Mock()
            mock_vlun_workflow.return_value = mock_vlun_wf_instance

            self.driver.terminate_connection(self.vol, connector)

            # In force detach scenario, remove_vlun_nvme should still be called
            # but without host lookup
            mock_vlun_wf_instance.remove_vlun_nvme.assert_called_once()
