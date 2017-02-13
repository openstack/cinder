# Copyright 2015 Violin Memory, Inc.
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

"""
Tests for Violin Memory 7000 Series All-Flash Array Common Driver
"""
import ddt
import math
import mock
import six

from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.volume.drivers.violin \
    import fake_vmem_client as vmemclient
from cinder.volume import configuration as conf
from cinder.volume.drivers.violin import v7000_common
from cinder.volume import volume_types


VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdeffedcba"
VOLUME = {"name": "volume-" + VOLUME_ID,
          "id": VOLUME_ID,
          "display_name": "fake_volume",
          "size": 2,
          "host": "irrelevant",
          "volume_type": None,
          "volume_type_id": None,
          }
SNAPSHOT_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbb"
SNAPSHOT = {"name": "snapshot-" + SNAPSHOT_ID,
            "id": SNAPSHOT_ID,
            "volume_id": VOLUME_ID,
            "volume_name": "volume-" + VOLUME_ID,
            "volume_size": 2,
            "display_name": "fake_snapshot",
            }
SRC_VOL_ID = "abcdabcd-1234-abcd-1234-abcdeffedcbc"
SRC_VOL = {"name": "volume-" + SRC_VOL_ID,
           "id": SRC_VOL_ID,
           "display_name": "fake_src_vol",
           "size": 2,
           "host": "irrelevant",
           "volume_type": None,
           "volume_type_id": None,
           }
INITIATOR_IQN = "iqn.1111-22.org.debian:11:222"
CONNECTOR = {"initiator": INITIATOR_IQN}
DEFAULT_DEDUP_POOL = {"storage_pool": 'PoolA',
                      "storage_pool_id": 99,
                      "dedup": True,
                      "thin": True,
                      }
DEFAULT_THIN_POOL = {"storage_pool": 'PoolA',
                     "storage_pool_id": 99,
                     "dedup": False,
                     "thin": True,
                     }
DEFAULT_THICK_POOL = {"storage_pool": 'PoolA',
                      "storage_pool_id": 99,
                      "dedup": False,
                      "thin": False,
                      }

