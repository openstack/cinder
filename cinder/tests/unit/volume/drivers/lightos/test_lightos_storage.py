# Copyright (C) 2016-2022 Lightbits Labs Ltd.
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


from copy import deepcopy
import functools
import hashlib
import http.client as httpstatus
import json
from typing import Dict
from typing import List
from typing import Tuple
from unittest import mock
import uuid

from cinder import context
from cinder import db
from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
from cinder.volume import configuration as conf
from cinder.volume.drivers import lightos


FAKE_LIGHTOS_CLUSTER_NODES: Dict[str, List] = {
    "nodes": [
        {"UUID": "926e6df8-73e1-11ec-a624-000000000001",
         "nvmeEndpoint": "192.168.75.10:4420"},
        {"UUID": "926e6df8-73e1-11ec-a624-000000000002",
         "nvmeEndpoint": "192.168.75.11:4420"},
        {"UUID": "926e6df8-73e1-11ec-a624-000000000003",
         "nvmeEndpoint": "192.168.75.12:4420"}
    ]
}

FAKE_LIGHTOS_CLUSTER_INFO: Dict[str, str] = {
    'UUID': "926e6df8-73e1-11ec-a624-07ba3880f6cc",
    'subsystemNQN': "nqn.2014-08.org.nvmexpress:NVMf:uuid:"
    "f4a89ce0-9fc2-4900-bfa3-00ad27995e7b"
}

FAKE_CLIENT_HOSTNQN = "hostnqn1"
VOLUME_BACKEND_NAME = "lightos_backend"
RESERVED_PERCENTAGE = 30
DEVICE_SCAN_ATTEMPTS_DEFAULT = 5
LIGHTOS_API_SERVICE_TIMEOUT = 30
VOLUME_BACKEND_NAME = "lightos_backend"
RESERVED_PERCENTAGE = 30
DEFAULT_COMPRESSION = False


class InitiatorConnectorFactoryMocker:
    @staticmethod
    def factory(protocol, root_helper, driver=None,
                use_multipath=False,
                device_scan_attempts=DEVICE_SCAN_ATTEMPTS_DEFAULT,
                arch=None,
                *args, **kwargs):
        return InitialConnectorMock()


class InitialConnectorMock:
    nqn = FAKE_CLIENT_HOSTNQN
    found_discovery_client = True

    def get_hostnqn(self):
        return self.__class__.nqn

    def find_dsc(self):
        return self.__class__.found_discovery_client

    def get_connector_properties(self, root):
        return dict(nqn=self.__class__.nqn,
                    found_dsc=self.__class__.found_discovery_client)


def get_connector_properties():
    connector = InitialConnectorMock()
    return dict(nqn=connector.get_hostnqn(),
                found_dsc=connector.find_dsc())


def get_vol_etag(volume):
    v = deepcopy(volume)
    v.pop("ETag", None)
    dump = json.dumps(v, sort_keys=True).encode('utf-8')
    return hashlib.md5(dump).hexdigest()


