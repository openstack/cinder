#    Copyright (c) 2023 Open-E, Inc.
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

from cinder import exception
from cinder.tests.unit import test
from cinder.volume.drivers.open_e.jovian_common import jdss_common as jcom

UUID_1 = '12345678-1234-1234-1234-000000000001'
UUID_2 = '12345678-1234-1234-1234-000000000002'
UUID_S1 = '12345678-1234-1234-1234-100000000001'
UUID_S2 = '12345678-1234-1234-1234-100000000002'

V_UUID_1 = 'v_12345678-1234-1234-1234-000000000001'
V_UUID_2 = 'v_12345678-1234-1234-1234-000000000002'
V_UUID_3 = 'v_12345678-1234-1234-1234-000000000003'
S_UUID_1 = f's_{UUID_S1}_{UUID_1}'
S_UUID_2 = f's_{UUID_S2}_{UUID_1}'
T_UUID_1 = 't_12345678-1234-1234-1234-000000000001'


VOLUME_GET_THAT_IS_CLONE = {
    "origin": f"Pool-0/{V_UUID_1}@{S_UUID_1}",
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

SNAPSHOT_GET = {
    'referenced': '57344',
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
    'name': S_UUID_1,
    'defer_destroy': 'off',
    'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
    'mlslabel': 'none',
    'logicalreferenced': '28672',
    'context': 'none'}

SNAPSHOT_MULTIPLE_CLONES = {
    'referenced': '57344',
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
    'clones': f'Pool-0/{V_UUID_2},Pool-0/{V_UUID_3}',
    'name': S_UUID_1,
    'defer_destroy': 'off',
    'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
    'mlslabel': 'none',
    'logicalreferenced': '28672',
    'context': 'none'}

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
     'name': S_UUID_1,
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
     'name': S_UUID_2,
     'defer_destroy': 'off',
     'san:volume_id': 'e82c7fcbd78df0ffe67d363412e5091421d313ca',
     'mlslabel': 'none',
     'logicalreferenced': '28672',
     'context': 'none'}]


class TestOpenEJovianDSSCommon(test.TestCase):

    def test_is_volume(self):

        self.assertFalse(jcom.is_volume("asdasd"))
        self.assertFalse(jcom.is_volume(UUID_1))
        self.assertTrue(jcom.is_volume(V_UUID_1))

    def test_is_snapshot(self):

        self.assertFalse(jcom.is_snapshot("asdasd"))
        self.assertFalse(jcom.is_snapshot(UUID_S1))
        self.assertTrue(jcom.is_snapshot(S_UUID_1))

    def test_idname(self):

        self.assertEqual(UUID_1, jcom.idname(V_UUID_1))
        self.assertEqual(UUID_S1, jcom.idname(S_UUID_1))
        self.assertEqual(UUID_1, jcom.idname(T_UUID_1))

        self.assertRaises(exception.VolumeDriverException, jcom.idname, 'asd')

    def test_vname(self):

        self.assertEqual(V_UUID_1, jcom.vname(UUID_1))
        self.assertEqual(V_UUID_1, jcom.vname(V_UUID_1))
        self.assertRaises(exception.VolumeDriverException,
                          jcom.vname, S_UUID_1)

    def test_sname_to_id(self):

        self.assertEqual((UUID_S1, UUID_1), jcom.sname_to_id(S_UUID_1))

    def test_sid_from_sname(self):

        self.assertEqual(UUID_S1, jcom.sid_from_sname(S_UUID_1))

    def test_vid_from_sname(self):
        self.assertEqual(UUID_1, jcom.vid_from_sname(S_UUID_1))

    def test_sname(self):
        self.assertEqual(S_UUID_1, jcom.sname(UUID_S1, UUID_1))

    def test_sname_from_snap(self):

        snap = copy.deepcopy(SNAPSHOT_GET)
        self.assertEqual(S_UUID_1, jcom.sname_from_snap(snap))

    def test_is_hidden(self):

        self.assertTrue(jcom.is_hidden(T_UUID_1))
        self.assertFalse(jcom.is_hidden(S_UUID_1))

    def test_origin_snapshot(self):

        vol = copy.deepcopy(VOLUME_GET_THAT_IS_CLONE)

        self.assertEqual(S_UUID_1, jcom.origin_snapshot(vol))

    def test_origin_volume(self):

        vol = copy.deepcopy(VOLUME_GET_THAT_IS_CLONE)

        self.assertEqual(V_UUID_1, jcom.origin_volume(vol))

    def test_snapshot_clones(self):

        clones = [V_UUID_2, V_UUID_3]
        snap = copy.deepcopy(SNAPSHOT_MULTIPLE_CLONES)
        self.assertEqual(clones, jcom.snapshot_clones(snap))

    def test_hidden(self):

        self.assertEqual(T_UUID_1, jcom.hidden(V_UUID_1))

    def test_get_newest_snapshot_name(self):
        snaps = copy.deepcopy(SNAPSHOTS_GET_NO_CLONES)

        self.assertEqual(S_UUID_2, jcom.get_newest_snapshot_name(snaps))
