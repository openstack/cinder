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
import json
import mock

from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.targets import spdknvmf as spdknvmf_driver


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


class JSONRPCException(Exception):
    def __init__(self, message):
        self.message = message


class JSONRPCClient(object):
    def __init__(self, addr=None, port=None):
        self.methods = {"get_bdevs": self.get_bdevs,
                        "construct_nvmf_subsystem":
                            self.construct_nvmf_subsystem,
                        "delete_nvmf_subsystem": self.delete_nvmf_subsystem,
                        "nvmf_subsystem_create": self.nvmf_subsystem_create,
                        "nvmf_subsystem_add_listener":
                            self.nvmf_subsystem_add_listener,
                        "nvmf_subsystem_add_ns":
                            self.nvmf_subsystem_add_ns,
                        "get_nvmf_subsystems": self.get_nvmf_subsystems}
        self.bdevs = copy.deepcopy(BDEVS)
        self.nvmf_subsystems = copy.deepcopy(NVMF_SUBSYSTEMS)

    def __del__(self):
        pass

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

    def get_nvmf_subsystems(self, params=None):
        return json.dumps({"result": self.nvmf_subsystems})

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

    def delete_nvmf_subsystem(self, params=None):
        found_id = -1
        i = 0
        for nvmf_subsystem in self.nvmf_subsystems:
            if nvmf_subsystem['nqn'] == params['nqn']:
                found_id = i
            i += 1

        if found_id != -1:
            del self.nvmf_subsystems[found_id]

        return json.dumps({"result": {}})

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
            return {}

        if 'error' in response:
            msg = "\n".join(["Got JSON-RPC error response",
                             "request:",
                             json.dumps(req, indent=2),
                             "response:",
                             json.dumps(response['error'], indent=2)])
            raise JSONRPCException(msg)

        return response['result']


class Target(object):
    def __init__(self, name="Nvme0n1p0"):
        self.name = name


class SpdkNvmfDriverTestCase(test.TestCase):
    def setUp(self):
        super(SpdkNvmfDriverTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.target_ip_address = '192.168.0.1'
        self.configuration.target_port = '4420'
        self.configuration.target_prefix = ""
        self.configuration.nvmet_port_id = "1"
        self.configuration.nvmet_ns_id = "fake_id"
        self.configuration.nvmet_subsystem_name = "nqn.2014-08.io.spdk"
        self.configuration.target_protocol = "nvmet_rdma"
        self.configuration.spdk_rpc_ip = "127.0.0.1"
        self.configuration.spdk_rpc_port = 8000
        self.driver = spdknvmf_driver.SpdkNvmf(configuration=
                                               self.configuration)
        self.jsonrpcclient = JSONRPCClient()

    def test__get_spdk_volume_name(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            bdevs = self.driver._rpc_call("get_bdevs")
            bdev_name = bdevs[0]['name']
            volume_name = self.driver._get_spdk_volume_name(bdev_name)
            self.assertEqual(bdev_name, volume_name)
            volume_name = self.driver._get_spdk_volume_name("fake")
            self.assertIsNone(volume_name)

    def test__get_nqn_with_volume_name(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            nqn = self.driver._get_nqn_with_volume_name("Nvme0n1p0")
            nqn_tmp = self.driver._rpc_call("get_nvmf_subsystems")[1]['nqn']
            self.assertEqual(nqn, nqn_tmp)
            nqn = self.driver._get_nqn_with_volume_name("fake")
            self.assertIsNone(nqn)

    def test__get_first_free_node(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            free_node = self.driver._get_first_free_node()
            self.assertEqual(3, free_node)

    def test_create_nvmeof_target(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            subsystems_first = self.driver._rpc_call("get_nvmf_subsystems")
            self.driver.create_nvmeof_target("Nvme0n1p1",
                                             "nqn.2016-06.io.spdk",
                                             "192.168.0.1",
                                             4420, "rdma", -1, -1, "")
            subsystems_last = self.driver._rpc_call("get_nvmf_subsystems")
            self.assertEqual(len(subsystems_first) + 1, len(subsystems_last))

    def test_delete_nvmeof_target(self):
        with mock.patch.object(self.driver, "_rpc_call",
                               self.jsonrpcclient.call):
            subsystems_first = self.driver._rpc_call("get_nvmf_subsystems")
            target = Target()
            self.driver.delete_nvmeof_target(target)
            subsystems_last = self.driver._rpc_call("get_nvmf_subsystems")
            self.assertEqual(len(subsystems_first) - 1, len(subsystems_last))
            target.name = "fake"
            self.driver.delete_nvmeof_target(target)
            self.assertEqual(len(subsystems_first) - 1, len(subsystems_last))
