# Copyright (c) 2014 LINBIT HA Solutions GmbH
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

import collections

import mock
from oslo_utils import importutils
from oslo_utils import timeutils

from cinder import context
from cinder import test
from cinder.volume import configuration as conf


class mock_dbus(object):
    def __init__(self):
        pass

    @staticmethod
    def Array(defaults, signature=None):
        return defaults


class mock_dm_utils(object):

    @staticmethod
    def dict_to_aux_props(x):
        return x


class mock_dm_const(object):

    TQ_GET_PATH = "get_path"


class mock_dm_exc(object):

    DM_SUCCESS = 0
    DM_EEXIST = 1
    DM_ENOENT = 2
    DM_ERROR = 1000

    pass


import sys
sys.modules['dbus'] = mock_dbus
sys.modules['drbdmanage'] = collections.namedtuple(
    'module', ['consts', 'exceptions', 'utils'])
sys.modules['drbdmanage.utils'] = collections.namedtuple(
    'module', ['dict_to_aux_props'])
sys.modules['drbdmanage.consts'] = collections.namedtuple(
    'module', [])
sys.modules['drbdmanage.exceptions'] = collections.namedtuple(
    'module', ['DM_EEXIST'])


from cinder.volume.drivers import drbdmanagedrv


def create_configuration(object):
    configuration = mock.MockObject(conf.Configuration)
    configuration.san_is_local = False
    configuration.append_config_values(mock.IgnoreArg())
    return configuration


class DrbdManageFakeDriver(object):

    resources = {}

    def __init__(self):
        self.calls = []

    def list_resources(self, res, serial, prop, req):
        self.calls.append(["list_resources", res, prop, req])
        if 'cinder-id' in prop and prop['cinder-id'].startswith("deadbeef"):
            return ([[mock_dm_exc.DM_ENOENT, "none", []]],
                    [])
        else:
            return ([[mock_dm_exc.DM_SUCCESS, "ACK", []]],
                    [("res", dict(prop))])

    def create_resource(self, res, props):
        self.calls.append(["create_resource", res, props])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []]]

    def create_volume(self, res, size, props):
        self.calls.append(["create_volume", res, size, props])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []]]

    def auto_deploy(self, res, red, delta, site_clients):
        self.calls.append(["auto_deploy", res, red, delta, site_clients])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []] * red]

    def list_volumes(self, res, ser, prop, req):
        self.calls.append(["list_volumes", res, ser, prop, req])
        if 'cinder-id' in prop and prop['cinder-id'].startswith("deadbeef"):
            return ([[mock_dm_exc.DM_SUCCESS, "none", []]],
                    [])
        else:
            return ([[mock_dm_exc.DM_SUCCESS, "ACK", []]],
                    [("res", dict(), [(2, dict(prop))])
                     ])

    def remove_volume(self, res, nr, force):
        self.calls.append(["remove_volume", res, nr, force])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []]]

    def text_query(self, cmd):
        self.calls.append(["text_query", cmd])
        if cmd[0] == mock_dm_const.TQ_GET_PATH:
            return ([(mock_dm_exc.DM_SUCCESS, "ack", [])], ['/dev/drbd0'])
        return ([(mock_dm_exc.DM_ERROR, 'unknown command', [])], [])

    def list_assignments(self, nodes, res, ser, prop, req):
        self.calls.append(["list_assignments", nodes, res, ser, prop, req])
        if 'cinder-id' in prop and prop['cinder-id'].startswith("deadbeef"):
            return ([[mock_dm_exc.DM_SUCCESS, "none", []]],
                    [])
        else:
            return ([[mock_dm_exc.DM_SUCCESS, "ACK", []]],
                    [("node", "res", dict(), [(2, dict(prop))])
                     ])

    def create_snapshot(self, res, snap, nodes, props):
        self.calls.append(["create_snapshot", res, snap, nodes, props])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []]]

    def list_snapshots(self, res, sn, serial, prop, req):
        self.calls.append(["list_snapshots", res, sn, serial, prop, req])
        if 'cinder-id' in prop and prop['cinder-id'].startswith("deadbeef"):
            return ([[mock_dm_exc.DM_SUCCESS, "none", []]],
                    [])
        else:
            return ([[mock_dm_exc.DM_SUCCESS, "ACK", []]],
                    [("res", [("snap", dict(prop))])
                     ])

    def remove_snapshot(self, res, snap, force):
        self.calls.append(["remove_snapshot", res, snap, force])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []]]

    def resize_volume(self, res, vol, ser, size, delta):
        self.calls.append(["resize_volume", res, vol, ser, size, delta])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []]]

    def restore_snapshot(self, res, snap, new, rprop, vprops):
        self.calls.append(["restore_snapshot", res, snap, new, rprop, vprops])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []]]

    def assign(self, host, resource, props):
        self.calls.append(["assign", host, resource, props])
        return [[mock_dm_exc.DM_SUCCESS, "ack", []]]


