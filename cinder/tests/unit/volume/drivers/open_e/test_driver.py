#    Copyright (c) 2020 Open-E, Inc.
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

import copy
from unittest import mock

from oslo_utils import units as o_units

from cinder import context
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume.drivers.open_e.jovian_common import driver
from cinder.volume.drivers.open_e.jovian_common import exception as jexc
from cinder.volume.drivers.open_e.jovian_common import jdss_common as jcom

UUID_1 = '12345678-1234-1234-1234-000000000001'
UUID_2 = '12345678-1234-1234-1234-000000000002'
UUID_3 = '12345678-1234-1234-1234-000000000003'
UUID_4 = '12345678-1234-1234-1234-000000000004'

UUID_S1 = '12345678-1234-1234-1234-100000000001'
UUID_S2 = '12345678-1234-1234-1234-100000000002'
UUID_S3 = '12345678-1234-1234-1234-100000000003'
UUID_S4 = '12345678-1234-1234-1234-100000000004'

CONFIG_OK = {
    'san_hosts': ['192.168.0.2'],
    'san_api_port': 82,
    'driver_use_ssl': 'false',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'jovian_user': 'admin',
    'jovian_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'jovian_block_size': '128K'
}

CONFIG_BLOCK_SIZE = {
    'san_hosts': ['192.168.0.2'],
    'san_api_port': 82,
    'driver_use_ssl': 'false',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'jovian_user': 'admin',
    'jovian_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'jovian_block_size': '64K'
}

CONFIG_BAD_BLOCK_SIZE = {
    'san_hosts': ['192.168.0.2'],
    'san_api_port': 82,
    'driver_use_ssl': 'false',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'jovian_user': 'admin',
    'jovian_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'jovian_block_size': '61K'
}

CONFIG_BACKEND_NAME = {
    'san_hosts': ['192.168.0.2'],
    'san_api_port': 82,
    'driver_use_ssl': 'true',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'jovian_user': 'admin',
    'jovian_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'volume_backend_name': 'JovianDSS',
    'reserved_percentage': 10,
    'jovian_block_size': '128K'
}

CONFIG_MULTI_HOST = {
    'san_hosts': ['192.168.0.2', '192.168.0.3'],
    'san_api_port': 82,
    'driver_use_ssl': 'true',
    'jovian_rest_send_repeats': 3,
    'jovian_recovery_delay': 60,
    'jovian_user': 'admin',
    'jovian_password': 'password',
    'jovian_ignore_tpath': [],
    'target_port': 3260,
    'jovian_pool': 'Pool-0',
    'target_prefix': 'iqn.2020-04.com.open-e.cinder:',
    'chap_password_len': 12,
    'san_thin_provision': False,
    'volume_backend_name': 'JovianDSS',
    'reserved_percentage': 10,
    'jovian_block_size': '128K'
}

VOLUME_GET_NO_SNAPSHOTS = {
    "origin": None,
    "relatime": None,
    "acltype": None,
    "vscan": None,
    "full_name": f"Pool-0/{jcom.vname(UUID_1)}",
    "userrefs": None,
    "primarycache": "all",
    "logbias": "latency",
    "creation": "1695048563",
    "sync": "always",
    "is_clone": False,
    "dedup": "off",
    "sharenfs": None,
    "receive_resume_token": None,
    "volsize": "1073741824",
    "referenced": "57344",
    "sharesmb": None,
    "createtxg": "19806101",
    "reservation": "0",
    "scontext": None,
    "mountpoint": None,
    "casesensitivity": None,
    "guid": "13628065397986503663",
    "usedbyrefreservation": "1079975936",
    "dnodesize": None,
    "written": "57344",
    "logicalused": "28672",
    "compressratio": "1.00",
    "rootcontext": "none",
    "default_scsi_id": "9e697f6e11336500",
    "type": "volume",
    "compression": "lz4",
    "snapdir": None,
    "overlay": None,
    "encryption": "off",
    "xattr": None,
    "volmode": "default",
    "copies": "1",
    "snapshot_limit": "18446744073709551615",
    "aclinherit": None,
    "defcontext": "none",
    "readonly": "off",
    "version": None,
    "recordsize": None,
    "filesystem_limit": None,
    "mounted": None,
    "mlslabel": "none",
    "secondarycache": "all",
    "refreservation": "1080033280",
    "available": "955831783424",
    "san:volume_id": "9e697f6e11336500480c13e4467b7964bed4b02e",
    "encryptionroot": None,
    "exec": None,
    "refquota": None,
    "refcompressratio": "1.00",
    "quota": None,
    "utf8only": None,
    "keylocation": "none",
    "snapdev": "hidden",
    "snapshot_count": "18446744073709551615",
    "fscontext": "none",
    "clones": None,
    "canmount": None,
    "keystatus": None,
    "atime": None,
    "usedbysnapshots": "0",
    "normalization": None,
    "usedbychildren": "0",
    "volblocksize": "65536",
    "usedbydataset": "57344",
    "objsetid": "18142",
    "name": "a1",
    "defer_destroy": None,
    "pbkdf2iters": "0",
    "checksum": "on",
    "redundant_metadata": "all",
    "filesystem_count": None,
    "devices": None,
    "keyformat": "none",
    "setuid": None,
    "used": "1080033280",
    "logicalreferenced": "28672",
    "context": "none",
    "zoned": None,
    "nbmand": None,
}

VOLUME_GET_THAT_IS_CLONE = {
    "origin": f"Pool-0/{jcom.vname(UUID_1)}@{jcom.sname(UUID_S1, UUID_1)}",
    "relatime": None,
    "acltype": None,
    "vscan": None,
    "full_name": f"Pool-0/{jcom.vname(UUID_2)}",
    "userrefs": None,
    "primarycache": "all",
    "logbias": "latency",
    "creation": "1695078560",
    "sync": "always",
    "is_clone": True,
    "dedup": "off",
    "sharenfs": None,
    "receive_resume_token": None,
    "volsize": "1073741824",
    "referenced": "57344",
    "sharesmb": None,
    "createtxg": "19812058",
    "reservation": "0",
    "scontext": None,
    "mountpoint": None,
    "casesensitivity": None,
    "guid": "4947994863040470005",
    "usedbyrefreservation": "0",
    "dnodesize": None,
    "written": "0",
    "logicalused": "0",
    "compressratio": "1.00",
    "rootcontext": "none",
    "default_scsi_id": "5c02d042ed8dbce2",
    "type": "volume",
    "compression": "lz4",
    "snapdir": None,
    "overlay": None,
    "encryption": "off",
    "xattr": None,
    "volmode": "default",
    "copies": "1",
    "snapshot_limit": "18446744073709551615",
    "aclinherit": None,
    "defcontext": "none",
    "readonly": "off",
    "version": None,
    "recordsize": None,
    "filesystem_limit": None,
    "mounted": None,
    "mlslabel": "none",
    "secondarycache": "all",
    "refreservation": "0",
    "available": "954751713280",
    "san:volume_id": "5c02d042ed8dbce2570c8d5dc276dd6a2431e138",
    "encryptionroot": None,
    "exec": None,
    "refquota": None,
    "refcompressratio": "1.00",
    "quota": None,
    "utf8only": None,
    "keylocation": "none",
    "snapdev": "hidden",
    "snapshot_count": "18446744073709551615",
    "fscontext": "none",
    "clones": None,
    "canmount": None,
    "keystatus": None,
    "atime": None,
    "usedbysnapshots": "0",
    "normalization": None,
    "usedbychildren": "0",
    "volblocksize": "65536",
    "usedbydataset": "0",
    "objsetid": "19228",
    "name": "a2",
    "defer_destroy": None,
    "pbkdf2iters": "0",
    "checksum": "on",
    "redundant_metadata": "all",
    "filesystem_count": None,
    "devices": None,
    "keyformat": "none",
    "setuid": None,
    "used": "0",
    "logicalreferenced": "28672",
    "context": "none",
    "zoned": None,
    "nbmand": None,
}