# Note:  select superfluous fields are removed for brevity
STATS_STORAGE_POOL_RESPONSE = [({
    'availsize_mb': 1572827,
    'category': 'Virtual Device',
    'name': 'dedup-pool',
    'object_id': '487d1940-c53f-55c3-b1d5-073af43f80fc',
    'size_mb': 2097124,
    'storage_pool_id': 1,
    'usedsize_mb': 524297},
    {'category': 'Virtual Device',
     'name': 'dedup-pool',
     'object_id': '487d1940-c53f-55c3-b1d5-073af43f80fc',
     'physicaldevices': [
         {'availsize_mb': 524281,
          'connection_type': 'fc',
          'name': 'VIOLIN:CONCERTO ARRAY.003',
          'object_id': '260f30b0-0300-59b5-b7b9-54aa55704a12',
          'owner': 'lab-host1',
          'size_mb': 524281,
          'type': 'Direct-Access',
          'usedsize_mb': 0},
         {'availsize_mb': 524281,
          'connection_type': 'fc',
          'name': 'VIOLIN:CONCERTO ARRAY.004',
          'object_id': '7b58eda2-69da-5aec-9e06-6607934efa93',
          'owner': 'lab-host1',
          'size_mb': 524281,
          'type': 'Direct-Access',
          'usedsize_mb': 0},
         {'availsize_mb': 0,
          'connection_type': 'fc',
          'name': 'VIOLIN:CONCERTO ARRAY.001',
          'object_id': '69adbea1-2349-5df5-a04a-abd7f14868b2',
          'owner': 'lab-host1',
          'size_mb': 524281,
          'type': 'Direct-Access',
          'usedsize_mb': 524281},
         {'availsize_mb': 524265,
          'connection_type': 'fc',
          'name': 'VIOLIN:CONCERTO ARRAY.002',
          'object_id': 'a14a0e36-8901-5987-95d8-aa574c6138a2',
          'owner': 'lab-host1',
          'size_mb': 524281,
          'type': 'Direct-Access',
          'usedsize_mb': 16}],
     'size_mb': 2097124,
     'storage_pool_id': 1,
     'total_physicaldevices': 4,
     'usedsize_mb': 524297}),
    ({'availsize': 0,
      'availsize_mb': 0,
      'category': None,
      'name': 'thick_pool_13531mgb',
      'object_id': '20610abd-4c58-546c-8905-bf42fab9a11b',
      'size': 0,
      'size_mb': 0,
      'storage_pool_id': 3,
      'tag': '',
      'total_physicaldevices': 0,
      'usedsize': 0,
      'usedsize_mb': 0},
     {'category': None,
      'name': 'thick_pool_13531mgb',
      'object_id': '20610abd-4c58-546c-8905-bf42fab9a11b',
      'resource_type': ['All'],
      'size': 0,
      'size_mb': 0,
      'storage_pool_id': 3,
      'tag': [''],
      'total_physicaldevices': 0,
      'usedsize': 0,
      'usedsize_mb': 0}),
    ({'availsize_mb': 627466,
      'category': 'Virtual Device',
      'name': 'StoragePool',
      'object_id': '1af66d9a-f62e-5b69-807b-892b087fa0b4',
      'size_mb': 21139267,
      'storage_pool_id': 7,
      'usedsize_mb': 20511801},
     {'category': 'Virtual Device',
      'name': 'StoragePool',
      'object_id': '1af66d9a-f62e-5b69-807b-892b087fa0b4',
      'physicaldevices': [
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN02.000',
           'object_id': 'ecc775f1-1228-5131-8f68-4176001786ef',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN01.000',
           'object_id': '5c60812b-34d2-5473-b7bf-21e30ec70311',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN08.001',
           'object_id': 'eb6d06b7-8d6f-5d9d-b720-e86d8ad1beab',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN03.001',
           'object_id': '063aced7-1f8f-5e15-b36e-e9d34a2826fa',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN07.001',
           'object_id': 'ebf34594-2b92-51fe-a6a8-b6cf91f05b2b',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN0A.000',
           'object_id': 'ff084188-b97f-5e30-9ff0-bc60e546ee06',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN06.001',
           'object_id': 'f9cbeadf-5524-5697-a3a6-667820e37639',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 167887,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN15.000',
           'object_id': 'aaacc124-26c9-519a-909a-a93d24f579a1',
           'owner': 'lab-host2',
           'size_mb': 167887,
           'type': 'Direct-Access',
           'usedsize_mb': 0},
          {'availsize_mb': 229276,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN09.001',
           'object_id': '30967a84-56a4-52a5-ac3f-b4f544257bbd',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 819293},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN04.001',
           'object_id': 'd997eb42-55d4-5e4c-b797-c68b748e7e1f',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN05.001',
           'object_id': '56ecf98c-f10b-5bb5-9d3b-5af6037dad73',
           'owner': 'lab-host1',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN0B.000',
           'object_id': 'cfb6f61c-508d-5394-8257-78b1f9bcad3b',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN0C.000',
           'object_id': '7b0bcb51-5c7d-5752-9e18-392057e534f0',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN0D.000',
           'object_id': 'b785a3b1-6316-50c3-b2e0-6bb0739499c6',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN0E.000',
           'object_id': '76b9d038-b757-515a-b962-439a4fd85fd5',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN0F.000',
           'object_id': '9591d24a-70c4-5e80-aead-4b788202c698',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN10.000',
           'object_id': '2bb09a2b-9063-595b-9d7a-7e5fad5016db',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN11.000',
           'object_id': 'b9ff58eb-5e6e-5c79-bf95-fae424492519',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN12.000',
           'object_id': '6abd4fd6-9841-5978-bfcb-5d398d1715b4',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569},
          {'availsize_mb': 230303,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN13.000',
           'object_id': 'ffd5a4b7-0f50-5a71-bbba-57a348b96c68',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 818266},
          {'availsize_mb': 0,
           'connection_type': 'block',
           'name': 'BKSC:OTHDISK-MFCN14.000',
           'object_id': '52ffbbae-bdac-5194-ba6b-62ee17bfafce',
           'owner': 'lab-host2',
           'size_mb': 1048569,
           'type': 'Direct-Access',
           'usedsize_mb': 1048569}],
      'size_mb': 21139267,
      'storage_pool_id': 7,
      'tag': [''],
      'total_physicaldevices': 21,
      'usedsize_mb': 20511801}),
    ({'availsize_mb': 1048536,
      'category': 'Virtual Device',
      'name': 'thick-pool',
      'object_id': 'c1e0becc-3497-5d74-977a-1e5a79769576',
      'size_mb': 2097124,
      'storage_pool_id': 9,
      'usedsize_mb': 1048588},
     {'category': 'Virtual Device',
      'name': 'thick-pool',
      'object_id': 'c1e0becc-3497-5d74-977a-1e5a79769576',
      'physicaldevices': [
          {'availsize_mb': 524255,
           'connection_type': 'fc',
           'name': 'VIOLIN:CONCERTO ARRAY.001',
           'object_id': 'a90c4a11-33af-5530-80ca-2360fa477781',
           'owner': 'lab-host1',
           'size_mb': 524281,
           'type': 'Direct-Access',
           'usedsize_mb': 26},
          {'availsize_mb': 0,
           'connection_type': 'fc',
           'name': 'VIOLIN:CONCERTO ARRAY.002',
           'object_id': '0a625ec8-2e80-5086-9644-2ea8dd5c32ec',
           'owner': 'lab-host1',
           'size_mb': 524281,
           'type': 'Direct-Access',
           'usedsize_mb': 524281},
          {'availsize_mb': 0,
           'connection_type': 'fc',
           'name': 'VIOLIN:CONCERTO ARRAY.004',
           'object_id': '7018670b-3a79-5bdc-9d02-2d85602f361a',
           'owner': 'lab-host1',
           'size_mb': 524281,
           'type': 'Direct-Access',
           'usedsize_mb': 524281},
          {'availsize_mb': 524281,
           'connection_type': 'fc',
           'name': 'VIOLIN:CONCERTO ARRAY.003',
           'object_id': 'd859d47b-ca65-5d9d-a1c0-e288bbf39f48',
           'owner': 'lab-host1',
           'size_mb': 524281,
           'type': 'Direct-Access',
           'usedsize_mb': 0}],
      'size_mb': 2097124,
      'storage_pool_id': 9,
      'total_physicaldevices': 4,
      'usedsize_mb': 1048588})]


