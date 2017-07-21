# Copyright (c) 2012 - 2016 EMC Corporation, Inc.
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

import mock

from cinder import context
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.volume.drivers.coprhd import common as coprhd_common
from cinder.volume.drivers.coprhd import fc as coprhd_fc
from cinder.volume.drivers.coprhd import iscsi as coprhd_iscsi
from cinder.volume.drivers.coprhd import scaleio as coprhd_scaleio
from cinder.volume import volume_types

"""
Test Data required for mocking
"""
export_group_details_data = {
    "inactive": False,
    "initiators": [{"creation_time": 1392194176020,
                    "host": {"id": "urn:storageos:Host:3e21edff-8662-4e60-ab5",
                             "link": {"href": "/compute/hosts/urn:storageos:H",
                                      "rel": "self"}},
                    "hostname": "lglw7134",
                    "id": "urn:storageos:Initiator:13945431-06b7-44a0-838c-50",
                    "inactive": False,
                    "initiator_node": "20:00:00:90:FA:13:81:8D",
                    "initiator_port": "iqn.1993-08.org.deb:01:222",
                    "link": {"href": "/compute/initiators/urn:storageos:Initi",
                             "rel": "self"},
                    "protocol": "iSCSI",
                    "registration_status": "REGISTERED",
                    "tags": []}],
    "name": "ccgroup",
    "project": 'project',
    "tags": [],
    "tenant": 'tenant',
    "type": "Host",
    "varray": {"id": "urn:storageos:VirtualArray:5af376e9-ce2f-493d-9079-a872",
               "link": {"href": "/vdc/varrays/urn:storageos:VirtualArray:5af3",
                        "rel": "self"}
               },
    "volumes": [{"id": "urn:storageos:Volume:6dc64865-bb25-431c-b321-ac268f16"
                 "a7ae:vdc1",
                 "lun": 1
                 }]
}

varray_detail_data = {"name": "varray"}

export_group_list = ["urn:storageos:ExportGroup:2dbce233-7da0-47cb-8ff3-68f48"]

iscsi_itl_list = {"itl": [{"hlu": 3,
                           "initiator": {"id": "urn:storageos:Initiator:13945",
                                         "link": {"rel": "self",
                                                  "href": "/comput"},
                                         "port": "iqn.1993-08.org.deb:01:222"},
                           "export": {"id": "urn:storageos:ExportGroup:2dbce2",
                                      "name": "ccgroup",
                                      "link": {"rel": "self",
                                               "href": "/block/expo"}},
                           "device": {"id": "urn:storageos:Volume:aa1fc84a-af",
                                      "link": {"rel": "self",
                                               "href": "/block/volumes/urn:s"},
                                      "wwn": "600009700001957015735330303535"},
                           "target": {"id": "urn:storageos:StoragePort:d7e42",
                                      "link": {"rel": "self",
                                               "href": "/vdc/stor:"},
                                      "port": "50:00:09:73:00:18:95:19",
                                      'ip_address': "10.10.10.10",
                                      'tcp_port': '22'}},
                          {"hlu": 3,
                           "initiator": {"id": "urn:storageos:Initiator:13945",
                                         "link": {"rel": "self",
                                                  "href": "/comput"},
                                         "port": "iqn.1993-08.org.deb:01:222"},
                           "export": {"id": "urn:storageos:ExportGroup:2dbce2",
                                      "name": "ccgroup",
                                      "link": {"rel": "self",
                                               "href": "/block/expo"}},
                           "device": {"id": "urn:storageos:Volume:aa1fc84a-af",
                                      "link": {"rel": "self",
                                               "href": "/block/volumes/urn:s"},
                                      "wwn": "600009700001957015735330303535"},
                           "target": {"id": "urn:storageos:StoragePort:d7e42",
                                      "link": {"rel": "self",
                                               "href": "/vdc/stor:"},
                                      "port": "50:00:09:73:00:18:95:19",
                                      'ip_address': "10.10.10.10",
                                      'tcp_port': '22'}}]}

