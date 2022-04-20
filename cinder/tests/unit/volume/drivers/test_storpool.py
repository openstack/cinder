# Copyright 2014 - 2017, 2019  StorPool
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


import itertools
import re
import sys
from unittest import mock

import ddt
from oslo_utils import units


fakeStorPool = mock.Mock()
fakeStorPool.spopenstack = mock.Mock()
fakeStorPool.spapi = mock.Mock()
fakeStorPool.spconfig = mock.Mock()
fakeStorPool.sptypes = mock.Mock()
sys.modules['storpool'] = fakeStorPool


from cinder import exception
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import storpool as driver


volume_types = {
    1: {},
    2: {'storpool_template': 'ssd'},
    3: {'storpool_template': 'hdd'}
}
volumes = {}
snapshots = {}


def MockExtraSpecs(vtype):
    return volume_types[vtype]


def mock_volume_types(f):
    def _types_inner_inner1(inst, *args, **kwargs):
        @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs',
                    new=MockExtraSpecs)
        def _types_inner_inner2():
            return f(inst, *args, **kwargs)

        return _types_inner_inner2()

    return _types_inner_inner1


def volumeName(vid):
    return 'os--volume--{id}'.format(id=vid)


def snapshotName(vtype, vid):
    return 'os--snap--{t}--{id}'.format(t=vtype, id=vid)


class MockDisk(object):
    def __init__(self, diskId):
        self.id = diskId
        self.generationLeft = -1
        self.agCount = 14
        self.agFree = 12
        self.agAllocated = 1


class MockVolume(object):
    def __init__(self, v):
        self.name = v['name']


class MockTemplate(object):
    def __init__(self, name):
        self.name = name


class MockApiError(Exception):
    def __init__(self, msg):
        super(MockApiError, self).__init__(msg)


class MockAPI(object):
    def __init__(self):
        self._disks = {diskId: MockDisk(diskId) for diskId in (1, 2, 3, 4)}
        self._disks[3].generationLeft = 42

        self._templates = [MockTemplate(name) for name in ('ssd', 'hdd')]

    def setlog(self, log):
        self._log = log

    def disksList(self):
        return self._disks

    def snapshotCreate(self, vname, snap):
        snapshots[snap['name']] = dict(volumes[vname])

    def snapshotUpdate(self, snap, data):
        sdata = snapshots[snap]
        sdata.update(data)

    def snapshotDelete(self, name):
        del snapshots[name]

    def volumeCreate(self, vol):
        name = vol['name']
        if name in volumes:
            raise MockApiError('volume already exists')
        data = dict(vol)

        if 'parent' in vol and 'template' not in vol:
            sdata = snapshots[vol['parent']]
            if 'template' in sdata:
                data['template'] = sdata['template']

        if 'baseOn' in vol and 'template' not in vol:
            vdata = volumes[vol['baseOn']]
            if 'template' in vdata:
                data['template'] = vdata['template']

        if 'template' not in data:
            data['template'] = None

        volumes[name] = data

    def volumeDelete(self, name):
        del volumes[name]

    def volumesList(self):
        return [MockVolume(v[1]) for v in volumes.items()]

    def volumeTemplatesList(self):
        return self._templates

    def volumesReassign(self, json):
        pass

    def volumeUpdate(self, name, data):
        if 'size' in data:
            volumes[name]['size'] = data['size']

        if 'rename' in data and data['rename'] != name:
            new_name = data['rename']
            volumes[new_name] = volumes[name]
            if volumes[new_name]['name'] == name:
                volumes[new_name]['name'] = new_name
            del volumes[name]

    def volumeRevert(self, name, data):
        if name not in volumes:
            raise MockApiError('No such volume {name}'.format(name=name))

        snapname = data['toSnapshot']
        if snapname not in snapshots:
            raise MockApiError('No such snapshot {name}'.format(name=snapname))

        volumes[name] = dict(snapshots[snapname])


class MockAttachDB(object):
    def __init__(self, log):
        self._api = MockAPI()

    def api(self):
        return self._api

    def volumeName(self, vid):
        return volumeName(vid)

    def snapshotName(self, vtype, vid):
        return snapshotName(vtype, vid)


def MockVolumeRevertDesc(toSnapshot):
    return {'toSnapshot': toSnapshot}


def MockVolumeUpdateDesc(size):
    return {'size': size}


def MockSPConfig(section = 's01'):
    res = {}
    m = re.match('^s0*([A-Za-z0-9]+)$', section)
    if m:
        res['SP_OURID'] = m.group(1)
    return res


