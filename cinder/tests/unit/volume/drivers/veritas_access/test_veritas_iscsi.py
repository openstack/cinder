# Copyright 2017 Veritas Technologies LLC.
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
Unit tests for Veritas Access cinder driver.
"""
import json
import tempfile
from unittest import mock
from xml.dom.minidom import Document

from oslo_config import cfg
from oslo_utils.secretutils import md5
import requests

from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.veritas_access import veritas_iscsi

CONF = cfg.CONF
FAKE_BACKEND = 'fake_backend'


class MockResponse(object):
    def __init__(self):
        self.status_code = 200

    def json(self):
        data = {'fake_key': 'fake_val'}
        return json.dumps(data)


class FakeXML(object):

    def __init__(self):
        self.tempdir = tempfile.mkdtemp()

    def create_vrts_fake_config_file(self):

        target = 'iqn.2017-02.com.veritas:faketarget'
        portal = '1.1.1.1'
        auth_detail = '0'
        doc = Document()

        vrts_node = doc.createElement("VRTS")
        doc.appendChild(vrts_node)

        vrts_target_node = doc.createElement("VrtsTargets")
        vrts_node.appendChild(vrts_target_node)

        target_node = doc.createElement("Target")

        vrts_target_node.appendChild(target_node)

        name_ele = doc.createElement("Name")
        portal_ele = doc.createElement("PortalIP")
        auth_ele = doc.createElement("Authentication")

        name_ele.appendChild(doc.createTextNode(target))
        portal_ele.appendChild(doc.createTextNode(portal))
        auth_ele.appendChild(doc.createTextNode(auth_detail))

        target_node.appendChild(name_ele)
        target_node.appendChild(portal_ele)
        target_node.appendChild(auth_ele)

        filename = 'vrts_config.xml'
        config_file_path = self.tempdir + '/' + filename

        f = open(config_file_path, 'w')
        doc.writexml(f)
        f.close()
        return config_file_path


class fake_volume(object):
    def __init__(self):
        self.id = 'fakeid'
        self.name = 'fakename'
        self.size = 1
        self.snapshot_id = False
        self.metadata = {'dense': True}


class fake_volume2(object):
    def __init__(self):
        self.id = 'fakeid2'
        self.name = 'fakename2'
        self.size = 2
        self.snapshot_id = False
        self.metadata = {'dense': True}


class fake_clone_volume(object):
    def __init__(self):
        self.id = 'fakecloneid'
        self.name = 'fakeclonename'
        self.size = 1
        self.snapshot_id = False


class fake_clone_volume2(object):
    def __init__(self):
        self.id = 'fakecloneid2'
        self.name = 'fakeclonename'
        self.size = 2
        self.snapshot_id = False


class fake_snapshot(object):
    def __init__(self):
        self.id = 'fakeid'
        self.volume_id = 'fakevolumeid'
        self.volume_size = 1


class ACCESSIscsiDriverTestCase(test.TestCase):
    """Tests ACCESSShareDriver."""

    volume = fake_volume()
    volume2 = fake_volume2()
    snapshot = fake_snapshot()
    clone_volume = fake_clone_volume()
    clone_volume2 = fake_clone_volume2()
    connector = {
        'initiator': 'iqn.1994-05.com.fakeinitiator'
    }

    def setUp(self):
        super(ACCESSIscsiDriverTestCase, self).setUp()
        self._create_fake_config()
        lcfg = self.configuration
        self._context = context.get_admin_context()
        self._driver = veritas_iscsi.ACCESSIscsiDriver(configuration=lcfg)
        self._driver.do_setup(self._context)

    def _create_fake_config(self):
        self.mock_object(veritas_iscsi.ACCESSIscsiDriver,
                         '_authenticate_access')
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.safe_get = self.fake_safe_get
        self.configuration.san_ip = '1.1.1.1'
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'passwd'
        self.configuration.san_api_port = 14161
        self.configuration.vrts_lun_sparse = True
        self.configuration.vrts_target_config = (
            FakeXML().create_vrts_fake_config_file())
        self.configuration.target_port = 3260
        self.configuration.volume_backend_name = FAKE_BACKEND

    def fake_safe_get(self, value):
        try:
            val = getattr(self.configuration, value)
        except AttributeError:
            val = None
        return val

    def test_create_volume(self):
        self.mock_object(self._driver, '_vrts_get_suitable_target')
        self.mock_object(self._driver, '_vrts_get_targets_store')
        self.mock_object(self._driver, '_access_api')

        mylist = []
        target = {}
        target['name'] = 'iqn.2017-02.com.veritas:faketarget'
        target['portal_ip'] = '1.1.1.1'
        target['auth'] = '0'
        mylist.append(target)

        self._driver._vrts_get_suitable_target.return_value = (
            'iqn.2017-02.com.veritas:faketarget')
        self._driver._access_api.return_value = True
        return_list = self._driver._vrts_parse_xml_file(
            self.configuration.vrts_target_config)

        self._driver.create_volume(self.volume)

        self.assertEqual(mylist, return_list)
        self.assertEqual(1, self._driver._access_api.call_count)

    def test_create_volume_negative(self):
        self.mock_object(self._driver, '_vrts_get_suitable_target')
        self.mock_object(self._driver, '_vrts_get_targets_store')
        self.mock_object(self._driver, '_access_api')

        self._driver._vrts_get_suitable_target.return_value = (
            'iqn.2017-02.com.veritas:faketarget')
        self._driver._access_api.return_value = False

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.create_volume,
                          self.volume)

    def test_create_volume_negative_no_suitable_target_found(self):
        self.mock_object(self._driver, '_vrts_get_suitable_target')
        self.mock_object(self._driver, '_access_api')

        self._driver._vrts_get_suitable_target.return_value = False

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.create_volume,
                          self.volume)
        self.assertEqual(0, self._driver._access_api.call_count)

    def test_delete_volume(self):
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_access_api')

        va_lun_name = self._driver._get_va_lun_name(self.volume.id)

        length = len(self.volume.id)
        index = int(length / 2)
        name1 = self.volume.id[:index]
        name2 = self.volume.id[index:]
        crc1 = md5(name1.encode('utf-8'),
                   usedforsecurity=False).hexdigest()[:5]
        crc2 = md5(name2.encode('utf-8'),
                   usedforsecurity=False).hexdigest()[:5]

        volume_name_to_ret = 'cinder' + '-' + crc1 + '-' + crc2

        lun = {}
        lun['lun_name'] = va_lun_name
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}
        self._driver._get_vrts_lun_list.return_value = lun_list

        self._driver._access_api.return_value = True

        self._driver.delete_volume(self.volume)
        self.assertEqual(volume_name_to_ret, va_lun_name)
        self.assertEqual(1, self._driver._access_api.call_count)

    def test_delete_volume_negative(self):
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_access_api')

        self._driver._access_api.return_value = False

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.delete_volume,
                          self.volume)

    def test_create_snapshot(self):
        self.mock_object(self._driver, '_access_api')

        self._driver._access_api.return_value = True

        self._driver.create_snapshot(self.snapshot)
        self.assertEqual(1, self._driver._access_api.call_count)

    def test_create_snapshot_negative(self):
        self.mock_object(self._driver, '_access_api')

        self._driver._access_api.return_value = False

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.create_snapshot,
                          self.snapshot)

        self.assertEqual(1, self._driver._access_api.call_count)

    def test_delete_snapshot(self):
        self.mock_object(self._driver, '_access_api')

        self._driver._access_api.return_value = True

        self._driver.delete_snapshot(self.snapshot)
        self.assertEqual(1, self._driver._access_api.call_count)

    def test_delete_snapshot_negative(self):
        self.mock_object(self._driver, '_access_api')

        self._driver._access_api.return_value = False

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.delete_snapshot,
                          self.snapshot)

        self.assertEqual(1, self._driver._access_api.call_count)

    def test_create_cloned_volume(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_vrts_extend_lun')
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_vrts_get_fs_list')
        self.mock_object(self._driver, '_vrts_is_space_available_in_store')

        va_lun_name = self._driver._get_va_lun_name(self.volume.id)

        lun = {}
        lun['lun_name'] = va_lun_name
        lun['fs_name'] = 'fake_fs'
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}

        self._driver._get_vrts_lun_list.return_value = lun_list

        self._driver._vrts_is_space_available_in_store.return_value = True

        self._driver._access_api.return_value = True

        self._driver.create_cloned_volume(self.clone_volume, self.volume)
        self.assertEqual(1, self._driver._access_api.call_count)
        self.assertEqual(0, self._driver._vrts_extend_lun.call_count)

    def test_create_cloned_volume_of_greater_size(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_vrts_extend_lun')
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_vrts_get_fs_list')
        self.mock_object(self._driver, '_vrts_is_space_available_in_store')

        va_lun_name = self._driver._get_va_lun_name(self.volume.id)

        lun = {}
        lun['lun_name'] = va_lun_name
        lun['fs_name'] = 'fake_fs'
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}

        self._driver._get_vrts_lun_list.return_value = lun_list

        self._driver._vrts_is_space_available_in_store.return_value = True

        self._driver._access_api.return_value = True

        self._driver.create_cloned_volume(self.clone_volume2, self.volume)
        self.assertEqual(1, self._driver._access_api.call_count)
        self.assertEqual(1, self._driver._vrts_extend_lun.call_count)

    def test_create_cloned_volume_negative(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_vrts_get_fs_list')
        self.mock_object(self._driver, '_vrts_is_space_available_in_store')

        va_lun_name = self._driver._get_va_lun_name(self.volume.id)

        lun = {}
        lun['lun_name'] = va_lun_name
        lun['fs_name'] = 'fake_fs'
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}

        self._driver._get_vrts_lun_list.return_value = lun_list

        self._driver._vrts_is_space_available_in_store.return_value = True

        self._driver._access_api.return_value = False

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.create_cloned_volume,
                          self.clone_volume, self.volume)

        self.assertEqual(1, self._driver._access_api.call_count)

    def test_create_volume_from_snapshot(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_vrts_extend_lun')
        self.mock_object(self._driver, '_vrts_get_targets_store')
        self.mock_object(self._driver, '_vrts_get_assigned_store')
        self.mock_object(self._driver, '_vrts_get_fs_list')
        self.mock_object(self._driver, '_vrts_is_space_available_in_store')

        snap_name = self._driver._get_va_lun_name(self.snapshot.id)

        snap = {}
        snap['snapshot_name'] = snap_name
        snap['target_name'] = 'fake_target'

        snapshots = []
        snapshots.append(snap)

        snap_info = {}
        snap_info['output'] = {'output': {'snapshots': snapshots}}

        self._driver._access_api.return_value = snap_info

        self._driver._vrts_is_space_available_in_store.return_value = True

        self._driver.create_volume_from_snapshot(self.volume, self.snapshot)
        self.assertEqual(2, self._driver._access_api.call_count)
        self.assertEqual(0, self._driver._vrts_extend_lun.call_count)

    def test_create_volume_from_snapshot_of_greater_size(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_vrts_extend_lun')
        self.mock_object(self._driver, '_vrts_get_targets_store')
        self.mock_object(self._driver, '_vrts_get_assigned_store')
        self.mock_object(self._driver, '_vrts_get_fs_list')
        self.mock_object(self._driver, '_vrts_is_space_available_in_store')

        snap_name = self._driver._get_va_lun_name(self.snapshot.id)

        snap = {}
        snap['snapshot_name'] = snap_name
        snap['target_name'] = 'fake_target'

        snapshots = []
        snapshots.append(snap)

        snap_info = {}
        snap_info['output'] = {'output': {'snapshots': snapshots}}

        self._driver._access_api.return_value = snap_info

        self._driver._vrts_is_space_available_in_store.return_value = True

        self._driver.create_volume_from_snapshot(self.volume2, self.snapshot)
        self.assertEqual(2, self._driver._access_api.call_count)
        self.assertEqual(1, self._driver._vrts_extend_lun.call_count)

    def test_create_volume_from_snapshot_negative(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_vrts_get_targets_store')

        snap = {}
        snap['snapshot_name'] = 'fake_snap_name'
        snap['target_name'] = 'fake_target'

        snapshots = []
        snapshots.append(snap)

        snap_info = {}
        snap_info['output'] = {'output': {'snapshots': snapshots}}

        self._driver._access_api.return_value = snap_info

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.create_volume_from_snapshot,
                          self.volume, self.snapshot)

        self.assertEqual(1, self._driver._access_api.call_count)
        self.assertEqual(0, self._driver._vrts_get_targets_store.call_count)

    def test_extend_volume(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_vrts_get_fs_list')
        self.mock_object(self._driver, '_vrts_is_space_available_in_store')

        va_lun_name = self._driver._get_va_lun_name(self.volume.id)

        lun = {}
        lun['lun_name'] = va_lun_name
        lun['fs_name'] = 'fake_fs'
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}

        self._driver._get_vrts_lun_list.return_value = lun_list
        self._driver._vrts_is_space_available_in_store.return_value = True

        self._driver._access_api.return_value = True

        self._driver.extend_volume(self.volume, 2)
        self.assertEqual(1, self._driver._access_api.call_count)

    def test_extend_volume_negative(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_vrts_get_fs_list')
        self.mock_object(self._driver, '_vrts_is_space_available_in_store')

        va_lun_name = self._driver._get_va_lun_name(self.volume.id)

        lun = {}
        lun['lun_name'] = va_lun_name
        lun['fs_name'] = 'fake_fs'
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}

        self._driver._get_vrts_lun_list.return_value = lun_list
        self._driver._vrts_is_space_available_in_store.return_value = True

        self._driver._access_api.return_value = False

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.extend_volume, self.volume, 2)
        self.assertEqual(1, self._driver._vrts_get_fs_list.call_count)
        self.assertEqual(1, self._driver._access_api.call_count)

    def test_extend_volume_negative_not_volume_found(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_vrts_get_fs_list')

        lun = {}
        lun['lun_name'] = 'fake_lun'
        lun['fs_name'] = 'fake_fs'
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}

        self._driver._get_vrts_lun_list.return_value = lun_list

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.extend_volume, self.volume, 2)

        self.assertEqual(0, self._driver._vrts_get_fs_list.call_count)
        self.assertEqual(0, self._driver._access_api.call_count)

    def test_initialize_connection(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_vrts_target_initiator_mapping')
        self.mock_object(self._driver, '_vrts_get_iscsi_properties')

        va_lun_name = self._driver._get_va_lun_name(self.volume.id)

        lun = {}
        lun['lun_name'] = va_lun_name
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}

        self._driver._get_vrts_lun_list.return_value = lun_list
        self._driver._access_api.return_value = True
        self._driver.initialize_connection(self.volume, self.connector)
        self.assertEqual(1, self._driver._vrts_get_iscsi_properties.call_count)

    def test_initialize_connection_negative(self):
        self.mock_object(self._driver, '_access_api')
        self.mock_object(self._driver, '_get_vrts_lun_list')
        self.mock_object(self._driver, '_vrts_target_initiator_mapping')
        self.mock_object(self._driver, '_vrts_get_iscsi_properties')

        lun = {}
        lun['lun_name'] = 'fakelun'
        lun['target_name'] = 'iqn.2017-02.com.veritas:faketarget'
        lun_list = {'output': {'output': {'luns': [lun]}}}
        self._driver.LUN_FOUND_INTERVAL = 5

        self._driver._get_vrts_lun_list.return_value = lun_list
        self._driver._access_api.return_value = True

        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.initialize_connection, self.volume,
                          self.connector)

        self.assertEqual(
            0, self._driver._vrts_target_initiator_mapping.call_count)
        self.assertEqual(0, self._driver._vrts_get_iscsi_properties.call_count)

    def test___vrts_get_iscsi_properties(self):
        self.mock_object(self._driver, '_access_api')

        va_lun_name = self._driver._get_va_lun_name(self.volume.id)
        storage_object = "'/fakestores/fakeio/" + va_lun_name + "'"

        lun_id_list = {}
        lun_id_list['output'] = ("[{'storage_object': " +
                                 storage_object + ", 'index': '1'}]")

        target_name = 'iqn.2017-02.com.veritas:faketarget'

        self._driver._access_api.return_value = lun_id_list

        iscsi_properties_ret_value = {}
        iscsi_properties_ret_value['target_discovered'] = True
        iscsi_properties_ret_value['target_iqn'] = target_name
        iscsi_properties_ret_value['target_portal'] = '1.1.1.1:3260'
        iscsi_properties_ret_value['target_lun'] = 1
        iscsi_properties_ret_value['volume_id'] = 'fakeid'
        iscsi_properties = self._driver._vrts_get_iscsi_properties(self.volume,
                                                                   target_name)

        self.assertEqual(iscsi_properties_ret_value, iscsi_properties)

    def test__access_api(self):
        self.mock_object(requests, 'session')

        provider = '%s:%s' % (self._driver._va_ip, self._driver._port)
        path = '/fake/path'
        input_data = {}
        mock_response = MockResponse()
        session = requests.session

        data = {'fake_key': 'fake_val'}
        json_data = json.dumps(data)

        session.request.return_value = mock_response
        ret_value = self._driver._access_api(session, provider, path,
                                             json.dumps(input_data), 'GET')

        self.assertEqual(json_data, ret_value)

    def test__access_api_negative(self):
        session = self._driver.session
        provider = '%s:%s' % (self._driver._va_ip, self._driver._port)
        path = '/fake/path'
        input_data = {}
        ret_value = self._driver._access_api(session, provider, path,
                                             json.dumps(input_data), 'GET')
        self.assertEqual(False, ret_value)

    def test__get_api(self):
        provider = '%s:%s' % (self._driver._va_ip, self._driver._port)
        tail = '/fake/path'
        ret = self._driver._get_api(provider, tail)

        api_root = 'https://%s/api/access' % (provider)
        to_be_ret = api_root + tail
        self.assertEqual(to_be_ret, ret)

    def test__vrts_target_initiator_mapping_negative(self):
        self.mock_object(self._driver, '_access_api')
        target_name = 'fake_target'
        initiator_name = 'fake_initiator'

        self._driver._access_api.return_value = False
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._vrts_target_initiator_mapping,
                          target_name, initiator_name)

    def test_get_volume_stats(self):
        self.mock_object(self._driver, '_authenticate_access')
        self.mock_object(self._driver, '_vrts_get_targets_store')
        self.mock_object(self._driver, '_vrts_get_fs_list')

        target_list = []
        target_details = {}
        target_details['fs_list'] = ['fs1']
        target_details['wwn'] = 'iqn.2017-02.com.veritas:faketarget'
        target_list.append(target_details)

        self._driver._vrts_get_targets_store.return_value = target_list

        fs_list = []
        fs_dict = {}
        fs_dict['name'] = 'fs1'
        fs_dict['file_storage_capacity'] = 10737418240
        fs_dict['file_storage_used'] = 1073741824
        fs_list.append(fs_dict)

        self._driver._vrts_get_fs_list.return_value = fs_list

        self._driver.get_volume_stats()
        data = {
            'volume_backend_name': FAKE_BACKEND,
            'vendor_name': 'Veritas',
            'driver_version': '1.0',
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': 10,
            'free_capacity_gb': 9,
            'reserved_percentage': 0,
            'thin_provisioning_support': True
        }

        self.assertEqual(data, self._driver._stats)