class DBMock(object):

    def __init__(self):
        self.data = {
            "projects": {},
        }

    def get_or_create_project(self, project_name) -> Dict:
        project = self.data["projects"].setdefault(project_name, {})
        return project

    def get_project(self, project_name) -> Dict:
        project = self.data["projects"].get(project_name, None)
        return project if project else None

    def delete_project(self, project_name) -> Dict:
        assert project_name != "default", "can't delete default project"
        project = self.get_project(project_name)
        if not project:
            return None
        self.data["projects"].remove(project)
        return project

    def create_volume(self, volume) -> Tuple[int, Dict]:
        assert volume["project_name"] and volume["name"], "must be provided"
        project = self.get_or_create_project(volume["project_name"])
        volumes = project.setdefault("volumes", [])
        existing_volume = next(iter([vol for vol in volumes
                                     if vol["name"] == volume["name"]]), None)
        if not existing_volume:
            volume["UUID"] = str(uuid.uuid4())
            volumes.append(volume)
            return httpstatus.OK, volume
        return httpstatus.CONFLICT, None

    def get_volume_by_uuid(self, project_name,
                           volume_uuid) -> Tuple[int, Dict]:
        assert project_name and volume_uuid, "must be provided"
        project = self.get_project(project_name)
        if not project:
            return httpstatus.NOT_FOUND, None
        proj_vols = project.get("volumes", None)
        if not proj_vols:
            return httpstatus.NOT_FOUND, None
        vol = next(iter([vol for vol in proj_vols
                         if vol["UUID"] == volume_uuid]), None)
        return (httpstatus.OK, vol) if vol else (httpstatus.NOT_FOUND, None)

    def update_volume_by_uuid(self, project_name,
                              volume_uuid, **kwargs) -> Tuple[int, Dict]:
        error_code, volume = self.get_volume_by_uuid(project_name, volume_uuid)
        if error_code != httpstatus.OK:
            return error_code, None
        etag = kwargs.get("etag", None)
        if etag:
            vol_etag = volume.get("ETag", None)
            if etag != vol_etag:
                return httpstatus.BAD_REQUEST, None
        if kwargs.get("size", None):
            volume["size"] = kwargs["size"]
        if kwargs.get("acl", None):
            volume["acl"] = {'values': kwargs.get('acl')}
        volume["ETag"] = get_vol_etag(volume)
        return httpstatus.OK, volume

    def get_volume_by_name(self, project_name,
                           volume_name) -> Tuple[int, Dict]:
        assert project_name and volume_name, "must be provided"
        project = self.get_project(project_name)
        if not project:
            return httpstatus.NOT_FOUND, None
        proj_vols = project.get("volumes", None)
        if not proj_vols:
            return httpstatus.NOT_FOUND, None
        vol = next(iter([vol for vol in proj_vols
                         if vol["name"] == volume_name]), None)
        return (httpstatus.OK, vol) if vol else (httpstatus.NOT_FOUND, None)

    def delete_volume(self, project_name, volume_uuid) -> Tuple[int, Dict]:
        assert project_name and volume_uuid, "must be provided"
        project = self.get_project(project_name)
        if not project:
            return httpstatus.NOT_FOUND, None
        proj_vols = project.get("volumes", None)
        if not proj_vols:
            return httpstatus.NOT_FOUND, None
        for vol in proj_vols:
            if vol["UUID"] == volume_uuid:
                proj_vols.remove(vol)
        return httpstatus.OK, vol

    def update_volume(self, **kwargs):
        assert("project_name" in kwargs and kwargs["project_name"]), \
            "project_name must be provided"

    def create_snapshot(self, snapshot) -> Tuple[int, Dict]:
        assert snapshot["project_name"] and snapshot["name"], \
            "must be provided"
        project = self.get_or_create_project(snapshot["project_name"])
        snapshots = project.setdefault("snapshots", [])
        existing_snap = next(iter([snap for snap in snapshots
                                   if snap["name"] == snapshot["name"]]), None)
        if not existing_snap:
            snapshot["UUID"] = str(uuid.uuid4())
            snapshots.append(snapshot)
            return httpstatus.OK, snapshot
        return httpstatus.CONFLICT, None

    def delete_snapshot(self, project_name, snapshot_uuid) -> Tuple[int, Dict]:
        assert project_name and snapshot_uuid, "must be provided"
        project = self.get_project(project_name)
        if not project:
            return httpstatus.NOT_FOUND, None
        proj_snaps = project.get("snapshots", None)
        if not proj_snaps:
            return httpstatus.NOT_FOUND, None
        for snap in proj_snaps:
            if snap["UUID"] == snapshot_uuid:
                proj_snaps.remove(snap)
        return httpstatus.OK, snap

    def get_snapshot_by_name(self, project_name,
                             snapshot_name) -> Tuple[int, Dict]:
        assert project_name and snapshot_name, "must be provided"
        project = self.get_project(project_name)
        if not project:
            return httpstatus.NOT_FOUND, None
        proj_snaps = project.get("snapshots", None)
        if not proj_snaps:
            return httpstatus.NOT_FOUND, None
        snap = next(iter([snap for snap in proj_snaps
                          if snap["name"] == snapshot_name]), None)
        return (httpstatus.OK, snap) if snap else (httpstatus.NOT_FOUND, None)

    def get_snapshot_by_uuid(self, project_name,
                             snapshot_uuid) -> Tuple[int, Dict]:
        assert project_name and snapshot_uuid, "must be provided"
        project = self.get_project(project_name)
        if not project:
            return httpstatus.NOT_FOUND, None
        proj_snaps = project.get("snapshots", None)
        if not proj_snaps:
            return httpstatus.NOT_FOUND, None
        snap = next(iter([snap for snap in proj_snaps
                          if snap["UUID"] == snapshot_uuid]), None)
        return (httpstatus.OK, snap) if snap else (httpstatus.NOT_FOUND, None)