fakeStorPool.spapi.ApiError = MockApiError
fakeStorPool.spconfig.SPConfig = MockSPConfig
fakeStorPool.spopenstack.AttachDB = MockAttachDB
fakeStorPool.sptypes.VolumeRevertDesc = MockVolumeRevertDesc
fakeStorPool.sptypes.VolumeUpdateDesc = MockVolumeUpdateDesc


class MockVolumeDB(object):
    """Simulate a Cinder database with a volume_get() method."""

    def __init__(self, vol_types=None):
        """Store the specified volume types mapping if necessary."""
        self.vol_types = vol_types if vol_types is not None else {}

    def volume_get(self, _context, vid):
        """Get a volume-like structure, only the fields we care about."""
        # Still, try to at least make sure we know about that volume
        return {
            'id': vid,
            'size': volumes[volumeName(vid)]['size'],
            'volume_type': self.vol_types.get(vid),
        }


@ddt.ddt
class StorPoolTestCase(test.TestCase):

    def setUp(self):
        super(StorPoolTestCase, self).setUp()

        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.volume_backend_name = 'storpool_test'
        self.cfg.storpool_template = None
        self.cfg.storpool_replication = 3

        mock_exec = mock.Mock()
        mock_exec.return_value = ('', '')

        self.driver = driver.StorPoolDriver(execute=mock_exec,
                                            configuration=self.cfg)
        self.driver.check_for_setup_error()

    @ddt.data(
        (5, TypeError),
        ({'no-host': None}, KeyError),
        ({'host': 'sbad'}, driver.StorPoolConfigurationInvalid),
        ({'host': 's01'}, None),
        ({'host': 'none'}, None),
    )
    @ddt.unpack
    def test_validate_connector(self, conn, exc):
        if exc is None:
            self.assertTrue(self.driver.validate_connector(conn))
        else:
            self.assertRaises(exc,
                              self.driver.validate_connector,
                              conn)

    @ddt.data(
        (5, TypeError),
        ({'no-host': None}, KeyError),
        ({'host': 'sbad'}, driver.StorPoolConfigurationInvalid),
    )
    @ddt.unpack
    def test_initialize_connection_bad(self, conn, exc):
        self.assertRaises(exc,
                          self.driver.initialize_connection,
                          None, conn)

    @ddt.data(
        (1, '42', 's01'),
        (2, '616', 's02'),
        (65, '1610', 'none'),
    )
    @ddt.unpack
    def test_initialize_connection_good(self, cid, hid, name):
        c = self.driver.initialize_connection({'id': hid}, {'host': name})
        self.assertEqual('storpool', c['driver_volume_type'])
        self.assertDictEqual({'client_id': cid, 'volume': hid,
                              'access_mode': 'rw'},
                             c['data'])

    def test_noop_functions(self):
        self.driver.terminate_connection(None, None)
        self.driver.create_export(None, None, {})
        self.driver.remove_export(None, None)

    def test_stats(self):
        stats = self.driver.get_volume_stats(refresh=True)
        self.assertEqual('StorPool', stats['vendor_name'])
        self.assertEqual('storpool', stats['storage_protocol'])
        self.assertListEqual(['default', 'template_hdd', 'template_ssd'],
                             sorted([p['pool_name'] for p in stats['pools']]))
        r = re.compile(r'^template_([A-Za-z0-9_]+)$')
        for pool in stats['pools']:
            self.assertEqual(21, pool['total_capacity_gb'])
            self.assertEqual(5, int(pool['free_capacity_gb']))

            self.assertTrue(pool['multiattach'])
            self.assertFalse(pool['QoS_support'])
            self.assertFalse(pool['thick_provisioning_support'])
            self.assertTrue(pool['thin_provisioning_support'])

            if pool['pool_name'] != 'default':
                m = r.match(pool['pool_name'])
                self.assertIsNotNone(m)
                self.assertIsNotNone(m.group(1))
                self.assertEqual(m.group(1), pool['storpool_template'])

    def assertVolumeNames(self, names):
        self.assertListEqual(sorted([volumeName(n) for n in names]),
                             sorted(volumes.keys()))
        self.assertListEqual(sorted([volumeName(n) for n in names]),
                             sorted(data['name'] for data in volumes.values()))

    def assertSnapshotNames(self, specs):
        self.assertListEqual(
            sorted(snapshotName(spec[0], spec[1]) for spec in specs),
            sorted(snapshots.keys()))

    @mock_volume_types
    def test_create_delete_volume(self):
        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

        self.driver.create_volume({'id': '1', 'name': 'v1', 'size': 1,
                                   'volume_type': None})
        self.assertCountEqual([volumeName('1')], volumes.keys())
        self.assertVolumeNames(('1',))
        v = volumes[volumeName('1')]
        self.assertEqual(1 * units.Gi, v['size'])
        self.assertIsNone(v['template'])
        self.assertEqual(3, v['replication'])

        caught = False
        try:
            self.driver.create_volume({'id': '1', 'name': 'v1', 'size': 0,
                                       'volume_type': None})
        except exception.VolumeBackendAPIException:
            caught = True
        self.assertTrue(caught)

        self.driver.delete_volume({'id': '1'})
        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)

        self.driver.create_volume({'id': '1', 'name': 'v1', 'size': 2,
                                   'volume_type': None})
        self.assertVolumeNames(('1',))
        v = volumes[volumeName('1')]
        self.assertEqual(2 * units.Gi, v['size'])
        self.assertIsNone(v['template'])
        self.assertEqual(3, v['replication'])

        self.driver.create_volume({'id': '2', 'name': 'v2', 'size': 3,
                                   'volume_type': {'id': 1}})
        self.assertVolumeNames(('1', '2'))
        v = volumes[volumeName('2')]
        self.assertEqual(3 * units.Gi, v['size'])
        self.assertIsNone(v['template'])
        self.assertEqual(3, v['replication'])

        self.driver.create_volume({'id': '3', 'name': 'v2', 'size': 4,
                                   'volume_type': {'id': 2}})
        self.assertVolumeNames(('1', '2', '3'))
        v = volumes[volumeName('3')]
        self.assertEqual(4 * units.Gi, v['size'])
        self.assertEqual('ssd', v['template'])
        self.assertNotIn('replication', v.keys())

        self.driver.create_volume({'id': '4', 'name': 'v2', 'size': 5,
                                   'volume_type': {'id': 3}})
        self.assertVolumeNames(('1', '2', '3', '4'))
        v = volumes[volumeName('4')]
        self.assertEqual(5 * units.Gi, v['size'])
        self.assertEqual('hdd', v['template'])
        self.assertNotIn('replication', v.keys())

        # Make sure the dictionary is not corrupted somehow...
        v = volumes[volumeName('1')]
        self.assertEqual(2 * units.Gi, v['size'])
        self.assertIsNone(v['template'])
        self.assertEqual(3, v['replication'])

        for vid in ('1', '2', '3', '4'):
            self.driver.delete_volume({'id': vid})
        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

    @mock_volume_types
    def test_update_migrated_volume(self):
        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

        # Create two volumes
        self.driver.create_volume({'id': '1', 'name': 'v1', 'size': 1,
                                   'volume_type': None})
        self.driver.create_volume({'id': '2', 'name': 'v2', 'size': 1,
                                   'volume_type': None})
        self.assertCountEqual([volumeName('1'), volumeName('2')],
                              volumes.keys())
        self.assertVolumeNames(('1', '2',))

        # Failure: the "migrated" volume does not even exist
        res = self.driver.update_migrated_volume(None, {'id': '1'},
                                                 {'id': '3', '_name_id': '1'},
                                                 'available')
        self.assertDictEqual({'_name_id': '1'}, res)

        # Success: rename the migrated volume to match the original
        res = self.driver.update_migrated_volume(None, {'id': '3'},
                                                 {'id': '2', '_name_id': '3'},
                                                 'available')
        self.assertDictEqual({'_name_id': None}, res)
        self.assertCountEqual([volumeName('1'), volumeName('3')],
                              volumes.keys())
        self.assertVolumeNames(('1', '3',))

        # Success: swap volume names with an existing volume
        res = self.driver.update_migrated_volume(None, {'id': '1'},
                                                 {'id': '3', '_name_id': '1'},
                                                 'available')
        self.assertDictEqual({'_name_id': None}, res)
        self.assertCountEqual([volumeName('1'), volumeName('3')],
                              volumes.keys())
        self.assertVolumeNames(('1', '3',))

        for vid in ('1', '3'):
            self.driver.delete_volume({'id': vid})
        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

    def test_clone_extend_volume(self):
        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

        self.driver.create_volume({'id': '1', 'name': 'v1', 'size': 1,
                                   'volume_type': None})
        self.assertVolumeNames(('1',))
        self.driver.extend_volume({'id': '1'}, 2)
        self.assertEqual(2 * units.Gi, volumes[volumeName('1')]['size'])

        with mock.patch.object(self.driver, 'db', new=MockVolumeDB()):
            self.driver.create_cloned_volume(
                {'id': '2', 'name': 'clo', 'size': 3, 'volume_type': None},
                {'id': 1})
        self.assertVolumeNames(('1', '2'))
        self.assertDictEqual({}, snapshots)
        # We do not provide a StorPool template name in either of the volumes'
        # types, so create_cloned_volume() should take the baseOn shortcut.
        vol2 = volumes[volumeName('2')]
        self.assertEqual(vol2['baseOn'], volumeName('1'))
        self.assertNotIn('parent', vol2)

        self.driver.delete_volume({'id': 1})
        self.driver.delete_volume({'id': 2})

        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

    @ddt.data(*itertools.product(
        [None] + [{'id': key} for key in sorted(volume_types.keys())],
        [None] + [{'id': key} for key in sorted(volume_types.keys())]))
    @ddt.unpack
    @mock_volume_types
    def test_create_cloned_volume(self, src_type, dst_type):
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

        src_template = (
            None
            if src_type is None
            else volume_types[src_type['id']].get('storpool_template')
        )
        dst_template = (
            None
            if dst_type is None
            else volume_types[dst_type['id']].get('storpool_template')
        )
        src_name = 's-none' if src_template is None else 's-' + src_template
        dst_name = 'd-none' if dst_template is None else 'd-' + dst_template

        snap_name = snapshotName('clone', '2')

        vdata1 = {
            'id': '1',
            'name': src_name,
            'size': 1,
            'volume_type': src_type,
        }
        self.assertEqual(
            self.driver._template_from_volume(vdata1),
            src_template)
        self.driver.create_volume(vdata1)
        self.assertVolumeNames(('1',))

        vdata2 = {
            'id': 2,
            'name': dst_name,
            'size': 1,
            'volume_type': dst_type,
        }
        self.assertEqual(
            self.driver._template_from_volume(vdata2),
            dst_template)
        with mock.patch.object(self.driver, 'db',
                               new=MockVolumeDB(vol_types={'1': src_type})):
            self.driver.create_cloned_volume(vdata2, {'id': '1'})
        self.assertVolumeNames(('1', '2'))
        vol2 = volumes[volumeName('2')]
        self.assertEqual(vol2['template'], dst_template)

        if src_template == dst_template:
            self.assertEqual(vol2['baseOn'], volumeName('1'))
            self.assertNotIn('parent', vol2)

            self.assertDictEqual({}, snapshots)
        else:
            self.assertNotIn('baseOn', vol2)
            self.assertEqual(vol2['parent'], snap_name)

            self.assertSnapshotNames((('clone', '2'),))
            self.assertEqual(snapshots[snap_name]['template'], dst_template)

        self.driver.delete_volume({'id': '1'})
        self.driver.delete_volume({'id': '2'})
        if src_template != dst_template:
            del snapshots[snap_name]

        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

    @mock_volume_types
    def test_config_replication(self):
        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

        save_repl = self.driver.configuration.storpool_replication

        self.driver.configuration.storpool_replication = 3
        stats = self.driver.get_volume_stats(refresh=True)
        pool = stats['pools'][0]
        self.assertEqual(21, pool['total_capacity_gb'])
        self.assertEqual(5, int(pool['free_capacity_gb']))

        self.driver.create_volume({'id': 'cfgrepl1', 'name': 'v1', 'size': 1,
                                   'volume_type': None})
        self.assertVolumeNames(('cfgrepl1',))
        v = volumes[volumeName('cfgrepl1')]
        self.assertEqual(3, v['replication'])
        self.assertIsNone(v['template'])
        self.driver.delete_volume({'id': 'cfgrepl1'})

        self.driver.configuration.storpool_replication = 2
        stats = self.driver.get_volume_stats(refresh=True)
        pool = stats['pools'][0]
        self.assertEqual(21, pool['total_capacity_gb'])
        self.assertEqual(8, int(pool['free_capacity_gb']))

        self.driver.create_volume({'id': 'cfgrepl2', 'name': 'v1', 'size': 1,
                                   'volume_type': None})
        self.assertVolumeNames(('cfgrepl2',))
        v = volumes[volumeName('cfgrepl2')]
        self.assertEqual(2, v['replication'])
        self.assertIsNone(v['template'])
        self.driver.delete_volume({'id': 'cfgrepl2'})

        self.driver.create_volume({'id': 'cfgrepl3', 'name': 'v1', 'size': 1,
                                   'volume_type': {'id': 2}})
        self.assertVolumeNames(('cfgrepl3',))
        v = volumes[volumeName('cfgrepl3')]
        self.assertNotIn('replication', v)
        self.assertEqual('ssd', v['template'])
        self.driver.delete_volume({'id': 'cfgrepl3'})

        self.driver.configuration.storpool_replication = save_repl

        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

    @mock_volume_types
    def test_config_template(self):
        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

        save_template = self.driver.configuration.storpool_template

        self.driver.configuration.storpool_template = None

        self.driver.create_volume({'id': 'cfgtempl1', 'name': 'v1', 'size': 1,
                                   'volume_type': None})
        self.assertVolumeNames(('cfgtempl1',))
        v = volumes[volumeName('cfgtempl1')]
        self.assertEqual(3, v['replication'])
        self.assertIsNone(v['template'])
        self.driver.delete_volume({'id': 'cfgtempl1'})

        self.driver.create_volume({'id': 'cfgtempl2', 'name': 'v1', 'size': 1,
                                   'volume_type': {'id': 2}})
        self.assertVolumeNames(('cfgtempl2',))
        v = volumes[volumeName('cfgtempl2')]
        self.assertNotIn('replication', v)
        self.assertEqual('ssd', v['template'])
        self.driver.delete_volume({'id': 'cfgtempl2'})

        self.driver.configuration.storpool_template = 'hdd'

        self.driver.create_volume({'id': 'cfgtempl3', 'name': 'v1', 'size': 1,
                                   'volume_type': None})
        self.assertVolumeNames(('cfgtempl3',))
        v = volumes[volumeName('cfgtempl3')]
        self.assertNotIn('replication', v)
        self.assertEqual('hdd', v['template'])
        self.driver.delete_volume({'id': 'cfgtempl3'})

        self.driver.create_volume({'id': 'cfgtempl4', 'name': 'v1', 'size': 1,
                                   'volume_type': {'id': 2}})
        self.assertVolumeNames(('cfgtempl4',))
        v = volumes[volumeName('cfgtempl4')]
        self.assertNotIn('replication', v)
        self.assertEqual('ssd', v['template'])
        self.driver.delete_volume({'id': 'cfgtempl4'})

        self.driver.configuration.storpool_template = save_template

        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

    @ddt.data(
        # No volume type at all: 'default'
        ('default', None),
        # No storpool_template in the type extra specs: 'default'
        ('default', {'id': 1}),
        # An actual template specified: 'template_*'
        ('template_ssd', {'id': 2}),
        ('template_hdd', {'id': 3}),
    )
    @ddt.unpack
    @mock_volume_types
    def test_get_pool(self, pool, volume_type):
        self.assertEqual(pool,
                         self.driver.get_pool({
                             'volume_type': volume_type
                         }))

    def test_volume_revert(self):
        vol_id = 'rev1'
        vol_name = volumeName(vol_id)
        snap_id = 'rev-s1'
        snap_name = snapshotName('snap', snap_id)

        self.assertVolumeNames([])
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

        self.driver.create_volume({'id': vol_id, 'name': 'v1', 'size': 1,
                                   'volume_type': None})
        self.assertVolumeNames((vol_id,))
        self.assertDictEqual({}, snapshots)

        self.driver.create_snapshot({'id': snap_id, 'volume_id': vol_id})
        self.assertVolumeNames((vol_id,))
        self.assertListEqual([snap_name], sorted(snapshots.keys()))
        self.assertDictEqual(volumes[vol_name], snapshots[snap_name])
        self.assertIsNot(volumes[vol_name], snapshots[snap_name])

        self.driver.extend_volume({'id': vol_id}, 2)
        self.assertVolumeNames((vol_id,))
        self.assertNotEqual(volumes[vol_name], snapshots[snap_name])

        self.driver.revert_to_snapshot(None, {'id': vol_id}, {'id': snap_id})
        self.assertVolumeNames((vol_id,))
        self.assertDictEqual(volumes[vol_name], snapshots[snap_name])
        self.assertIsNot(volumes[vol_name], snapshots[snap_name])

        self.driver.delete_snapshot({'id': snap_id})
        self.assertVolumeNames((vol_id,))
        self.assertDictEqual({}, snapshots)

        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               'No such snapshot',
                               self.driver.revert_to_snapshot, None,
                               {'id': vol_id}, {'id': snap_id})

        self.driver.delete_volume({'id': vol_id})
        self.assertDictEqual({}, volumes)
        self.assertDictEqual({}, snapshots)

        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               'No such volume',
                               self.driver.revert_to_snapshot, None,
                               {'id': vol_id}, {'id': snap_id})