SNAPSHOTS_GET_NO_CLONES = [
    {'referenced': '57344',
     'userrefs': '0',
     'primarycache': 'all',
     'creation': '2023-06-28 16:49:33',
     'volsize': '1073741824',
     'createtxg': '18402390',
     'guid': '15554334551928551694',
     'compressratio': '1.00',
     'rootcontext': 'none',
     'encryption': 'off',
     'defcontext': 'none',
     'written': '0',
     'type': 'snapshot',
     'secondarycache': 'all',
     'used': '0',
     'refcompressratio': '1.00',
     'fscontext': 'none',
     'objsetid': '106843',
     'name': jcom.sname(UUID_S1, UUID_1),
     'defer_destroy': 'off',
     'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
     'mlslabel': 'none',
     'logicalreferenced': '28672',
     'context': 'none'},
    {'referenced': '57344',
     'userrefs': '0',
     'primarycache': 'all',
     'creation': '2023-06-28 18:44:49',
     'volsize': '1073741824',
     'createtxg': '18403768',
     'guid': '18319280142829358721',
     'compressratio': '1.00',
     'rootcontext': 'none',
     'encryption': 'off',
     'defcontext': 'none',
     'written': '0',
     'type': 'snapshot',
     'secondarycache': 'all',
     'used': '0',
     'refcompressratio': '1.00',
     'fscontext': 'none',
     'objsetid': '107416',
     'name': jcom.sname(UUID_S2, UUID_1),
     'defer_destroy': 'off',
     'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
     'mlslabel': 'none',
     'logicalreferenced': '28672',
     'context': 'none'}]

SNAPSHOTS_GET_INTERMEDIATE_SNAP = [
    {'referenced': '57344',
     'userrefs': '0',
     'primarycache': 'all',
     'creation': '2023-06-28 16:49:33',
     'volsize': '1073741824',
     'createtxg': '18402390',
     'guid': '15554334551928551694',
     'compressratio': '1.00',
     'rootcontext': 'none',
     'encryption': 'off',
     'defcontext': 'none',
     'written': '0',
     'type': 'snapshot',
     'secondarycache': 'all',
     'used': '0',
     'refcompressratio': '1.00',
     'fscontext': 'none',
     'objsetid': '106843',
     'name': jcom.vname(UUID_S1),
     'defer_destroy': 'off',
     'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
     'mlslabel': 'none',
     'logicalreferenced': '28672',
     'context': 'none'}]

SNAPSHOTS_GET_ONE_CLONE = [
    {'referenced': '57344',
     'userrefs': '0',
     'primarycache': 'all',
     'creation': '2023-06-28 16:49:33',
     'volsize': '1073741824',
     'createtxg': '18402390',
     'guid': '15554334551928551694',
     'compressratio': '1.00',
     'rootcontext': 'none',
     'encryption': 'off',
     'defcontext': 'none',
     'written': '0',
     'type': 'snapshot',
     'secondarycache': 'all',
     'used': '0',
     'refcompressratio': '1.00',
     'fscontext': 'none',
     'objsetid': '106843',
     'name': jcom.sname(UUID_S1, UUID_1),
     'defer_destroy': 'off',
     'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
     'mlslabel': 'none',
     'logicalreferenced': '28672',
     'context': 'none'},
    {'referenced': '57344',
     'userrefs': '0',
     'primarycache': 'all',
     'creation': '2023-06-28 18:44:49',
     'volsize': '1073741824',
     'createtxg': '18403768',
     'guid': '18319280142829358721',
     'compressratio': '1.00',
     'rootcontext': 'none',
     'encryption': 'off',
     'defcontext': 'none',
     'written': '0',
     'type': 'snapshot',
     'secondarycache': 'all',
     'used': '0',
     'refcompressratio': '1.00',
     'fscontext': 'none',
     'objsetid': '107416',
     'clones': 'Pool-0/' + jcom.vname(UUID_2),
     'name': jcom.sname(UUID_S2, UUID_1),
     'defer_destroy': 'off',
     'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
     'mlslabel': 'none',
     'logicalreferenced': '28672',
     'context': 'none'}]

SNAPSHOTS_GET_MULTIPLE_CLONES = [
    {'referenced': '57344',
     'userrefs': '0',
     'primarycache': 'all',
     'creation': '2023-06-28 16:49:33',
     'volsize': '1073741824',
     'createtxg': '18402390',
     'guid': '15554334551928551694',
     'compressratio': '1.00',
     'rootcontext': 'none',
     'encryption': 'off',
     'defcontext': 'none',
     'written': '0',
     'type': 'snapshot',
     'secondarycache': 'all',
     'used': '0',
     'refcompressratio': '1.00',
     'fscontext': 'none',
     'objsetid': '106843',
     'name': jcom.sname(UUID_S1, UUID_1),
     'defer_destroy': 'off',
     'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
     'mlslabel': 'none',
     'logicalreferenced': '28672',
     'context': 'none'},
    {'referenced': '57344',
     'userrefs': '0',
     'primarycache': 'all',
     'creation': '2023-06-28 18:44:49',
     'volsize': '1073741824',
     'createtxg': '18403768',
     'guid': '18319280142829358721',
     'compressratio': '1.00',
     'rootcontext': 'none',
     'encryption': 'off',
     'defcontext': 'none',
     'written': '0',
     'type': 'snapshot',
     'secondarycache': 'all',
     'used': '0',
     'refcompressratio': '1.00',
     'fscontext': 'none',
     'objsetid': '107416',
     'clones': f'Pool-0/{jcom.vname(UUID_2)},Pool-0/{jcom.vname(UUID_3)}',
     'name': jcom.sname(UUID_S2, UUID_1),
     'defer_destroy': 'off',
     'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
     'mlslabel': 'none',
     'logicalreferenced': '28672',
     'context': 'none'}]

