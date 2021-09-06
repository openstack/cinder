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

import re
from unittest import mock

from oslo_utils import units as o_units

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.volume.drivers.open_e import iscsi
from cinder.volume.drivers.open_e.jovian_common import exception as jexc
from cinder.volume.drivers.open_e.jovian_common import jdss_common as jcom

UUID_1 = '12345678-1234-1234-1234-000000000001'
UUID_2 = '12345678-1234-1234-1234-000000000002'
UUID_3 = '12345678-1234-1234-1234-000000000003'
UUID_4 = '12345678-1234-1234-1234-000000000004'

CONFIG_OK = {
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
    'jovian_block_size': '128K'
}

CONFIG_BLOCK_SIZE = {
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
    'jovian_block_size': '64K'
}

CONFIG_BAD_BLOCK_SIZE = {
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

SNAPSHOTS_CASCADE_1 = [
    {"name": jcom.sname(UUID_1),
     "clones": "Pool-0/" + jcom.sname(UUID_1)},
    {"name": jcom.sname(UUID_2),
     "clones": "Pool-0/" + jcom.sname(UUID_2)},
    {"name": jcom.sname(UUID_3),
     "clones": "Pool-0/" + jcom.sname(UUID_3)}]

SNAPSHOTS_CASCADE_2 = [
    {"name": jcom.sname(UUID_1),
     "clones": "Pool-0/" + jcom.sname(UUID_1)},
    {"name": jcom.vname(UUID_2),
     "clones": "Pool-0/" + jcom.vname(UUID_2)},
    {"name": jcom.sname(UUID_3),
     "clones": "Pool-0/" + jcom.sname(UUID_3)}]

SNAPSHOTS_CASCADE_3 = [
    {"name": jcom.vname(UUID_4),
     "clones": "Pool-0/" + jcom.vname(UUID_4)}]

SNAPSHOTS_EMPTY = []

SNAPSHOTS_CLONE = [
    {"name": jcom.vname(UUID_1),
     "clones": "Pool-0/" + jcom.vname(UUID_1)}]

SNAPSHOTS_GARBAGE = [
    {"name": jcom.sname(UUID_1),
     "clones": "Pool-0/" + jcom.vname(UUID_2)},
    {"name": jcom.sname(UUID_2),
     "clones": ""}]

SNAPSHOTS_RECURSIVE_1 = [
    {"name": jcom.sname(UUID_1),
     "clones": "Pool-0/" + jcom.sname(UUID_1)},
    {"name": jcom.sname(UUID_2),
     "clones": "Pool-0/" + jcom.hidden(UUID_2)}]

SNAPSHOTS_RECURSIVE_CHAIN_1 = [
    {"name": jcom.sname(UUID_3),
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

    def get_driver(self, config):
        ctx = context.get_admin_context()

        cfg = mock.Mock()
        cfg.append_config_values.return_value = None
        cfg.get = lambda val, default: config.get(val, default)

        jdssd = iscsi.JovianISCSIDriver()

        jdssd.configuration = cfg
        lib_to_patch = ('cinder.volume.drivers.open_e.jovian_common.rest.'
                        'JovianRESTAPI')
        with mock.patch(lib_to_patch) as ra:
            ra.is_pool_exists.return_value = True
            jdssd.do_setup(ctx)
        jdssd.ra = mock.Mock()
        return jdssd, ctx

    def start_patches(self, patches):
        for p in patches:
            p.start()

    def stop_patches(self, patches):
        for p in patches:
            p.stop()

    def test_check_for_setup_error(self):

        cfg = mock.Mock()
        cfg.append_config_values.return_value = None

        jdssd = iscsi.JovianISCSIDriver()
        jdssd.configuration = cfg

        jdssd.ra = mock.Mock()

        # No IP
        jdssd.ra.is_pool_exists.return_value = True
        jdssd.jovian_hosts = []
        jdssd.block_size = ['64K']

        self.assertRaises(exception.VolumeDriverException,
                          jdssd.check_for_setup_error)

        # No pool detected
        jdssd.ra.is_pool_exists.return_value = False
        jdssd.jovian_hosts = ['192.168.0.2']
        jdssd.block_size = ['64K']

        self.assertRaises(exception.VolumeDriverException,
                          jdssd.check_for_setup_error)
        # Bad block size
        jdssd.ra.is_pool_exists.return_value = True
        jdssd.jovian_hosts = ['192.168.0.2', '192.168.0.3']
        jdssd.block_size = ['61K']

        self.assertRaises(exception.InvalidConfigurationValue,
                          jdssd.check_for_setup_error)

    def test_get_provider_location(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
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
        self.assertEqual(out, jdssd._get_provider_location(UUID_1))
        self.stop_patches(patches)

    def test_create_volume(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vol.size = 1
        host = CONFIG_OK["san_hosts"][0]
        port = CONFIG_OK["target_port"]

        target_name = CONFIG_OK["target_prefix"] + UUID_1

        jdssd.ra.create_lun.return_value = None
        jdssd.ra.get_active_host.return_value = host

        ret = jdssd.create_volume(vol)

        location = '{host}:{port},1 {name} 0'.format(
            host=host,
            port=port,
            name=target_name
        )
        self.assertEqual(location, ret['provider_location'])
        cred_format = (r"CHAP [0-9,a-z,A-Z]{{{name_len}}} "
                       "[0-9,a-z,A-Z]{{{pass_len}}}").format(
            name_len=8,
            pass_len=CONFIG_OK['chap_password_len'])
        self.assertIsNotNone(re.match(cred_format, ret['provider_auth']))

    def test_create_volume_small_block(self):

        jdssd, ctx = self.get_driver(CONFIG_BLOCK_SIZE)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vol.size = 1
        host = CONFIG_OK["san_hosts"][0]
        port = CONFIG_OK["target_port"]

        target_name = CONFIG_OK["target_prefix"] + UUID_1
        vname = jcom.vname(UUID_1)

        jdssd.ra.create_lun.return_value = None
        jdssd.ra.get_active_host.return_value = host

        ret = jdssd.create_volume(vol)

        jdssd.ra.create_lun.assert_called_once_with(
            vname, o_units.Gi, sparse=False, block_size="64K")

        location = '{host}:{port},1 {name} 0'.format(
            host=host,
            port=port,
            name=target_name
        )
        self.assertEqual(location, ret['provider_location'])
        cred_format = (r"CHAP [0-9,a-z,A-Z]{{{name_len}}} "
                       "[0-9,a-z,A-Z]{{{pass_len}}}").format(
            name_len=8,
            pass_len=CONFIG_OK['chap_password_len'])
        self.assertIsNotNone(re.match(cred_format, ret['provider_auth']))

    def test_hide_object(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        vname = jcom.vname(UUID_1)

        jdssd.ra.modify_lun.return_value = None
        jdssd._hide_object(vname)

        hidden_volume = {"name": jcom.hidden(UUID_1)}
        jdssd.ra.modify_lun.assert_called_once_with(vname, hidden_volume)

    def test_clean_garbage_snapshots(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        o_vname = jcom.vname(UUID_1)
        o_snaps = SNAPSHOTS_GARBAGE.copy()

        jdssd.ra.delete_snapshot.return_value = None
        jdssd._clean_garbage_snapshots(o_vname, o_snaps)
        jdssd.ra.delete_snapshot.assert_called_once_with(
            o_vname,
            SNAPSHOTS_GARBAGE[1]["name"])
        # Test exception handling
        for exc in get_jdss_exceptions():
            o_snaps = SNAPSHOTS_GARBAGE.copy()
            jdssd.ra.delete_snapshot.side_effect = exc
            try:
                jdssd._clean_garbage_snapshots(o_vname, o_snaps)
            except Exception as err:
                self.assertIsInstance(err, exception.VolumeBackendAPIException)

    def test_cascade_volume_delete_snapshots(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        o_vname = jcom.vname(UUID_1)

        # Volume with 3 snapshots and no descendants
        # We should delete snapshots and then cal for volume deletion
        o_snaps = SNAPSHOTS_CASCADE_1.copy()

        jdssd.ra.modify_lun.return_value = None
        jdssd.ra.delete_snapshot.return_value = None
        jdssd.ra.get_snapshots.side_effect = [
            SNAPSHOTS_EMPTY,
            SNAPSHOTS_EMPTY,
            SNAPSHOTS_EMPTY]

        with mock.patch.object(jdssd, "_gc_delete", return_value=None) as gc:
            jdssd._cascade_volume_delete(o_vname, o_snaps)
            gc.assert_called_once_with(o_vname)
        delete_snapshot_expected = [
            mock.call(o_vname,
                      SNAPSHOTS_CASCADE_1[0]["name"],
                      recursively_children=True,
                      recursively_dependents=True,
                      force_umount=True),
            mock.call(o_vname,
                      SNAPSHOTS_CASCADE_1[1]["name"],
                      recursively_children=True,
                      recursively_dependents=True,
                      force_umount=True),
            mock.call(o_vname,
                      SNAPSHOTS_CASCADE_1[2]["name"],
                      recursively_children=True,
                      recursively_dependents=True,
                      force_umount=True)]
        jdssd.ra.delete_snapshot.assert_has_calls(delete_snapshot_expected)

    def test_cascade_volume_delete_with_clone(self):
        # Volume with 2 snapshots and 1 clone
        # We should delete snapshots and then cal for volume hiding
        jdssd, ctx = self.get_driver(CONFIG_OK)
        o_vname = jcom.vname(UUID_1)
        o_snaps = SNAPSHOTS_CASCADE_2.copy()

        jdssd.ra.modify_lun.return_value = None
        jdssd.ra.delete_snapshot.return_value = None
        jdssd.ra.get_snapshots.side_effect = [
            SNAPSHOTS_EMPTY,
            SNAPSHOTS_EMPTY]

        patches = [mock.patch.object(jdssd, "_gc_delete"),
                   mock.patch.object(jdssd, "_hide_object")]

        self.start_patches(patches)

        jdssd._cascade_volume_delete(o_vname, o_snaps)

        jdssd._hide_object.assert_called_once_with(o_vname)
        jdssd._gc_delete.assert_not_called()

        self.stop_patches(patches)

        delete_snapshot_expected = [
            mock.call(o_vname,
                      SNAPSHOTS_CASCADE_2[0]["name"],
                      recursively_children=True,
                      recursively_dependents=True,
                      force_umount=True),
            mock.call(o_vname,
                      SNAPSHOTS_CASCADE_2[2]["name"],
                      recursively_children=True,
                      recursively_dependents=True,
                      force_umount=True)]
        jdssd.ra.delete_snapshot.assert_has_calls(delete_snapshot_expected)

    def test_cascade_volume_delete_snapshot_clone(self):
        # Volume with 3 snapshots and 1 clone of a snapshots
        # We should delete childless snapshots
        #           and then cal for volume deletion

        jdssd, ctx = self.get_driver(CONFIG_OK)
        o_vname = jcom.vname(UUID_1)
        o_snaps = SNAPSHOTS_CASCADE_1.copy()

        jdssd.ra.modify_lun.return_value = None
        jdssd.ra.delete_snapshot.return_value = None
        jdssd.ra.get_snapshots.side_effect = [
            SNAPSHOTS_EMPTY,
            SNAPSHOTS_CASCADE_3.copy(),
            SNAPSHOTS_EMPTY]
        get_snapshots = [
            mock.call(SNAPSHOTS_CASCADE_1[0]['name']),
            mock.call(SNAPSHOTS_CASCADE_1[1]['name']),
            mock.call(SNAPSHOTS_CASCADE_1[2]['name'])
        ]
        hide_object_expected = [
            mock.call(SNAPSHOTS_CASCADE_1[1]["name"]),
            mock.call(o_vname)]

        patches = [mock.patch.object(jdssd, "_gc_delete"),
                   mock.patch.object(jdssd, "_hide_object")]

        self.start_patches(patches)

        jdssd._cascade_volume_delete(o_vname, o_snaps)
        jdssd._hide_object.assert_has_calls(hide_object_expected)
        jdssd._gc_delete.assert_not_called()

        self.stop_patches(patches)

        jdssd.ra.get_snapshots.assert_has_calls(get_snapshots)

        delete_snapshot_expected = [
            mock.call(o_vname,
                      SNAPSHOTS_CASCADE_2[0]["name"],
                      recursively_children=True,
                      recursively_dependents=True,
                      force_umount=True),
            mock.call(o_vname,
                      SNAPSHOTS_CASCADE_2[2]["name"],
                      recursively_children=True,
                      recursively_dependents=True,
                      force_umount=True)]
        jdssd.ra.delete_snapshot.assert_has_calls(delete_snapshot_expected)

    def test_delete_volume_with_snapshots(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vname = jcom.vname(UUID_1)
        jdssd.ra.get_snapshots.side_effect = [SNAPSHOTS_CASCADE_1.copy()]

        patches = [mock.patch.object(jdssd, "_cascade_volume_delete"),
                   mock.patch.object(jdssd, "_gc_delete"),
                   mock.patch.object(jdssd, "_hide_object")]

        self.start_patches(patches)

        jdssd.delete_volume(vol, cascade=False)
        jdssd._gc_delete.assert_not_called()
        jdssd._cascade_volume_delete.assert_not_called()
        jdssd._hide_object.assert_called_once_with(vname)

        self.stop_patches(patches)

        jdssd.ra.get_snapshots.assert_called_once_with(vname)

    def test_delete_volume_without_snapshots(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vname = jcom.vname(UUID_1)
        jdssd.ra.get_snapshots.side_effect = [SNAPSHOTS_EMPTY.copy()]

        patches = [mock.patch.object(jdssd, "_cascade_volume_delete"),
                   mock.patch.object(jdssd, "_gc_delete"),
                   mock.patch.object(jdssd, "_hide_object")]

        self.start_patches(patches)

        jdssd.delete_volume(vol, cascade=False)
        jdssd._gc_delete.assert_called_once_with(vname)
        jdssd._cascade_volume_delete.assert_not_called()
        jdssd._hide_object.assert_not_called()

        self.stop_patches(patches)

        jdssd.ra.get_snapshots.assert_called_once_with(vname)

    def test_delete_volume_exceptions(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1

        patches = [mock.patch.object(jdssd, "_cascade_volume_delete"),
                   mock.patch.object(jdssd, "_gc_delete"),
                   mock.patch.object(jdssd, "_hide_object")]

        self.start_patches(patches)

        for exc in get_jdss_exceptions():
            jdssd.ra.get_snapshots.side_effect = exc
            try:
                jdssd.delete_volume(vol, cascade=False)
            except Exception as err:
                self.assertIsInstance(err, exception.VolumeBackendAPIException)

        jdssd._gc_delete.assert_not_called()
        jdssd._cascade_volume_delete.assert_not_called()
        jdssd._hide_object.assert_not_called()

        self.stop_patches(patches)

    def test_gc_delete_not_clone(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1

        get_lun_resp = {'vscan': None,
                        'full_name': 'Pool-0/' + jcom.vname(UUID_1),
                        'userrefs': None,
                        'primarycache': 'all',
                        'logbias': 'latency',
                        'creation': '1591543140',
                        'sync': 'always',
                        'is_clone': False,
                        'dedup': 'off',
                        'sharenfs': None,
                        'receive_resume_token': None,
                        'volsize': '1073741824'}

        jdssd.ra.get_lun.return_value = get_lun_resp
        jdssd.ra.delete_lun.return_value = None

        patches = [mock.patch.object(jdssd, "_delete_back_recursively")]

        self.start_patches(patches)

        jdssd._gc_delete(jcom.vname(UUID_1))

        jdssd._delete_back_recursively.assert_not_called()
        jdssd.ra.delete_lun.assert_called_once_with(jcom.vname(UUID_1),
                                                    force_umount=True)

        self.stop_patches(patches)

    def test_gc_delete_is_clone(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        origin = "Pool-0/{vorig}@{sorig}".format(vorig=jcom.vname(UUID_1),
                                                 sorig=jcom.vname(UUID_2))

        get_lun_resp = {'origin': origin,
                        'vscan': None,
                        'full_name': 'Pool-0/' + jcom.vname(UUID_2),
                        'userrefs': None,
                        'primarycache': 'all',
                        'logbias': 'latency',
                        'creation': '1591543140',
                        'sync': 'always',
                        'is_clone': True,
                        'dedup': 'off',
                        'sharenfs': None,
                        'receive_resume_token': None,
                        'volsize': '1073741824'}

        jdssd.ra.get_lun.return_value = get_lun_resp
        jdssd.ra.delete_lun.return_value = None

        patches = [mock.patch.object(jdssd, "_delete_back_recursively")]

        self.start_patches(patches)

        jdssd._gc_delete(jcom.vname(UUID_1))

        jdssd._delete_back_recursively.assert_called_once_with(
            jcom.vname(UUID_1), jcom.vname(UUID_2))
        jdssd.ra.delete_lun.assert_not_called()

        self.stop_patches(patches)

    def test_delete_back_recursively_res_active(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        opvname = jcom.vname(UUID_1)
        opsname = jcom.sname(UUID_2)

        jdssd._delete_back_recursively(opvname, opsname)

        jdssd.ra.delete_snapshot.assert_called_once_with(
            opvname,
            opsname,
            recursively_children=True,
            recursively_dependents=True,
            force_umount=True)

    def test_delete_back_recursively_hidden_have_snapshots(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        opvname = jcom.hidden(UUID_1)
        opsname = jcom.sname(UUID_2)

        jdssd.ra.get_snapshots.return_value = SNAPSHOTS_RECURSIVE_1.copy()

        jdssd._delete_back_recursively(opvname, opsname)

        jdssd.ra.delete_snapshot.assert_called_once_with(
            opvname,
            opsname,
            recursively_children=True,
            recursively_dependents=True,
            force_umount=True)

    def test_delete_back_recursively_single_snapshot(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        opvname = jcom.hidden(UUID_2)
        opsname = jcom.sname(UUID_3)

        jdssd.ra.get_snapshots.side_effect = [
            SNAPSHOTS_RECURSIVE_CHAIN_1.copy(),
            SNAPSHOTS_RECURSIVE_CHAIN_2.copy()]

        origin = "Pool-0/{vorig}@{sorig}".format(vorig=jcom.vname(UUID_1),
                                                 sorig=jcom.vname(UUID_2))
        get_lun_resp = {'origin': origin,
                        'vscan': None,
                        'full_name': 'Pool-0/' + jcom.hidden(UUID_2),
                        'userrefs': None,
                        'primarycache': 'all',
                        'logbias': 'latency',
                        'creation': '1591543140',
                        'sync': 'always',
                        'is_clone': True,
                        'dedup': 'off',
                        'sharenfs': None,
                        'receive_resume_token': None,
                        'volsize': '1073741824'}
        jdssd.ra.get_lun.return_value = get_lun_resp
        jdssd._delete_back_recursively(opvname, opsname)

        jdssd.ra.delete_snapshot.assert_called_once_with(
            jcom.vname(UUID_1),
            jcom.vname(UUID_2),
            recursively_children=True,
            recursively_dependents=True,
            force_umount=True)

        get_snapshots_expected = [mock.call(opvname)]
        jdssd.ra.get_snapshots.assert_has_calls(get_snapshots_expected)

    def test_extend_volume(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        jdssd.ra.extend_lun.return_value = None
        jdssd.extend_volume(vol, 2)

        jdssd.ra.extend_lun.assert_called_once_with(
            jcom.vname(UUID_1),
            2147483648)

    def test_extend_volume_exceptions(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1

        for exc in get_jdss_exceptions():
            try:
                jdssd.extend_volume(vol, 2)
            except Exception as err:
                self.assertIsInstance(err, exception.VolumeBackendAPIException)

    def test_revert_to_snapshot(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        snap = fake_snapshot.fake_snapshot_obj(ctx)
        snap.id = UUID_2

        vname = jcom.vname(UUID_1)
        sname = jcom.sname(UUID_2)

        get_lun_resp_1 = {'vscan': None,
                          'full_name': 'Pool-0/' + UUID_1,
                          'userrefs': None,
                          'primarycache': 'all',
                          'logbias': 'latency',
                          'creation': '1591543140',
                          'sync': 'always',
                          'is_clone': False,
                          'dedup': 'off',
                          'sharenfs': None,
                          'receive_resume_token': None,
                          'volsize': '2147483648'}

        get_lun_resp_2 = {'vscan': None,
                          'full_name': 'Pool-0/' + UUID_1,
                          'userrefs': None,
                          'primarycache': 'all',
                          'logbias': 'latency',
                          'creation': '1591543140',
                          'sync': 'always',
                          'is_clone': False,
                          'dedup': 'off',
                          'sharenfs': None,
                          'receive_resume_token': None,
                          'volsize': '1073741824'}

        jdssd.ra.get_lun.side_effect = [get_lun_resp_1, get_lun_resp_2]

        get_lun_expected = [mock.call(vname), mock.call(vname)]

        jdssd.revert_to_snapshot(ctx, vol, snap)

        jdssd.ra.get_lun.assert_has_calls(get_lun_expected)

        jdssd.ra.rollback_volume_to_snapshot.assert_called_once_with(vname,
                                                                     sname)
        jdssd.ra.extend_lun(vname, '2147483648')

    def test_revert_to_snapshot_exception(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        snap = fake_snapshot.fake_snapshot_obj(ctx)
        snap.id = UUID_2

        vname = jcom.vname(UUID_1)

        get_lun_resp_no_size = {'vscan': None,
                                'full_name': 'Pool-0/' + vname,
                                'userrefs': None,
                                'primarycache': 'all',
                                'logbias': 'latency',
                                'creation': '1591543140',
                                'sync': 'always',
                                'is_clone': False,
                                'dedup': 'off',
                                'sharenfs': None,
                                'receive_resume_token': None,
                                'volsize': None}

        get_lun_resp_1 = {'vscan': None,
                          'full_name': 'Pool-0/' + vname,
                          'userrefs': None,
                          'primarycache': 'all',
                          'logbias': 'latency',
                          'creation': '1591543140',
                          'sync': 'always',
                          'is_clone': False,
                          'dedup': 'off',
                          'sharenfs': None,
                          'receive_resume_token': None,
                          'volsize': '2147483648'}

        get_lun_resp_2 = {'vscan': None,
                          'full_name': 'Pool-0/' + vname,
                          'userrefs': None,
                          'primarycache': 'all',
                          'logbias': 'latency',
                          'creation': '1591543140',
                          'sync': 'always',
                          'is_clone': False,
                          'dedup': 'off',
                          'sharenfs': None,
                          'receive_resume_token': None,
                          'volsize': '1073741824'}

        jdssd.ra.get_lun.side_effect = [get_lun_resp_no_size, get_lun_resp_2]

        self.assertRaises(exception.VolumeDriverException,
                          jdssd.revert_to_snapshot,
                          ctx,
                          vol,
                          snap)

        jdssd.ra.get_lun.side_effect = [get_lun_resp_1, get_lun_resp_2]

        jdssd.ra.rollback_volume_to_snapshot.side_effect = [
            jexc.JDSSResourceNotFoundException(res=vname)]
        self.assertRaises(exception.VolumeBackendAPIException,
                          jdssd.revert_to_snapshot,
                          ctx,
                          vol,
                          snap)

        jdssd.ra.get_lun.side_effect = [get_lun_resp_1,
                                        jexc.JDSSException("some_error")]

        jdssd.ra.rollback_volume_to_snapshot.side_effect = [
            jexc.JDSSResourceNotFoundException(res=vname)]
        self.assertRaises(exception.VolumeBackendAPIException,
                          jdssd.revert_to_snapshot,
                          ctx,
                          vol,
                          snap)

    def test_clone_object(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        origin = jcom.vname(UUID_1)
        clone = jcom.vname(UUID_2)

        jdssd.ra.create_snapshot.return_value = None
        jdssd.ra.create_volume_from_snapshot.return_value = None

        jdssd._clone_object(origin, clone)
        jdssd.ra.create_snapshot.assert_called_once_with(origin, clone)
        jdssd.ra.create_volume_from_snapshot.assert_called_once_with(
            clone,
            clone,
            origin,
            sparse=False)

    def test_clone_object_dne(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)
        calls = []
        origin = jcom.vname(UUID_1)
        clone = jcom.vname(UUID_2)
        calls.append(mock.call(origin, clone))

        jdssd.ra.create_snapshot.side_effect = (
            jexc.JDSSResourceNotFoundException(res=origin))

        self.assertRaises(exception.VolumeNotFound,
                          jdssd._clone_object, origin, clone)

        origin = jcom.sname(UUID_1)
        calls.append(mock.call(origin, clone))

        self.assertRaises(exception.SnapshotNotFound,
                          jdssd._clone_object, origin, clone)
        jdssd.ra.create_snapshot.assert_has_calls(calls)

    def test_clone_object_exists(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        origin = jcom.vname(UUID_1)
        clone = jcom.vname(UUID_2)

        jdssd.ra.create_snapshot.side_effect = (
            jexc.JDSSSnapshotExistsException(snapshot=clone))

        jdssd.ra.delete_snapshot.side_effect = (
            jexc.JDSSSnapshotIsBusyException(snapshot=clone))

        self.assertRaises(exception.Duplicate,
                          jdssd._clone_object, origin, clone)
        jdssd.ra.delete_snapshot.assert_called_once_with(origin, clone)
        jdssd.ra.create_snapshot.assert_called_once_with(origin, clone)

    def test_clone_object_volume_exists(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        origin = jcom.vname(UUID_1)
        clone = jcom.vname(UUID_2)

        jdssd.ra.create_snapshot.return_value = None
        jdssd.ra.create_volume_from_snapshot.side_effect = (
            jexc.JDSSVolumeExistsException(volume=clone))

        self.assertRaises(exception.Duplicate,
                          jdssd._clone_object, origin, clone)
        jdssd.ra.create_snapshot.assert_called_once_with(origin, clone)
        jdssd.ra.create_volume_from_snapshot.assert_called_once_with(
            clone,
            clone,
            origin,
            sparse=CONFIG_OK['san_thin_provision'])

    def test_create_cloned_volume(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        origin_vname = jcom.vname(UUID_1)
        clone_vname = jcom.vname(UUID_2)

        orig_vol = fake_volume.fake_volume_obj(ctx)
        orig_vol.id = UUID_1
        orig_vol.size = 1

        clone_vol = fake_volume.fake_volume_obj(ctx)
        clone_vol.id = UUID_2
        clone_vol.size = 1

        host = CONFIG_OK["san_hosts"][0]
        port = CONFIG_OK["target_port"]
        target_name = CONFIG_OK["target_prefix"] + UUID_2

        location = '{host}:{port},1 {name} 0'.format(
            host=host,
            port=port,
            name=target_name
        )

        cred_format = (r"CHAP [0-9,a-z,A-Z]{{{name_len}}} "
                       "[0-9,a-z,A-Z]{{{pass_len}}}").format(
            name_len=8,
            pass_len=CONFIG_OK['chap_password_len'])

        patches = [
            mock.patch.object(jdssd, "_clone_object", return_value=None),
            mock.patch.object(jdssd, "extend_volume", return_value=None),
            mock.patch.object(
                jdssd,
                "_get_provider_location",
                return_value=location),
            mock.patch.object(
                jdssd,
                "_get_provider_auth",
                return_value=cred_format)]

        jdssd.ra.get_lun.return_value = {
            'vscan': None,
            'full_name': 'Pool-0/' + UUID_2,
            'userrefs': None,
            'primarycache': 'all',
            'logbias': 'latency',
            'creation': '1591543140',
            'sync': 'always',
            'is_clone': False,
            'dedup': 'off',
            'sharenfs': None,
            'receive_resume_token': None,
            'volsize': '1073741824'}

        self.start_patches(patches)

        ret = jdssd.create_cloned_volume(clone_vol, orig_vol)

        jdssd.extend_volume.assert_not_called()
        jdssd._clone_object.assert_called_once_with(origin_vname, clone_vname)
        self.stop_patches(patches)

        jdssd.ra.get_lun.assert_called_once_with(jcom.vname(clone_vol.id))
        self.assertEqual(location, ret['provider_location'])
        self.assertEqual(cred_format, ret['provider_auth'])

    def test_create_volume_from_snapshot(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        origin_sname = jcom.sname(UUID_1)

        clone_vname = jcom.vname(UUID_2)

        orig_snap = fake_snapshot.fake_snapshot_obj(ctx)
        orig_snap.id = UUID_1

        clone_vol = fake_volume.fake_volume_obj(ctx)
        clone_vol.id = UUID_2
        clone_vol.size = 1

        host = CONFIG_OK["san_hosts"][0]
        port = CONFIG_OK["target_port"]
        target_name = CONFIG_OK["target_prefix"] + UUID_2

        location = '{host}:{port},1 {name} 0'.format(
            host=host,
            port=port,
            name=target_name
        )

        cred_format = (r"CHAP [0-9,a-z,A-Z]{{{name_len}}} "
                       "[0-9,a-z,A-Z]{{{pass_len}}}").format(
            name_len=8,
            pass_len=CONFIG_OK['chap_password_len'])

        patches = [
            mock.patch.object(jdssd, "_clone_object", return_value=None),
            mock.patch.object(jdssd, "extend_volume", return_value=None),
            mock.patch.object(
                jdssd,
                "_get_provider_location",
                return_value=location),
            mock.patch.object(
                jdssd,
                "_get_provider_auth",
                return_value=cred_format)]

        jdssd.ra.get_lun.return_value = {
            'vscan': None,
            'full_name': 'Pool-0/' + UUID_2,
            'userrefs': None,
            'primarycache': 'all',
            'logbias': 'latency',
            'creation': '1591543140',
            'sync': 'always',
            'is_clone': False,
            'dedup': 'off',
            'sharenfs': None,
            'receive_resume_token': None,
            'volsize': '1073741824'}

        self.start_patches(patches)

        ret = jdssd.create_volume_from_snapshot(clone_vol, orig_snap)

        jdssd.extend_volume.assert_not_called()
        jdssd._clone_object.assert_called_once_with(origin_sname, clone_vname)
        self.stop_patches(patches)

        jdssd.ra.get_lun.assert_called_once_with(jcom.vname(clone_vol.id))
        self.assertEqual(location, ret['provider_location'])
        self.assertEqual(cred_format, ret['provider_auth'])

    def test_create_volume_from_snapshot_extend(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        origin_sname = jcom.sname(UUID_1)

        clone_vname = jcom.vname(UUID_2)

        orig_snap = fake_snapshot.fake_snapshot_obj(ctx)
        orig_snap.id = UUID_1

        clone_vol = fake_volume.fake_volume_obj(ctx)
        clone_vol.id = UUID_2
        clone_vol.size = 2

        host = CONFIG_OK["san_hosts"][0]
        port = CONFIG_OK["target_port"]
        target_name = CONFIG_OK["target_prefix"] + UUID_2

        location = '{host}:{port},1 {name} 0'.format(
            host=host,
            port=port,
            name=target_name
        )

        cred_format = (r"CHAP [0-9,a-z,A-Z]{{{name_len}}} "
                       "[0-9,a-z,A-Z]{{{pass_len}}}").format(
            name_len=8,
            pass_len=CONFIG_OK['chap_password_len'])

        patches = [
            mock.patch.object(jdssd, "_clone_object", return_value=None),
            mock.patch.object(jdssd, "extend_volume", return_value=None),
            mock.patch.object(
                jdssd,
                "_get_provider_location",
                return_value=location),
            mock.patch.object(
                jdssd,
                "_get_provider_auth",
                return_value=cred_format)]

        jdssd.ra.get_lun.return_value = {
            'vscan': None,
            'full_name': 'Pool-0/' + UUID_2,
            'userrefs': None,
            'primarycache': 'all',
            'logbias': 'latency',
            'creation': '1591543140',
            'sync': 'always',
            'is_clone': False,
            'dedup': 'off',
            'sharenfs': None,
            'receive_resume_token': None,
            'volsize': '1073741824'}

        self.start_patches(patches)

        ret = jdssd.create_volume_from_snapshot(clone_vol, orig_snap)

        jdssd.extend_volume.assert_called_once_with(clone_vol, clone_vol.size)
        jdssd._clone_object.assert_called_once_with(origin_sname, clone_vname)
        self.stop_patches(patches)

        jdssd.ra.get_lun.assert_called_once_with(jcom.vname(clone_vol.id))
        self.assertEqual(location, ret['provider_location'])
        self.assertEqual(cred_format, ret['provider_auth'])

    def test_create_snapshot(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        vname = jcom.vname(UUID_1)

        sname = jcom.sname(UUID_2)

        snap = fake_snapshot.fake_snapshot_obj(ctx, id=UUID_2)
        snap.volume_id = UUID_1

        patches = [
            mock.patch.object(jdssd, "_clone_object", return_value=None)]

        self.start_patches(patches)

        jdssd.create_snapshot(snap)

        jdssd._clone_object.assert_called_once_with(vname, sname)
        self.stop_patches(patches)

    def test_delete_snapshot_no_child(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        sname = jcom.sname(UUID_2)

        snap = fake_snapshot.fake_snapshot_obj(ctx, id=UUID_2)

        jdssd.ra.get_snapshots.return_value = SNAPSHOTS_EMPTY
        patches = [
            mock.patch.object(
                jdssd,
                "_clean_garbage_snapshots",
                return_value=SNAPSHOTS_EMPTY),
            mock.patch.object(jdssd, "_clone_object", return_value=None),
            mock.patch.object(jdssd, "_hide_object", return_value=None),
            mock.patch.object(jdssd, "_gc_delete", return_value=None)]

        self.start_patches(patches)

        jdssd.create_snapshot(snap)

        jdssd.delete_snapshot(snap)
        jdssd._gc_delete.assert_called_once_with(sname)
        jdssd._hide_object.assert_not_called()
        jdssd._clean_garbage_snapshots.assert_called_once_with(
            sname,
            SNAPSHOTS_EMPTY)
        self.stop_patches(patches)

    def test_delete_snapshot_has_clone(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        sname = jcom.sname(UUID_2)

        snap = fake_snapshot.fake_snapshot_obj(ctx, id=UUID_2)

        jdssd.ra.get_snapshots.return_value = SNAPSHOTS_EMPTY
        patches = [
            mock.patch.object(
                jdssd,
                "_clean_garbage_snapshots",
                return_value=SNAPSHOTS_CLONE),
            mock.patch.object(jdssd, "_clone_object", return_value=None),
            mock.patch.object(jdssd, "_hide_object", return_value=None),
            mock.patch.object(jdssd, "_gc_delete", return_value=None)]

        self.start_patches(patches)

        jdssd.create_snapshot(snap)

        jdssd.delete_snapshot(snap)
        jdssd._gc_delete.assert_not_called()
        jdssd._hide_object.assert_called_once_with(sname)
        jdssd._clean_garbage_snapshots.assert_called_once_with(
            sname,
            SNAPSHOTS_EMPTY)
        self.stop_patches(patches)

    def test_local_path(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_snapshot.fake_snapshot_obj(ctx, id=UUID_1)

        self.assertRaises(NotImplementedError, jdssd.local_path, vol)

    def test_get_provider_auth(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        auth = jdssd._get_provider_auth()
        cred_format = (r"CHAP [0-9,a-z,A-Z]{{{name_len}}} "
                       "[0-9,a-z,A-Z]{{{pass_len}}}").format(
            name_len=8,
            pass_len=CONFIG_OK['chap_password_len'])
        self.assertIsNotNone(re.match(cred_format, auth))

    def test_get_provider_auth_long(self):
        long_pass_config = CONFIG_OK.copy()
        long_pass_config['chap_password_len'] = 16
        jdssd, ctx = self.get_driver(long_pass_config)

        auth = jdssd._get_provider_auth()
        cred_format = (r"CHAP [0-9,a-z,A-Z]{{{name_len}}} "
                       "[0-9,a-z,A-Z]{{{pass_len}}}").format(
            name_len=8,
            pass_len=16)
        self.assertIsNotNone(re.match(cred_format, auth))

    def test_create_export(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1

        patches = [
            mock.patch.object(
                jdssd,
                "_ensure_target_volume",
                return_value=None),
            mock.patch.object(
                jdssd,
                "_get_provider_location",
                return_value='provider_location')]

        self.start_patches(patches)

        ret = jdssd.create_export(ctx, vol, "connector")
        jdssd._ensure_target_volume.assert_called_once_with(vol)

        self.stop_patches(patches)

        self.assertEqual('provider_location', ret["provider_location"])

    def test_ensure_export(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1

        patches = [
            mock.patch.object(
                jdssd,
                "_ensure_target_volume",
                return_value=None)]

        self.start_patches(patches)

        jdssd.ensure_export(ctx, vol)
        jdssd._ensure_target_volume.assert_called_once_with(vol)

        self.stop_patches(patches)

    def test_remove_export(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)
        vol = fake_volume.fake_volume_obj(ctx, id=UUID_1)

        patches = [
            mock.patch.object(
                jdssd,
                "_remove_target_volume",
                return_value=None)]

        self.start_patches(patches)

        jdssd.remove_export(ctx, vol)
        jdssd._remove_target_volume.assert_called_once_with(vol)

        self.stop_patches(patches)

    def test_update_volume_stats(self):
        jdssd, ctx = self.get_driver(CONFIG_BACKEND_NAME)

        location_info = 'JovianISCSIDriver:192.168.0.2:Pool-0'
        correct_out = {
            'vendor_name': 'Open-E',
            'driver_version': "1.0.2",
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': 100,
            'free_capacity_gb': 50,
            'reserved_percentage': 10,
            'volume_backend_name': CONFIG_BACKEND_NAME['volume_backend_name'],
            'QoS_support': False,
            'location_info': location_info,
            'multiattach': True
        }
        jdssd.ra.get_pool_stats.return_value = {
            'size': 100 * o_units.Gi,
            'available': 50 * o_units.Gi}
        jdssd.ra.get_active_host.return_value = CONFIG_OK['san_hosts']
        jdssd._update_volume_stats()

        self.assertEqual(correct_out, jdssd._stats)

    def test_create_target(self):

        jdssd, ctx = self.get_driver(CONFIG_BACKEND_NAME)

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        jdssd.ra.create_target.return_value = None
        jdssd._create_target(target_name, use_chap=True)

        jdssd.ra.create_target.assert_called_once_with(
            target_name, use_chap=True)

        jdssd.ra.create_target.side_effect = jexc.JDSSResourceExistsException(
            res=target_name)

        self.assertRaises(exception.Duplicate,
                          jdssd._create_target,
                          target_name,
                          use_chap=True)

    def test_attach_target_volume(self):

        jdssd, ctx = self.get_driver(CONFIG_BACKEND_NAME)

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

        self.assertRaises(exception.VolumeBackendAPIException,
                          jdssd._attach_target_volume,
                          target_name,
                          vname)
        jdssd.ra.delete_target.assert_called_once_with(target_name)

    def test_set_target_credentials(self):
        jdssd, ctx = self.get_driver(CONFIG_BACKEND_NAME)

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

        self.assertRaises(exception.VolumeBackendAPIException,
                          jdssd._set_target_credentials,
                          target_name,
                          cred)
        jdssd.ra.delete_target.assert_called_once_with(target_name)

    def test_create_target_volume(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        target_name = CONFIG_OK['target_prefix'] + UUID_1
        vol.provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name', 'password': '123456789012'}

        patches = [
            mock.patch.object(jdssd, "_create_target"),
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials")]

        self.start_patches(patches)
        jdssd._create_target_volume(vol)
        jdssd._create_target.assert_called_once_with(target_name, True)
        jdssd._attach_target_volume.assert_called_once_with(
            target_name, jcom.vname(UUID_1))
        jdssd._set_target_credentials.assert_called_once_with(
            target_name, cred)
        self.stop_patches(patches)

    def test_ensure_target_volume(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vname = jcom.vname(UUID_1)

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        vol.provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name'}

        patches = [
            mock.patch.object(jdssd, "_create_target"),
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials"),
            mock.patch.object(jdssd, "_attach_target_volume")]

        jdssd.ra.is_target.return_value = True
        jdssd.ra.is_target_lun.return_value = True
        jdssd.ra.get_target_user.return_value = [cred]

        self.start_patches(patches)

        jdssd._ensure_target_volume(vol)

        jdssd.ra.is_target.assert_called_once_with(target_name)

        jdssd.ra.is_target_lun.assert_called_once_with(target_name, vname)

        jdssd.ra.get_target_user.assert_called_once_with(target_name)

        jdssd.ra.delete_target_user.assert_not_called()
        jdssd._set_target_credentials.assert_not_called()
        self.stop_patches(patches)

    def test_ensure_target_volume_not_attached(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vname = jcom.vname(UUID_1)
        target_name = CONFIG_OK['target_prefix'] + UUID_1
        vol.provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name'}

        patches = [
            mock.patch.object(jdssd, "_create_target"),
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials"),
            mock.patch.object(jdssd, "_attach_target_volume")]

        jdssd.ra.is_target.return_value = True
        jdssd.ra.is_target_lun.return_value = False
        jdssd.ra.get_target_user.return_value = [cred]

        self.start_patches(patches)

        jdssd._ensure_target_volume(vol)

        jdssd.ra.is_target.assert_called_once_with(target_name)
        jdssd.ra.is_target_lun.assert_called_once_with(target_name, vname)

        jdssd._attach_target_volume.assert_called_once_with(
            target_name, vname)
        jdssd.ra.get_target_user.assert_called_once_with(target_name)

        jdssd.ra.delete_target_user.assert_not_called()
        jdssd._set_target_credentials.assert_not_called()
        self.stop_patches(patches)

    def test_ensure_target_volume_no_target(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        target_name = CONFIG_OK['target_prefix'] + UUID_1
        vol.provider_auth = 'chap user_name 123456789012'

        cred = {'name': 'user_name'}

        patches = [
            mock.patch.object(jdssd, "_create_target_volume"),
            mock.patch.object(jdssd, "_attach_target_volume"),
            mock.patch.object(jdssd, "_set_target_credentials"),
            mock.patch.object(jdssd, "_attach_target_volume")]

        jdssd.ra.is_target.return_value = False
        jdssd.ra.get_target_user.return_value = cred['name']

        self.start_patches(patches)

        jdssd._ensure_target_volume(vol)

        jdssd.ra.is_target.assert_called_once_with(target_name)
        jdssd._create_target_volume.assert_called_once_with(vol)

        jdssd.ra.is_target_lun.assert_not_called()
        self.stop_patches(patches)

    def test_remove_target_volume(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        target_name = CONFIG_OK['target_prefix'] + UUID_1

        jdssd.ra.detach_target_vol.return_value = None
        jdssd.ra.delete_target.return_value = None

        jdssd._remove_target_volume(vol)

        jdssd.ra.detach_target_vol.assert_called_once_with(target_name,
                                                           jcom.vname(UUID_1))
        jdssd.ra.delete_target.assert_called_with(target_name)

    def test_remove_target_volume_no_target(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        target_name = CONFIG_OK['target_prefix'] + UUID_1

        jdssd.ra.detach_target_vol.return_value = None
        jdssd.ra.detach_target_vol.side_effect = (
            jexc.JDSSResourceNotFoundException(res=target_name))
        jdssd.ra.delete_target.return_value = None

        jdssd._remove_target_volume(vol)

        jdssd.ra.detach_target_vol.assert_called_once_with(target_name,
                                                           jcom.vname(UUID_1))
        jdssd.ra.delete_target.assert_called_with(target_name)

    def test_remove_target_volume_fail_to_detach(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        target_name = CONFIG_OK['target_prefix'] + UUID_1

        jdssd.ra.detach_target_vol.side_effect = (
            jexc.JDSSRESTException(reason='running test', request='test'))
        jdssd.ra.delete_target.return_value = None

        self.assertRaises(exception.VolumeBackendAPIException,
                          jdssd._remove_target_volume, vol)

        jdssd.ra.detach_target_vol.assert_called_once_with(
            target_name, jcom.vname(UUID_1))
        jdssd.ra.delete_target.assert_not_called()

    def test_remove_target_volume_fail_to_delete(self):

        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        target_name = CONFIG_OK['target_prefix'] + UUID_1

        jdssd.ra.detach_target_vol.return_value = None
        jdssd.ra.delete_target.side_effect = (
            jexc.JDSSRESTException(reason='running test', request='test'))

        self.assertRaises(exception.VolumeBackendAPIException,
                          jdssd._remove_target_volume, vol)

        jdssd.ra.detach_target_vol.assert_called_once_with(target_name,
                                                           jcom.vname(UUID_1))
        jdssd.ra.delete_target.assert_called_with(target_name)

    def test_get_iscsi_properties(self):
        jdssd, ctx = self.get_driver(CONFIG_OK)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vol.provider_auth = 'chap user_name 123456789012'

        connector = {'multipath': True}

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        ret = jdssd._get_iscsi_properties(vol, connector)
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
        jdssd, ctx = self.get_driver(CONFIG_MULTI_HOST)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vol.provider_auth = 'chap user_name 123456789012'

        connector = {'multipath': True}

        target_name = CONFIG_OK['target_prefix'] + UUID_1
        ret = jdssd._get_iscsi_properties(vol, connector)
        expected = {'auth_method': 'chap',
                    'auth_password': '123456789012',
                    'auth_username': 'user_name',
                    'target_discovered': False,
                    'target_iqns': [target_name, target_name],
                    'target_lun': 0,
                    'target_luns': [0, 0],
                    'target_portals': ['192.168.0.2:3260', '192.168.0.3:3260']}
        self.assertEqual(expected, ret)

    def test_initialize_connection(self):

        jdssd, ctx = self.get_driver(CONFIG_MULTI_HOST)

        vol = fake_volume.fake_volume_obj(ctx)
        vol.id = UUID_1
        vol.provider_auth = 'chap user_name 123456789012'

        connector = {'multipath': True, 'ip': '172.16.0.2'}

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

        ret = jdssd.initialize_connection(vol, connector)

        self.assertEqual(con_info, ret)
