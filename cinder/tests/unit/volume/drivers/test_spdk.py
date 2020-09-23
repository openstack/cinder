#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#          http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy
import json
from unittest import mock

from os_brick import initiator
from os_brick.initiator import connector
from oslo_utils import timeutils
from oslo_utils import units

from cinder import context
from cinder import objects
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers import spdk as spdk_driver

BDEVS = [{
    "num_blocks": 4096000,
    "name": "Nvme0n1",
    "driver_specific": {
        "nvme": {
            "trid": {
                "trtype": "PCIe",
                "traddr": "0000:00:04.0"
            },
            "ns_data": {
                "id": 1
            },
            "pci_address": "0000:00:04.0",
            "vs": {
                "nvme_version": "1.1"
            },
            "ctrlr_data": {
                "firmware_revision": "1.0",
                "serial_number": "deadbeef",
                "oacs": {
                    "ns_manage": 0,
                    "security": 0,
                    "firmware": 0,
                    "format": 0
                },
                "vendor_id": "0x8086",
                "model_number": "QEMU NVMe Ctrl"
            },
            "csts": {
                "rdy": 1,
                "cfs": 0
            }
        }
    },
    "supported_io_types": {
        "reset": True,
        "nvme_admin": True,
        "unmap": False,
        "read": True,
        "write_zeroes": False,
        "write": True,
        "flush": True,
        "nvme_io": True
    },
    "claimed": False,
    "block_size": 512,
    "product_name": "NVMe disk",
    "aliases": ["Nvme0n1"]
}, {
    "num_blocks": 8192,
    "uuid": "70efd305-4e66-49bd-99ff-faeda5c3052d",
    "aliases": [
        "Nvme0n1p0"
    ],
    "driver_specific": {
        "lvol": {
            "base_bdev": "Nvme0n1",
            "lvol_store_uuid": "58b17014-d4a1-4f85-9761-093643ed18f1",
            "thin_provision": False
        }
    },
    "supported_io_types": {
        "reset": True,
        "nvme_admin": False,
        "unmap": True,
        "read": True,
        "write_zeroes": True,
        "write": True,
        "flush": False,
        "nvme_io": False
    },
    "claimed": False,
    "block_size": 4096,
    "product_name": "Split Disk",
    "name": "Nvme0n1p0"
}, {
    "num_blocks": 8192,
    "uuid": "70efd305-4e66-49bd-99ff-faeda5c3052d",
    "aliases": [
        "Nvme0n1p1"
    ],
    "driver_specific": {
        "lvol": {
            "base_bdev": "Nvme0n1",
            "lvol_store_uuid": "58b17014-d4a1-4f85-9761-093643ed18f1",
            "thin_provision": False
        }
    },
    "supported_io_types": {
        "reset": True,
        "nvme_admin": False,
        "unmap": True,
        "read": True,
        "write_zeroes": True,
        "write": True,
        "flush": False,
        "nvme_io": False
    },
    "claimed": False,
    "block_size": 4096,
    "product_name": "Split Disk",
    "name": "Nvme0n1p1"
}, {
    "num_blocks": 8192,
    "uuid": "70efd305-4e66-49bd-99ff-faeda5c3052d",
    "aliases": [
        "lvs_test/lvol0"
    ],
    "driver_specific": {
        "lvol": {
            "base_bdev": "Malloc0",
            "lvol_store_uuid": "58b17014-d4a1-4f85-9761-093643ed18f1",
            "thin_provision": False
        }
    },
    "supported_io_types": {
        "reset": True,
        "nvme_admin": False,
        "unmap": True,
        "read": True,
        "write_zeroes": True,
        "write": True,
        "flush": False,
        "nvme_io": False
    },
    "claimed": False,
    "block_size": 4096,
    "product_name": "Logical Volume",
    "name": "58b17014-d4a1-4f85-9761-093643ed18f1_4294967297"
}, {
    "num_blocks": 8192,
    "uuid": "8dec1964-d533-41df-bea7-40520efdb416",
    "aliases": [
        "lvs_test/lvol1"
    ],
    "driver_specific": {
        "lvol": {
            "base_bdev": "Malloc0",
            "lvol_store_uuid": "58b17014-d4a1-4f85-9761-093643ed18f1",
            "thin_provision": True
        }
    },
    "supported_io_types": {
        "reset": True,
        "nvme_admin": False,
        "unmap": True,
        "read": True,
        "write_zeroes": True,
        "write": True,
        "flush": False,
        "nvme_io": False
    },
    "claimed": False,
    "block_size": 4096,
    "product_name": "Logical Volume",
    "name": "58b17014-d4a1-4f85-9761-093643ed18f1_4294967298"
}]