fcitl_itl_list = {"itl": [{"hlu": 3,
                           "initiator": {"id": "urn:storageos:Initiator:13945",
                                         "link": {"rel": "self",
                                                  "href": "/comput"},
                                         "port": "12:34:56:78:90:12:34:56"},
                           "export": {"id": "urn:storageos:ExportGroup:2dbce2",
                                      "name": "ccgroup",
                                      "link": {"rel": "self",
                                               "href": "/block/expo"}},
                           "device": {"id": "urn:storageos:Volume:aa1fc84a-af",
                                      "link": {"rel": "self",
                                               "href": "/block/volumes/urn:s"},
                                      "wwn": "600009700001957015735330303535"},
                           "target": {"id": "urn:storageos:StoragePort:d7e42",
                                      "link": {"rel": "self",
                                               "href": "/vdc/stor:"},
                                      "port": "12:34:56:78:90:12:34:56",
                                      'ip_address': "10.10.10.10",
                                      'tcp_port': '22'}},
                          {"hlu": 3,
                           "initiator": {"id": "urn:storageos:Initiator:13945",
                                         "link": {"rel": "self",
                                                  "href": "/comput"},
                                         "port": "12:34:56:78:90:12:34:56"},
                           "export": {"id": "urn:storageos:ExportGroup:2dbce2",
                                      "name": "ccgroup",
                                      "link": {"rel": "self",
                                               "href": "/block/expo"}},
                           "device": {"id": "urn:storageos:Volume:aa1fc84a-af",
                                      "link": {"rel": "self",
                                               "href": "/block/volumes/urn:s"},
                                      "wwn": "600009700001957015735330303535"},
                           "target": {"id": "urn:storageos:StoragePort:d7e42",
                                      "link": {"rel": "self",
                                               "href": "/vdc/stor:"},
                                      "port": "12:34:56:78:90:12:34:56",
                                      'ip_address': "10.10.10.10",
                                      'tcp_port': '22'}}]}

scaleio_itl_list = {"itl": [{"hlu": -1,
                             "initiator": {"id":
                                           "urn:storageos:Initiator:920aee",
                                           "link": {"rel": "self",
                                                    "href":
                                                    "/compute/initiators"},
                                           "port": "bfdf432500000004"},
                             "export": {"id":
                                        "urn:storageos:ExportGroup:5449235",
                                        "name": "10.108.225.109",
                                        "link": {"rel": "self",
                                                 "href":
                                                 "/block/exports/urn:stor"}},
                             "device": {"id":
                                        "urn:storageos:Volume:b3624a83-3eb",
                                        "link": {"rel": "self",
                                                 "href": "/block/volume"},
                                        "wwn":
                                        "4F48CC4C27A43248092128B400000004"},
                             "target": {}},
                            {"hlu": -1,
                             "initiator": {"id":
                                           "urn:storageos:Initiator:920aee",
                                           "link": {"rel": "self",
                                                    "href":
                                                    "/compute/initiators/"},
                                           "port": "bfdf432500000004"},
                             "export": {"id":
                                        "urn:storageos:ExportGroup:5449235",
                                        "name": "10.108.225.109",
                                        "link": {"rel": "self",
                                                 "href":
                                                 "/block/exports/urn:stor"}},
                             "device": {"id":
                                        "urn:storageos:Volume:c014e96a-557",
                                        "link": {"rel": "self",
                                                 "href":
                                                 "/block/volumes/urn:stor"},
                                        "wwn":
                                        "4F48CC4C27A43248092129320000000E"},
                             "target": {}}]}


class test_volume_data(object):
    name = 'test-vol1'
    size = 1
    volume_name = 'test-vol1'
    id = fake.VOLUME_ID
    group_id = None
    provider_auth = None
    project_id = fake.PROJECT_ID
    display_name = 'test-vol1'
    display_description = 'test volume',
    volume_type_id = None
    provider_id = fake.PROVIDER_ID

    def __init__(self, volume_type_id):
        self.volume_type_id = volume_type_id


class source_test_volume_data(object):
    name = 'source_test-vol1'
    size = 1
    volume_name = 'source_test-vol1'
    id = fake.VOLUME2_ID
    group_id = None
    provider_auth = None
    project_id = fake.PROJECT_ID
    display_name = 'source_test-vol1'
    display_description = 'test volume'
    volume_type_id = None

    def __init__(self, volume_type_id):
        self.volume_type_id = volume_type_id


class test_clone_volume_data(object):
    name = 'clone-test-vol1'
    size = 1
    volume_name = 'clone-test-vol1'
    id = fake.VOLUME3_ID
    provider_auth = None
    project_id = fake.PROJECT_ID
    display_name = 'clone-test-vol1'
    display_description = 'clone test volume'
    volume_type_id = None

    def __init__(self, volume_type_id):
        self.volume_type_id = volume_type_id