class LightOSStorageVolumeDriverTest(test.TestCase):

    def setUp(self):
        """Initialize LightOS Storage Driver."""
        super(LightOSStorageVolumeDriverTest, self).setUp()

        configuration = mock.Mock(conf.Configuration)

        configuration.lightos_api_address = \
            "10.10.10.71,10.10.10.72,10.10.10.73"
        configuration.lightos_api_port = 443
        configuration.lightos_jwt = None
        configuration.lightos_snapshotname_prefix = 'openstack_'
        configuration.lightos_intermediate_snapshot_name_prefix = 'for_clone_'
        configuration.lightos_default_compression_enabled = (
            DEFAULT_COMPRESSION)
        configuration.lightos_default_num_replicas = 3
        configuration.num_volume_device_scan_tries = (
            DEVICE_SCAN_ATTEMPTS_DEFAULT)
        configuration.lightos_api_service_timeout = LIGHTOS_API_SERVICE_TIMEOUT
        configuration.driver_ssl_cert_verify = False
        # for some reason this value is not initialized by the driver parent
        # configs
        configuration.volume_name_template = 'volume-%s'
        configuration.initiator_connector = (
            "cinder.tests.unit.volume.drivers.lightos."
            "test_lightos_storage.InitiatorConnectorFactoryMocker")
        configuration.volume_backend_name = VOLUME_BACKEND_NAME
        configuration.reserved_percentage = RESERVED_PERCENTAGE

        def mocked_safe_get(config, variable_name):
            if hasattr(config, variable_name):
                return config.__getattribute__(variable_name)
            else:
                return None

        configuration.safe_get = functools.partial(mocked_safe_get,
                                                   configuration)
        self.driver = lightos.LightOSVolumeDriver(configuration=configuration)
        self.ctxt = context.get_admin_context()
        self.db: DBMock = DBMock()

        # define a default send_cmd override to return default values.
        def send_cmd_default_mock(cmd, timeout, **kwargs):
            if cmd == "get_nodes":
                return (httpstatus.OK, FAKE_LIGHTOS_CLUSTER_NODES)
            if cmd == "get_node":
                self.assertTrue(kwargs["UUID"])
                for node in FAKE_LIGHTOS_CLUSTER_NODES["nodes"]:
                    if kwargs["UUID"] == node["UUID"]:
                        return (httpstatus.OK, node)
                return (httpstatus.NOT_FOUND, node)
            elif cmd == "get_cluster_info":
                return (httpstatus.OK, FAKE_LIGHTOS_CLUSTER_INFO)
            elif cmd == "create_volume":
                project_name = kwargs["project_name"]
                volume = {
                    "project_name": project_name,
                    "name": kwargs["name"],
                    "size": kwargs["size"],
                    "n_replicas": kwargs["n_replicas"],
                    "compression": kwargs["compression"],
                    "src_snapshot_name": kwargs["src_snapshot_name"],
                    "acl": {'values': kwargs.get('acl')},
                    "state": "Available",
                }
                volume["ETag"] = get_vol_etag(volume)
                code, new_vol = self.db.create_volume(volume)
                return (code, new_vol)
            elif cmd == "delete_volume":
                return self.db.delete_volume(kwargs["project_name"],
                                             kwargs["volume_uuid"])
            elif cmd == "get_volume":
                return self.db.get_volume_by_uuid(kwargs["project_name"],
                                                  kwargs["volume_uuid"])
            elif cmd == "get_volume_by_name":
                return self.db.get_volume_by_name(kwargs["project_name"],
                                                  kwargs["volume_name"])
            elif cmd == "extend_volume":
                size = kwargs.get("size", None)
                return self.db.update_volume_by_uuid(kwargs["project_name"],
                                                     kwargs["volume_uuid"],
                                                     size=size)
            elif cmd == "create_snapshot":
                snapshot = {
                    "project_name": kwargs.get("project_name", None),
                    "name": kwargs.get("name", None),
                    "state": "Available",
                }
                return self.db.create_snapshot(snapshot)
            elif cmd == "delete_snapshot":
                return self.db.delete_snapshot(kwargs["project_name"],
                                               kwargs["snapshot_uuid"])
            elif cmd == "get_snapshot":
                return self.db.get_snapshot_by_uuid(kwargs["project_name"],
                                                    kwargs["snapshot_uuid"])
            elif cmd == "get_snapshot_by_name":
                return self.db.get_snapshot_by_name(kwargs["project_name"],
                                                    kwargs["snapshot_name"])
            elif cmd == "update_volume":
                return self.db.update_volume_by_uuid(**kwargs)

            else:
                raise RuntimeError(
                    f"'{cmd}' is not implemented. kwargs: {kwargs}")

        self.driver.cluster.send_cmd = send_cmd_default_mock

    def test_setup_should_fail_if_lightos_client_cant_auth_cluster(self):
        """Verify lightos_client fail with bad auth."""

        def side_effect(cmd, timeout):
            if cmd == "get_cluster_info":
                return (httpstatus.UNAUTHORIZED, None)
            else:
                raise RuntimeError()

        self.driver.cluster.send_cmd = side_effect
        self.assertRaises(exception.InvalidAuthKey,
                          self.driver.do_setup, None)

    def test_setup_should_succeed(self):
        """Test that lightos_client succeed."""
        self.driver.do_setup(None)

    def test_create_volume_should_succeed(self):
        """Test that lightos_client succeed."""
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)

        self.driver.create_volume(volume)
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_create_volume_same_volume_twice_succeed(self):
        """Test succeed to create an exiting volume."""
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)

        self.driver.create_volume(volume)
        self.driver.create_volume(volume)
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_create_volume_in_failed_state(self):
        """Verify scenario of created volume in failed state:

        Driver is expected to issue a deletion command and raise exception
        """
        def send_cmd_mock(cmd, **kwargs):
            if cmd == "create_volume":
                project_name = kwargs["project_name"]
                volume = {
                    "project_name": project_name,
                    "name": kwargs["name"],
                    "size": kwargs["size"],
                    "n_replicas": kwargs["n_replicas"],
                    "compression": kwargs["compression"],
                    "src_snapshot_name": kwargs["src_snapshot_name"],
                    "acl": {'values': kwargs.get('acl')},
                    "state": "Failed",
                }
                volume["ETag"] = get_vol_etag(volume)
                code, new_vol = self.db.create_volume(volume)
                return (code, new_vol)
            elif cmd == "delete_volume":
                return self.db.delete_volume(kwargs["project_name"],
                                             kwargs["volume_uuid"])
            elif cmd == "get_volume":
                return self.db.get_volume_by_uuid(kwargs["project_name"],
                                                  kwargs["volume_uuid"])
            elif cmd == "get_volume_by_name":
                return self.db.get_volume_by_name(kwargs["project_name"],
                                                  kwargs["volume_name"])
            else:
                raise RuntimeError(
                    f"'{cmd}' is not implemented. kwargs: {kwargs}")

        self.driver.do_setup(None)
        self.driver.cluster.send_cmd = send_cmd_mock
        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, volume)
        proj = self.db.data["projects"][lightos.LIGHTOS_DEFAULT_PROJECT_NAME]
        actual_volumes = proj["volumes"]
        self.assertEqual(0, len(actual_volumes))
        db.volume_destroy(self.ctxt, volume.id)

    def test_delete_volume_fail_if_not_created(self):
        """Test that lightos_client fail creating an already exists volume."""
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_extend_volume_should_succeed(self):
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)

        self.driver.create_volume(volume)
        self.driver.extend_volume(volume, 6)
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_get_volume_specs_compression_True(self):
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(
            self.ctxt, self,
            extra_specs={'compression': 'True'},
            name='my_vol_typ1')

        vol_type2 = test_utils.create_volume_type(
            self.ctxt, self,
            extra_specs={'compression': '<is> True'},
            name='my_vol_type2')

        vol_type3 = test_utils.create_volume_type(
            self.ctxt, self,
            name='my_vol_type3')

        volume1 = test_utils.create_volume(self.ctxt, size=4,
                                           volume_type_id=vol_type.id)
        volume2 = test_utils.create_volume(self.ctxt, size=4,
                                           volume_type_id=vol_type2.id)
        volume3 = test_utils.create_volume(self.ctxt, size=4,
                                           volume_type_id=vol_type3.id)
        compression, _, _ = self.driver._get_volume_specs(volume1)
        self.assertTrue(compression == "True")
        compression, _, _ = self.driver._get_volume_specs(volume2)
        self.assertTrue(compression == "True")
        compression, _, _ = self.driver._get_volume_specs(volume3)
        self.assertTrue(compression == "False")

        db.volume_destroy(self.ctxt, volume1.id)
        db.volume_destroy(self.ctxt, volume2.id)
        db.volume_destroy(self.ctxt, volume3.id)

    def test_get_volume_specs_compression_False(self):
        self.driver.do_setup(None)
        self.driver.configuration.lightos_default_compression_enabled = True
        vol_type = test_utils.create_volume_type(
            self.ctxt, self,
            extra_specs={'compression': 'False'},
            name='my_vol_typ1')

        vol_type2 = test_utils.create_volume_type(
            self.ctxt, self,
            extra_specs={'compression': '<is> False'},
            name='my_vol_type2')

        vol_type3 = test_utils.create_volume_type(
            self.ctxt, self,
            name='my_vol_type3')
        volume1 = test_utils.create_volume(self.ctxt, size=4,
                                           volume_type_id=vol_type.id)
        volume2 = test_utils.create_volume(self.ctxt, size=4,
                                           volume_type_id=vol_type2.id)
        volume3 = test_utils.create_volume(self.ctxt, size=4,
                                           volume_type_id=vol_type3.id)
        compression, _, _ = self.driver._get_volume_specs(volume1)
        self.assertTrue(compression == "False")
        compression, _, _ = self.driver._get_volume_specs(volume2)
        self.assertTrue(compression == "False")
        compression, _, _ = self.driver._get_volume_specs(volume3)
        self.assertTrue(compression == "True")

        db.volume_destroy(self.ctxt, volume1.id)
        db.volume_destroy(self.ctxt, volume2.id)
        db.volume_destroy(self.ctxt, volume3.id)

    def test_extend_volume_should_fail_if_volume_does_not_exist(self):
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)

        self.assertRaises(exception.VolumeNotFound,
                          self.driver.extend_volume, volume, 6)
        db.volume_destroy(self.ctxt, volume.id)

    def test_create_snapshot(self):
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        snapshot = test_utils.create_snapshot(self.ctxt, volume_id=volume.id)

        self.driver.create_volume(volume)
        self.driver.create_snapshot(snapshot)
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_delete_snapshot(self):
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        snapshot = test_utils.create_snapshot(self.ctxt, volume_id=volume.id)

        self.driver.create_volume(volume)
        self.driver.create_snapshot(snapshot)
        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_create_volume_from_snapshot(self):
        self.driver.do_setup(None)
        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        snapshot = test_utils.create_snapshot(self.ctxt, volume_id=volume.id)
        self.driver.create_volume_from_snapshot(volume, snapshot)
        proj = self.db.data["projects"][lightos.LIGHTOS_DEFAULT_PROJECT_NAME]
        actual_volumes = proj["volumes"]
        self.assertEqual(1, len(actual_volumes))
        self.driver.delete_snapshot(snapshot)
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)
        db.snapshot_destroy(self.ctxt, snapshot.id)

    def test_initialize_connection(self):
        InitialConnectorMock.nqn = "hostnqn1"
        InitialConnectorMock.found_discovery_client = True
        self.driver.do_setup(None)
        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        self.driver.create_volume(volume)
        connection_props = \
            self.driver.initialize_connection(volume,
                                              get_connector_properties())
        self.assertIn('driver_volume_type', connection_props)
        self.assertEqual('lightos', connection_props['driver_volume_type'])
        self.assertEqual(FAKE_LIGHTOS_CLUSTER_INFO['subsystemNQN'],
                         connection_props['data']['subsysnqn'])
        self.assertEqual(
            self.db.data['projects']['default']['volumes'][0]['UUID'],
            connection_props['data']['uuid'])

        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_initialize_connection_no_hostnqn_should_fail(self):
        InitialConnectorMock.nqn = ""
        InitialConnectorMock.found_discovery_client = True
        self.driver.do_setup(None)
        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        self.driver.create_volume(volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, volume,
                          get_connector_properties())
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_initialize_connection_no_dsc_should_fail(self):
        InitialConnectorMock.nqn = "hostnqn1"
        InitialConnectorMock.found_discovery_client = False
        self.driver.do_setup(None)
        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        self.driver.create_volume(volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, volume,
                          get_connector_properties())
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_terminate_connection_with_hostnqn(self):
        InitialConnectorMock.nqn = "hostnqn1"
        InitialConnectorMock.found_discovery_client = True
        self.driver.do_setup(None)
        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        self.driver.create_volume(volume)
        self.driver.terminate_connection(volume, get_connector_properties())
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_terminate_connection_with_empty_hostnqn_should_fail(self):
        InitialConnectorMock.nqn = ""
        InitialConnectorMock.found_discovery_client = True
        self.driver.do_setup(None)
        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        self.driver.create_volume(volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection, volume,
                          get_connector_properties())
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_force_terminate_connection_with_empty_hostnqn(self):
        InitialConnectorMock.nqn = ""
        InitialConnectorMock.found_discovery_client = True
        self.driver.do_setup(None)
        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        self.driver.create_volume(volume)
        self.driver.terminate_connection(volume, get_connector_properties(),
                                         force=True)
        self.driver.delete_volume(volume)
        db.volume_destroy(self.ctxt, volume.id)

    def test_check_for_setup_error(self):
        InitialConnectorMock.nqn = "hostnqn1"
        InitialConnectorMock.found_discovery_client = True
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()

    def test_check_for_setup_error_no_subsysnqn_should_fail(self):
        InitialConnectorMock.nqn = "hostnqn1"
        InitialConnectorMock.found_discovery_client = True
        self.driver.do_setup(None)
        self.driver.cluster.subsystemNQN = ""
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_no_hostnqn_should_fail(self):
        InitialConnectorMock.nqn = ""
        InitialConnectorMock.found_discovery_client = True
        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)

    def test_check_for_setup_error_no_dsc_should_succeed(self):
        InitialConnectorMock.nqn = "hostnqn1"
        InitialConnectorMock.found_discovery_client = False
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()

    def test_create_clone(self):
        self.driver.do_setup(None)

        vol_type = test_utils.create_volume_type(self.ctxt, self,
                                                 name='my_vol_type')
        volume = test_utils.create_volume(self.ctxt, size=4,
                                          volume_type_id=vol_type.id)
        clone = test_utils.create_volume(self.ctxt, size=4,
                                         volume_type_id=vol_type.id)

        self.driver.create_volume(volume)
        self.driver.create_cloned_volume(clone, volume)
        self.driver.delete_volume(volume)
        self.driver.delete_volume(clone)

        db.volume_destroy(self.ctxt, volume.id)
        db.volume_destroy(self.ctxt, clone.id)

    def test_get_volume_stats(self):
        """Test that lightos_client succeed."""
        self.driver.do_setup(None)
        volumes_data = self.driver.get_volume_stats(refresh=False)
        assert len(volumes_data) == 0, "Expected empty config"

        volumes_data = self.driver.get_volume_stats(refresh=True)
        assert volumes_data['vendor_name'] == 'LightOS Storage', \
            "Expected 'LightOS Storage', received %s" % \
            volumes_data['vendor_name']
        assert volumes_data['volume_backend_name'] == VOLUME_BACKEND_NAME, \
            "Expected %s, received %s" % \
            (VOLUME_BACKEND_NAME, volumes_data['volume_backend_name'])
        assert volumes_data['driver_version'] == self.driver.VERSION, \
            "Expected %s, received %s" % \
            (self.driver.VERSION, volumes_data['driver_version'])
        assert volumes_data['storage_protocol'] == "lightos", \
            "Expected 'lightos', received %s" % \
            volumes_data['storage_protocol']
        assert volumes_data['reserved_percentage'] == RESERVED_PERCENTAGE, \
            "Expected %d, received %s" % \
            (RESERVED_PERCENTAGE, volumes_data['reserved_percentage'])
        assert volumes_data['QoS_support'] is False, \
            "Expected False, received %s" % volumes_data['QoS_support']
        assert volumes_data['online_extend_support'] is True, \
            "Expected True, received %s" % \
            volumes_data['online_extend_support']
        assert volumes_data['thin_provisioning_support'] is True, \
            "Expected True, received %s" % \
            volumes_data['thin_provisioning_support']
        assert volumes_data['compression'] == [True, False], \
            "Expected [True, False], received %s" % volumes_data['compression']
        assert volumes_data['multiattach'] is True, \
            "Expected True, received %s" % volumes_data['multiattach']
        assert volumes_data['free_capacity_gb'] == 'infinite', \
            "Expected 'infinite', received %s" % \
            volumes_data['free_capacity_gb']
