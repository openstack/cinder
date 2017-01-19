# Copyright (c) 2016 FalconStor, Inc.
# All Rights Reserved.
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

from copy import deepcopy
import mock
import time

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.falconstor import fc
from cinder.volume.drivers.falconstor import iscsi
from cinder.volume.drivers.falconstor import rest_proxy as proxy


DRIVER_PATH = "cinder.volume.drivers.falconstor"
BASE_DRIVER = DRIVER_PATH + ".fss_common.FalconstorBaseDriver"
ISCSI_DRIVER = DRIVER_PATH + ".iscsi.FSSISCSIDriver"

PRIMARY_IP = '10.0.0.1'
SECONDARY_IP = '10.0.0.2'
FAKE_ID = 123
FAKE_SINGLE_POOLS = {'A': 1}
FAKE_MULTIPLE_POOLS = {'P': 1, 'O': 2}
FAKE = 'fake'
FAKE_HOST = 'fakehost'
API_RESPONSE = {'rc': 0}
ISCSI_VOLUME_BACKEND_NAME = "FSSISCSIDriver"
SESSION_ID = "a76d506c-abcd-1234-efgh-710e1fd90527"
VOLUME_ID = '6068ea6d-f221-4213-bde9-f1b50aecdf36'
ADD_VOLUME_ID = '6068ed7f-f231-4283-bge9-f1b51aecdf36'
GROUP_ID = 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'

PORTAL_RESPONSE = {'rc': 0, 'ipaddress': FAKE}
VOLUME_METADATA = {'metadata': {'FSS-vid': 1}}
EXTENT_NEW_SIZE = 3
DATA_SERVER_INFO = 0, {'metadata': {'vendor': 'FalconStor', 'version': '1.5'}}

FSS_SINGLE_TYPE = 'single'
RAWTIMESTAMP = '1324975390'

VOLUME = {'id': VOLUME_ID,
          'name': "volume-" + VOLUME_ID,
          'display_name': 'fake_volume',
          'display_description': '',
          'size': 1,
          'host': "hostname@backend#%s" % FAKE_ID,
          'volume_type': None,
          'volume_type_id': None,
          'consistencygroup_id': None,
          'volume_metadata': [],
          'metadata': {"Type": "work"}}

SRC_VOL_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbc"
SRC_VOL = {
    "name": "volume-" + SRC_VOL_ID,
    "id": SRC_VOL_ID,
    "display_name": "fake_src_vol",
    "size": 1,
    "host": "hostname@backend#%s" % FAKE_ID,
    "volume_type": None,
    "volume_type_id": None,
    "volume_size": 1
}

VOLUME_NAME = 'cinder-' + VOLUME['id']
SRC_VOL_NAME = 'cinder-' + SRC_VOL['id']
DATA_OUTPUT = VOLUME_NAME, VOLUME_METADATA
SNAPSHOT_METADATA = {'fss-tm-comment': None}

ADD_VOLUME_IN_CG = {
    'id': ADD_VOLUME_ID,
    'display_name': 'abc123',
    'display_description': '',
    'size': 1,
    'consistencygroup_id': GROUP_ID,
    'status': 'available',
    'host': "hostname@backend#%s" % FAKE_ID}

REMOVE_VOLUME_IN_CG = {
    'id': 'fe2dbc515810451dab2f8c8a48d15bee',
    'display_name': 'fe2dbc515810451dab2f8c8a48d15bee',
    'display_description': '',
    'size': 1,
    'consistencygroup_id': GROUP_ID,
    'status': 'available',
    'host': "hostname@backend#%s" % FAKE_ID}

CONSISTGROUP = {'id': GROUP_ID,
                'name': 'fake_group',
                'description': 'fake_group_des',
                'status': ''}
CG_SNAPSHOT = {
    'consistencygroup_id': GROUP_ID,
    'id': '3c61b0f9-842e-46bf-b061-5e0031d8083f',
    'name': 'cgsnapshot1',
    'description': 'cgsnapshot1',
    'status': ''}

SNAPSHOT_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbb"
ENCODED_SNAPSHOT_ID = "cinder-8W45SsgKTG2dnSUHoiQeuA"
SNAPSHOT = {'name': "snapshot-" + SNAPSHOT_ID,
            'id': SNAPSHOT_ID,
            'volume_id': VOLUME_ID,
            'volume_name': "volume-" + VOLUME_ID,
            'volume_size': 2,
            'display_name': "fake_snapshot",
            'display_description': '',
            'volume': VOLUME,
            'metadata': SNAPSHOT_METADATA,
            'status': ''}
SNAPSHOT_LONG_NAME = {
    'name': "SnapshotsActionsV1Test-Snapshot-" + SNAPSHOT_ID,
    'id': SNAPSHOT_ID,
    'volume_id': VOLUME_ID,
    'volume_size': 2,
    'display_name': 'SnapshotsActionsV1Test-Snapshot-901108447',
    'volume': VOLUME,
    'metadata': SNAPSHOT_METADATA,
    'status': ''}

INITIATOR_IQN = 'iqn.2015-08.org.falconstor:01:fss'
TARGET_IQN = "iqn.2015-06.com.falconstor:freestor.fss-12345abc"
TARGET_PORT = "3260"
ISCSI_PORT_NAMES = ["ct0.eth2", "ct0.eth3", "ct1.eth2", "ct1.eth3"]
ISCSI_IPS = ["10.0.0." + str(i + 1) for i in range(len(ISCSI_PORT_NAMES))]