LVOL_STORES = [{
    "uuid": "58b17014-d4a1-4f85-9761-093643ed18f1",
    "base_bdev": "Nvme0n1",
    "free_clusters": 5976,
    "cluster_size": 1048576,
    "total_data_clusters": 5976,
    "block_size": 4096,
    "name": "lvs_test"
}]


NVMF_SUBSYSTEMS = [{
    "listen_addresses": [],
    "subtype": "Discovery",
    "nqn": "nqn.2014-08.org.nvmexpress.discovery",
    "hosts": [],
    "allow_any_host": True
}, {
    "listen_addresses": [],
    "subtype": "NVMe",
    "hosts": [{
        "nqn": "nqn.2016-06.io.spdk:init"
    }],
    "namespaces": [{
        "bdev_name": "Nvme0n1p0",
        "nsid": 1,
        "name": "Nvme0n1p0"
    }],
    "allow_any_host": False,
    "serial_number": "SPDK00000000000001",
    "nqn": "nqn.2016-06.io.spdk:cnode1"
}, {
    "listen_addresses": [],
    "subtype": "NVMe",
    "hosts": [],
    "namespaces": [{
        "bdev_name": "Nvme1n1p0",
        "nsid": 1,
        "name": "Nvme1n1p0"
    }],
    "allow_any_host": True,
    "serial_number": "SPDK00000000000002",
    "nqn": "nqn.2016-06.io.spdk:cnode2"
}]


class Volume(object):
    def __init__(self):
        self.size = 1
        self.name = "lvol2"


class Snapshot(object):
    def __init__(self):
        self.name = "snapshot0"
        self.volume_size = 1


class JSONRPCException(Exception):
    def __init__(self, message):
        self.message = message