@ddt.ddt
class V7000CommonTestCase(test.TestCase):
    """Test case for Violin drivers."""
    def setUp(self):
        super(V7000CommonTestCase, self).setUp()
        self.conf = self.setup_configuration()
        self.driver = v7000_common.V7000Common(self.conf)
        self.driver.container = 'myContainer'
        self.driver.device_id = 'ata-VIOLIN_MEMORY_ARRAY_23109R00000022'
        self.stats = {}

    def setup_configuration(self):
        config = mock.Mock(spec=conf.Configuration)
        config.volume_backend_name = 'v7000_common'
        config.san_ip = '1.1.1.1'
        config.san_login = 'admin'
        config.san_password = ''
        config.san_thin_provision = False
        config.san_is_local = False
        config.gateway_mga = '2.2.2.2'
        config.gateway_mgb = '3.3.3.3'
        config.use_igroups = False
        config.violin_request_timeout = 300
        config.container = 'myContainer'
        config.violin_pool_allocation_method = 'random'
        config.violin_dedup_only_pools = None
        config.violin_dedup_capable_pools = None
        return config

    @mock.patch('vmemclient.open')
    def setup_mock_client(self, _m_client, m_conf=None):
        """Create a fake backend communication factory.

        The xg-tools creates a Concerto connection object (for V7000
        devices) and returns it for use on a call to vmemclient.open().
        """
        # configure the concerto object mock with defaults
        _m_concerto = mock.Mock(name='Concerto',
                                version='1.1.1',
                                spec=vmemclient.mock_client_conf)

        # if m_conf, clobber the defaults with it
        if m_conf:
            _m_concerto.configure_mock(**m_conf)

        # set calls to vmemclient.open() to return this mocked concerto object
        _m_client.return_value = _m_concerto

        return _m_client

    def setup_mock_concerto(self, m_conf=None):
        """Create a fake Concerto communication object."""
        _m_concerto = mock.Mock(name='Concerto',
                                version='1.1.1',
                                spec=vmemclient.mock_client_conf)

        if m_conf:
            _m_concerto.configure_mock(**m_conf)

        return _m_concerto

    def test_check_for_setup_error(self):
        """No setup errors are found."""
        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._is_supported_vmos_version = mock.Mock(return_value=True)

        result = self.driver.check_for_setup_error()

        self.driver._is_supported_vmos_version.assert_called_with(
            self.driver.vmem_mg.version)
        self.assertIsNone(result)

    def test_create_lun(self):
        """Lun is successfully created."""
        response = {'success': True, 'msg': 'Create resource successfully.'}
        size_in_mb = VOLUME['size'] * units.Ki

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)

        result = self.driver._create_lun(VOLUME)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.create_lun,
            'Create resource successfully.',
            VOLUME['id'], size_in_mb, False, False, size_in_mb,
            storage_pool_id=99)
        self.assertIsNone(result)

    def test_create_dedup_lun(self):
        """Lun is successfully created."""
        vol = VOLUME.copy()
        vol['size'] = 100
        vol['volume_type_id'] = '1'

        response = {'success': True, 'msg': 'Create resource successfully.'}
        size_in_mb = vol['size'] * units.Ki
        full_size_mb = size_in_mb

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        # simulate extra specs of {'thin': 'true', 'dedupe': 'true'}
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="True")

        self.driver._get_violin_extra_spec = mock.Mock(
            return_value=None)
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_DEDUP_POOL)

        result = self.driver._create_lun(vol)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.create_lun,
            'Create resource successfully.',
            VOLUME['id'], size_in_mb / 10, True, True, full_size_mb,
            storage_pool_id=99)
        self.assertIsNone(result)

    def test_fail_extend_dedup_lun(self):
        """Volume extend fails when new size would shrink the volume."""
        vol = VOLUME.copy()
        vol['volume_type_id'] = '1'

        size_in_mb = vol['size'] * units.Ki
        self.driver.vmem_mg = self.setup_mock_concerto()
        type(self.driver.vmem_mg.utility).is_external_head = mock.PropertyMock(
            return_value=False)

        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="True")

        failure = exception.VolumeDriverException
        self.assertRaises(failure, self.driver._extend_lun,
                          vol, size_in_mb)

    def test_extend_dedup_lun_external_head(self):
        """Volume extend fails when new size would shrink the volume."""
        vol = VOLUME.copy()
        vol['volume_type_id'] = '1'
        new_volume_size = 10

        response = {'success': True, 'message': 'Expand resource successfully'}
        conf = {
            'lun.extend_lun.return_value': response,
        }

        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        type(self.driver.vmem_mg.utility).is_external_head = mock.PropertyMock(
            return_value=False)

        change_in_size_mb = (new_volume_size - VOLUME['size']) * units.Ki
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._extend_lun(VOLUME, new_volume_size)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.extend_lun,
            response['message'], VOLUME['id'], change_in_size_mb)
        self.assertIsNone(result)

    def test_create_non_dedup_lun(self):
        """Lun is successfully created."""
        vol = VOLUME.copy()
        vol['size'] = 100
        vol['volume_type_id'] = '1'

        response = {'success': True, 'msg': 'Create resource successfully.'}
        size_in_mb = vol['size'] * units.Ki
        full_size_mb = size_in_mb

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        # simulate extra specs of {'thin': 'false', 'dedupe': 'false'}
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="False")

        self.driver._get_violin_extra_spec = mock.Mock(
            return_value=None)

        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)

        result = self.driver._create_lun(vol)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.create_lun,
            'Create resource successfully.',
            VOLUME['id'], size_in_mb, False, False, full_size_mb,
            storage_pool_id=99)
        self.assertIsNone(result)

    def test_create_lun_fails(self):
        """Array returns error that the lun already exists."""
        response = {'success': False,
                    'msg': 'Duplicate Virtual Device name. Error: 0x90010022'}
        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)
        self.driver._send_cmd = mock.Mock(return_value=response)

        self.assertIsNone(self.driver._create_lun(VOLUME))

    def test_create_lun_on_a_storage_pool(self):
        """Lun is successfully created."""
        vol = VOLUME.copy()
        vol['size'] = 100
        vol['volume_type_id'] = '1'

        response = {'success': True, 'msg': 'Create resource successfully.'}
        size_in_mb = vol['size'] * units.Ki
        full_size_mb = size_in_mb

        conf = {
            'lun.create_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="False")

        # simulates extra specs: {'storage_pool', 'StoragePool'}
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePool")
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)

        result = self.driver._create_lun(vol)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.create_lun,
            'Create resource successfully.',
            VOLUME['id'], size_in_mb, False, False, full_size_mb,
            storage_pool_id=99)
        self.assertIsNone(result)

    def test_delete_lun(self):
        """Lun is deleted successfully."""
        response = {'success': True, 'msg': 'Delete resource successfully'}
        success_msgs = ['Delete resource successfully', '']

        conf = {
            'lun.delete_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)
        self.driver._delete_lun_snapshot_bookkeeping = mock.Mock()

        result = self.driver._delete_lun(VOLUME)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.delete_lun,
            success_msgs, VOLUME['id'])
        self.driver._delete_lun_snapshot_bookkeeping.assert_called_with(
            VOLUME['id'])

        self.assertIsNone(result)

    # TODO(vthirumalai): More delete lun failure cases to be added after
    # collecting the possible responses from Concerto

    def test_extend_lun(self):
        """Volume extend completes successfully."""
        new_volume_size = 10
        change_in_size_mb = (new_volume_size - VOLUME['size']) * units.Ki

        response = {'success': True, 'message': 'Expand resource successfully'}

        conf = {
            'lun.extend_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)

        result = self.driver._extend_lun(VOLUME, new_volume_size)

        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.lun.extend_lun,
            response['message'], VOLUME['id'], change_in_size_mb)
        self.assertIsNone(result)

    def test_extend_lun_new_size_is_too_small(self):
        """Volume extend fails when new size would shrink the volume."""
        new_volume_size = 0
        change_in_size_mb = (new_volume_size - VOLUME['size']) * units.Ki

        response = {'success': False, 'msg': 'Invalid size. Error: 0x0902000c'}
        failure = exception.ViolinBackendErr

        conf = {
            'lun.resize_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(side_effect=failure(message='fail'))

        self.assertRaises(failure, self.driver._extend_lun,
                          VOLUME, change_in_size_mb)

    def test_create_volume_from_snapshot(self):
        """Create a new cinder volume from a given snapshot of a lun."""
        object_id = '12345'
        vdev_id = 11111
        lun_info_response = {'subType': 'THICK',
                             'virtualDeviceID': vdev_id}
        response = {'success': True,
                    'object_id': object_id,
                    'msg': 'Copy TimeMark successfully.'}
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'

        conf = {
            'lun.get_lun_info.return_value': lun_info_response,
            'lun.copy_snapshot_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)
        self.driver._wait_for_lun_or_snap_copy = mock.Mock()

        result = self.driver._create_volume_from_snapshot(SNAPSHOT, VOLUME)

        self.driver.vmem_mg.lun.copy_snapshot_to_new_lun.assert_called_with(
            source_lun=SNAPSHOT['volume_id'],
            source_snapshot_comment=compressed_snap_id,
            destination=VOLUME['id'], storage_pool_id=99)
        self.driver._wait_for_lun_or_snap_copy.assert_called_with(
            SNAPSHOT['volume_id'], dest_vdev_id=vdev_id)

        self.assertIsNone(result)

    def test_create_volume_from_snapshot_on_a_storage_pool(self):
        """Create a new cinder volume from a given snapshot of a lun."""
        dest_vol = VOLUME.copy()
        dest_vol['size'] = 100
        dest_vol['volume_type_id'] = '1'
        object_id = '12345'
        vdev_id = 11111
        lun_info_response = {'subType': 'THICK',
                             'virtualDeviceID': vdev_id}
        response = {'success': True,
                    'object_id': object_id,
                    'msg': 'Copy TimeMark successfully.'}
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'

        conf = {
            'lun.get_lun_info.return_value': lun_info_response,
            'lun.copy_snapshot_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePool")
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="False")
        self.driver._wait_for_lun_or_snap_copy = mock.Mock()

        result = self.driver._create_volume_from_snapshot(SNAPSHOT, dest_vol)

        self.assertIsNone(result)

    def test_create_volume_from_snapshot_fails(self):
        """Array returns error that the lun already exists."""
        vdev_id = 11111
        lun_info_response = {'subType': 'THICK',
                             'virtualDeviceID': vdev_id}
        response = {'success': False,
                    'msg': 'Duplicate Virtual Device name. Error: 0x90010022'}
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'
        failure = exception.ViolinBackendErrExists

        conf = {
            'lun.get_lun_info.return_value': lun_info_response,
            'lun.copy_snapshot_to_new_lun.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._send_cmd = mock.Mock(return_value=response)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)

        self.driver._send_cmd = mock.Mock(side_effect=failure(message='fail'))

        self.assertRaises(failure, self.driver._create_volume_from_snapshot,
                          SNAPSHOT, VOLUME)

    @ddt.data(2, 10)
    def test_create_lun_from_lun_and_resize(self, size):
        """lun full clone to new volume completes successfully."""
        larger_size_flag = False
        dest_vol = VOLUME.copy()
        if size > VOLUME['size']:
            dest_vol['size'] = size
            larger_size_flag = True
        object_id = fake.OBJECT_ID
        lun_info_response = {'subType': 'THICK'}
        copy_response = {'success': True,
                         'object_id': object_id,
                         'msg': 'Copy Snapshot resource successfully'}

        conf = {
            'lun.get_lun_info.return_value': lun_info_response,
            'lun.copy_lun_to_new_lun.return_value': copy_response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._ensure_snapshot_resource_area = mock.Mock()
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)
        self.driver._wait_for_lun_or_snap_copy = mock.Mock()
        self.driver._extend_lun = mock.Mock()

        result = self.driver._create_lun_from_lun(SRC_VOL, dest_vol)

        self.driver._ensure_snapshot_resource_area.assert_called_with(
            SRC_VOL['id'])
        self.driver.vmem_mg.lun.copy_lun_to_new_lun.assert_called_with(
            source=SRC_VOL['id'], destination=VOLUME['id'], storage_pool_id=99)
        self.driver._wait_for_lun_or_snap_copy.assert_called_with(
            SRC_VOL['id'], dest_obj_id=object_id)
        if larger_size_flag:
            self.driver._extend_lun.assert_called_once_with(
                dest_vol, dest_vol['size'])
        else:
            self.assertFalse(self.driver._extend_lun.called)

        self.assertIsNone(result)

    @ddt.data(2, 10)
    def test_create_lun_from_lun_on_a_storage_pool_and_resize(self, size):
        """lun full clone to new volume completes successfully."""
        larger_size_flag = False
        dest_vol = VOLUME.copy()
        if size > VOLUME['size']:
            dest_vol['size'] = size
            larger_size_flag = True
        dest_vol['volume_type_id'] = fake.VOLUME_TYPE_ID
        object_id = fake.OBJECT_ID
        lun_info_response = {'subType': 'THICK'}
        copy_response = {'success': True,
                         'object_id': object_id,
                         'msg': 'Copy Snapshot resource successfully'}

        conf = {
            'lun.get_lun_info.return_value': lun_info_response,
            'lun.copy_lun_to_new_lun.return_value': copy_response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._ensure_snapshot_resource_area = mock.Mock()
        self.driver._wait_for_lun_or_snap_copy = mock.Mock()
        self.driver._extend_lun = mock.Mock()

        # simulates extra specs: {'storage_pool', 'StoragePool'}
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePool")
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THIN_POOL)

        self.driver._get_volume_type_extra_spec = mock.Mock(
            side_effect=["True", "False"])

        result = self.driver._create_lun_from_lun(SRC_VOL, dest_vol)

        self.driver._ensure_snapshot_resource_area.assert_called_with(
            SRC_VOL['id'])
        self.driver.vmem_mg.lun.copy_lun_to_new_lun.assert_called_with(
            source=SRC_VOL['id'], destination=dest_vol['id'],
            storage_pool_id=99)
        self.driver._wait_for_lun_or_snap_copy.assert_called_with(
            SRC_VOL['id'], dest_obj_id=object_id)
        if larger_size_flag:
            self.driver._extend_lun.assert_called_once_with(
                dest_vol, dest_vol['size'])
        else:
            self.assertFalse(self.driver._extend_lun.called)

        self.assertIsNone(result)

    def test_create_lun_from_lun_fails(self):
        """lun full clone to new volume fails correctly."""
        failure = exception.ViolinBackendErr
        lun_info_response = {
            'subType': 'THICK',
        }
        copy_response = {
            'success': False,
            'msg': 'Snapshot Resource is not created ' +
            'for this virtual device. Error: 0x0901008c',
        }

        conf = {
            'lun.get_lun_info.return_value': lun_info_response,
            'lun.copy_lun_to_new_lun.return_value': copy_response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._ensure_snapshot_resource_area = mock.Mock()
        self.driver._send_cmd = mock.Mock(side_effect=failure(message='fail'))
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)

        self.assertRaises(failure, self.driver._create_lun_from_lun,
                          SRC_VOL, VOLUME)

    def test_create_lun_from_thin_lun_fails(self):
        """lun full clone of thin lun is not supported."""
        failure = exception.ViolinBackendErr
        lun_info_response = {
            'subType': 'THIN',
        }

        conf = {
            'lun.get_lun_info.return_value': lun_info_response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        self.assertRaises(failure, self.driver._create_lun_from_lun,
                          SRC_VOL, VOLUME)

    def test_create_lun_from_dedup_lun_fails(self):
        """lun full clone of dedup lun is not supported."""
        failure = exception.ViolinBackendErr
        lun_info_response = {
            'subType': 'DEDUP',
        }

        conf = {
            'lun.get_lun_info.return_value': lun_info_response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        self.assertRaises(failure, self.driver._create_lun_from_lun,
                          SRC_VOL, VOLUME)

    def test_send_cmd(self):
        """Command callback completes successfully."""
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        response = {'success': True, 'msg': 'Operation successful'}

        request_func = mock.Mock(return_value=response)

        result = self.driver._send_cmd(request_func, success_msg, request_args)

        self.assertEqual(response, result)

    def test_send_cmd_request_timed_out(self):
        """The callback retry timeout hits immediately."""
        failure = exception.ViolinRequestRetryTimeout
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        self.conf.violin_request_timeout = 0

        request_func = mock.Mock()

        self.assertRaises(failure, self.driver._send_cmd,
                          request_func, success_msg, request_args)

    def test_send_cmd_response_has_no_message(self):
        """The callback returns no message on the first call."""
        success_msg = 'success'
        request_args = ['arg1', 'arg2', 'arg3']
        response1 = {'success': True, 'msg': None}
        response2 = {'success': True, 'msg': 'success'}

        request_func = mock.Mock(side_effect=[response1, response2])

        self.assertEqual(response2, self.driver._send_cmd
                         (request_func, success_msg, request_args))

    def test_check_error_code(self):
        """Return an exception for a valid error code."""
        failure = exception.ViolinBackendErr
        response = {'success': False, 'msg': 'Error: 0x90000000'}
        self.assertRaises(failure, self.driver._check_error_code,
                          response)

    def test_check_error_code_non_fatal_error(self):
        """Returns no exception for a non-fatal error code."""
        response = {'success': False, 'msg': 'Error: 0x9001003c'}
        self.assertIsNone(self.driver._check_error_code(response))

    def test_compress_snapshot_id(self):
        test_snap_id = "12345678-abcd-1234-cdef-0123456789ab"
        expected = "12345678abcd1234cdef0123456789ab"

        self.assertEqual(32, len(expected))
        result = self.driver._compress_snapshot_id(test_snap_id)
        self.assertEqual(expected, result)

    def test_ensure_snapshot_resource_area(self):
        result_dict = {'success': True, 'res': 'Successful'}

        self.driver.vmem_mg = self.setup_mock_concerto()
        snap = self.driver.vmem_mg.snapshot
        snap.lun_has_a_snapshot_resource = mock.Mock(return_value=False)
        snap.create_snapshot_resource = mock.Mock(return_value=result_dict)
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)

        with mock.patch('cinder.db.sqlalchemy.api.volume_get',
                        return_value=VOLUME):
            result = self.driver._ensure_snapshot_resource_area(VOLUME_ID)

        self.assertIsNone(result)
        snap.lun_has_a_snapshot_resource.assert_called_with(lun=VOLUME_ID)
        snap.create_snapshot_resource.assert_called_with(
            lun=VOLUME_ID,
            size=int(math.ceil(0.2 * (VOLUME['size'] * 1024))),
            enable_notification=False,
            policy=v7000_common.CONCERTO_DEFAULT_SRA_POLICY,
            enable_expansion=
            v7000_common.CONCERTO_DEFAULT_SRA_ENABLE_EXPANSION,
            expansion_threshold=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_THRESHOLD,
            expansion_increment=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_INCREMENT,
            expansion_max_size=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_MAX_SIZE,
            enable_shrink=v7000_common.CONCERTO_DEFAULT_SRA_ENABLE_SHRINK,
            storage_pool_id=99)

    def test_ensure_snapshot_resource_area_with_storage_pool(self):

        dest_vol = VOLUME.copy()
        dest_vol['size'] = 2
        dest_vol['volume_type_id'] = '1'

        result_dict = {'success': True, 'res': 'Successful'}

        self.driver.vmem_mg = self.setup_mock_concerto()
        snap = self.driver.vmem_mg.snapshot
        snap.lun_has_a_snapshot_resource = mock.Mock(return_value=False)
        snap.create_snapshot_resource = mock.Mock(return_value=result_dict)

        # simulates extra specs: {'storage_pool', 'StoragePool'}
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePool")
        self.driver._get_storage_pool = mock.Mock(
            return_value=DEFAULT_THICK_POOL)

        self.driver._get_volume_type_extra_spec = mock.Mock(
            side_effect=["True", "False"])

        with mock.patch('cinder.db.sqlalchemy.api.volume_get',
                        return_value=dest_vol):
            result = self.driver._ensure_snapshot_resource_area(VOLUME_ID)

        self.assertIsNone(result)
        snap.lun_has_a_snapshot_resource.assert_called_with(lun=VOLUME_ID)
        snap.create_snapshot_resource.assert_called_with(
            lun=VOLUME_ID,
            size=int(math.ceil(0.2 * (VOLUME['size'] * 1024))),
            enable_notification=False,
            policy=v7000_common.CONCERTO_DEFAULT_SRA_POLICY,
            enable_expansion=
            v7000_common.CONCERTO_DEFAULT_SRA_ENABLE_EXPANSION,
            expansion_threshold=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_THRESHOLD,
            expansion_increment=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_INCREMENT,
            expansion_max_size=
            v7000_common.CONCERTO_DEFAULT_SRA_EXPANSION_MAX_SIZE,
            enable_shrink=v7000_common.CONCERTO_DEFAULT_SRA_ENABLE_SHRINK,
            storage_pool_id=99)

    def test_ensure_snapshot_resource_policy(self):
        result_dict = {'success': True, 'res': 'Successful'}

        self.driver.vmem_mg = self.setup_mock_concerto()

        snap = self.driver.vmem_mg.snapshot
        snap.lun_has_a_snapshot_policy = mock.Mock(return_value=False)
        snap.create_snapshot_policy = mock.Mock(return_value=result_dict)

        result = self.driver._ensure_snapshot_policy(VOLUME_ID)
        self.assertIsNone(result)
        snap.lun_has_a_snapshot_policy.assert_called_with(lun=VOLUME_ID)

        snap.create_snapshot_policy.assert_called_with(
            lun=VOLUME_ID,
            max_snapshots=v7000_common.CONCERTO_DEFAULT_POLICY_MAX_SNAPSHOTS,
            enable_replication=False,
            enable_snapshot_schedule=False,
            enable_cdp=False,
            retention_mode=v7000_common.CONCERTO_DEFAULT_POLICY_RETENTION_MODE)

    def test_delete_lun_snapshot_bookkeeping(self):
        result_dict = {'success': True, 'res': 'Successful'}

        self.driver.vmem_mg = self.setup_mock_concerto()
        snap = self.driver.vmem_mg.snapshot
        snap.get_snapshots = mock.Mock(
            return_value=[],
            side_effect=vmemclient.core.error.NoMatchingObjectIdError)
        snap.delete_snapshot_policy = mock.Mock(return_value=result_dict)
        snap.delete_snapshot_resource = mock.Mock()

        result = self.driver._delete_lun_snapshot_bookkeeping(
            volume_id=VOLUME_ID)

        self.assertIsNone(result)

        snap.get_snapshots.assert_called_with(VOLUME_ID)
        snap.delete_snapshot_policy.assert_called_with(lun=VOLUME_ID)
        snap.delete_snapshot_resource.assert_called_with(lun=VOLUME_ID)

    def test_create_lun_snapshot(self):
        response = {'success': True, 'msg': 'Create TimeMark successfully'}

        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._ensure_snapshot_resource_area = (
            mock.Mock(return_value=True))
        self.driver._ensure_snapshot_policy = mock.Mock(return_value=True)
        self.driver._send_cmd = mock.Mock(return_value=response)

        with mock.patch('cinder.db.sqlalchemy.api.volume_get',
                        return_value=VOLUME):
            result = self.driver._create_lun_snapshot(SNAPSHOT)

        self.assertIsNone(result)

        self.driver._ensure_snapshot_resource_area.assert_called_with(
            VOLUME_ID)
        self.driver._ensure_snapshot_policy.assert_called_with(VOLUME_ID)
        self.driver._send_cmd.assert_called_with(
            self.driver.vmem_mg.snapshot.create_lun_snapshot,
            'Create TimeMark successfully',
            lun=VOLUME_ID,
            comment=self.driver._compress_snapshot_id(SNAPSHOT_ID),
            priority=v7000_common.CONCERTO_DEFAULT_PRIORITY,
            enable_notification=False)

    def test_delete_lun_snapshot(self):
        response = {'success': True, 'msg': 'Delete TimeMark successfully'}
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'
        oid = 'abc123-abc123abc123-abc123'

        conf = {
            'snapshot.snapshot_comment_to_object_id.return_value': oid,
            'snapshot.delete_lun_snapshot.return_value': response,
        }

        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)

        result = self.driver._delete_lun_snapshot(SNAPSHOT)

        self.assertTrue(result)

    def test_delete_lun_snapshot_with_retry(self):
        response = [
            {'success': False, 'msg': 'Error 0x50f7564c'},
            {'success': True, 'msg': 'Delete TimeMark successfully'}]
        compressed_snap_id = 'abcdabcd1234abcd1234abcdeffedcbb'
        oid = 'abc123-abc123abc123-abc123'

        conf = {
            'snapshot.snapshot_comment_to_object_id.return_value': oid,
            'snapshot.delete_lun_snapshot.side_effect': response,
        }

        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._compress_snapshot_id = mock.Mock(
            return_value=compressed_snap_id)

        result = self.driver._delete_lun_snapshot(SNAPSHOT)

        self.assertTrue(result)
        self.assertEqual(
            len(response),
            self.driver.vmem_mg.snapshot.delete_lun_snapshot.call_count)

    def test_wait_for_lun_or_snap_copy_completes_for_snap(self):
        """waiting for a snapshot to copy succeeds."""
        vdev_id = 11111
        response = (vdev_id, None, 100)

        conf = {
            'snapshot.get_snapshot_copy_status.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        result = self.driver._wait_for_lun_or_snap_copy(
            SRC_VOL['id'], dest_vdev_id=vdev_id)

        (self.driver.vmem_mg.snapshot.get_snapshot_copy_status.
         assert_called_with(SRC_VOL['id']))
        self.assertTrue(result)

    def test_wait_for_lun_or_snap_copy_completes_for_lun(self):
        """waiting for a lun to copy succeeds."""
        object_id = '12345'
        response = (object_id, None, 100)

        conf = {
            'lun.get_lun_copy_status.return_value': response,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        result = self.driver._wait_for_lun_or_snap_copy(
            SRC_VOL['id'], dest_obj_id=object_id)

        self.driver.vmem_mg.lun.get_lun_copy_status.assert_called_with(
            SRC_VOL['id'])
        self.assertTrue(result)

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_volume_type_extra_spec(self,
                                        m_get_volume_type,
                                        m_get_admin_context):
        """Volume_type extra specs are found successfully."""
        vol = VOLUME.copy()
        vol['volume_type_id'] = 1
        volume_type = {'extra_specs': {'override:test_key': 'test_value'}}

        m_get_admin_context.return_value = None
        m_get_volume_type.return_value = volume_type

        result = self.driver._get_volume_type_extra_spec(vol, 'test_key')

        m_get_admin_context.assert_called_with()
        m_get_volume_type.assert_called_with(None, vol['volume_type_id'])
        self.assertEqual('test_value', result)

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_violin_extra_spec(self,
                                   m_get_volume_type,
                                   m_get_admin_context):
        """Volume_type extra specs are found successfully."""
        vol = VOLUME.copy()
        vol['volume_type_id'] = 1
        volume_type = {'extra_specs': {'violin:test_key': 'test_value'}}

        m_get_admin_context.return_value = None
        m_get_volume_type.return_value = volume_type

        result = self.driver._get_volume_type_extra_spec(vol, 'test_key')

        m_get_admin_context.assert_called_with()
        m_get_volume_type.assert_called_with(None, vol['volume_type_id'])
        self.assertEqual(result, 'test_value')

    def test_process_extra_specs_dedup(self):
        '''Process the given extra specs and fill the required dict.'''
        vol = VOLUME.copy()
        vol['volume_type_id'] = 1
        spec_dict = {
            'pool_type': 'dedup',
            'size_mb': 205,
            'thick': False,
            'dedup': True,
            'thin': True}

        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="True")

        result = self.driver._process_extra_specs(vol)
        self.assertEqual(spec_dict, result)

    def test_process_extra_specs_no_specs(self):
        '''Fill the required spec_dict in the absence of extra specs.'''
        vol = VOLUME.copy()
        spec_dict = {
            'pool_type': 'thick',
            'size_mb': 2048,
            'thick': True,
            'dedup': False,
            'thin': False}

        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="False")

        result = self.driver._process_extra_specs(vol)
        self.assertEqual(spec_dict, result)

    def test_process_extra_specs_no_specs_thin(self):
        '''Fill the required spec_dict in the absence of extra specs.'''
        vol = VOLUME.copy()
        spec_dict = {
            'pool_type': 'thin',
            'size_mb': 205,
            'thick': False,
            'dedup': False,
            'thin': True}

        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._get_volume_type_extra_spec = mock.Mock(
            return_value="False")

        save_thin = self.conf.san_thin_provision
        self.conf.san_thin_provision = True
        result = self.driver._process_extra_specs(vol)
        self.assertEqual(spec_dict, result)
        self.conf.san_thin_provision = save_thin

    def test_process_extra_specs_thin(self):
        '''Fill the required spec_dict in the absence of extra specs.'''
        vol = VOLUME.copy()
        vol['volume_type_id'] = 1
        spec_dict = {
            'pool_type': 'thin',
            'size_mb': 205,
            'thick': False,
            'dedup': False,
            'thin': True}

        self.driver.vmem_mg = self.setup_mock_concerto()
        self.driver._get_volume_type_extra_spec = mock.Mock(
            side_effect=["True", "False"])

        result = self.driver._process_extra_specs(vol)
        self.assertEqual(spec_dict, result)

    def test_get_storage_pool_with_extra_specs(self):
        '''Select a suitable pool based on specified extra specs.'''
        vol = VOLUME.copy()
        vol['volume_type_id'] = 1
        pool_type = "thick"

        selected_pool = {
            'storage_pool': 'StoragePoolA',
            'storage_pool_id': 99,
            'dedup': False,
            'thin': False}

        conf = {
            'pool.select_storage_pool.return_value': selected_pool,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePoolA",
        )

        result = self.driver._get_storage_pool(
            vol,
            100,
            pool_type,
            "create_lun")

        self.assertEqual(result, selected_pool)

    def test_get_storage_pool_configured_pools(self):
        '''Select a suitable pool based on configured pools.'''
        vol = VOLUME.copy()
        pool_type = "dedup"

        self.conf.violin_dedup_only_pools = ['PoolA', 'PoolB']
        self.conf.violin_dedup_capable_pools = ['PoolC', 'PoolD']

        selected_pool = {
            'dedup': True,
            'storage_pool': 'PoolA',
            'storage_pool_id': 123,
            'thin': True,
        }

        conf = {
            'pool.select_storage_pool.return_value': selected_pool,
        }

        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)
        self.driver._get_violin_extra_spec = mock.Mock(
            return_value="StoragePoolA")

        result = self.driver._get_storage_pool(
            vol,
            100,
            pool_type,
            "create_lun",
        )

        self.assertEqual(result, selected_pool)
        self.driver.vmem_mg.pool.select_storage_pool.assert_called_with(
            100,
            pool_type,
            None,
            self.conf.violin_dedup_only_pools,
            self.conf.violin_dedup_capable_pools,
            "random",
            "create_lun",
        )

    def test_get_volume_stats(self):
        '''Getting stats works successfully.'''

        self.conf.reserved_percentage = 0

        expected_answers = {
            'vendor_name': 'Violin Memory, Inc.',
            'reserved_percentage': 0,
            'QoS_support': False,
            'free_capacity_gb': 2781,
            'total_capacity_gb': 14333,
            'consistencygroup_support': False,
        }
        owner = 'lab-host1'

        def lookup(value):
            return six.text_type(value) + '.vmem.com'
        conf = {
            'pool.get_storage_pools.return_value': STATS_STORAGE_POOL_RESPONSE,
        }
        self.driver.vmem_mg = self.setup_mock_concerto(m_conf=conf)

        with mock.patch('socket.getfqdn', side_effect=lookup):
            result = self.driver._get_volume_stats(owner)

        self.assertDictEqual(expected_answers, result)