class test_snapshot_data(object):
    name = 'snapshot1'
    display_name = 'snapshot1'
    size = 1
    id = fake.SNAPSHOT_ID
    volume_name = 'test-vol1'
    volume_id = fake.VOLUME_ID
    volume = None
    volume_size = 1
    project_id = fake.PROJECT_ID
    status = fields.SnapshotStatus.AVAILABLE

    def __init__(self, src_volume):
        self.volume = src_volume


def get_connector_data():
    connector = {'ip': '10.0.0.2',
                 'initiator': 'iqn.1993-08.org.deb:01:222',
                 'wwpns': ["1234567890123456", "1234567890543211"],
                 'wwnns': ["223456789012345", "223456789054321"],
                 'host': 'fakehost'}
    return connector


class test_group_data(object):
    name = 'group_name'
    display_name = 'group_name'
    id = fake.GROUP_ID
    volume_type_ids = None
    volume_types = None
    group_type_id = None
    status = fields.GroupStatus.AVAILABLE

    def __init__(self, volume_types, group_type_id):
        self.group_type_id = group_type_id
        self.volume_types = volume_types


class test_group_type_data(object):
    name = 'group_name'
    display_name = 'group_name'
    groupsnapshot_id = None
    id = fake.GROUP_TYPE_ID
    description = 'group'


class test_group_snap_data(object):
    name = 'cg_snap_name'
    display_name = 'cg_snap_name'
    id = fake.GROUP_SNAPSHOT_ID
    group_id = fake.GROUP_ID
    status = fields.GroupStatus.AVAILABLE
    snapshots = []
    group = None
    group_type_id = None

    def __init__(self, volume_types, group_type_id):
        self.group_type_id = group_type_id
        self.group = test_group_data(volume_types, group_type_id)


class MockedEMCCoprHDDriverCommon(coprhd_common.EMCCoprHDDriverCommon):

    def __init__(self, protocol, default_backend_name,
                 configuration=None):

        super(MockedEMCCoprHDDriverCommon, self).__init__(
            protocol, default_backend_name, configuration)

    def authenticate_user(self):
        pass

    def get_exports_count_by_initiators(self, initiator_ports):
        return 0

    def _get_coprhd_volume_name(self, vol, verbose=False):
        if verbose is True:
            return {'volume_name': "coprhd_vol_name",
                    'volume_uri': "coprhd_vol_uri"}
        else:
            return "coprhd_vol_name"

    def _get_coprhd_snapshot_name(self, snapshot, resUri):
        return "coprhd_snapshot_name"

    def _get_coprhd_cgid(self, cgid):
        return "cg_uri"

    def init_volume_api(self):
        self.volume_api = mock.Mock()
        self.volume_api.get.return_value = {
            'name': 'source_test-vol1',
            'size': 1,
            'volume_name': 'source_test-vol1',
            'id': fake.VOLUME_ID,
            'group_id': fake.GROUP_ID,
            'provider_auth': None,
            'project_id': fake.PROJECT_ID,
            'display_name': 'source_test-vol1',
            'display_description': 'test volume',
            'volume_type_id': fake.VOLUME_TYPE_ID}

    def init_coprhd_api_components(self):
        self.volume_obj = mock.Mock()
        self.volume_obj.create.return_value = "volume_created"
        self.volume_obj.volume_query.return_value = "volume_uri"
        self.volume_obj.get_storageAttributes.return_value = (
            'block', 'volume_name')
        self.volume_obj.storage_resource_query.return_value = "volume_uri"
        self.volume_obj.is_volume_detachable.return_value = False
        self.volume_obj.volume_clone_detach.return_value = 'detached'
        self.volume_obj.getTags.return_value = (
            ["Openstack-vol", "Openstack-vol1"])
        self.volume_obj.tag.return_value = "tagged"
        self.volume_obj.clone.return_value = "volume-cloned"

        if(self.protocol == "iSCSI"):
            self.volume_obj.get_exports_by_uri.return_value = (
                iscsi_itl_list)
        elif(self.protocol == "FC"):
            self.volume_obj.get_exports_by_uri.return_value = (
                fcitl_itl_list)
        else:
            self.volume_obj.get_exports_by_uri.return_value = (
                scaleio_itl_list)

        self.volume_obj.list_volumes.return_value = []
        self.volume_obj.show.return_value = {"id": "vol_id"}
        self.volume_obj.expand.return_value = "expanded"

        self.tag_obj = mock.Mock()
        self.tag_obj.list_tags.return_value = [
            "Openstack-vol", "Openstack-vol1"]
        self.tag_obj.tag_resource.return_value = "Tagged"

        self.exportgroup_obj = mock.Mock()
        self.exportgroup_obj.exportgroup_list.return_value = (
            export_group_list)
        self.exportgroup_obj.exportgroup_show.return_value = (
            export_group_details_data)

        self.exportgroup_obj.exportgroup_add_volumes.return_value = (
            "volume-added")

        self.host_obj = mock.Mock()
        self.host_obj.list_by_tenant.return_value = []
        self.host_obj.list_all.return_value = [{'id': "host1_id",
                                                'name': "host1"}]
        self.host_obj.list_initiators.return_value = [
            {'name': "12:34:56:78:90:12:34:56"},
            {'name': "12:34:56:78:90:54:32:11"},
            {'name': "bfdf432500000004"}]

        self.hostinitiator_obj = mock.Mock()
        self.varray_obj = mock.Mock()
        self.varray_obj.varray_show.return_value = varray_detail_data

        self.snapshot_obj = mock.Mock()
        mocked_snap_obj = self.snapshot_obj.return_value
        mocked_snap_obj.storageResource_query.return_value = (
            "resourceUri")
        mocked_snap_obj.snapshot_create.return_value = (
            "snapshot_created")
        mocked_snap_obj.snapshot_query.return_value = "snapshot_uri"

        self.consistencygroup_obj = mock.Mock()
        mocked_group_object = self.consistencygroup_obj.return_value
        mocked_group_object.create.return_value = "CG-Created"
        mocked_group_object.consistencygroup_query.return_value = "CG-uri"