class JSONRPCClient(object):
    def __init__(self, addr=None, port=None):
        self.methods = {"bdev_get_bdevs": self.get_bdevs,
                        "bdev_lvol_get_lvstores": self.get_lvol_stores,
                        "bdev_lvol_delete": self.destroy_lvol_bdev,
                        "bdev_lvol_snapshot": self.snapshot_lvol_bdev,
                        "bdev_lvol_clone": self.clone_lvol_bdev,
                        "bdev_lvol_create": self.construct_lvol_bdev,
                        "bdev_lvol_resize": self.resize_lvol_bdev,
                        "nvmf_get_subsystems": self.get_nvmf_subsystems,
                        "construct_nvmf_subsystem":
                            self.construct_nvmf_subsystem,
                        "nvmf_create_subsystem":
                            self.nvmf_subsystem_create,
                        "nvmf_subsystem_add_listener":
                            self.nvmf_subsystem_add_listener,
                        "nvmf_subsystem_add_ns":
                            self.nvmf_subsystem_add_ns,
                        "bdev_lvol_inflate": self.inflate_lvol_bdev}
        self.bdevs = copy.deepcopy(BDEVS)
        self.nvmf_subsystems = copy.deepcopy(NVMF_SUBSYSTEMS)
        self.lvol_stores = copy.deepcopy(LVOL_STORES)

    def get_bdevs(self, params=None):
        if params and 'name' in params:
            for bdev in self.bdevs:
                for alias in bdev['aliases']:
                    if params['name'] in alias:
                        return json.dumps({"result": [bdev]})
                if bdev['name'] == params['name']:
                    return json.dumps({"result": [bdev]})
            return json.dumps({"error": "Not found"})

        return json.dumps({"result": self.bdevs})

    def destroy_lvol_bdev(self, params=None):
        if 'name' not in params:
            return json.dumps({})
        i = 0
        found_bdev = -1
        for bdev in self.bdevs:
            if bdev['name'] == params['name']:
                found_bdev = i
                break
            i += 1

        if found_bdev != -1:
            del self.bdevs[found_bdev]
        return json.dumps({"result": {}})

    def get_lvol_stores(self, params=None):
        return json.dumps({"result": self.lvol_stores})

    def snapshot_lvol_bdev(self, params=None):
        snapshot = {
            'num_blocks': 5376,
            'name': '58b17014-d4a1-4f85-9761-093643ed18f2',
            'aliases': ['lvs_test/%s' % params['snapshot_name']],
            'driver_specific': {
                'lvol': {
                    'base_bdev': u'Malloc0',
                    'lvol_store_uuid': u'58b17014-d4a1-4f85-9761-093643ed18f1',
                    'thin_provision': False,
                    'clones': ['clone0', 'clone1']
                }
            },
            'claimed': False,
            'block_size': 4096,
            'product_name': 'Logical Volume',
            'supported_io_types': {
                'reset': True,
                'nvme_admin': False,
                'unmap': True,
                'read': True,
                'write_zeroes': True,
                'write': True,
                'flush': False,
                'nvme_io': False
            }
        }
        self.bdevs.append(snapshot)

        return json.dumps({"result": [snapshot]})

    def clone_lvol_bdev(self, params=None):
        clone = {
            'num_blocks': 7936,
            'supported_io_types': {
                'reset': True,
                'nvme_admin': False,
                'unmap': True,
                'read': True,
                'write_zeroes': True,
                'write': True,
                'flush': False,
                'nvme_io': False
            },
            'name': '3735a554-0dce-4d13-ba67-597d41186104',
            'driver_specific': {
                'lvol': {
                    'base_bdev': 'Malloc0',
                    'lvol_store_uuid': '58b17014-d4a1-4f85-9761-093643ed18f1',
                    'thin_provision': False
                }
            },
            'block_size': 4096,
            'claimed': False,
            'aliases': [u'lvs_test/%s' % params['clone_name']],
            'product_name': 'Logical Volume',
            'uuid': '3735a554-0dce-4d13-ba67-597d41186104'
        }

        self.bdevs.append(clone)

        return json.dumps({"result": [clone]})

    def construct_lvol_bdev(self, params=None):
        lvol_bdev = {
            "num_blocks": 8192,
            "uuid": "8dec1964-d533-41df-bea7-40520efdb416",
            "aliases": [
                "lvs_test/%s" % params['lvol_name']
            ],
            "driver_specific": {
                "lvol": {
                    "base_bdev": "Malloc0",
                    "lvol_store_uuid": "58b17014-d4a1-4f85-9761-093643ed18f1",
                    "thin_provision": True
                }
            },
            "supported_io_types": {
                "reset": True,
                "nvme_admin": False,
                "unmap": True,
                "read": True,
                "write_zeroes": True,
                "write": True,
                "flush": False,
                "nvme_io": False
            },
            "claimed": False,
            "block_size": 4096,
            "product_name": "Logical Volume",
            "name": "58b17014-d4a1-4f85-9761-093643ed18f1_4294967299"
        }
        self.bdevs.append(lvol_bdev)

        return json.dumps({"result": [{}]})

    def get_nvmf_subsystems(self, params=None):
        return json.dumps({"result": self.nvmf_subsystems})

    def resize_lvol_bdev(self, params=None):
        if params:
            if "name" in params:
                tmp_bdev = json.loads(
                    self.get_bdevs(params={"name": params['name']}))['result']
                if "size" in params:
                    for bdev in self.bdevs:
                        if bdev['name'] == tmp_bdev[0]['name']:
                            bdev['num_blocks'] = params['size'] \
                                / bdev['block_size']
                    return json.dumps({"result": {}})

        return json.dumps({"error": {}})

    def inflate_lvol_bdev(self, params=None):
        return json.dumps({'result': {}})

    def construct_nvmf_subsystem(self, params=None):
        nvmf_subsystem = {
            "listen_addresses": [],
            "subtype": "NVMe",
            "hosts": [],
            "namespaces": [{
                "bdev_name": "Nvme1n1p0",
                "nsid": 1,
                "name": "Nvme1n1p0"
            }],
            "allow_any_host": True,
            "serial_number": params['serial_number'],
            "nqn": params['nqn']
        }
        self.nvmf_subsystems.append(nvmf_subsystem)

        return json.dumps({"result": nvmf_subsystem})

    def nvmf_subsystem_create(self, params=None):
        nvmf_subsystem = {
            "namespaces": [],
            "nqn": params['nqn'],
            "serial_number": "S0000000000000000001",
            "allow_any_host": False,
            "subtype": "NVMe",
            "hosts": [],
            "listen_addresses": []
        }

        self.nvmf_subsystems.append(nvmf_subsystem)

        return json.dumps({"result": nvmf_subsystem})

    def nvmf_subsystem_add_listener(self, params=None):
        for nvmf_subsystem in self.nvmf_subsystems:
            if nvmf_subsystem['nqn'] == params['nqn']:
                nvmf_subsystem['listen_addresses'].append(
                    params['listen_address']
                )

        return json.dumps({"result": ""})

    def nvmf_subsystem_add_ns(self, params=None):
        for nvmf_subsystem in self.nvmf_subsystems:
            if nvmf_subsystem['nqn'] == params['nqn']:
                nvmf_subsystem['namespaces'].append(
                    params['namespace']
                )

        return json.dumps({"result": ""})

    def call(self, method, params=None):
        req = {}
        req['jsonrpc'] = '2.0'
        req['method'] = method
        req['id'] = 1
        if (params):
            req['params'] = params
        response = json.loads(self.methods[method](params))
        if not response:
            if method == "kill_instance":
                return {}
            msg = "Timeout while waiting for response:"
            raise JSONRPCException(msg)

        if 'error' in response:
            msg = "\n".join(["Got JSON-RPC error response",
                             "request:",
                             json.dumps(req, indent=2),
                             "response:",
                             json.dumps(response['error'], indent=2)])
            raise JSONRPCException(msg)

        return response['result']