class DrbdManageTestCase(test.TestCase):

    def setUp(self):
        self.ctxt = context.get_admin_context()
        self._mock = mock.Mock()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.san_is_local = True
        self.configuration.reserved_percentage = 1

        super(DrbdManageTestCase, self).setUp()

        self.stubs.Set(importutils, 'import_object',
                       self.fake_import_object)
        self.stubs.Set(drbdmanagedrv.DrbdManageDriver,
                       'call_or_reconnect',
                       self.fake_issue_dbus_call)
        self.stubs.Set(drbdmanagedrv.DrbdManageDriver,
                       'dbus_connect',
                       self.fake_issue_dbus_connect)

        sys.modules['cinder.volume.drivers.drbdmanagedrv'].dm_const \
            = mock_dm_const
        sys.modules['cinder.volume.drivers.drbdmanagedrv'].dm_utils \
            = mock_dm_utils
        sys.modules['cinder.volume.drivers.drbdmanagedrv'].dm_exc \
            = mock_dm_exc

        self.configuration.safe_get = lambda x: 'fake'

    # Infrastructure
    def fake_import_object(self, what, configuration, db, executor):
        return None

    def fake_issue_dbus_call(self, fn, *args):
        return fn(*args)

    def fake_issue_dbus_connect(self):
        self.odm = DrbdManageFakeDriver()

    def call_or_reconnect(self, method, *params):
        return method(*params)

    # Tests per se

    def test_create_volume(self):
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'deadbeef-8068-11e4-98c0-5254008ea111',
                   'volume_type_id': 'drbdmanage',
                   'created_at': timeutils.utcnow()}

        dmd = drbdmanagedrv.DrbdManageDriver(configuration=self.configuration)
        dmd.drbdmanage_devs_on_controller = False
        dmd.odm = DrbdManageFakeDriver()
        dmd.create_volume(testvol)
        self.assertEqual("create_resource", dmd.odm.calls[0][0])
        self.assertEqual("list_volumes", dmd.odm.calls[1][0])
        self.assertEqual("create_volume", dmd.odm.calls[2][0])
        self.assertEqual(1048576, dmd.odm.calls[2][2])
        self.assertEqual("auto_deploy", dmd.odm.calls[3][0])
        self.assertEqual(len(dmd.odm.calls), 4)

    def test_create_volume_controller_all_vols(self):
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'deadbeef-8068-11e4-98c0-5254008ea111',
                   'volume_type_id': 'drbdmanage',
                   'created_at': timeutils.utcnow()}

        dmd = drbdmanagedrv.DrbdManageDriver(configuration=self.configuration)
        dmd.drbdmanage_devs_on_controller = True
        dmd.odm = DrbdManageFakeDriver()
        dmd.create_volume(testvol)
        self.assertEqual("create_resource", dmd.odm.calls[0][0])
        self.assertEqual("list_volumes", dmd.odm.calls[1][0])
        self.assertEqual("create_volume", dmd.odm.calls[2][0])
        self.assertEqual(1048576, dmd.odm.calls[2][2])
        self.assertEqual("auto_deploy", dmd.odm.calls[3][0])
        self.assertEqual("assign", dmd.odm.calls[4][0])
        self.assertEqual(len(dmd.odm.calls), 5)

    def test_delete_volume(self):
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'ba253fd0-8068-11e4-98c0-5254008ea111',
                   'volume_type_id': 'drbdmanage',
                   'created_at': timeutils.utcnow()}

        dmd = drbdmanagedrv.DrbdManageDriver(configuration=self.configuration)
        dmd.odm = DrbdManageFakeDriver()
        dmd.delete_volume(testvol)
        self.assertEqual("list_volumes", dmd.odm.calls[0][0])
        self.assertEqual(testvol['id'], dmd.odm.calls[0][3]["cinder-id"])
        self.assertEqual("remove_volume", dmd.odm.calls[1][0])

    def test_local_path(self):
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'ba253fd0-8068-11e4-98c0-5254008ea111',
                   'volume_type_id': 'drbdmanage',
                   'created_at': timeutils.utcnow()}

        dmd = drbdmanagedrv.DrbdManageDriver(configuration=self.configuration)
        dmd.odm = DrbdManageFakeDriver()
        data = dmd.local_path(testvol)
        self.assertTrue(data.startswith("/dev/drbd"))

    def test_create_snapshot(self):
        testsnap = {'id': 'ca253fd0-8068-11e4-98c0-5254008ea111',
                    'volume_id': 'ba253fd0-8068-11e4-98c0-5254008ea111'}

        dmd = drbdmanagedrv.DrbdManageDriver(configuration=self.configuration)
        dmd.odm = DrbdManageFakeDriver()
        dmd.create_snapshot(testsnap)
        self.assertEqual("list_volumes", dmd.odm.calls[0][0])
        self.assertEqual("list_assignments", dmd.odm.calls[1][0])
        self.assertEqual("create_snapshot", dmd.odm.calls[2][0])
        self.assertTrue('node' in dmd.odm.calls[2][3])

    def test_delete_snapshot(self):
        testsnap = {'id': 'ca253fd0-8068-11e4-98c0-5254008ea111'}

        dmd = drbdmanagedrv.DrbdManageDriver(configuration=self.configuration)
        dmd.odm = DrbdManageFakeDriver()
        dmd.delete_snapshot(testsnap)
        self.assertEqual("list_snapshots", dmd.odm.calls[0][0])
        self.assertEqual("remove_snapshot", dmd.odm.calls[1][0])

    def test_extend_volume(self):
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'ba253fd0-8068-11e4-98c0-5254008ea111',
                   'volume_type_id': 'drbdmanage',
                   'created_at': timeutils.utcnow()}

        dmd = drbdmanagedrv.DrbdManageDriver(configuration=self.configuration)
        dmd.odm = DrbdManageFakeDriver()
        dmd.extend_volume(testvol, 5)
        self.assertEqual("list_volumes", dmd.odm.calls[0][0])
        self.assertEqual(testvol['id'], dmd.odm.calls[0][3]["cinder-id"])
        self.assertEqual("resize_volume", dmd.odm.calls[1][0])
        self.assertEqual("res", dmd.odm.calls[1][1])
        self.assertEqual(2, dmd.odm.calls[1][2])
        self.assertEqual(-1, dmd.odm.calls[1][3])
        self.assertEqual(5242880, dmd.odm.calls[1][4]['size'])

    def test_create_cloned_volume(self):
        srcvol = {'project_id': 'testprjid',
                  'name': 'testvol',
                  'size': 1,
                  'id': 'ba253fd0-8068-11e4-98c0-5254008ea111',
                  'volume_type_id': 'drbdmanage',
                  'created_at': timeutils.utcnow()}

        newvol = {'id': 'ca253fd0-8068-11e4-98c0-5254008ea111'}

        dmd = drbdmanagedrv.DrbdManageDriver(configuration=self.configuration)
        dmd.odm = DrbdManageFakeDriver()
        dmd.create_cloned_volume(newvol, srcvol)
        self.assertEqual("list_volumes", dmd.odm.calls[0][0])
        self.assertEqual("list_assignments", dmd.odm.calls[1][0])
        self.assertEqual("create_snapshot", dmd.odm.calls[2][0])
        self.assertEqual("list_snapshots", dmd.odm.calls[3][0])
        self.assertEqual("restore_snapshot", dmd.odm.calls[4][0])
        self.assertEqual("list_snapshots", dmd.odm.calls[5][0])
        self.assertEqual("remove_snapshot", dmd.odm.calls[6][0])
        self.assertEqual("remove_snapshot", dmd.odm.calls[6][0])