class EMCCoprHDISCSIDriverTest(test.TestCase):

    def setUp(self):
        super(EMCCoprHDISCSIDriverTest, self).setUp()
        self.create_coprhd_setup()

    def create_coprhd_setup(self):

        self.configuration = mock.Mock()
        self.configuration.coprhd_hostname = "10.10.10.10"
        self.configuration.coprhd_port = "4443"
        self.configuration.volume_backend_name = "EMCCoprHDISCSIDriver"
        self.configuration.coprhd_username = "user-name"
        self.configuration.coprhd_password = "password"
        self.configuration.coprhd_tenant = "tenant"
        self.configuration.coprhd_project = "project"
        self.configuration.coprhd_varray = "varray"
        self.configuration.coprhd_emulate_snapshot = False

        self.volume_type = self.create_coprhd_volume_type()
        self.volume_type_id = self.volume_type.id
        self.group_type = test_group_type_data()
        self.group_type_id = self.group_type.id

        self.mock_object(coprhd_iscsi.EMCCoprHDISCSIDriver,
                         '_get_common_driver',
                         self._get_mocked_common_driver)
        self.driver = coprhd_iscsi.EMCCoprHDISCSIDriver(
            configuration=self.configuration)

    def tearDown(self):
        self._cleanUp()
        super(EMCCoprHDISCSIDriverTest, self).tearDown()

    def _cleanUp(self):
        self.delete_vipr_volume_type()

    def create_coprhd_volume_type(self):
        ctx = context.get_admin_context()
        vipr_volume_type = volume_types.create(ctx,
                                               "coprhd-volume-type",
                                               {'CoprHD:VPOOL':
                                                'vpool_coprhd'})
        return vipr_volume_type

    def _get_mocked_common_driver(self):
        return MockedEMCCoprHDDriverCommon(
            protocol="iSCSI",
            default_backend_name="EMCViPRISCSIDriver",
            configuration=self.configuration)

    def delete_vipr_volume_type(self):
        ctx = context.get_admin_context()
        volume_types.destroy(ctx, self.volume_type_id)

    def test_create_destroy(self):
        volume = test_volume_data(self.volume_type_id)

        self.driver.create_volume(volume)
        self.driver.delete_volume(volume)

    def test_get_volume_stats(self):
        vol_stats = self.driver.get_volume_stats(True)
        self.assertEqual('unknown', vol_stats['free_capacity_gb'])

    def test_create_volume_clone(self):
        src_volume_data = test_volume_data(self.volume_type_id)
        clone_volume_data = test_clone_volume_data(self.volume_type_id)
        self.driver.create_volume(src_volume_data)
        self.driver.create_cloned_volume(clone_volume_data, src_volume_data)
        self.driver.delete_volume(src_volume_data)
        self.driver.delete_volume(clone_volume_data)

    def test_create_destroy_snapshot(self):
        volume_data = test_volume_data(self.volume_type_id)
        snapshot_data = test_snapshot_data(
            source_test_volume_data(self.volume_type_id))

        self.driver.create_volume(volume_data)
        self.driver.create_snapshot(snapshot_data)
        self.driver.delete_snapshot(snapshot_data)
        self.driver.delete_volume(volume_data)

    def test_create_volume_from_snapshot(self):

        src_vol_data = source_test_volume_data(self.volume_type_id)
        self.driver.create_volume(src_vol_data)

        volume_data = test_volume_data(self.volume_type_id)
        snapshot_data = test_snapshot_data(src_vol_data)

        self.driver.create_snapshot(snapshot_data)
        self.driver.create_volume_from_snapshot(volume_data, snapshot_data)

        self.driver.delete_snapshot(snapshot_data)
        self.driver.delete_volume(src_vol_data)
        self.driver.delete_volume(volume_data)

    def test_extend_volume(self):
        volume_data = test_volume_data(self.volume_type_id)
        self.driver.create_volume(volume_data)
        self.driver.extend_volume(volume_data, 2)
        self.driver.delete_volume(volume_data)

    def test_initialize_and_terminate_connection(self):
        connector_data = get_connector_data()
        volume_data = test_volume_data(self.volume_type_id)

        self.driver.create_volume(volume_data)
        res_initialize = self.driver.initialize_connection(
            volume_data, connector_data)
        expected_initialize = {'driver_volume_type': 'iscsi',
                               'data': {'target_lun': 3,
                                        'target_portal': '10.10.10.10:22',
                                        'target_iqn':
                                        '50:00:09:73:00:18:95:19',
                                        'target_discovered': False,
                                        'volume_id': fake.VOLUME_ID}}
        self.assertEqual(
            expected_initialize, res_initialize, 'Unexpected return data')

        self.driver.terminate_connection(volume_data, connector_data)
        self.driver.delete_volume(volume_data)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_delete_empty_group(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True]
        group_data = test_group_data([self.volume_type],
                                     self.group_type_id)
        ctx = context.get_admin_context()
        self.driver.create_group(ctx, group_data)
        model_update, volumes_model_update = (
            self.driver.delete_group(ctx, group_data, []))
        self.assertEqual([], volumes_model_update, 'Unexpected return data')

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_update_delete_group(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True, True, True]
        group_data = test_group_data([self.volume_type],
                                     self.group_type_id)
        ctx = context.get_admin_context()
        self.driver.create_group(ctx, group_data)

        volume = test_volume_data(self.volume_type_id)
        self.driver.create_volume(volume)

        model_update, ret1, ret2 = (
            self.driver.update_group(ctx, group_data, [volume], []))

        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)

        model_update, volumes_model_update = (
            self.driver.delete_group(ctx, group_data, [volume]))
        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)
        self.assertEqual([{'status': 'deleted', 'id': fake.VOLUME_ID}],
                         volumes_model_update)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_delete_group_snap(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True]
        group_snap_data = test_group_snap_data([self.volume_type],
                                               self.group_type_id)
        ctx = context.get_admin_context()

        model_update, snapshots_model_update = (
            self.driver.create_group_snapshot(ctx, group_snap_data, []))
        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)
        self.assertEqual([], snapshots_model_update, 'Unexpected return data')

        model_update, snapshots_model_update = (
            self.driver.delete_group_snapshot(ctx, group_snap_data, []))
        self.assertEqual({}, model_update, 'Unexpected return data')
        self.assertEqual([], snapshots_model_update, 'Unexpected return data')