class SpdkDriverTestCase(test.TestCase):
    def setUp(self):
        super(SpdkDriverTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.target_helper = ""
        self.configuration.target_ip_address = "192.168.0.1"
        self.configuration.target_port = 4420
        self.configuration.target_prefix = "nqn.2014-08.io.spdk"
        self.configuration.nvmet_port_id = "1"
        self.configuration.nvmet_ns_id = "fake_id"
        self.configuration.nvmet_subsystem_name = "2014-08.io.spdk"
        self.configuration.target_protocol = "nvmet_rdma"
        self.configuration.spdk_rpc_ip = "127.0.0.1"
        self.configuration.spdk_rpc_port = 8000
        self.configuration.spdk_rpc_protocol = "https"
        mock_safe_get = mock.Mock()
        mock_safe_get.return_value = 'spdk-nvmeof'
        self.configuration.safe_get = mock_safe_get
        self.jsonrpcclient = JSONRPCClient()
        self.driver = spdk_driver.SPDKDriver(configuration=
                                             self.configuration)
        self._context = context.get_admin_context()
        self.updated_at = timeutils.utcnow()

    def test__update_volume_stats(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            self.driver._update_volume_stats()
            self.assertEqual(1, len(self.driver._stats['pools']))
            self.assertEqual("lvs_test",
                             self.driver._stats['pools'][0]['pool_name'])
            self.assertEqual('SPDK', self.driver._stats['volume_backend_name'])
            self.assertEqual('Open Source', self.driver._stats['vendor_name'])
            self.assertEqual('NVMe-oF', self.driver._stats['storage_protocol'])
            self.assertIsNotNone(self.driver._stats['driver_version'])

    def test__get_spdk_volume_name(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            bdev = self.driver._get_spdk_volume_name("lvs_test/lvol0")
            self.assertEqual('58b17014-d4a1-4f85-9761'
                             '-093643ed18f1_4294967297',
                             bdev)
            bdev = self.driver._get_spdk_volume_name("Nvme1n1")
            self.assertIsNone(bdev)

    def test__get_spdk_lvs_uuid(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            bdev = self.driver._rpc_call(
                "bdev_get_bdevs", params={"name": "lvs_test/lvol0"})
            self.assertEqual(
                bdev[0]['driver_specific']['lvol']['lvol_store_uuid'],
                self.driver._get_spdk_lvs_uuid(
                    "58b17014-d4a1-4f85-9761-093643ed18f1_4294967297"))
            self.assertIsNone(
                self.driver._get_spdk_lvs_uuid("lvs_test/fake"))

    def test__get_spdk_lvs_free_space(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            lvs = self.driver._rpc_call("bdev_lvol_get_lvstores")
            lvol_store = None
            for lvol in lvs:
                if lvol['name'] == "lvs_test":
                    lvol_store = lvol
            self.assertIsNotNone(lvol_store)
            free_size = (lvol_store['free_clusters']
                         * lvol_store['cluster_size']
                         / units.Gi)
            self.assertEqual(free_size,
                             self.driver._get_spdk_lvs_free_space(
                                 "58b17014-d4a1-4f85-9761-093643ed18f1"))
            self.assertEqual(0,
                             self.driver._get_spdk_lvs_free_space("fake"))

    def test__delete_bdev(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            self.driver._delete_bdev("lvs_test/lvol1")
            bdev = self.driver._get_spdk_volume_name("lvs_test/lvol1")
            self.assertIsNone(bdev)

            self.driver._delete_bdev("lvs_test/lvol1")
            bdev = self.driver._get_spdk_volume_name("lvs_test/lvol1")
            self.assertIsNone(bdev)

    def test__create_volume(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            self.driver._create_volume(Volume())
            bdev = self.driver._get_spdk_volume_name("lvs_test/lvol2")
            self.assertEqual("58b17014-d4a1-4f85-9761"
                             "-093643ed18f1_4294967299",
                             bdev)
            volume_clone = Volume()
            volume_clone.name = "clone0"
            self.driver._rpc_call("bdev_lvol_snapshot",
                                  params={'snapshot_name': "snapshot0",
                                          'lvol_name': "lvs_test/lvol2"})
            bdev = self.driver._get_spdk_volume_name("lvs_test/snapshot0")
            self.assertEqual("58b17014-d4a1-4f85-9761-093643ed18f2", bdev)
            snapshot = Snapshot()
            self.driver._create_volume(volume_clone, snapshot)
            bdev = self.driver._get_spdk_volume_name("lvs_test/clone0")
            self.assertEqual("3735a554-0dce-4d13-ba67-597d41186104", bdev)

    def test_check_for_setup_error(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            self.driver.check_for_setup_error()

    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_create_volume(self, volume_get):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            db_volume = fake_volume.fake_db_volume()
            ctxt = context.get_admin_context()
            db_volume = objects.Volume._from_db_object(ctxt, objects.Volume(),
                                                       db_volume)
            volume_get.return_value = db_volume
            self.driver.create_volume(db_volume)
            bdev = self.driver._get_spdk_volume_name("lvs_test/%s"
                                                     % db_volume.name)
            self.assertEqual("58b17014-d4a1-4f85-9761"
                             "-093643ed18f1_4294967299",
                             bdev)

    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_delete_volume(self, volume_get):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            db_volume = fake_volume.fake_db_volume()
            with mock.patch.object(self.driver.target_driver, "_rpc_call",
                                   self.jsonrpcclient.call):
                nqn = "nqn.2016-06.io.spdk:cnode%s" \
                      % self.driver.target_driver._get_first_free_node()
            db_volume['provider_id'] = nqn
            ctxt = context.get_admin_context()
            db_volume = objects.Volume._from_db_object(ctxt, objects.Volume(),
                                                       db_volume)
            volume_get.return_value = db_volume
            start_bdevs_len = len(self.driver._rpc_call('bdev_get_bdevs'))
            self.driver.create_volume(db_volume)
            tmp_bdevs = self.driver._rpc_call('bdev_get_bdevs')
            self.assertEqual(start_bdevs_len + 1, len(tmp_bdevs))
            volume = Volume()
            volume.name = "lvs_test/%s" % db_volume.name
            volume_name = self.driver._get_spdk_volume_name(volume.name)
            self.driver._rpc_call('bdev_lvol_delete', {"name": volume_name})
            self.driver.delete_volume(volume)
            bdev = self.driver._get_spdk_volume_name("lvs_test/%s"
                                                     % db_volume.name)
            self.assertIsNone(bdev)
            tmp_bdevs = self.driver._rpc_call('bdev_get_bdevs')
            self.assertEqual(start_bdevs_len, len(tmp_bdevs))

    def get_volume_stats(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            self.driver.get_volume_stats(True)
            self.driver.get_volume_stats(False)

    def test_create_volume_from_snapshot(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            volume_clone = Volume()
            volume_clone.name = "clone0"
            self.driver._rpc_call("bdev_lvol_snapshot",
                                  params={'snapshot_name': "snapshot0",
                                          'lvol_name': "lvs_test/lvol2"})
            snapshot = Snapshot()
            self.driver.create_volume_from_snapshot(volume_clone, snapshot)
            bdev = self.driver._get_spdk_volume_name("lvs_test/clone0")
            self.assertEqual("3735a554-0dce-4d13-ba67-597d41186104", bdev)

    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_create_snapshot(self, volume_get):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            db_volume = fake_volume.fake_db_volume()
            db_volume['name'] = "lvs_test/lvol0"
            ctxt = context.get_admin_context()
            db_volume = objects.Volume._from_db_object(ctxt, objects.Volume(),
                                                       db_volume)
            volume_get.return_value = db_volume
            snapshot = {}
            snapshot['volume_id'] = db_volume['id']
            snapshot['name'] = "snapshot0"
            snapshot['volume'] = db_volume
            for bdev in self.jsonrpcclient.bdevs:
                if bdev['aliases'][-1] == "lvs_test/lvol0":
                    bdev['aliases'].append(db_volume.name)
            self.driver.create_snapshot(snapshot)
            bdev = self.driver._get_spdk_volume_name("lvs_test/snapshot0")
            self.assertEqual("58b17014-d4a1-4f85-9761-093643ed18f2", bdev)

    def test_delete_snapshot(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            snapshot = Snapshot()
            snapshot.name = "snapshot0"
            self.driver._rpc_call("bdev_lvol_snapshot",
                                  params = {'snapshot_name': snapshot.name})
            self.driver.delete_snapshot(snapshot)
            snapshot = self.driver._get_spdk_volume_name("lvs_test/" +
                                                         snapshot.name)
            self.assertIsNone(snapshot)

    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_create_cloned_volume(self, volume_get):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            db_volume = fake_volume.fake_db_volume()
            db_volume['name'] = "lvs_test/lvol0"
            db_volume['size'] = 1
            ctxt = context.get_admin_context()
            db_volume = objects.Volume._from_db_object(ctxt, objects.Volume(),
                                                       db_volume)
            cloned_volume = Volume()
            cloned_volume.name = 'lvs_test/cloned_volume'
            for bdev in self.jsonrpcclient.bdevs:
                if bdev['aliases'][-1] == "lvs_test/lvol0":
                    bdev['aliases'].append(db_volume.name)
            self.driver.create_cloned_volume(cloned_volume, db_volume)
            bdev = self.driver._get_spdk_volume_name("lvs_test/cloned_volume")
            self.assertEqual("3735a554-0dce-4d13-ba67-597d41186104", bdev)

    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_copy_image_to_volume(self, volume_get):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            db_volume = fake_volume.fake_db_volume()
            db_volume['provider_location'] = "127.0.0.1:3262 RDMA " \
                                             "2016-06.io.spdk:cnode2"
            ctxt = context.get_admin_context()
            db_volume = objects.Volume._from_db_object(ctxt, objects.Volume(),
                                                       db_volume)
            volume_get.return_value = db_volume
            with mock.patch.object(self.driver.target_driver, "_rpc_call",
                                   self.jsonrpcclient.call):
                self.driver.copy_image_to_volume(ctxt, db_volume, None, None)

    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_copy_volume_to_image(self, volume_get):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            provider_location = "127.0.0.1:3262 RDMA 2016-06.io.spdk:cnode2"
            volume = test_utils.create_volume(
                self._context, volume_type_id=fake.VOLUME_TYPE_ID,
                updated_at=self.updated_at,
                provider_location=provider_location)
            extra_specs = {
                'image_service:store_id': 'fake-store'
            }
            test_utils.create_volume_type(self._context.elevated(),
                                          id=fake.VOLUME_TYPE_ID,
                                          name="test_type",
                                          extra_specs=extra_specs)

            ctxt = context.get_admin_context()
            volume_get.return_value = volume
            with mock.patch.object(self.driver.target_driver, "_rpc_call",
                                   self.jsonrpcclient.call):
                self.driver.copy_volume_to_image(ctxt, volume, None, None)

    def test_extend_volume(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            volume = Volume()
            volume.name = "lvs_test/lvol0"
            self.driver.extend_volume(volume, 2)
            bdev = self.driver._rpc_call("bdev_get_bdevs",
                                         params={"name": "lvs_test/lvol0"})
            self.assertEqual(2 * units.Gi,
                             bdev[0]['num_blocks'] * bdev[0]['block_size'])

    def test_ensure_export(self):
        pass

    def test_create_export(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            db_volume = fake_volume.fake_db_volume()
            db_volume['provider_location'] = "192.168.0.1:4420 rdma " \
                                             "2014-08.io.spdk:cnode2"
            ctxt = context.get_admin_context()
            db_volume = objects.Volume._from_db_object(ctxt, objects.Volume(),
                                                       db_volume)
            with mock.patch.object(self.driver.target_driver, "_rpc_call",
                                   self.jsonrpcclient.call):
                expected_return = {
                    'provider_location':
                    self.driver.target_driver.get_nvmeof_location(
                        "nqn.%s:cnode%s" % (
                            self.configuration.nvmet_subsystem_name,
                            self.driver.target_driver._get_first_free_node()
                        ),
                        self.configuration.target_ip_address,
                        self.configuration.target_port, "rdma",
                        self.configuration.nvmet_ns_id
                    ),
                    'provider_auth': ''
                }
                export = self.driver.create_export(ctxt, db_volume, None)
                self.assertEqual(expected_return, export)

    def test_remove_export(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            db_volume = fake_volume.fake_db_volume()
            db_volume['provider_location'] = "127.0.0.1:4420 rdma " \
                                             "2016-06.io.spdk:cnode2"
            ctxt = context.get_admin_context()
            db_volume = objects.Volume._from_db_object(ctxt, objects.Volume(),
                                                       db_volume)
            with mock.patch.object(self.driver.target_driver, "_rpc_call",
                                   self.jsonrpcclient.call):
                self.driver.create_export(ctxt, db_volume, None)
                self.assertIsNone(self.driver.remove_export(ctxt, db_volume))

    def test_initialize_connection(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            db_volume = fake_volume.fake_db_volume()
            db_volume['provider_location'] = "127.0.0.1:3262 RDMA " \
                                             "2016-06.io.spdk:cnode2 1"
            ctxt = context.get_admin_context()
            db_volume = objects.Volume._from_db_object(ctxt, objects.Volume(),
                                                       db_volume)
            target_connector = \
                connector.InitiatorConnector.factory(initiator.NVME,
                                                     utils.get_root_helper())
            self.driver.initialize_connection(db_volume, target_connector)

    def test_validate_connector(self):
        mock_connector = {'initiator': 'fake_init'}
        self.assertTrue(self.driver.validate_connector(mock_connector))

    def test_terminate_connection(self):
        pass