ISCSI_PORTS = {"iqn": TARGET_IQN, "lun": 1}
ISCSI_CONNECTOR = {'initiator': INITIATOR_IQN,
                   'host': "hostname@backend#%s" % FAKE_ID}
ISCSI_INFO = {
    'driver_volume_type': 'iscsi',
    'data': {
        'target_discovered': True,
        'discard': True,
        'encrypted': False,
        'qos_specs': None,
        'access_mode': 'rw',
        'volume_id': VOLUME_ID,
        'target_iqn': ISCSI_PORTS['iqn'],
        'target_portal': ISCSI_IPS[0] + ':' + TARGET_PORT,
        'target_lun': 1
    },
}

ISCSI_MULTIPATH_INFO = {
    'driver_volume_type': 'iscsi',
    'data''data': {
        'target_discovered': False,
        'discard': True,
        'encrypted': False,
        'qos_specs': None,
        'access_mode': 'rw',
        'volume_id': VOLUME_ID,
        'target_iqns': [ISCSI_PORTS['iqn']],
        'target_portals': [ISCSI_IPS[0] + ':' + TARGET_PORT],
        'target_luns': [1]
    },
}

FC_INITIATOR_WWPNS = ['2100000d778301c3', '2101000d77a301c3']
FC_TARGET_WWPNS = ['11000024ff2d2ca4', '11000024ff2d2ca5',
                   '11000024ff2d2c23', '11000024ff2d2c24']
FC_WWNS = ['20000024ff2d2ca4', '20000024ff2d2ca5',
           '20000024ff2d2c23', '20000024ff2d2c24']
FC_CONNECTOR = {'ip': '10.10.0.1',
                'initiator': 'iqn.1988-08.org.oracle:568eb4ccbbcc',
                'wwpns': FC_INITIATOR_WWPNS,
                'wwnns': FC_WWNS,
                'host': FAKE_HOST,
                'multipath': False}
FC_INITIATOR_TARGET_MAP = {
    FC_INITIATOR_WWPNS[0]: [FC_TARGET_WWPNS[0], FC_TARGET_WWPNS[1]],
    FC_INITIATOR_WWPNS[1]: [FC_TARGET_WWPNS[2], FC_TARGET_WWPNS[3]]
}
FC_DEVICE_MAPPING = {
    "fabric": {
        'initiator_port_wwn_list': FC_INITIATOR_WWPNS,
        'target_port_wwn_list': FC_WWNS
    }
}

FC_INFO = {
    'driver_volume_type': 'fibre_channel',
    'data': {
        'target_discovered': True,
        'volume_id': VOLUME_ID,
        'target_lun': 1,
        'target_wwn': FC_TARGET_WWPNS,
        'initiator_target_map': FC_INITIATOR_TARGET_MAP
    }
}


def Fake_sleep(time):
    pass


class FSSDriverTestCase(test.TestCase):

    def setUp(self):
        super(FSSDriverTestCase, self).setUp()
        self.mock_config = mock.Mock()
        self.mock_config.san_ip = PRIMARY_IP
        self.mock_config.san_login = FAKE
        self.mock_config.san_password = FAKE
        self.mock_config.fss_pools = FAKE_SINGLE_POOLS
        self.mock_config.san_is_local = False
        self.mock_config.fss_debug = False
        self.mock_config.additional_retry_list = False
        self.mock_object(time, 'sleep', Fake_sleep)