class EMCCoprHDFCDriverTest(test.TestCase):

    def setUp(self):
        super(EMCCoprHDFCDriverTest, self).setUp()
        self.create_coprhd_setup()

    def create_coprhd_setup(self):

        self.configuration = mock.Mock()
        self.configuration.coprhd_hostname = "10.10.10.10"
        self.configuration.coprhd_port = "4443"
        self.configuration.volume_backend_name = "EMCCoprHDFCDriver"
        self.configuration.coprhd_username = "user-name"
        self.configuration.coprhd_password = "password"
        self.configuration.coprhd_tenant = "tenant"
        self.configuration.coprhd_project = "project"
        self.configuration.coprhd_varray = "varray"
        self.configuration.coprhd_emulate_snapshot = False

        self.volume_type = self.create_coprhd_volume_type()
        self.volume_type_id = self.volume_type.id
        self.group_type = test_group_type_data()
        self.group_type_id = self.group_type.id

        self.mock_object(coprhd_fc.EMCCoprHDFCDriver,
                         '_get_common_driver',
                         self._get_mocked_common_driver)
        self.driver = coprhd_fc.EMCCoprHDFCDriver(
            configuration=self.configuration)

    def tearDown(self):
        self._cleanUp()
        super(EMCCoprHDFCDriverTest, self).tearDown()

    def _cleanUp(self):
        self.delete_vipr_volume_type()

    def create_coprhd_volume_type(self):
        ctx = context.get_admin_context()
        vipr_volume_type = volume_types.create(ctx,
                                               "coprhd-volume-type",
                                               {'CoprHD:VPOOL': 'vpool_vipr'})
        return vipr_volume_type

    def _get_mocked_common_driver(self):
        return MockedEMCCoprHDDriverCommon(
            protocol="FC",
            default_backend_name="EMCViPRFCDriver",
            configuration=self.configuration)

    def delete_vipr_volume_type(self):
        ctx = context.get_admin_context()
        volume_types.destroy(ctx, self.volume_type_id)

    def test_create_destroy(self):
        volume = test_volume_data(self.volume_type_id)

        self.driver.create_volume(volume)
        self.driver.delete_volume(volume)

    def test_get_volume_stats(self):
        vol_stats = self.driver.get_volume_stats(True)
        self.assertEqual('unknown', vol_stats['free_capacity_gb'])

    def test_create_volume_clone(self):

        src_volume_data = test_volume_data(self.volume_type_id)
        clone_volume_data = test_clone_volume_data(self.volume_type_id)
        self.driver.create_volume(src_volume_data)
        self.driver.create_cloned_volume(clone_volume_data, src_volume_data)
        self.driver.delete_volume(src_volume_data)
        self.driver.delete_volume(clone_volume_data)

    def test_create_destroy_snapshot(self):

        volume_data = test_volume_data(self.volume_type_id)
        snapshot_data = test_snapshot_data(
            source_test_volume_data(self.volume_type_id))

        self.driver.create_volume(volume_data)
        self.driver.create_snapshot(snapshot_data)
        self.driver.delete_snapshot(snapshot_data)
        self.driver.delete_volume(volume_data)

    def test_create_volume_from_snapshot(self):
        src_vol_data = source_test_volume_data(self.volume_type_id)
        self.driver.create_volume(src_vol_data)

        volume_data = test_volume_data(self.volume_type_id)
        snapshot_data = test_snapshot_data(src_vol_data)

        self.driver.create_snapshot(snapshot_data)
        self.driver.create_volume_from_snapshot(volume_data, snapshot_data)

        self.driver.delete_snapshot(snapshot_data)
        self.driver.delete_volume(src_vol_data)
        self.driver.delete_volume(volume_data)

    def test_extend_volume(self):
        volume_data = test_volume_data(self.volume_type_id)
        self.driver.create_volume(volume_data)
        self.driver.extend_volume(volume_data, 2)
        self.driver.delete_volume(volume_data)

    def test_initialize_and_terminate_connection(self):

        connector_data = get_connector_data()
        volume_data = test_volume_data(self.volume_type_id)

        self.driver.create_volume(volume_data)
        res_initiatlize = self.driver.initialize_connection(
            volume_data, connector_data)
        expected_initialize = {'driver_volume_type': 'fibre_channel',
                               'data': {'target_lun': 3,
                                        'initiator_target_map':
                                        {'1234567890543211':
                                         ['1234567890123456',
                                          '1234567890123456'],
                                         '1234567890123456':
                                         ['1234567890123456',
                                          '1234567890123456']},
                                        'target_wwn': ['1234567890123456',
                                                       '1234567890123456'],
                                        'target_discovered': False,
                                        'volume_id': fake.VOLUME_ID}}
        self.assertEqual(
            expected_initialize, res_initiatlize, 'Unexpected return data')

        res_terminate = self.driver.terminate_connection(
            volume_data, connector_data)
        expected_terminate = {'driver_volume_type': 'fibre_channel',
                              'data': {'initiator_target_map':
                                       {'1234567890543211':
                                        ['1234567890123456',
                                         '1234567890123456'],
                                        '1234567890123456':
                                        ['1234567890123456',
                                         '1234567890123456']},
                                       'target_wwn': ['1234567890123456',
                                                      '1234567890123456']}}
        self.assertEqual(
            expected_terminate, res_terminate, 'Unexpected return data')

        self.driver.delete_volume(volume_data)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_delete_empty_group(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True]
        group_data = test_group_data([self.volume_type],
                                     self.group_type_id)
        ctx = context.get_admin_context()
        self.driver.create_group(ctx, group_data)
        model_update, volumes_model_update = (
            self.driver.delete_group(ctx, group_data, []))
        self.assertEqual([], volumes_model_update, 'Unexpected return data')

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_update_delete_group(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True, True]
        group_data = test_group_data([self.volume_type],
                                     self.group_type_id)
        ctx = context.get_admin_context()
        self.driver.create_group(ctx, group_data)

        volume = test_volume_data(self.volume_type_id)
        self.driver.create_volume(volume)

        model_update, ret1, ret2 = (
            self.driver.update_group(ctx, group_data, [volume], []))

        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)

        model_update, volumes_model_update = (
            self.driver.delete_group(ctx, group_data, [volume]))
        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)
        self.assertEqual([{'status': 'deleted', 'id': fake.VOLUME_ID}],
                         volumes_model_update)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_delete_group_snap(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True]
        group_snap_data = test_group_snap_data([self.volume_type],
                                               self.group_type_id)
        ctx = context.get_admin_context()

        model_update, snapshots_model_update = (
            self.driver.create_group_snapshot(ctx, group_snap_data, []))
        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)
        self.assertEqual([], snapshots_model_update, 'Unexpected return data')

        model_update, snapshots_model_update = (
            self.driver.delete_group_snapshot(ctx, group_snap_data, []))
        self.assertEqual({}, model_update, 'Unexpected return data')
        self.assertEqual([], snapshots_model_update, 'Unexpected return data')