SNAPSHOT_GET_ONE_CLONE = {
    "referenced": "57344",
    "userrefs": "0",
    "primarycache": "all",
    "creation": "2023-09-19 01:08:25",
    "volsize": "1073741824",
    "createtxg": "19812047",
    "guid": "7433980076067517643",
    "compressratio": "1.00",
    "rootcontext": "none",
    "encryption": "off",
    "defcontext": "none",
    "written": "57344",
    "type": "snapshot",
    "secondarycache": "all",
    "used": "0",
    "refcompressratio": "1.00",
    "fscontext": "none",
    "clones": f"Pool-0/{jcom.vname(UUID_2)}",
    "objsetid": "19220",
    "defer_destroy": "off",
    "san:volume_id": "9e697f6e11336500480c13e4467b7964bed4b02e",
    "mlslabel": "none",
    "logicalreferenced": "28672",
    "context": "none"
}

SNAPSHOTS_CASCADE_1 = [
    {"name": jcom.sname(UUID_S1, UUID_1),
     "clones": "Pool-0/" + jcom.sname(UUID_S1, UUID_1)},
    {"name": jcom.sname(UUID_S1, UUID_2),
     "clones": "Pool-0/" + jcom.sname(UUID_S1, UUID_2)},
    {"name": jcom.sname(UUID_S1, UUID_3),
     "clones": "Pool-0/" + jcom.sname(UUID_S1, UUID_3)}]

SNAPSHOTS_CASCADE_2 = [
    {"name": jcom.sname(UUID_S1, UUID_1),
     "clones": "Pool-0/" + jcom.sname(UUID_S1, UUID_1)},
    {"name": jcom.vname(UUID_2),
     "clones": "Pool-0/" + jcom.vname(UUID_2)},
    {"name": jcom.sname(UUID_S1, UUID_3),
     "clones": "Pool-0/" + jcom.sname(UUID_S1, UUID_3)}]

SNAPSHOTS_CASCADE_3 = [
    {"name": jcom.vname(UUID_4),
     "clones": "Pool-0/" + jcom.vname(UUID_4)}]

SNAPSHOTS_EMPTY = []

SNAPSHOTS_CLONE = [
    {"name": jcom.vname(UUID_1),
     "clones": "Pool-0/" + jcom.vname(UUID_1)}]

SNAPSHOTS_GARBAGE = [
    {"name": jcom.sname(UUID_S1, UUID_1),
     "clones": "Pool-0/" + jcom.vname(UUID_2)},
    {"name": jcom.sname(UUID_S1, UUID_2),
     "clones": ""}]

SNAPSHOTS_RECURSIVE_1 = [
    {"name": jcom.sname(UUID_S1, UUID_1),
     "clones": "Pool-0/" + jcom.sname(UUID_S1, UUID_1)},
    {"name": jcom.sname(UUID_S1, UUID_2),
     "clones": "Pool-0/" + jcom.hidden(UUID_2)}]

SNAPSHOTS_RECURSIVE_CHAIN_1 = [
    {"name": jcom.sname(UUID_S1, UUID_3),
     "clones": "Pool-0/" + jcom.hidden(UUID_3)}]

SNAPSHOTS_RECURSIVE_CHAIN_2 = [
    {"name": jcom.vname(UUID_2),
     "clones": "Pool-0/" + jcom.hidden(UUID_2)}]


def get_jdss_exceptions():

    out = [jexc.JDSSException(reason="Testing"),
           jexc.JDSSRESTException(request="ra request", reason="Testing"),
           jexc.JDSSRESTProxyException(host="test_host", reason="Testing"),
           jexc.JDSSResourceNotFoundException(res="test_resource"),
           jexc.JDSSVolumeNotFoundException(volume="test_volume"),
           jexc.JDSSSnapshotNotFoundException(snapshot="test_snapshot"),
           jexc.JDSSResourceExistsException(res="test_resource"),
           jexc.JDSSSnapshotExistsException(snapshot="test_snapshot"),
           jexc.JDSSVolumeExistsException(volume="test_volume"),
           jexc.JDSSSnapshotIsBusyException(snapshot="test_snapshot")]

    return out