class TestFSSISCSIDriver(FSSDriverTestCase):
    def __init__(self, method):
        super(TestFSSISCSIDriver, self).__init__(method)

    def setUp(self):
        super(TestFSSISCSIDriver, self).setUp()
        self.mock_config.use_chap_auth = False
        self.mock_config.use_multipath_for_image_xfer = False
        self.mock_config.volume_backend_name = ISCSI_VOLUME_BACKEND_NAME
        self.driver = iscsi.FSSISCSIDriver(configuration=self.mock_config)
        self.mock_utils = mock.Mock()
        self.driver.driver_utils = self.mock_utils

    def test_initialized_should_set_fss_info(self):
        self.assertEqual(self.driver.proxy.fss_host,
                         self.driver.configuration.san_ip)
        self.assertEqual(self.driver.proxy.fss_defined_pools,
                         self.driver.configuration.fss_pools)

    def test_check_for_setup_error(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    @mock.patch.object(proxy.RESTProxy, 'create_vdev',
                       return_value=DATA_OUTPUT)
    def test_create_volume(self, mock_create_vdev):
        self.driver.create_volume(VOLUME)
        mock_create_vdev.assert_called_once_with(VOLUME)

    @mock.patch.object(proxy.RESTProxy, '_get_fss_volume_name',
                       return_value=VOLUME_NAME)
    def test_extend_volume(self, mock__get_fss_volume_name):
        """Volume extended_volume successfully."""
        self.driver.proxy.extend_vdev = mock.Mock()
        result = self.driver.extend_volume(VOLUME, EXTENT_NEW_SIZE)
        mock__get_fss_volume_name.assert_called_once_with(VOLUME)
        self.driver.proxy.extend_vdev.assert_called_once_with(VOLUME_NAME,
                                                              VOLUME["size"],
                                                              EXTENT_NEW_SIZE)
        self.assertIsNone(result)

    @mock.patch.object(proxy.RESTProxy, '_get_fss_volume_name')
    def test_clone_volume(self, mock__get_fss_volume_name):
        mock__get_fss_volume_name.side_effect = [VOLUME_NAME, SRC_VOL_NAME]
        self.driver.proxy.clone_volume = mock.Mock(
            return_value=VOLUME_METADATA)
        self.driver.proxy.extend_vdev = mock.Mock()

        self.driver.create_cloned_volume(VOLUME, SRC_VOL)
        self.driver.proxy.clone_volume.assert_called_with(VOLUME_NAME,
                                                          SRC_VOL_NAME)

        mock__get_fss_volume_name.assert_any_call(VOLUME)
        mock__get_fss_volume_name.assert_any_call(SRC_VOL)
        self.assertEqual(2, mock__get_fss_volume_name.call_count)

        self.driver.proxy.extend_vdev(VOLUME_NAME, VOLUME["size"],
                                      SRC_VOL["size"])
        self.driver.proxy.extend_vdev.assert_called_with(VOLUME_NAME,
                                                         VOLUME["size"],
                                                         SRC_VOL["size"])

    @mock.patch.object(proxy.RESTProxy, 'delete_vdev')
    def test_delete_volume(self, mock_delete_vdev):
        result = self.driver.delete_volume(VOLUME)
        mock_delete_vdev.assert_called_once_with(VOLUME)
        self.assertIsNone(result)

    @mock.patch.object(proxy.RESTProxy, 'create_snapshot',
                                        return_value=API_RESPONSE)
    def test_create_snapshot(self, mock_create_snapshot):
        snap_name = SNAPSHOT.get('display_name')
        SNAPSHOT_METADATA["fss-tm-comment"] = snap_name
        result = self.driver.create_snapshot(SNAPSHOT)
        mock_create_snapshot.assert_called_once_with(SNAPSHOT)
        self.assertEqual(result, {'metadata': SNAPSHOT_METADATA})

    @mock.patch.object(proxy.RESTProxy, 'create_snapshot',
                                        return_value=API_RESPONSE)
    def test_create_snapshot_exceed_characters_len(self, mock_create_snapshot):
        SNAPSHOT_METADATA["fss-tm-comment"] = ENCODED_SNAPSHOT_ID
        result = self.driver.create_snapshot(SNAPSHOT_LONG_NAME)
        mock_create_snapshot.assert_called_once_with(SNAPSHOT_LONG_NAME)
        self.assertEqual(result, {'metadata': SNAPSHOT_METADATA})

    @mock.patch.object(proxy.RESTProxy, 'delete_snapshot',
                                        return_value=API_RESPONSE)
    def test_delete_snapshot(self, mock_delete_snapshot):
        result = self.driver.delete_snapshot(SNAPSHOT)
        mock_delete_snapshot.assert_called_once_with(SNAPSHOT)
        self.assertIsNone(result)

    @mock.patch.object(proxy.RESTProxy, 'create_volume_from_snapshot',
                       return_value=(VOLUME_NAME, VOLUME_METADATA))
    @mock.patch.object(proxy.RESTProxy, '_get_fss_volume_name',
                                        return_value=VOLUME_NAME)
    def test_create_volume_from_snapshot(self, mock__get_fss_volume_name,
                                         mock_create_volume_from_snapshot):
        vol_size = VOLUME['size']
        snap_size = SNAPSHOT['volume_size']
        self.driver.proxy.extend_vdev = mock.Mock()

        self.assertEqual(
            self.driver.create_volume_from_snapshot(VOLUME, SNAPSHOT),
            dict(metadata=VOLUME_METADATA))
        mock_create_volume_from_snapshot.assert_called_once_with(VOLUME,
                                                                 SNAPSHOT)

        if vol_size != snap_size:
            mock__get_fss_volume_name.assert_called_once_with(VOLUME)
            self.driver.proxy.extend_vdev(VOLUME_NAME, snap_size, vol_size)
            self.driver.proxy.extend_vdev.assert_called_with(VOLUME_NAME,
                                                             snap_size,
                                                             vol_size)

    @mock.patch.object(proxy.RESTProxy, 'create_group')
    def test_create_consistency_group(self, mock_create_group):
        ctxt = context.get_admin_context()
        model_update = self.driver.create_consistencygroup(ctxt, CONSISTGROUP)
        mock_create_group.assert_called_once_with(CONSISTGROUP)
        self.assertDictEqual({'status': 'available'}, model_update)

    @mock.patch.object(proxy.RESTProxy, 'destroy_group')
    @mock.patch(BASE_DRIVER + ".delete_volume", autospec=True)
    def test_delete_consistency_group(self, mock_delete_vdev,
                                      mock_destroy_group):
        mock_cgroup = mock.MagicMock()
        mock_cgroup.id = FAKE_ID
        mock_cgroup['status'] = "deleted"
        mock_context = mock.Mock()
        mock_volume = mock.MagicMock()
        expected_volume_updates = [{
            'id': mock_volume.id,
            'status': 'deleted'
        }]
        model_update, volumes = self.driver.delete_consistencygroup(
            mock_context, mock_cgroup, [mock_volume])

        mock_destroy_group.assert_called_with(mock_cgroup)
        self.assertEqual(expected_volume_updates, volumes)
        self.assertEqual(mock_cgroup['status'], model_update['status'])
        mock_delete_vdev.assert_called_with(self.driver, mock_volume)

    @mock.patch.object(proxy.RESTProxy, 'set_group')
    def test_update_consistency_group(self, mock_set_group):
        ctxt = context.get_admin_context()
        add_vols = [
            {'name': 'vol1', 'id': 'vol1', 'display_name': ''},
            {'name': 'vol2', 'id': 'vol2', 'display_name': ''}
        ]
        remove_vols = [
            {'name': 'vol3', 'id': 'vol3', 'display_name': ''},
            {'name': 'vol4', 'id': 'vol4', 'display_name': ''}
        ]

        expected_addvollist = ["cinder-%s" % volume['id'] for volume in
                               add_vols]
        expected_remvollist = ["cinder-%s" % vol['id'] for vol in remove_vols]

        self.driver.update_consistencygroup(ctxt, CONSISTGROUP,
                                            add_volumes=add_vols,
                                            remove_volumes=remove_vols)
        mock_set_group.assert_called_with(GROUP_ID,
                                          addvollist=expected_addvollist,
                                          remvollist=expected_remvollist)

    @mock.patch.object(proxy.RESTProxy, 'create_cgsnapshot')
    def test_create_cgsnapshot(self, mock_create_cgsnapshot):
        mock_cgsnap = CG_SNAPSHOT
        mock_context = mock.Mock()
        mock_snap = mock.MagicMock()
        model_update, snapshots = self.driver.create_cgsnapshot(mock_context,
                                                                mock_cgsnap,
                                                                [mock_snap])
        mock_create_cgsnapshot.assert_called_once_with(mock_cgsnap)
        self.assertEqual({'status': 'available'}, model_update)
        expected_snapshot_update = [{
            'id': mock_snap.id,
            'status': 'available'
        }]
        self.assertEqual(expected_snapshot_update, snapshots)

    @mock.patch.object(proxy.RESTProxy, 'delete_cgsnapshot')
    def test_delete_cgsnapshot(self, mock_delete_cgsnapshot):
        mock_cgsnap = mock.Mock()
        mock_cgsnap.id = FAKE_ID
        mock_cgsnap.status = 'deleted'
        mock_context = mock.Mock()
        mock_snap = mock.MagicMock()

        model_update, snapshots = self.driver.delete_cgsnapshot(mock_context,
                                                                mock_cgsnap,
                                                                [mock_snap])
        mock_delete_cgsnapshot.assert_called_once_with(mock_cgsnap)
        self.assertEqual({'status': mock_cgsnap.status}, model_update)

        expected_snapshot_update = [dict(id=mock_snap.id, status='deleted')]
        self.assertEqual(expected_snapshot_update, snapshots)

    @mock.patch.object(proxy.RESTProxy, 'initialize_connection_iscsi',
                       return_value=ISCSI_PORTS)
    def test_initialize_connection(self, mock_initialize_connection_iscsi):
        FSS_HOSTS = []
        FSS_HOSTS.append(PRIMARY_IP)
        ret = self.driver.initialize_connection(VOLUME, ISCSI_CONNECTOR)
        mock_initialize_connection_iscsi.assert_called_once_with(
            VOLUME,
            ISCSI_CONNECTOR,
            FSS_HOSTS)
        result = deepcopy(ISCSI_INFO)
        self.assertDictEqual(result, ret)

    @mock.patch.object(proxy.RESTProxy, 'initialize_connection_iscsi')
    @mock.patch(ISCSI_DRIVER + "._check_multipath", autospec=True)
    def test_initialize_connection_multipath(self, mock__check_multipath,
                                             mock_initialize_connection_iscsi):
        fss_hosts = []
        fss_hosts.append(self.mock_config.san_ip)
        mock_initialize_connection_iscsi.return_value = ISCSI_PORTS
        mock__check_multipath.retuen_value = True

        self.mock_config.use_multipath_for_image_xfer = True
        self.mock_config.fss_san_secondary_ip = SECONDARY_IP
        multipath_connector = deepcopy(ISCSI_CONNECTOR)
        multipath_connector["multipath"] = True
        fss_hosts.append(SECONDARY_IP)

        self.driver.initialize_connection(VOLUME, multipath_connector)
        mock_initialize_connection_iscsi.assert_called_once_with(
            VOLUME,
            multipath_connector,
            fss_hosts)

    @mock.patch.object(proxy.RESTProxy, 'terminate_connection_iscsi')
    def test_terminate_connection(self, mock_terminate_connection_iscsi):
        self.driver.terminate_connection(VOLUME, ISCSI_CONNECTOR)
        mock_terminate_connection_iscsi.assert_called_once_with(
            VOLUME,
            ISCSI_CONNECTOR)

    @mock.patch.object(proxy.RESTProxy, '_manage_existing_volume')
    @mock.patch.object(proxy.RESTProxy, '_get_existing_volume_ref_vid')
    def test_manage_existing(self, mock__get_existing_volume_ref_vid,
                             mock__manage_existing_volume):
        ref_vid = 1
        volume_ref = {'source-id': ref_vid}
        self.driver.manage_existing(VOLUME, volume_ref)
        mock__get_existing_volume_ref_vid.assert_called_once_with(volume_ref)
        mock__manage_existing_volume.assert_called_once_with(
            volume_ref['source-id'], VOLUME)

    @mock.patch.object(proxy.RESTProxy, '_get_existing_volume_ref_vid',
                       return_value=5120)
    def test_manage_existing_get_size(self, mock__get_existing_volume_ref_vid):
        ref_vid = 1
        volume_ref = {'source-id': ref_vid}
        expected_size = 5
        size = self.driver.manage_existing_get_size(VOLUME, volume_ref)
        mock__get_existing_volume_ref_vid.assert_called_once_with(volume_ref)
        self.assertEqual(expected_size, size)

    @mock.patch.object(proxy.RESTProxy, 'unmanage')
    def test_unmanage(self, mock_unmanage):
        self.driver.unmanage(VOLUME)
        mock_unmanage.assert_called_once_with(VOLUME)


class TestFSSFCDriver(FSSDriverTestCase):

    def setUp(self):
        super(TestFSSFCDriver, self).setUp()
        self.driver = fc.FSSFCDriver(configuration=self.mock_config)
        self.driver._lookup_service = mock.Mock()

    @mock.patch.object(proxy.RESTProxy, 'fc_initialize_connection')
    def test_initialize_connection(self, mock_fc_initialize_connection):
        fss_hosts = []
        fss_hosts.append(PRIMARY_IP)
        self.driver.initialize_connection(VOLUME, FC_CONNECTOR)
        mock_fc_initialize_connection.assert_called_once_with(
            VOLUME,
            FC_CONNECTOR,
            fss_hosts)

    @mock.patch.object(proxy.RESTProxy, '_check_fc_host_devices_empty',
                       return_value=False)
    @mock.patch.object(proxy.RESTProxy, 'fc_terminate_connection',
                       return_value=FAKE_ID)
    def test_terminate_connection(self, mock_fc_terminate_connection,
                                  mock__check_fc_host_devices_empty):
        self.driver.terminate_connection(VOLUME, FC_CONNECTOR)
        mock_fc_terminate_connection.assert_called_once_with(
            VOLUME,
            FC_CONNECTOR)
        mock__check_fc_host_devices_empty.assert_called_once_with(FAKE_ID)


class TestRESTProxy(test.TestCase):
    """Test REST Proxy Driver."""

    def setUp(self):
        super(TestRESTProxy, self).setUp()
        configuration = mock.Mock(conf.Configuration)
        configuration.san_ip = FAKE
        configuration.san_login = FAKE
        configuration.san_password = FAKE
        configuration.fss_pools = FAKE_SINGLE_POOLS
        configuration.fss_debug = False
        configuration.additional_retry_list = None

        self.proxy = proxy.RESTProxy(configuration)
        self.FSS_MOCK = mock.MagicMock()
        self.proxy.FSS = self.FSS_MOCK
        self.FSS_MOCK._fss_request.return_value = API_RESPONSE
        self.mock_object(time, 'sleep', Fake_sleep)

    def test_do_setup(self):
        self.proxy.do_setup()
        self.FSS_MOCK.fss_login.assert_called_once_with()
        self.assertNotEqual(self.proxy.session_id, SESSION_ID)

    def test_create_volume(self):
        sizemb = self.proxy._convert_size_to_mb(VOLUME['size'])
        volume_name = self.proxy._get_fss_volume_name(VOLUME)
        _pool_id = self.proxy._selected_pool_id(FAKE_SINGLE_POOLS, "P")

        params = dict(storagepoolid=_pool_id,
                      sizemb=sizemb,
                      category="virtual",
                      name=volume_name)
        self.proxy.create_vdev(VOLUME)
        self.FSS_MOCK.create_vdev.assert_called_once_with(params)

    @mock.patch.object(proxy.RESTProxy, '_get_fss_vid_from_name',
                       return_value=FAKE_ID)
    def test_extend_volume(self, mock__get_fss_vid_from_name):
        size = self.proxy._convert_size_to_mb(EXTENT_NEW_SIZE - VOLUME['size'])
        params = dict(
            action='expand',
            sizemb=size
        )
        volume_name = self.proxy._get_fss_volume_name(VOLUME)
        self.proxy.extend_vdev(volume_name, VOLUME["size"], EXTENT_NEW_SIZE)

        mock__get_fss_vid_from_name.assert_called_once_with(volume_name,
                                                            FSS_SINGLE_TYPE)
        self.FSS_MOCK.extend_vdev.assert_called_once_with(FAKE_ID, params)

    @mock.patch.object(proxy.RESTProxy, '_get_fss_vid_from_name',
                       return_value=FAKE_ID)
    def test_delete_volume(self, mock__get_fss_vid_from_name):
        volume_name = self.proxy._get_fss_volume_name(VOLUME)
        self.proxy.delete_vdev(VOLUME)
        mock__get_fss_vid_from_name.assert_called_once_with(volume_name,
                                                            FSS_SINGLE_TYPE)
        self.FSS_MOCK.delete_vdev.assert_called_once_with(FAKE_ID)

    @mock.patch.object(proxy.RESTProxy, '_get_fss_vid_from_name',
                       return_value=FAKE_ID)
    def test_clone_volume(self, mock__get_fss_vid_from_name):
        self.FSS_MOCK.create_mirror.return_value = API_RESPONSE
        self.FSS_MOCK.sync_mirror.return_value = API_RESPONSE
        _pool_id = self.proxy._selected_pool_id(FAKE_SINGLE_POOLS, "O")
        mirror_params = dict(
            category='virtual',
            selectioncriteria='anydrive',
            mirrortarget="virtual",
            storagepoolid=_pool_id
        )
        ret = self.proxy.clone_volume(VOLUME_NAME, SRC_VOL_NAME)

        self.FSS_MOCK.create_mirror.assert_called_once_with(FAKE_ID,
                                                            mirror_params)
        self.FSS_MOCK.sync_mirror.assert_called_once_with(FAKE_ID)
        self.FSS_MOCK.promote_mirror.assert_called_once_with(FAKE_ID,
                                                             VOLUME_NAME)
        self.assertNotEqual(ret, VOLUME_METADATA)

    @mock.patch.object(proxy.RESTProxy, 'create_vdev_snapshot')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_vid_from_name',
                       return_value=FAKE_ID)
    @mock.patch.object(proxy.RESTProxy, '_get_vol_name_from_snap',
                       return_value=VOLUME_NAME)
    def test_create_snapshot(self, mock__get_vol_name_from_snap,
                             mock__get_fss_vid_from_name,
                             mock_create_vdev_snapshot):
        self.FSS_MOCK._check_if_snapshot_tm_exist.return_value = [
            False, False, SNAPSHOT['volume_size']]

        self.proxy.create_snapshot(SNAPSHOT)
        self.FSS_MOCK._check_if_snapshot_tm_exist.assert_called_once_with(
            FAKE_ID)
        sizemb = self.proxy._convert_size_to_mb(SNAPSHOT['volume_size'])
        mock_create_vdev_snapshot.assert_called_once_with(FAKE_ID, sizemb)
        _pool_id = self.proxy._selected_pool_id(FAKE_SINGLE_POOLS, "O")
        self.FSS_MOCK.create_timemark_policy.assert_called_once_with(
            FAKE_ID,
            storagepoolid=_pool_id)
        self.FSS_MOCK.create_timemark.assert_called_once_with(
            FAKE_ID,
            SNAPSHOT["display_name"])

    @mock.patch.object(proxy.RESTProxy, '_get_timestamp',
                       return_value=RAWTIMESTAMP)
    @mock.patch.object(proxy.RESTProxy, '_get_fss_vid_from_name',
                       return_value=FAKE_ID)
    @mock.patch.object(proxy.RESTProxy, '_get_vol_name_from_snap',
                       return_value=VOLUME_NAME)
    def test_delete_snapshot(self, mock__get_vol_name_from_snap,
                             mock__get_fss_vid_from_name,
                             mock__get_timestamp):
        timestamp = '%s_%s' % (FAKE_ID, RAWTIMESTAMP)

        self.proxy.delete_snapshot(SNAPSHOT)
        mock__get_vol_name_from_snap.assert_called_once_with(SNAPSHOT)
        self.FSS_MOCK.delete_timemark.assert_called_once_with(timestamp)
        self.FSS_MOCK.get_timemark.assert_any_call(FAKE_ID)
        self.assertEqual(2, self.FSS_MOCK.get_timemark.call_count)

    @mock.patch.object(proxy.RESTProxy, '_get_timestamp')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_vid_from_name')
    @mock.patch.object(proxy.RESTProxy, '_get_vol_name_from_snap')
    def test_create_volume_from_snapshot(self, mock__get_vol_name_from_snap,
                                         mock__get_fss_vid_from_name,
                                         mock__get_timestamp):
        tm_info = {"rc": 0,
                   "data":
                       {
                           "guid": "497bad5e-e589-bb0a-e0e7-00004eeac169",
                           "name": "SANDisk-001",
                           "total": "1",
                           "timemark": [
                               {
                                   "size": 131072,
                                   "comment": "123test456",
                                   "hastimeview": False,
                                   "priority": "low",
                                   "quiescent": "yes",
                                   "timeviewdata": "notkept",
                                   "rawtimestamp": "1324975390",
                                   "timestamp": "2015-10-11 16:43:10"
                               }]
                       }
                   }
        mock__get_vol_name_from_snap.return_value = VOLUME_NAME
        new_vol_name = self.proxy._get_fss_volume_name(VOLUME)
        mock__get_fss_vid_from_name.return_value = FAKE_ID

        self.FSS_MOCK.get_timemark.return_value = tm_info
        mock__get_timestamp.return_value = RAWTIMESTAMP
        timestamp = '%s_%s' % (FAKE_ID, RAWTIMESTAMP)
        _pool_id = self.proxy._selected_pool_id(FAKE_SINGLE_POOLS, "O")

        self.proxy.create_volume_from_snapshot(VOLUME, SNAPSHOT)
        self.FSS_MOCK.get_timemark.assert_called_once_with(FAKE_ID)
        mock__get_timestamp.assert_called_once_with(tm_info,
                                                    SNAPSHOT['display_name'])
        self.FSS_MOCK.copy_timemark.assert_called_once_with(
            timestamp,
            storagepoolid=_pool_id,
            name=new_vol_name)

    @mock.patch.object(proxy.RESTProxy, '_get_group_name_from_id')
    def test_create_consistency_group(self, mock__get_group_name_from_id):

        mock__get_group_name_from_id.return_value = CONSISTGROUP['name']
        params = dict(name=CONSISTGROUP['name'])
        self.proxy.create_group(CONSISTGROUP)
        self.FSS_MOCK.create_group.assert_called_once_with(params)

    @mock.patch.object(proxy.RESTProxy, '_get_fss_gid_from_name')
    @mock.patch.object(proxy.RESTProxy, '_get_group_name_from_id')
    def test_delete_consistency_group(self, mock__get_group_name_from_id,
                                      mock__get_fss_gid_from_name):
        mock__get_group_name_from_id.return_value = CONSISTGROUP['name']
        mock__get_fss_gid_from_name.return_value = FAKE_ID

        self.proxy.destroy_group(CONSISTGROUP)
        mock__get_group_name_from_id.assert_called_once_with(
            CONSISTGROUP['id'])
        mock__get_fss_gid_from_name.assert_called_once_with(
            CONSISTGROUP['name'])
        self.FSS_MOCK.destroy_group.assert_called_once_with(FAKE_ID)

    @mock.patch.object(proxy.RESTProxy, '_get_fss_vid_from_name')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_gid_from_name')
    @mock.patch.object(proxy.RESTProxy, '_get_group_name_from_id')
    def test_update_consistency_group(self, mock__get_group_name_from_id,
                                      mock__get_fss_gid_from_name,
                                      mock__get_fss_vid_from_name):
        join_vid_list = [1, 2]
        leave_vid_list = [3, 4]
        mock__get_group_name_from_id.return_value = CONSISTGROUP['name']
        mock__get_fss_gid_from_name.return_value = FAKE_ID
        mock__get_fss_vid_from_name.side_effect = [join_vid_list,
                                                   leave_vid_list]
        add_vols = [
            {'name': 'vol1', 'id': 'vol1'},
            {'name': 'vol2', 'id': 'vol2'}
        ]
        remove_vols = [
            {'name': 'vol3', 'id': 'vol3'},
            {'name': 'vol4', 'id': 'vol4'}
        ]
        expected_addvollist = ["cinder-%s" % volume['id'] for volume in
                               add_vols]
        expected_remvollist = ["cinder-%s" % vol['id'] for vol in remove_vols]

        self.proxy.set_group(CONSISTGROUP, addvollist=expected_addvollist,
                             remvollist=expected_remvollist)

        if expected_addvollist:
            mock__get_fss_vid_from_name.assert_any_call(expected_addvollist)

        if expected_remvollist:
            mock__get_fss_vid_from_name.assert_any_call(expected_remvollist)
        self.assertEqual(2, mock__get_fss_vid_from_name.call_count)

        join_params = dict()
        leave_params = dict()

        join_params.update(
            action='join',
            virtualdevices=join_vid_list
        )
        leave_params.update(
            action='leave',
            virtualdevices=leave_vid_list
        )
        self.FSS_MOCK.set_group.assert_called_once_with(FAKE_ID, join_params,
                                                        leave_params)

    @mock.patch.object(proxy.RESTProxy, 'create_vdev_snapshot')
    @mock.patch.object(proxy.RESTProxy, 'create_group_timemark')
    @mock.patch.object(proxy.RESTProxy, '_get_vdev_id_from_group_id')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_gid_from_name')
    @mock.patch.object(proxy.RESTProxy, '_get_group_name_from_id')
    def test_create_cgsnapshot(self, mock__get_group_name_from_id,
                               mock__get_fss_gid_from_name,
                               mock__get_vdev_id_from_group_id,
                               mock_create_group_timemark,
                               mock_create_vdev_snapshot
                               ):
        vid_list = [1]

        group_name = "cinder-consisgroup-%s" % CG_SNAPSHOT[
            'consistencygroup_id']
        mock__get_group_name_from_id.return_value = group_name
        mock__get_fss_gid_from_name.return_value = FAKE_ID
        mock__get_vdev_id_from_group_id.return_value = vid_list
        gsnap_name = self.proxy._encode_name(CG_SNAPSHOT['id'])
        self.FSS_MOCK._check_if_snapshot_tm_exist.return_value = (
            False,
            False,
            1024)

        self.proxy.create_cgsnapshot(CG_SNAPSHOT)
        mock__get_group_name_from_id.assert_called_once_with(
            CG_SNAPSHOT['consistencygroup_id'])
        mock__get_fss_gid_from_name.assert_called_once_with(group_name)
        mock__get_vdev_id_from_group_id.assert_called_once_with(FAKE_ID)
        _pool_id = self.proxy._selected_pool_id(FAKE_SINGLE_POOLS, "O")

        for vid in vid_list:
            self.FSS_MOCK._check_if_snapshot_tm_exist.assert_called_with(vid)
            mock_create_vdev_snapshot.assert_called_once_with(vid, 1024)
            self.FSS_MOCK.create_timemark_policy.assert_called_once_with(
                vid,
                storagepoolid=_pool_id)

        mock_create_group_timemark.assert_called_once_with(FAKE_ID, gsnap_name)

    @mock.patch.object(proxy.RESTProxy, 'delete_group_timemark')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_group_membercount')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_gid_from_name')
    @mock.patch.object(proxy.RESTProxy, '_get_group_name_from_id')
    def test_delete_cgsnapshot(self, mock__get_group_name_from_id,
                               mock__get_fss_gid_from_name,
                               mock__get_fss_group_membercount,
                               mock_delete_group_timemark):
        tm_info = {
            "rc": 0,
            "data":
                {
                    "name": "GroupTestABC",
                    "total": 1,
                    "timemark": [{
                        "size": 65536,
                        "comment": "cinder-PGGwaaaaaaaar+wYV4AMdgIPw",
                        "priority": "low",
                        "quiescent": "yes",
                        "hastimeview": "false",
                        "timeviewdata": "notkept",
                        "rawtimestamp": "1324974940",
                        "timestamp": "2015-10-15 16:35:40"}]
                }
        }
        final_tm_data = {
            "rc": 0,
            "data":
                {"name": "GroupTestABC",
                 "total": 1,
                 "timemark": []
                 }}

        mock__get_group_name_from_id.return_value = CG_SNAPSHOT[
            'consistencygroup_id']
        mock__get_fss_gid_from_name.return_value = FAKE_ID
        self.FSS_MOCK.get_group_timemark.side_effect = [tm_info, final_tm_data]
        encode_snap_name = self.proxy._encode_name(CG_SNAPSHOT['id'])
        self.proxy.delete_cgsnapshot(CG_SNAPSHOT)
        mock__get_fss_group_membercount.assert_called_once_with(FAKE_ID)

        self.assertEqual(2, self.FSS_MOCK.get_group_timemark.call_count)
        self.FSS_MOCK.get_group_timemark.assert_any_call(FAKE_ID)
        rawtimestamp = self.proxy._get_timestamp(tm_info, encode_snap_name)
        timestamp = '%s_%s' % (FAKE_ID, rawtimestamp)
        mock_delete_group_timemark.assert_called_once_with(timestamp)
        self.FSS_MOCK.delete_group_timemark_policy.assert_called_once_with(
            FAKE_ID)

    @mock.patch.object(proxy.RESTProxy, 'initialize_connection_iscsi')
    def test_iscsi_initialize_connection(self,
                                         mock_initialize_connection_iscsi):
        fss_hosts = []
        fss_hosts.append(PRIMARY_IP)
        self.proxy.initialize_connection_iscsi(VOLUME, ISCSI_CONNECTOR,
                                               fss_hosts)
        mock_initialize_connection_iscsi.assert_called_once_with(
            VOLUME,
            ISCSI_CONNECTOR,
            fss_hosts)

    @mock.patch.object(proxy.RESTProxy, 'terminate_connection_iscsi')
    def test_iscsi_terminate_connection(self, mock_terminate_connection_iscsi):
        self.FSS_MOCK._get_target_info.return_value = (FAKE_ID, INITIATOR_IQN)

        self.proxy.terminate_connection_iscsi(VOLUME, ISCSI_CONNECTOR)
        mock_terminate_connection_iscsi.assert_called_once_with(
            VOLUME,
            ISCSI_CONNECTOR)

    @mock.patch.object(proxy.RESTProxy, 'rename_vdev')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_volume_name')
    def test_manage_existing(self, mock__get_fss_volume_name,
                             mock_rename_vdev):
        new_vol_name = 'rename-vol'
        mock__get_fss_volume_name.return_value = new_vol_name

        self.proxy._manage_existing_volume(FAKE_ID, VOLUME)
        mock__get_fss_volume_name.assert_called_once_with(VOLUME)
        mock_rename_vdev.assert_called_once_with(FAKE_ID, new_vol_name)

    @mock.patch.object(proxy.RESTProxy, 'list_volume_info')
    def test_manage_existing_get_size(self, mock_list_volume_info):
        volume_ref = {'source-id': FAKE_ID}
        vdev_info = {
            "rc": 0,
            "data": {
                "name": "cinder-2ab1f70a-6c89-432c-84e3-5fa6c187fb92",
                "type": "san",
                "category": "virtual",
                "sizemb": 1020
            }}

        mock_list_volume_info.return_value = vdev_info
        self.proxy._get_existing_volume_ref_vid(volume_ref)
        mock_list_volume_info.assert_called_once_with(FAKE_ID)

    @mock.patch.object(proxy.RESTProxy, 'rename_vdev')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_vid_from_name')
    @mock.patch.object(proxy.RESTProxy, '_get_fss_volume_name')
    def test_unmanage(self, mock__get_fss_volume_name,
                      mock__get_fss_vid_from_name,
                      mock_rename_vdev):

        mock__get_fss_volume_name.return_value = VOLUME_NAME
        mock__get_fss_vid_from_name.return_value = FAKE_ID
        unmanaged_vol_name = VOLUME_NAME + "-unmanaged"

        self.proxy.unmanage(VOLUME)
        mock__get_fss_volume_name.assert_called_once_with(VOLUME)
        mock__get_fss_vid_from_name.assert_called_once_with(VOLUME_NAME,
                                                            FSS_SINGLE_TYPE)
        mock_rename_vdev.assert_called_once_with(FAKE_ID, unmanaged_vol_name)