class EMCCoprHDScaleIODriverTest(test.TestCase):

    def setUp(self):
        super(EMCCoprHDScaleIODriverTest, self).setUp()
        self.create_coprhd_setup()

    def create_coprhd_setup(self):

        self.configuration = mock.Mock()
        self.configuration.coprhd_hostname = "10.10.10.10"
        self.configuration.coprhd_port = "4443"
        self.configuration.volume_backend_name = "EMCCoprHDFCDriver"
        self.configuration.coprhd_username = "user-name"
        self.configuration.coprhd_password = "password"
        self.configuration.coprhd_tenant = "tenant"
        self.configuration.coprhd_project = "project"
        self.configuration.coprhd_varray = "varray"
        self.configuration.coprhd_scaleio_rest_gateway_host = "10.10.10.11"
        self.configuration.coprhd_scaleio_rest_gateway_port = 443
        self.configuration.coprhd_scaleio_rest_server_username = (
            "scaleio_username")
        self.configuration.coprhd_scaleio_rest_server_password = (
            "scaleio_password")
        self.configuration.scaleio_verify_server_certificate = False
        self.configuration.scaleio_server_certificate_path = (
            "/etc/scaleio/certs")

        self.volume_type = self.create_coprhd_volume_type()
        self.volume_type_id = self.volume_type.id
        self.group_type = test_group_type_data()
        self.group_type_id = self.group_type.id

        self.mock_object(coprhd_scaleio.EMCCoprHDScaleIODriver,
                         '_get_common_driver',
                         self._get_mocked_common_driver)
        self.mock_object(coprhd_scaleio.EMCCoprHDScaleIODriver,
                         '_get_client_id',
                         self._get_client_id)
        self.driver = coprhd_scaleio.EMCCoprHDScaleIODriver(
            configuration=self.configuration)

    def tearDown(self):
        self._cleanUp()
        super(EMCCoprHDScaleIODriverTest, self).tearDown()

    def _cleanUp(self):
        self.delete_vipr_volume_type()

    def create_coprhd_volume_type(self):
        ctx = context.get_admin_context()
        vipr_volume_type = volume_types.create(ctx,
                                               "coprhd-volume-type",
                                               {'CoprHD:VPOOL': 'vpool_vipr'})
        return vipr_volume_type

    def _get_mocked_common_driver(self):
        return MockedEMCCoprHDDriverCommon(
            protocol="scaleio",
            default_backend_name="EMCCoprHDScaleIODriver",
            configuration=self.configuration)

    def _get_client_id(self, server_ip, server_port, server_username,
                       server_password, sdc_ip):
        return "bfdf432500000004"

    def delete_vipr_volume_type(self):
        ctx = context.get_admin_context()
        volume_types.destroy(ctx, self.volume_type_id)

    def test_create_destroy(self):
        volume = test_volume_data(self.volume_type_id)

        self.driver.create_volume(volume)
        self.driver.delete_volume(volume)

    def test_get_volume_stats(self):
        vol_stats = self.driver.get_volume_stats(True)
        self.assertEqual('unknown', vol_stats['free_capacity_gb'])

    def test_create_volume_clone(self):

        src_volume_data = test_volume_data(self.volume_type_id)
        clone_volume_data = test_clone_volume_data(self.volume_type_id)
        self.driver.create_volume(src_volume_data)
        self.driver.create_cloned_volume(clone_volume_data, src_volume_data)
        self.driver.delete_volume(src_volume_data)
        self.driver.delete_volume(clone_volume_data)

    def test_create_destroy_snapshot(self):

        volume_data = test_volume_data(self.volume_type_id)
        snapshot_data = test_snapshot_data(
            source_test_volume_data(self.volume_type_id))

        self.driver.create_volume(volume_data)
        self.driver.create_snapshot(snapshot_data)
        self.driver.delete_snapshot(snapshot_data)
        self.driver.delete_volume(volume_data)

    def test_create_volume_from_snapshot(self):
        src_vol_data = source_test_volume_data(self.volume_type_id)
        self.driver.create_volume(src_vol_data)

        volume_data = test_volume_data(self.volume_type_id)
        snapshot_data = test_snapshot_data(src_vol_data)

        self.driver.create_snapshot(snapshot_data)
        self.driver.create_volume_from_snapshot(volume_data, snapshot_data)

        self.driver.delete_snapshot(snapshot_data)
        self.driver.delete_volume(src_vol_data)
        self.driver.delete_volume(volume_data)

    def test_extend_volume(self):
        volume_data = test_volume_data(self.volume_type_id)
        self.driver.create_volume(volume_data)
        self.driver.extend_volume(volume_data, 2)
        self.driver.delete_volume(volume_data)

    def test_initialize_and_terminate_connection(self):

        connector_data = get_connector_data()
        volume_data = test_volume_data(self.volume_type_id)

        self.driver.create_volume(volume_data)
        res_initiatlize = self.driver.initialize_connection(
            volume_data, connector_data)
        exp_name = res_initiatlize['data']['scaleIO_volname']
        expected_initialize = {'data': {'bandwidthLimit': None,
                                        'hostIP': '10.0.0.2',
                                        'iopsLimit': None,
                                        'scaleIO_volname': exp_name,
                                        'scaleIO_volume_id': fake.PROVIDER_ID,
                                        'serverIP': '10.10.10.11',
                                        'serverPassword': 'scaleio_password',
                                        'serverPort': 443,
                                        'serverToken': None,
                                        'serverUsername': 'scaleio_username'},
                               'driver_volume_type': 'scaleio'}
        self.assertEqual(
            expected_initialize, res_initiatlize, 'Unexpected return data')

        self.driver.terminate_connection(
            volume_data, connector_data)
        self.driver.delete_volume(volume_data)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_delete_empty_group(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True]
        group_data = test_group_data([self.volume_type],
                                     self.group_type_id)
        ctx = context.get_admin_context()
        self.driver.create_group(ctx, group_data)
        model_update, volumes_model_update = (
            self.driver.delete_group(ctx, group_data, []))
        self.assertEqual([], volumes_model_update, 'Unexpected return data')

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_update_delete_group(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True, True, True]
        group_data = test_group_data([self.volume_type],
                                     self.group_type_id)
        ctx = context.get_admin_context()
        self.driver.create_group(ctx, group_data)

        volume = test_volume_data(self.volume_type_id)
        self.driver.create_volume(volume)

        model_update, ret1, ret2 = (
            self.driver.update_group(ctx, group_data, [volume], []))

        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)

        model_update, volumes_model_update = (
            self.driver.delete_group(ctx, group_data, [volume]))
        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)
        self.assertEqual([{'status': 'deleted', 'id': fake.VOLUME_ID}],
                         volumes_model_update)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_delete_group_snap(self, cg_ss_enabled):
        cg_ss_enabled.side_effect = [True, True]
        group_snap_data = test_group_snap_data([self.volume_type],
                                               self.group_type_id)
        ctx = context.get_admin_context()

        model_update, snapshots_model_update = (
            self.driver.create_group_snapshot(ctx, group_snap_data, []))
        self.assertEqual({'status': fields.GroupStatus.AVAILABLE},
                         model_update)
        self.assertEqual([], snapshots_model_update, 'Unexpected return data')

        model_update, snapshots_model_update = (
            self.driver.delete_group_snapshot(ctx, group_snap_data, []))
        self.assertEqual({}, model_update, 'Unexpected return data')
        self.assertEqual([], snapshots_model_update, 'Unexpected return data')