class TestOpenEJovianDSSDriver(test.TestCase):

    def get_jdss_driver(self, config):
        ctx = context.get_admin_context()

        cfg = mock.Mock()
        cfg.append_config_values.return_value = None
        cfg.get = lambda val, default: config.get(val, default)

        jdssd = driver.JovianDSSDriver(cfg)

        lib_to_patch = ('cinder.volume.drivers.open_e.jovian_common.driver.'
                        'rest.JovianRESTAPI')
        with mock.patch(lib_to_patch) as ra:
            ra.is_pool_exists.return_value = True
        jdssd.ra = mock.Mock()
        return jdssd, ctx

    def start_patches(self, patches):
        for p in patches:
            p.start()

    def stop_patches(self, patches):
        for p in patches:
            p.stop()

    def test_create_volume(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)

        vol.id = UUID_1
        vol.size = 1

        jdssd.ra.create_lun.return_value = None

        jdssd.create_volume(vol.id, 1)

        create_vol_expected = [mock.call(jcom.vname(vol.id),
                                         1073741824,
                                         sparse=False,
                                         block_size=None)]

        jdssd.create_volume(vol.id, 1, sparse=True)

        create_vol_expected += [mock.call(jcom.vname(vol.id),
                                          1073741824,
                                          sparse=True,
                                          block_size=None)]

        jdssd.create_volume(vol.id, 1, sparse=True, block_size="64K")

        create_vol_expected += [mock.call(jcom.vname(vol.id),
                                          1073741824,
                                          sparse=True,
                                          block_size="64K")]

        jdssd.ra.create_lun.assert_has_calls(create_vol_expected)

    def test_promote_newest_delete_no_snapshots(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        # test provide empty snapshot list
        snapshots = []
        jdssd.ra.get_snapshots.return_value = []
        resp = {'data': {"vscan": None,
                         "full_name": "Pool-0/v_" + UUID_1,
                         "userrefs": None,
                         "primarycache": "all",
                         "logbias": "latency",
                         "creation": "1591543140",
                         "sync": "always",
                         "is_clone": False,
                         "dedup": "off",
                         "sharenfs": None,
                         "receive_resume_token": None,
                         "volsize": "1073741824"},
                'error': None,
                'code': 200}
        jdssd.ra.get_lun.return_value = resp
        jdssd.ra.delete_lun.return_value = None
        jdssd._promote_newest_delete(vname, snapshots)
        delete_vol_expected = [mock.call(vname,
                                         force_umount=True,
                                         recursively_children=True)]
        jdssd.ra.delete_lun.assert_has_calls(delete_vol_expected)

        # test provide none as snapshot list
        snapshots = None
        jdssd.ra.get_snapshots.return_value = []
        resp = {'data': {"vscan": None,
                         "full_name": "Pool-0/v_" + UUID_1,
                         "userrefs": None,
                         "primarycache": "all",
                         "logbias": "latency",
                         "creation": "1591543140",
                         "sync": "always",
                         "is_clone": False,
                         "dedup": "off",
                         "sharenfs": None,
                         "receive_resume_token": None,
                         "volsize": "1073741824"},
                'error': None,
                'code': 200}
        jdssd.ra.get_lun.return_value = resp
        jdssd.ra.delete_lun.return_value = None
        jdssd._promote_newest_delete(vname, snapshots)
        delete_vol_expected = [mock.call(vname,
                                         force_umount=True,
                                         recursively_children=True)]
        jdssd.ra.delete_lun.assert_has_calls(delete_vol_expected)

    def test_promote_newest_delete_has_snapshots(self):
        '''Test promote-remove on volume with snapshots

        We should sucessevely remove volume if it have snapshots
        with no clones.
        Also no promote should be called.
        '''

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        snapshots = copy.deepcopy(SNAPSHOTS_GET_NO_CLONES)
        jdssd.ra.get_snapshots.return_value = []
        resp = {"vscan": None,
                "full_name": "Pool-0/v_" + UUID_1,
                "userrefs": None,
                "primarycache": "all",
                "logbias": "latency",
                "creation": "1591543140",
                "sync": "always",
                "is_clone": False,
                "dedup": "off",
                "sharenfs": None,
                "receive_resume_token": None,
                "volsize": "1073741824"},
        jdssd.ra.get_lun.return_value = resp
        jdssd.ra.delete_lun.return_value = None
        jdssd._promote_newest_delete(vname, snapshots)
        delete_vol_expected = [mock.call(vname,
                                         force_umount=True,
                                         recursively_children=True)]
        jdssd.ra.promote.assert_not_called()
        jdssd.ra.delete_lun.assert_has_calls(delete_vol_expected)

    def test_promote_newest_delete_has_clone(self):
        '''Test promote-remove on volume with clone

        We should sucessevely remove volume if it have snapshot
        with no clone.
        '''

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        snapshots = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)

        self.assertEqual(f'Pool-0/{jcom.vname(UUID_2)}',
                         snapshots[1]['clones'])
        jdssd.ra.get_snapshots.return_value = []
        resp = {'data': {"vscan": None,
                         "full_name": "Pool-0/v_" + UUID_1,
                         "userrefs": None,
                         "primarycache": "all",
                         "logbias": "latency",
                         "creation": "1591543140",
                         "sync": "always",
                         "is_clone": False,
                         "dedup": "off",
                         "sharenfs": None,
                         "receive_resume_token": None,
                         "volsize": "1073741824"},
                'error': None,
                'code': 200}
        jdssd.ra.get_lun.return_value = resp
        jdssd.ra.delete_lun.return_value = None

        jdssd._promote_newest_delete(vname, snapshots)
        delete_vol_expected = [mock.call(vname,
                                         force_umount=True,
                                         recursively_children=True)]
        promote_vol_expected = [mock.call(vname,
                                          jcom.sname(UUID_S2, UUID_1),
                                          jcom.vname(UUID_2))]
        jdssd.ra.promote.assert_has_calls(promote_vol_expected)
        jdssd.ra.delete_lun.assert_has_calls(delete_vol_expected)

    def test_promote_newest_delete_has_multiple_clones(self):
        '''Test promote-remove on volume with clone

        We should sucessevely remove volume if it have snapshot
        with no clone.
        '''

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        snapshots = copy.deepcopy(SNAPSHOTS_GET_MULTIPLE_CLONES)
        jdssd.ra.get_snapshots.return_value = []
        resp = {'data': {"vscan": None,
                         "full_name": "Pool-0/s_" + UUID_S2,
                         "userrefs": None,
                         "primarycache": "all",
                         "logbias": "latency",
                         "creation": "1591543140",
                         "sync": "always",
                         "is_clone": False,
                         "dedup": "off",
                         "sharenfs": None,
                         "receive_resume_token": None,
                         "volsize": "1073741824"},
                'error': None,
                'code': 200}
        jdssd.ra.get_lun.return_value = resp
        jdssd.ra.delete_lun.return_value = None
        jdssd._promote_newest_delete(vname, snapshots)
        delete_vol_expected = [mock.call(vname,
                                         force_umount=True,
                                         recursively_children=True)]
        promote_vol_expected = [mock.call(vname,
                                          jcom.sname(UUID_S2, UUID_1),
                                          jcom.vname(UUID_3))]
        jdssd.ra.promote.assert_has_calls(promote_vol_expected)
        jdssd.ra.delete_lun.assert_has_calls(delete_vol_expected)

    def test_delete_vol_with_source_snap_no_snap(self):
        '''Test _delete_vol_with_source_snap

        We should sucessevely remove volume with no snapshots.
        '''
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        jdssd.ra.get_lun.return_value = copy.deepcopy(VOLUME_GET_NO_SNAPSHOTS)
        jdssd.ra.delete_lun.return_value = None

        delete_vol_expected = [mock.call(vname,
                                         force_umount=True,
                                         recursively_children=False)]

        jdssd._delete_vol_with_source_snap(vname, recursive=False)

        jdssd.ra.delete_lun.assert_has_calls(delete_vol_expected)
        jdssd.ra.delete_snapshot.assert_not_called()

    def test_delete_vol_with_source_snap(self):
        '''Test _delete_vol_with_source_snap

        We should sucessevely remove volume that is clone.
        We should not remove source snapshot
        if that snapshot is not related to volume to remove
        '''
        # Snapshot does belong to parent volume

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_2)
        jdssd.ra.get_lun.return_value = \
            copy.deepcopy(VOLUME_GET_THAT_IS_CLONE)
        jdssd.ra.delete_lun.return_value = None

        delete_vol_expected = [mock.call(vname,
                                         force_umount=True,
                                         recursively_children=False)]

        jdssd._delete_vol_with_source_snap(vname, recursive=False)

        jdssd.ra.delete_lun.assert_has_calls(delete_vol_expected)
        jdssd.ra.delete_snapshot.assert_not_called()

    def test_delete_vol_with_source_snap_snap_delete(self):
        # Snapshot belongs to volume to delete

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_2)
        lun_info = copy.deepcopy(VOLUME_GET_THAT_IS_CLONE)
        origin = f"Pool-0/{jcom.vname(UUID_1)}@{jcom.sname(UUID_S2, UUID_2)}"
        lun_info['origin'] = origin

        jdssd.ra.get_lun.return_value = lun_info

        jdssd.ra.delete_lun.return_value = None

        delete_vol_expected = [mock.call(vname,
                                         force_umount=True,
                                         recursively_children=False)]
        delete_snapshot_expected = [mock.call(jcom.vname(UUID_1),
                                              jcom.sname(UUID_S2, UUID_2),
                                              recursively_children=True,
                                              force_umount=True)]
        jdssd._delete_vol_with_source_snap(vname, recursive=False)

        jdssd.ra.delete_lun.assert_has_calls(delete_vol_expected)
        jdssd.ra.delete_snapshot.assert_has_calls(delete_snapshot_expected)

    def test_clean_garbage_resources(self):

        # Make sure that we request list of snapshots if none is provide
        # Make sure we remove intermediate volume like snapshot if it has
        # no volumes associated with it
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        snap_list = copy.deepcopy(SNAPSHOTS_GET_INTERMEDIATE_SNAP)
        get_snapshots_expectes = [mock.call(jcom.vname(UUID_1))]
        delete_snapshot_expected = [mock.call(jcom.vname(UUID_1),
                                              jcom.vname(UUID_S1),
                                              force_umount=True)]

        jdssd.ra.get_snapshots.side_effect = [snap_list, []]

        ret = jdssd._clean_garbage_resources(vname, snapshots=None)

        self.assertEqual([], ret)
        jdssd.ra.get_snapshots.assert_has_calls(get_snapshots_expectes)
        jdssd.ra.delete_snapshot.assert_has_calls(delete_snapshot_expected)

    def test_clean_garbage_resources_do_nothing(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        snap_list = SNAPSHOTS_GET_ONE_CLONE.copy()
        get_snapshots_expectes = [mock.call(jcom.vname(UUID_1))]

        jdssd.ra.get_snapshots.side_effect = [snap_list, snap_list]

        ret = jdssd._clean_garbage_resources(vname, snapshots=None)

        self.assertEqual(SNAPSHOTS_GET_ONE_CLONE, ret)
        jdssd.ra.get_snapshots.assert_has_calls(get_snapshots_expectes)
        jdssd.ra.delete_snapshot.assert_not_called()

    def test_clean_garbage_resources_clean_hidden(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        snap_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)
        snap_list[1]['clones'] = f"Pool-0/{jcom.hidden(UUID_2)}"
        snap_list[1]['name'] = jcom.sname(UUID_S2, UUID_1)

        get_snapshots_expectes = [mock.call(jcom.vname(UUID_1)),
                                  mock.call(jcom.vname(UUID_1))]

        jdssd.ra.get_snapshots.side_effect = [snap_list,
                                              SNAPSHOTS_GET_NO_CLONES]
        with mock.patch.object(jdssd, '_promote_newest_delete') as pnd:
            pnd.side_effect = [None]
            ret = jdssd._clean_garbage_resources(vname, snapshots=None)
            self.assertEqual(SNAPSHOTS_GET_NO_CLONES, ret)
            pnd.assert_has_calls([mock.call(jcom.hidden(UUID_2))])

        jdssd.ra.get_snapshots.assert_has_calls(get_snapshots_expectes)
        jdssd.ra.delete_snapshot.assert_not_called()

    def test_clean_garbage_resources_clean_snapshot(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)
        snap_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)
        snap_list[1]['clones'] = f"Pool-0/{jcom.sname(UUID_S2, UUID_1)}"
        snap_list[1]['name'] = jcom.sname(UUID_S2, UUID_1)

        get_snapshots_expectes = [mock.call(jcom.vname(UUID_1))]

        jdssd.ra.get_snapshots.side_effect = [snap_list]
        with mock.patch.object(jdssd, '_promote_newest_delete') as pnd:
            pnd.side_effect = [None]

            ret = jdssd._clean_garbage_resources(vname, snapshots=None)
            pnd.assert_not_called()
            self.assertEqual(snap_list, ret)

        jdssd.ra.get_snapshots.assert_has_calls(get_snapshots_expectes)
        jdssd.ra.delete_snapshot.assert_not_called()

    def test_list_busy_snapshots(self):

        # Check operation with regular clone
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        snap_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)

        ret = jdssd._list_busy_snapshots(vname, snap_list)
        self.assertEqual([SNAPSHOTS_GET_ONE_CLONE[1]], ret)

        # Check hidden clone
        snap_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)

        snap_list[0]['clones'] = f"Pool-0/{jcom.hidden(UUID_2)}"
        snap_list[0]['name'] = jcom.sname(UUID_S2, UUID_1)

        ret = jdssd._list_busy_snapshots(vname, snap_list)
        self.assertEqual(snap_list, ret)

        # Check exlude dedicated volume flag
        snap_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)

        ret = jdssd._list_busy_snapshots(vname, snap_list,
                                         exclude_dedicated_volumes=True)
        self.assertEqual([], ret)

    def _clean_volume_snapshots_mount_points(self):

        # Single attached snapshot case
        vname = jcom.vname(UUID_1)
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        snap_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)
        cname = jcom.sname(UUID_S2, UUID_1)
        snap_list[1]['clones'] = cname = f'Pool-0/{cname}'

        ret_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)
        ret_list[1].pop('clones')

        jdssd.ra.get_snapshots.return_value = ret_list
        with mock.patch.object(jdssd, '_delete_volume'):
            ret = jdssd._clean_volume_snapshots_mount_points(vname, snap_list)
            jdssd._delete_volume.assert_called_once_with(cname, cascade=True)

        jdssd.ra.get_snapshots.assert_called_once_with(vname)
        self.assertEqual(ret_list, ret)

        # Multiple attached snapshot case
        vname = jcom.vname(UUID_1)
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        snap_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)
        cname0 = jcom.sname(UUID_S1, UUID_1)
        cname1 = jcom.sname(UUID_S2, UUID_1)
        snap_list[0]['clones'] = cname = f'Pool-0/{cname0}'
        snap_list[1]['clones'] = cname = f'Pool-0/{cname1}'

        ret_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)
        ret_list[0].pop('clones')
        ret_list[1].pop('clones')

        jdssd.ra.get_snapshots.return_value = ret_list

        del_vol_expected = [mock.call(jcom.vname(cname0), cascade=True),
                            mock.call(jcom.vname(cname1), cascade=True)]

        with mock.patch.object(jdssd, '_delete_volume'):
            ret = jdssd._clean_volume_snapshots_mount_points(vname, snap_list)
            jdssd._delete_volume.assert_has_calls(del_vol_expected)

        jdssd.ra.get_snapshots.assert_called_once_with(vname)
        self.assertEqual(ret_list, ret)

    def test_delete_volume_no_snap(self):

        vname = jcom.vname(UUID_1)
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        jdssd.ra.delete_lun.return_value = None

        del_lun_exp = [mock.call(
            jcom.vname(UUID_1),
            force_umount=True,
            recursively_children=False)]

        jdssd._delete_volume(vname)

        jdssd.ra.delete_lun.assert_has_calls(del_lun_exp)
        jdssd.ra.get_snapshots.assert_not_called()

    def test_delete_volume_cascade_with_clones(self):

        vname = jcom.vname(UUID_1)
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        jdssd.ra.delete_lun.side_effect = [
            jexc.JDSSResourceIsBusyException(res=vname)]

        del_lun_exp = [mock.call(jcom.vname(UUID_1),
                                 force_umount=True,
                                 recursively_children=True)]

        snap_list = copy.deepcopy(SNAPSHOTS_GET_ONE_CLONE)

        get_snap_exp = [mock.call(jcom.vname(UUID_1))]

        jdssd.ra.get_snapshots.side_effect = [snap_list]

        pnd_exp = [mock.call(jcom.vname(UUID_1), snapshots=snap_list)]
        with mock.patch.object(jdssd, '_promote_newest_delete'):
            jdssd._delete_volume(vname, cascade=True)
            jdssd._promote_newest_delete.assert_has_calls(pnd_exp)

        jdssd.ra.delete_lun.assert_has_calls(del_lun_exp)
        jdssd.ra.get_snapshots.assert_has_calls(get_snap_exp)

    def test_delete_volume(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        with mock.patch.object(jdssd, '_delete_volume'):
            jdssd.delete_volume(UUID_1)
            jdssd._delete_volume.assert_called_once_with(vname, cascade=False)

    def test_get_provider_location(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        host = CONFIG_OK["san_hosts"][0]
        port = CONFIG_OK["target_port"]
        target_name = CONFIG_OK["target_prefix"] + UUID_1
        patches = [mock.patch.object(
            jdssd.ra,
            "get_active_host",
            return_value=host)]
        out = '{host}:{port},1 {name} 0'.format(
            host=host,
            port=port,
            name=target_name
        )
        self.start_patches(patches)
        self.assertEqual(out, jdssd.get_provider_location(UUID_1))
        self.stop_patches(patches)

    def test_get_target_name(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        ret = jdssd._get_target_name(UUID_1)
        self.assertEqual(ret, f'iqn.2020-04.com.open-e.cinder:{UUID_1}')

    def test_get_iscsi_properties(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        provider_auth = 'chap user_name 123456789012'

        multipath = True

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        ret = jdssd._get_iscsi_properties(UUID_1,
                                          provider_auth,
                                          multipath=multipath)
        expected = {'auth_method': 'chap',
                    'auth_password': '123456789012',
                    'auth_username': 'user_name',
                    'target_discovered': False,
                    'target_iqns': [target_name],
                    'target_lun': 0,
                    'target_luns': [0],
                    'target_portals': ['192.168.0.2:3260']}
        self.assertEqual(expected, ret)

    def test_get_iscsi_properties_multipath(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_MULTI_HOST)

        provider_auth = 'chap user_name 123456789012'

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        ret = jdssd._get_iscsi_properties(UUID_1,
                                          provider_auth,
                                          multipath=True)
        expected = {'auth_method': 'chap',
                    'auth_password': '123456789012',
                    'auth_username': 'user_name',
                    'target_discovered': False,
                    'target_iqns': [target_name, target_name],
                    'target_lun': 0,
                    'target_luns': [0, 0],
                    'target_portals': ['192.168.0.2:3260', '192.168.0.3:3260']}
        self.assertEqual(expected, ret)

    def test_remove_target_volume(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        target_name = CONFIG_OK['target_prefix'] + UUID_1

        jdssd.ra.detach_target_vol.return_value = None
        jdssd.ra.delete_target.return_value = None

        jdssd._remove_target_volume(UUID_1, jcom.vname(UUID_1))

        jdssd.ra.detach_target_vol.assert_called_once_with(target_name,
                                                           jcom.vname(UUID_1))
        jdssd.ra.delete_target.assert_called_with(target_name)

    def test_remove_target_volume_no_target(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        vname = jcom.vname(UUID_1)

        jdssd.ra.detach_target_vol.return_value = None
        jdssd.ra.detach_target_vol.side_effect = (
            jexc.JDSSResourceNotFoundException(res=target_name))
        jdssd.ra.delete_target.return_value = None

        jdssd._remove_target_volume(UUID_1, vname)

        jdssd.ra.detach_target_vol.assert_called_once_with(target_name,
                                                           jcom.vname(UUID_1))
        jdssd.ra.delete_target.assert_called_with(target_name)

    def test_remove_target_volume_fail_to_detach(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        target_name = CONFIG_OK['target_prefix'] + UUID_1

        jdssd.ra.detach_target_vol.side_effect = (
            jexc.JDSSRESTException(reason='running test', request='test'))
        jdssd.ra.delete_target.return_value = None

        self.assertRaises(jexc.JDSSException,
                          jdssd._remove_target_volume,
                          UUID_1,
                          jcom.vname(UUID_1))

        jdssd.ra.detach_target_vol.assert_called_once_with(
            target_name, jcom.vname(UUID_1))
        jdssd.ra.delete_target.assert_not_called()

    def test_remove_target_volume_fail_to_delete(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        target_name = CONFIG_OK['target_prefix'] + UUID_1

        jdssd.ra.detach_target_vol.return_value = None
        jdssd.ra.delete_target.side_effect = (
            jexc.JDSSRESTException(reason='running test', request='test'))

        self.assertRaises(jexc.JDSSException,
                          jdssd._remove_target_volume,
                          UUID_1,
                          jcom.vname(UUID_1))

        jdssd.ra.detach_target_vol.assert_called_once_with(target_name,
                                                           jcom.vname(UUID_1))
        jdssd.ra.delete_target.assert_called_with(target_name)

    def test_ensure_export(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_MULTI_HOST)

        provider_auth = 'chap user_name 123456789012'

        with mock.patch.object(jdssd, "_ensure_target_volume"):
            jdssd.ensure_export(UUID_1, provider_auth)
            jdssd._ensure_target_volume.assert_called_once_with(
                UUID_1,
                jcom.vname(UUID_1),
                provider_auth)

    def test_initialize_connection(self):

        # Test Ok
        jdssd, ctx = self.get_jdss_driver(CONFIG_MULTI_HOST)

        volume_id = UUID_1
        provider_auth = 'chap user_name 123456789012'

        multipath = True

        target_name = CONFIG_OK['target_prefix'] + UUID_1

        properties = {'auth_method': 'chap',
                      'auth_password': '123456789012',
                      'auth_username': 'user_name',
                      'target_discovered': False,
                      'target_iqns': [target_name, target_name],
                      'target_lun': 0,
                      'target_luns': [0, 0],
                      'target_portals': ['192.168.0.2:3260',
                                         '192.168.0.3:3260']}

        con_info = {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

        vname = jcom.vname(volume_id)
        with mock.patch.object(jdssd, '_ensure_target_volume'):
            ret = jdssd.initialize_connection(volume_id, provider_auth,
                                              multipath=multipath)
            jdssd._ensure_target_volume.assert_called_with(UUID_1, vname,
                                                           provider_auth)

        self.assertEqual(con_info, ret)

        # Test initialize for snapshot
        jdssd, ctx = self.get_jdss_driver(CONFIG_MULTI_HOST)

        volume_id = UUID_1
        snapshot_id = UUID_S1

        provider_auth = 'chap user_name 123456789012'

        multipath = True

        target_name = CONFIG_OK['target_prefix'] + UUID_S1

        properties = {'auth_method': 'chap',
                      'auth_password': '123456789012',
                      'auth_username': 'user_name',
                      'target_discovered': False,
                      'target_iqns': [target_name, target_name],
                      'target_lun': 0,
                      'target_luns': [0, 0],
                      'target_portals': ['192.168.0.2:3260',
                                         '192.168.0.3:3260']}

        con_info = {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

        sname = jcom.sname(snapshot_id, volume_id)
        with mock.patch.object(jdssd, '_ensure_target_volume'):
            ret = jdssd.initialize_connection(volume_id, provider_auth,
                                              snapshot_id=snapshot_id,
                                              multipath=multipath)
            jdssd._ensure_target_volume.assert_called_with(UUID_S1, sname,
                                                           provider_auth,
                                                           mode='ro')

        self.assertEqual(con_info, ret)

        # Test no auth
        jdssd, ctx = self.get_jdss_driver(CONFIG_MULTI_HOST)

        volume_id = UUID_1

        provider_auth = None

        multipath = True

        target_name = CONFIG_OK['target_prefix'] + UUID_1

        properties = {'auth_method': 'chap',
                      'auth_password': '123456789012',
                      'auth_username': 'user_name',
                      'target_discovered': False,
                      'target_iqns': [target_name, target_name],
                      'target_lun': 0,
                      'target_luns': [0, 0],
                      'target_portals': ['192.168.0.2:3260',
                                         '192.168.0.3:3260']}

        con_info = {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

        sname = jcom.sname(snapshot_id, volume_id)
        with mock.patch.object(jdssd, '_ensure_target_volume'):

            self.assertRaises(jexc.JDSSException,
                              jdssd.initialize_connection,
                              volume_id,
                              provider_auth,
                              multipath=multipath)
            jdssd._ensure_target_volume.assert_not_called()

    def test_create_target_volume(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        vid = jcom.vname(UUID_1)
        target_name = CONFIG_OK['target_prefix'] + UUID_1
        provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name', 'password': '123456789012'}

        patches = [
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials")]

        self.start_patches(patches)
        jdssd._create_target_volume(UUID_1, vid, provider_auth)
        jdssd.ra.create_target.assert_called_once_with(target_name,
                                                       use_chap=True)
        jdssd._attach_target_volume.assert_called_once_with(
            target_name, jcom.vname(UUID_1))
        jdssd._set_target_credentials.assert_called_once_with(
            target_name, cred)
        self.stop_patches(patches)

    def test_create_target_volume_for_snapshot_attachment(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        vid = jcom.sname(UUID_S1, UUID_1)
        target_name = CONFIG_OK['target_prefix'] + UUID_S1
        provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name', 'password': '123456789012'}

        patches = [
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials")]

        self.start_patches(patches)
        jdssd._create_target_volume(UUID_S1, vid, provider_auth)
        jdssd.ra.create_target.assert_called_once_with(target_name,
                                                       use_chap=True)
        jdssd._attach_target_volume.assert_called_once_with(
            target_name, jcom.sname(UUID_S1, UUID_1))
        jdssd._set_target_credentials.assert_called_once_with(
            target_name, cred)
        self.stop_patches(patches)

    def test_attach_target_volume(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_BACKEND_NAME)

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        vname = jcom.vname(UUID_1)

        jdssd.ra.attach_target_vol.return_value = None
        jdssd.ra.delete_target.return_value = None

        jdssd._attach_target_volume(target_name, vname)

        jdssd.ra.attach_target_vol.assert_called_once_with(
            target_name, vname)
        jdssd.ra.delete_target.assert_not_called()

        ex = jexc.JDSSResourceExistsException(res=target_name)
        jdssd.ra.attach_target_vol.side_effect = ex

        self.assertRaises(jexc.JDSSException,
                          jdssd._attach_target_volume,
                          target_name,
                          vname)
        jdssd.ra.delete_target.assert_called_once_with(target_name)

    def test_set_target_credentials(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_BACKEND_NAME)

        target_name = CONFIG_BACKEND_NAME['target_prefix'] + UUID_1
        cred = {'name': 'user_name', 'password': '123456789012'}

        jdssd.ra.create_target_user.return_value = None
        jdssd.ra.delete_target.return_value = None

        jdssd._set_target_credentials(target_name, cred)

        jdssd.ra.create_target_user.assert_called_once_with(
            target_name, cred)
        jdssd.ra.delete_target.assert_not_called()

        ex = jexc.JDSSResourceExistsException(res=target_name)
        jdssd.ra.create_target_user.side_effect = ex

        self.assertRaises(jexc.JDSSException,
                          jdssd._set_target_credentials,
                          target_name,
                          cred)
        jdssd.ra.delete_target.assert_called_once_with(target_name)

    def test_clone_object(self):

        # test ok
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        ovname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_S1, UUID_1)
        cvname = jcom.vname(UUID_2)
        jdssd._clone_object(cvname, sname, ovname, sparse=True)

        jdssd.ra.create_snapshot.assesrt_not_called()
        jdssd.ra.create_volume_from_snapshot.assert_called_once_with(
            cvname, sname, ovname, sparse=True)

        # test create snapshot
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        ovname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_S1, UUID_1)
        cvname = jcom.vname(UUID_2)
        jdssd._clone_object(cvname, sname, ovname, sparse=True)

        jdssd.ra.create_snapshot.assesrt_not_called()
        jdssd.ra.create_volume_from_snapshot.assert_called_once_with(
            cvname, sname, ovname, sparse=True)

        # test create from snapshot failed
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        ovname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_S1, UUID_1)
        cvname = jcom.vname(UUID_2)
        jdssd.ra.create_volume_from_snapshot.side_effect = [
            jexc.JDSSVolumeExistsException(volume=cvname)]
        self.assertRaises(jexc.JDSSException,
                          jdssd._clone_object,
                          cvname,
                          sname,
                          ovname,
                          sparse=True)

        jdssd.ra.create_snapshot.assesrt_not_called()
        jdssd.ra.create_volume_from_snapshot.assert_called_once_with(
            cvname, sname, ovname, sparse=True)
        jdssd.ra.delete_snapshot(ovname, sname,
                                 force_umount=True,
                                 recursively_children=True)

    def test_resize_volume(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        vname = jcom.vname(UUID_1)
        jdssd.resize_volume(UUID_1, 2)

        jdssd.ra.extend_lun.assert_called_once_with(vname, o_units.Gi * 2)

    def test_create_cloned_volume(self):

        # test ok
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        cvname = jcom.vname(UUID_2)
        vname = jcom.vname(UUID_1)

        jdssd.ra.get_lun.return_value = copy.deepcopy(VOLUME_GET_THAT_IS_CLONE)
        with mock.patch.object(jdssd, '_clone_object'):
            jdssd.create_cloned_volume(UUID_2, UUID_1, 1, sparse=False)

            jdssd._clone_object.assert_called_once_with(
                cvname, cvname, vname,
                sparse=False,
                create_snapshot=True)

        # test clone from snapshot
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        cvname = jcom.vname(UUID_2)
        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_S1, UUID_1)
        jdssd.ra.get_lun.return_value = copy.deepcopy(VOLUME_GET_THAT_IS_CLONE)
        with mock.patch.object(jdssd, '_clone_object'):
            jdssd.create_cloned_volume(UUID_2, UUID_1, 1,
                                       snapshot_name=UUID_S1,
                                       sparse=False)

            jdssd._clone_object.assert_called_once_with(
                cvname, sname, vname,
                sparse=False,
                create_snapshot=False)

        # test extend
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        cvname = jcom.vname(UUID_2)
        vname = jcom.vname(UUID_1)

        get_vol = copy.deepcopy(VOLUME_GET_THAT_IS_CLONE)

        get_vol['volsize'] = "1073145824"
        jdssd.ra.get_lun.return_value = get_vol
        with mock.patch.object(jdssd, '_clone_object'), \
                mock.patch.object(jdssd, "resize_volume"):
            jdssd.create_cloned_volume(UUID_2, UUID_1, 1, sparse=False)

            jdssd._clone_object.assert_called_once_with(
                cvname, cvname, vname,
                sparse=False,
                create_snapshot=True)
            jdssd.resize_volume.assert_called_once_with(UUID_2, 1)

    def test_create_snapshot(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_BACKEND_NAME)

        jdssd.create_snapshot(UUID_S1, UUID_1)

        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_S1, UUID_1)

        jdssd.ra.create_snapshot.assert_called_once_with(vname, sname)

    def test_create_export_snapshot(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_BACKEND_NAME)
        provider_auth = 'chap user_name 123456789012'

        sname = jcom.sname(UUID_S1, UUID_1)
        vname = jcom.vname(UUID_1)

        with mock.patch.object(jdssd, '_clone_object'), \
                mock.patch.object(jdssd, '_ensure_target_volume'):
            jdssd.create_export_snapshot(UUID_S1, UUID_1, provider_auth)

            jdssd._clone_object.assert_called_once_with(sname, sname, vname,
                                                        sparse=True,
                                                        create_snapshot=False)

            jdssd._ensure_target_volume(UUID_S1, sname, provider_auth)

    def test_remove_export(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        patches = [
            mock.patch.object(
                jdssd,
                "_remove_target_volume",
                return_value=None)]

        self.start_patches(patches)

        jdssd.remove_export(UUID_1)
        jdssd._remove_target_volume.assert_called_once_with(UUID_1, vname)

        self.stop_patches(patches)

    def test_remove_export_snapshot(self):

        # remove ok
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        with mock.patch.object(jdssd, "_remove_target_volume"), \
                mock.patch.object(jdssd, "_delete_volume"):

            jdssd.remove_export_snapshot(UUID_S1, UUID_1)
            jdssd._delete_volume.assert_called_once()
            jdssd._remove_target_volume.assert_called_once()

        # remove export failed
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        vname = jcom.sname(UUID_S1, UUID_1)
        with mock.patch.object(jdssd, "_remove_target_volume"), \
                mock.patch.object(jdssd, "_delete_volume"):

            jdssd._remove_target_volume.side_effect = [
                jexc.JDSSResourceIsBusyException(res=vname)]

            self.assertRaises(jexc.JDSSResourceIsBusyException,
                              jdssd.remove_export_snapshot,
                              UUID_S1,
                              UUID_1)
            jdssd._delete_volume.assert_called_once()
            jdssd._remove_target_volume.assert_called_once()

    def test_delete_snapshot(self):

        # Delete ok, letion of snapshot with no clones
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_S1, UUID_1)

        jdssd.ra.delete_snapshot.side_effect = [None]

        jdssd._delete_snapshot(vname, sname)
        jdssd.ra.delete_snapshot.assert_called_once_with(vname, sname,
                                                         force_umount=True)

        # Test deletion of snapshot with clones
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_S1, UUID_1)
        side_eff = [jexc.JDSSSnapshotIsBusyException(snapshot=sname), None]
        jdssd.ra.delete_snapshot.side_effect = side_eff

        side_eff = [copy.deepcopy(SNAPSHOT_GET_ONE_CLONE)]

        jdssd.ra.get_snapshot.side_effect = side_eff

        with mock.patch.object(jdssd, '_promote_newest_delete'):
            jdssd._delete_snapshot(vname, sname)
            jdssd._promote_newest_delete.assert_not_called()
        jdssd.ra.delete_snapshot.assert_called_once_with(vname, sname,
                                                         force_umount=True)

        # Test deletion of attached snapshot
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_S1, UUID_1)
        side_eff = [jexc.JDSSSnapshotIsBusyException(snapshot=sname), None]
        jdssd.ra.delete_snapshot.side_effect = side_eff

        get_snap = copy.deepcopy(SNAPSHOT_GET_ONE_CLONE)

        get_snap['clones'] = f"Pool-0/{sname}"
        side_eff = [get_snap]

        jdssd.ra.get_snapshot.side_effect = side_eff

        delete_snap_expected = [mock.call(vname, sname, force_umount=True),
                                mock.call(vname, sname, force_umount=True)]

        with mock.patch.object(jdssd, '_promote_newest_delete'):

            jdssd._delete_snapshot(vname, sname)
            jdssd._promote_newest_delete.assert_called_once_with(sname)

        jdssd.ra.delete_snapshot.assert_has_calls(delete_snap_expected)

    def test_delete_snapshot_wrapper(self):
        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        volume_name = UUID_1
        snapshot_name = UUID_S1

        with mock.patch.object(jdssd, "_delete_snapshot"):
            jdssd.delete_snapshot(volume_name, snapshot_name)

            jdssd._delete_snapshot.assert_called_once_with(
                jcom.vname(UUID_1),
                jcom.sname(UUID_S1, UUID_1))

    def test_ensure_target_volume(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        id = UUID_1
        vid = jcom.vname(UUID_1)

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name'}

        patches = [
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials"),
            mock.patch.object(jdssd, "_attach_target_volume")]

        jdssd.ra.is_target.return_value = True
        jdssd.ra.is_target_lun.return_value = True
        jdssd.ra.get_target_user.return_value = [cred]

        self.start_patches(patches)

        jdssd._ensure_target_volume(id, vid, provider_auth)

        jdssd.ra.is_target.assert_called_once_with(target_name)

        jdssd.ra.is_target_lun.assert_called_once_with(target_name, vid)

        jdssd.ra.get_target_user.assert_called_once_with(target_name)

        jdssd.ra.delete_target_user.assert_not_called()
        jdssd._set_target_credentials.assert_not_called()
        self.stop_patches(patches)

    def test_ensure_target_volume_not_attached(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        id = UUID_1
        vid = jcom.vname(UUID_1)

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name'}

        patches = [
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials"),
            mock.patch.object(jdssd, "_attach_target_volume")]

        jdssd.ra.is_target.return_value = True
        jdssd.ra.is_target_lun.return_value = False
        jdssd.ra.get_target_user.return_value = [cred]

        self.start_patches(patches)

        jdssd._ensure_target_volume(id, vid, provider_auth)

        jdssd.ra.is_target.assert_called_once_with(target_name)
        jdssd.ra.is_target_lun.assert_called_once_with(target_name, vid)

        jdssd._attach_target_volume.assert_called_once_with(
            target_name, vid)
        jdssd.ra.get_target_user.assert_called_once_with(target_name)

        jdssd.ra.delete_target_user.assert_not_called()
        jdssd._set_target_credentials.assert_not_called()
        self.stop_patches(patches)

    def test_ensure_target_volume_no_target(self):

        jdssd, ctx = self.get_jdss_driver(CONFIG_OK)

        id = UUID_1
        vid = jcom.vname(UUID_1)

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name'}

        patches = [
            mock.patch.object(jdssd, "_create_target_volume"),
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials"),
            mock.patch.object(jdssd, "_attach_target_volume")]

        jdssd.ra.is_target.return_value = False
        jdssd.ra.get_target_user.return_value = cred['name']

        self.start_patches(patches)

        jdssd._ensure_target_volume(id, vid, provider_auth)

        jdssd.ra.is_target.assert_called_once_with(target_name)
        jdssd._create_target_volume.assert_called_once_with(id,
                                                            vid,
                                                            provider_auth)

        jdssd.ra.is_target_lun.assert_not_called()
        self.stop_patches(patches)
