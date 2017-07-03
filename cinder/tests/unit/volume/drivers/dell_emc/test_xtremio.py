# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
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

import copy
import time

import mock
import six

from cinder import exception
from cinder import test
from cinder.tests.unit.consistencygroup import fake_consistencygroup as fake_cg
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit.fake_volume import fake_volume_obj
from cinder.volume.drivers.dell_emc import xtremio

typ2id = {'volumes': 'vol-id',
          'snapshots': 'vol-id',
          'initiators': 'initiator-id',
          'initiator-groups': 'ig-id',
          'lun-maps': 'mapping-id',
          'consistency-groups': 'cg-id',
          'consistency-group-volumes': 'cg-vol-id',
          }

xms_init = {'xms': {1: {'version': '4.2.0',
                        'sw-version': '4.2.0-30'}},
            'clusters': {1: {'name': 'brick1',
                             'sys-sw-version': "4.2.0-devel_ba23ee5381eeab73",
                             'ud-ssd-space': '8146708710',
                             'ud-ssd-space-in-use': '708710',
                             'vol-size': '29884416',
                             'chap-authentication-mode': 'disabled',
                             'chap-discovery-mode': 'disabled',
                             "index": 1,
                             },
                         },
            'target-groups': {'Default': {"index": 1, "name": "Default"},
                              },
            'iscsi-portals': {'10.205.68.5/16':
                              {"port-address":
                               "iqn.2008-05.com.xtremio:001e67939c34",
                               "ip-port": 3260,
                               "ip-addr": "10.205.68.5/16",
                               "name": "10.205.68.5/16",
                               "index": 1,
                               },
                              },
            'targets': {'X1-SC2-target1': {'index': 1, "name": "X1-SC2-fc1",
                                           "port-address":
                                           "21:00:00:24:ff:57:b2:36",
                                           'port-type': 'fc',
                                           'port-state': 'up',
                                           },
                        'X1-SC2-target2': {'index': 2, "name": "X1-SC2-fc2",
                                           "port-address":
                                           "21:00:00:24:ff:57:b2:55",
                                           'port-type': 'fc',
                                           'port-state': 'up',
                                           }
                        },
            'volumes': {},
            'initiator-groups': {},
            'initiators': {},
            'lun-maps': {},
            'consistency-groups': {},
            'consistency-group-volumes': {},
            }

xms_data = None

xms_filters = {
    'eq': lambda x, y: x == y,
    'ne': lambda x, y: x != y,
    'gt': lambda x, y: x > y,
    'ge': lambda x, y: x >= y,
    'lt': lambda x, y: x < y,
    'le': lambda x, y: x <= y,
}


def get_xms_obj_by_name(typ, name):
    for item in xms_data[typ].values():
        if 'name' in item and item['name'] == name:
            return item
    raise exception.NotFound()


def clean_xms_data():
    global xms_data
    xms_data = copy.deepcopy(xms_init)


def fix_data(data, object_type):
    d = {}
    for key, value in data.items():
        if 'name' in key:
            key = 'name'
        d[key] = value

    if object_type == 'lun-maps':
        d['lun'] = 1

        vol_idx = get_xms_obj_by_name('volumes', data['vol-id'])['index']
        ig_idx = get_xms_obj_by_name('initiator-groups',
                                     data['ig-id'])['index']

        d['name'] = '_'.join([six.text_type(vol_idx),
                              six.text_type(ig_idx),
                              '1'])

    d[typ2id[object_type]] = ["a91e8c81c2d14ae4865187ce4f866f8a",
                              d.get('name'),
                              len(xms_data.get(object_type, [])) + 1]
    d['index'] = len(xms_data[object_type]) + 1
    return d


def get_xms_obj_key(data):
    for key in data.keys():
        if 'name' in key:
            return key


def get_obj(typ, name, idx):
    if name:
        return {"content": get_xms_obj_by_name(typ, name)}
    elif idx:
        if idx not in xms_data.get(typ, {}):
            raise exception.NotFound()
        return {"content": xms_data[typ][idx]}


def xms_request(object_type='volumes', method='GET', data=None,
                name=None, idx=None, ver='v1'):
    if object_type == 'snapshots':
        object_type = 'volumes'

    try:
        res = xms_data[object_type]
    except KeyError:
        raise exception.VolumeDriverException
    if method == 'GET':
        if name or idx:
            return get_obj(object_type, name, idx)
        else:
            if data and data.get('full') == 1:
                filter_term = data.get('filter')
                if not filter_term:
                    entities = list(res.values())
                else:
                    field, oper, value = filter_term.split(':', 2)
                    comp = xms_filters[oper]
                    entities = [o for o in res.values()
                                if comp(o.get(field), value)]
                return {object_type: entities}
            else:
                return {object_type: [{"href": "/%s/%d" % (object_type,
                                                           obj['index']),
                                       "name": obj.get('name')}
                                      for obj in res.values()]}
    elif method == 'POST':
        data = fix_data(data, object_type)
        name_key = get_xms_obj_key(data)
        try:
            if name_key and get_xms_obj_by_name(object_type, data[name_key]):
                raise (exception
                       .VolumeBackendAPIException
                       ('Volume by this name already exists'))
        except exception.NotFound:
            pass
        data['index'] = len(xms_data[object_type]) + 1
        xms_data[object_type][data['index']] = data
        # find the name key
        if name_key:
            data['name'] = data[name_key]
        if object_type == 'lun-maps':
            data['ig-name'] = data['ig-id']

        return {"links": [{"href": "/%s/%d" %
                          (object_type, data[typ2id[object_type]][2])}]}
    elif method == 'DELETE':
        if object_type == 'consistency-group-volumes':
            data = [cgv for cgv in
                    xms_data['consistency-group-volumes'].values()
                    if cgv['vol-id'] == data['vol-id']
                    and cgv['cg-id'] == data['cg-id']][0]
        else:
            data = get_obj(object_type, name, idx)['content']
        if data:
            del xms_data[object_type][data['index']]
        else:
            raise exception.NotFound()
    elif method == 'PUT':
        obj = get_obj(object_type, name, idx)['content']
        data = fix_data(data, object_type)
        del data['index']
        obj.update(data)


def xms_bad_request(object_type='volumes', method='GET', data=None,
                    name=None, idx=None, ver='v1'):
    if method == 'GET':
        raise exception.NotFound()
    elif method == 'POST':
        raise exception.VolumeBackendAPIException('Failed to create ig')


def xms_failed_rename_snapshot_request(object_type='volumes',
                                       method='GET', data=None,
                                       name=None, idx=None, ver='v1'):
    if method == 'POST':
        xms_data['volumes'][27] = {}
        return {
            "links": [
                {
                    "href": "https://host/api/json/v2/types/snapshots/27",
                    "rel": "self"}]}
    elif method == 'PUT':
        raise exception.VolumeBackendAPIException(data='Failed to delete')
    elif method == 'DELETE':
        del xms_data['volumes'][27]


class D(dict):
    def update(self, *args, **kwargs):
        self.__dict__.update(*args, **kwargs)
        return dict.update(self, *args, **kwargs)


class CommonData(object):
    context = {'user': 'admin', }
    connector = {'ip': '10.0.0.2',
                 'initiator': 'iqn.1993-08.org.debian:01:222',
                 'wwpns': ["123456789012345", "123456789054321"],
                 'wwnns': ["223456789012345", "223456789054321"],
                 'host': 'fakehost',
                 }

    test_volume = fake_volume_obj(context,
                                  name='vol1',
                                  size=1,
                                  volume_name='vol1',
                                  id='192eb39b-6c2f-420c-bae3-3cfd117f0001',
                                  provider_auth=None,
                                  project_id='project',
                                  display_name='vol1',
                                  display_description='test volume',
                                  volume_type_id=None,
                                  consistencygroup_id=
                                  '192eb39b-6c2f-420c-bae3-3cfd117f0345',
                                  )
    test_snapshot = D()
    test_snapshot.update({'name': 'snapshot1',
                          'size': 1,
                          'id': '192eb39b-6c2f-420c-bae3-3cfd117f0002',
                          'volume_name': 'vol-vol1',
                          'volume_id': '192eb39b-6c2f-420c-bae3-3cfd117f0001',
                          'project_id': 'project',
                          'consistencygroup_id':
                          '192eb39b-6c2f-420c-bae3-3cfd117f0345',
                          })
    test_snapshot.__dict__.update(test_snapshot)
    test_volume2 = {'name': 'vol2',
                    'size': 1,
                    'volume_name': 'vol2',
                    'id': '192eb39b-6c2f-420c-bae3-3cfd117f0004',
                    'provider_auth': None,
                    'project_id': 'project',
                    'display_name': 'vol2',
                    'display_description': 'test volume 2',
                    'volume_type_id': None,
                    'consistencygroup_id':
                    '192eb39b-6c2f-420c-bae3-3cfd117f0345',
                    }
    test_clone = {'name': 'clone1',
                  'size': 1,
                  'volume_name': 'vol3',
                  'id': '192eb39b-6c2f-420c-bae3-3cfd117f0003',
                  'provider_auth': None,
                  'project_id': 'project',
                  'display_name': 'clone1',
                  'display_description': 'volume created from snapshot',
                  'volume_type_id': None,
                  'consistencygroup_id':
                  '192eb39b-6c2f-420c-bae3-3cfd117f0345',
                  }
    unmanaged1 = {'id': 'unmanaged1',
                  'name': 'unmanaged1',
                  'size': 3,
                  }
    group = {'id': '192eb39b-6c2f-420c-bae3-3cfd117f0345',
             'name': 'cg1',
             'status': 'OK',
             }

    cgsnapshot = {
        'id': '192eb39b-6c2f-420c-bae3-3cfd117f9876',
        'consistencygroup_id': group['id'],
        'group_id': None, }

    cgsnapshot_as_group_id = {
        'id': '192eb39b-6c2f-420c-bae3-3cfd117f9876',
        'consistencygroup_id': None,
        'group_id': group['id'], }


class BaseXtremIODriverTestCase(test.TestCase):
    def __init__(self, *args, **kwargs):
        super(BaseXtremIODriverTestCase, self).__init__(*args, **kwargs)
        self.config = mock.Mock(san_login='',
                                san_password='',
                                san_ip='',
                                xtremio_cluster_name='brick1',
                                xtremio_provisioning_factor=20.0,
                                max_over_subscription_ratio=20.0,
                                xtremio_volumes_per_glance_cache=100,
                                driver_ssl_cert_verify=True,
                                driver_ssl_cert_path= '/test/path/root_ca.crt',
                                xtremio_array_busy_retry_count=5,
                                xtremio_array_busy_retry_interval=5)

        def safe_get(key):
            return getattr(self.config, key)
        self.config.safe_get = safe_get

    def setUp(self):
        super(BaseXtremIODriverTestCase, self).setUp()
        clean_xms_data()

        self.driver = xtremio.XtremIOISCSIDriver(configuration=self.config)
        self.driver.client = xtremio.XtremIOClient42(self.config,
                                                     self.config
                                                     .xtremio_cluster_name)
        self.data = CommonData()


@mock.patch('cinder.volume.drivers.dell_emc.xtremio.XtremIOClient.req')
class XtremIODriverISCSITestCase(BaseXtremIODriverTestCase):
    # ##### SetUp Check #####
    def test_check_for_setup_error(self, req):
        req.side_effect = xms_request
        self.driver.check_for_setup_error()
        self.assertEqual(self.driver.client.__class__.__name__,
                         'XtremIOClient42')

    def test_fail_check_for_setup_error(self, req):
        req.side_effect = xms_request
        clusters = xms_data.pop('clusters')
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        xms_data['clusters'] = clusters

    def test_check_for_setup_error_ver4(self, req):
        req.side_effect = xms_request
        xms_data['xms'][1]['sw-version'] = '4.0.10-34.hotfix1'
        self.driver.check_for_setup_error()
        self.assertEqual(self.driver.client.__class__.__name__,
                         'XtremIOClient4')

    def test_fail_check_for_array_version(self, req):
        req.side_effect = xms_request
        cluster = xms_data['clusters'][1]
        ver = cluster['sys-sw-version']
        cluster['sys-sw-version'] = '2.0.0-test'
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.check_for_setup_error)
        cluster['sys-sw-version'] = ver

    def test_client4_uses_v2(self, req):
        def base_req(*args, **kwargs):
            self.assertIn('v2', args)
        req.side_effect = base_req
        self.driver.client.req('volumes')

    def test_get_stats(self, req):
        req.side_effect = xms_request
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(self.driver.backend_name,
                         stats['volume_backend_name'])

# ##### Volumes #####
    def test_create_volume_with_cg(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)

    def test_extend_volume(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.extend_volume(self.data.test_volume, 5)

    def test_fail_extend_volume(self, req):
        req.side_effect = xms_request
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume, self.data.test_volume, 5)

    def test_delete_volume(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_duplicate_volume(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.data.test_volume)

# ##### Snapshots #####
    def test_create_snapshot(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.assertEqual(self.data.test_snapshot['id'],
                         xms_data['volumes'][2]['name'])

    def test_create_delete_snapshot(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.assertEqual(self.data.test_snapshot['id'],
                         xms_data['volumes'][2]['name'])
        self.driver.delete_snapshot(self.data.test_snapshot)

    def test_failed_rename_snapshot(self, req):
        req.side_effect = xms_failed_rename_snapshot_request
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot,
                          self.data.test_snapshot)
        self.assertEqual(0, len(xms_data['volumes']))

    def test_volume_from_snapshot(self, req):
        req.side_effect = xms_request
        xms_data['volumes'] = {}
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.driver.create_volume_from_snapshot(self.data.test_volume2,
                                                self.data.test_snapshot)

# ##### Clone Volume #####
    def test_clone_volume(self, req):
        req.side_effect = xms_request
        self.driver.db = mock.Mock()
        (self.driver.db.
         image_volume_cache_get_by_volume_id.return_value) = mock.MagicMock()
        self.driver.create_volume(self.data.test_volume)
        xms_data['volumes'][1]['num-of-dest-snaps'] = 50
        self.driver.create_cloned_volume(self.data.test_clone,
                                         self.data.test_volume)

    def test_clone_volume_exceed_conf_limit(self, req):
        req.side_effect = xms_request
        self.driver.db = mock.Mock()
        (self.driver.db.
         image_volume_cache_get_by_volume_id.return_value) = mock.MagicMock()
        self.driver.create_volume(self.data.test_volume)
        xms_data['volumes'][1]['num-of-dest-snaps'] = 200
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          self.data.test_clone,
                          self.data.test_volume)

    @mock.patch.object(xtremio.XtremIOClient4, 'create_snapshot')
    def test_clone_volume_exceed_array_limit(self, create_snap, req):
        create_snap.side_effect = exception.XtremIOSnapshotsLimitExceeded()
        req.side_effect = xms_request
        self.driver.db = mock.Mock()
        (self.driver.db.
         image_volume_cache_get_by_volume_id.return_value) = mock.MagicMock()
        self.driver.create_volume(self.data.test_volume)
        xms_data['volumes'][1]['num-of-dest-snaps'] = 50
        self.assertRaises(exception.CinderException,
                          self.driver.create_cloned_volume,
                          self.data.test_clone,
                          self.data.test_volume)

    def test_clone_volume_too_many_snaps(self, req):
        req.side_effect = xms_request
        response = mock.MagicMock()
        response.status_code = 400
        response.json.return_value = {
            "message": "too_many_snapshots_per_vol",
            "error_code": 400
        }
        self.assertRaises(exception.XtremIOSnapshotsLimitExceeded,
                          self.driver.client.handle_errors,
                          response, '', '')

    def test_clone_volume_too_many_objs(self, req):
        req.side_effect = xms_request
        response = mock.MagicMock()
        response.status_code = 400
        response.json.return_value = {
            "message": "too_many_objs",
            "error_code": 400
        }
        self.assertRaises(exception.XtremIOSnapshotsLimitExceeded,
                          self.driver.client.handle_errors,
                          response, '', '')

    def test_update_migrated_volume(self, req):
        original = self.data.test_volume
        new = self.data.test_volume2
        update = (self.driver.
                  update_migrated_volume({},
                                         original, new, 'available'))
        req.assert_called_once_with('volumes', 'PUT',
                                    {'name': original['id']}, new['id'],
                                    None, 'v2')
        self.assertEqual({'_name_id': None,
                          'provider_location': None}, update)

    def test_update_migrated_volume_failed_rename(self, req):
        req.side_effect = exception.VolumeBackendAPIException(
            data='failed rename')
        original = self.data.test_volume
        new = copy.deepcopy(self.data.test_volume2)
        fake_provider = '__provider'
        new['provider_location'] = fake_provider
        new['_name_id'] = None
        update = (self.driver.
                  update_migrated_volume({},
                                         original, new, 'available'))
        self.assertEqual({'_name_id': new['id'],
                          'provider_location': fake_provider},
                         update)

    def test_clone_volume_and_resize(self, req):
        req.side_effect = xms_request
        self.driver.db = mock.Mock()
        (self.driver.db.
         image_volume_cache_get_by_volume_id.return_value) = mock.MagicMock()
        self.driver.create_volume(self.data.test_volume)
        vol = xms_data['volumes'][1]
        vol['num-of-dest-snaps'] = 0
        clone = self.data.test_clone.copy()
        clone['size'] = 2
        with mock.patch.object(self.driver,
                               'extend_volume') as extend:
            self.driver.create_cloned_volume(clone, self.data.test_volume)
            extend.assert_called_once_with(clone, clone['size'])

    def test_clone_volume_and_resize_fail(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        vol = xms_data['volumes'][1]

        def failed_extend(obj_type='volumes', method='GET', data=None,
                          *args, **kwargs):
            if method == 'GET':
                return {'content': vol}
            elif method == 'POST':
                return {'links': [{'href': 'volume/2'}]}
            elif method == 'PUT':
                if 'name' in data:
                    return
                raise exception.VolumeBackendAPIException('Failed Clone')

        req.side_effect = failed_extend
        self.driver.db = mock.Mock()
        (self.driver.db.
         image_volume_cache_get_by_volume_id.return_value) = mock.MagicMock()
        vol['num-of-dest-snaps'] = 0
        clone = self.data.test_clone.copy()
        clone['size'] = 2
        with mock.patch.object(self.driver,
                               'delete_volume') as delete:
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.create_cloned_volume,
                              clone,
                              self.data.test_volume)
            self.assertTrue(delete.called)

# ##### Connection #####
    def test_no_portals_configured(self, req):
        req.side_effect = xms_request
        portals = xms_data['iscsi-portals'].copy()
        xms_data['iscsi-portals'].clear()
        lunmap = {'lun': 4}
        self.assertRaises(exception.VolumeDriverException,
                          self.driver._get_iscsi_properties, lunmap)
        xms_data['iscsi-portals'] = portals

    def test_initialize_connection(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_volume(self.data.test_volume2)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertEqual(1, map_data['data']['target_lun'])

    def test_initialize_connection_existing_ig(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_volume(self.data.test_volume2)
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)
        i1 = xms_data['initiators'][1]
        i1['ig-id'] = ['', i1['ig-id'], 1]
        i1['chap-authentication-initiator-password'] = 'chap_password1'
        i1['chap-discovery-initiator-password'] = 'chap_password2'
        self.driver.initialize_connection(self.data.test_volume2,
                                          self.data.connector)

    def test_terminate_connection(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_volume(self.data.test_volume2)
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)

    def test_terminate_connection_fail_on_bad_volume(self, req):
        req.side_effect = xms_request
        self.assertRaises(exception.NotFound,
                          self.driver.terminate_connection,
                          self.data.test_volume,
                          self.data.connector)

    def test_get_ig_indexes_from_initiators_called_once(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        i1 = xms_data['initiators'][1]
        i1['ig-id'] = ['', i1['ig-id'], 1]
        self.assertEqual(1, map_data['data']['target_lun'])

        with mock.patch.object(self.driver,
                               '_get_ig_indexes_from_initiators') as get_idx:
            get_idx.return_value = [1]
            self.driver.terminate_connection(self.data.test_volume,
                                             self.data.connector)
            get_idx.assert_called_once_with(self.data.connector)

    def test_initialize_connection_after_enabling_chap(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_volume(self.data.test_volume2)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertIsNone(map_data['data'].get('access_mode'))
        c1 = xms_data['clusters'][1]
        c1['chap-authentication-mode'] = 'initiator'
        c1['chap-discovery-mode'] = 'initiator'
        i1 = xms_data['initiators'][1]
        i1['ig-id'] = ['', i1['ig-id'], 1]
        i1['chap-authentication-initiator-password'] = 'chap_password1'
        i1['chap-discovery-initiator-password'] = 'chap_password2'
        map_data = self.driver.initialize_connection(self.data.test_volume2,
                                                     self.data.connector)
        self.assertEqual('chap_password1', map_data['data']['auth_password'])
        self.assertEqual('chap_password2',
                         map_data['data']['discovery_auth_password'])

    def test_initialize_connection_after_disabling_chap(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_volume(self.data.test_volume2)
        c1 = xms_data['clusters'][1]
        c1['chap-authentication-mode'] = 'initiator'
        c1['chap-discovery-mode'] = 'initiator'
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)
        i1 = xms_data['initiators'][1]
        i1['ig-id'] = ['', i1['ig-id'], 1]
        i1['chap-authentication-initiator-password'] = 'chap_password1'
        i1['chap-discovery-initiator-password'] = 'chap_password2'
        i1['chap-authentication-initiator-password'] = None
        i1['chap-discovery-initiator-password'] = None
        self.driver.initialize_connection(self.data.test_volume2,
                                          self.data.connector)

    @mock.patch('oslo_utils.strutils.mask_dict_password')
    def test_initialize_connection_masks_password(self, mask_dict, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)
        self.assertTrue(mask_dict.called)

    def test_add_auth(self, req):
        req.side_effect = xms_request
        data = {}
        self.driver._add_auth(data, True, True)
        self.assertIn('initiator-discovery-user-name', data,
                      'Missing discovery user in data')
        self.assertIn('initiator-discovery-password', data,
                      'Missing discovery password in data')

    def test_initialize_connection_bad_ig(self, req):
        req.side_effect = xms_bad_request
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.data.test_volume,
                          self.data.connector)
        self.driver.delete_volume(self.data.test_volume)

# ##### Manage Volumes #####
    def test_manage_volume(self, req):
        req.side_effect = xms_request
        xms_data['volumes'] = {1: {'name': 'unmanaged1',
                                   'index': 1,
                                   'vol-size': '3',
                                   },
                               }
        ref_vol = {"source-name": "unmanaged1"}
        self.driver.manage_existing(self.data.test_volume, ref_vol)

    def test_failed_manage_volume(self, req):
        req.side_effect = xms_request
        xms_data['volumes'] = {1: {'name': 'unmanaged1',
                                   'index': 1,
                                   'vol-size': '3',
                                   },
                               }
        invalid_ref = {"source-name": "invalid"}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          self.data.test_volume, invalid_ref)

    def test_get_manage_volume_size(self, req):
        req.side_effect = xms_request
        xms_data['volumes'] = {1: {'name': 'unmanaged1',
                                   'index': 1,
                                   'vol-size': '1000000',
                                   },
                               }
        ref_vol = {"source-name": "unmanaged1"}
        size = self.driver.manage_existing_get_size(self.data.test_volume,
                                                    ref_vol)
        self.assertEqual(1, size)

    def test_manage_volume_size_invalid_input(self, req):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          self.data.test_volume, {})

    def test_failed_manage_volume_size(self, req):
        req.side_effect = xms_request
        xms_data['volumes'] = {1: {'name': 'unmanaged1',
                                   'index': 1,
                                   'vol-size': '3',
                                   },
                               }
        invalid_ref = {"source-name": "invalid"}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          self.data.test_volume, invalid_ref)

    def test_unmanage_volume(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.unmanage(self.data.test_volume)

    def test_failed_unmanage_volume(self, req):
        req.side_effect = xms_request
        self.assertRaises(exception.VolumeNotFound, self.driver.unmanage,
                          self.data.test_volume2)

    def test_manage_snapshot(self, req):
        req.side_effect = xms_request
        vol_uid = self.data.test_snapshot.volume_id
        xms_data['volumes'] = {1: {'name': vol_uid,
                                   'index': 1,
                                   'vol-size': '3',
                                   },
                               2: {'name': 'unmanaged',
                                   'index': 2,
                                   'ancestor-vol-id': ['', vol_uid, 1],
                                   'vol-size': '3'}
                               }
        ref_vol = {"source-name": "unmanaged"}
        self.driver.manage_existing_snapshot(self.data.test_snapshot, ref_vol)

    def test_get_manage_snapshot_size(self, req):
        req.side_effect = xms_request
        vol_uid = self.data.test_snapshot.volume_id
        xms_data['volumes'] = {1: {'name': vol_uid,
                                   'index': 1,
                                   'vol-size': '3',
                                   },
                               2: {'name': 'unmanaged',
                                   'index': 2,
                                   'ancestor-vol-id': ['', vol_uid, 1],
                                   'vol-size': '3'}
                               }
        ref_vol = {"source-name": "unmanaged"}
        self.driver.manage_existing_snapshot_get_size(self.data.test_snapshot,
                                                      ref_vol)

    def test_manage_snapshot_invalid_snapshot(self, req):
        req.side_effect = xms_request
        xms_data['volumes'] = {1: {'name': 'unmanaged1',
                                   'index': 1,
                                   'vol-size': '3',
                                   'ancestor-vol-id': []}
                               }
        ref_vol = {"source-name": "unmanaged1"}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          self.data.test_snapshot, ref_vol)

    def test_unmanage_snapshot(self, req):
        req.side_effect = xms_request
        vol_uid = self.data.test_snapshot.volume_id
        xms_data['volumes'] = {1: {'name': vol_uid,
                                   'index': 1,
                                   'vol-size': '3',
                                   },
                               2: {'name': 'unmanaged',
                                   'index': 2,
                                   'ancestor-vol-id': ['', vol_uid, 1],
                                   'vol-size': '3'}
                               }
        ref_vol = {"source-name": "unmanaged"}
        self.driver.manage_existing_snapshot(self.data.test_snapshot, ref_vol)
        self.driver.unmanage_snapshot(self.data.test_snapshot)

# ##### Consistancy Groups #####
    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_cg_create(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]

        self.driver.create_consistencygroup(d.context, d.group)
        self.assertEqual(1, len(xms_data['consistency-groups']))

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_cg_update(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]

        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.update_consistencygroup(d.context, d.group,
                                            add_volumes=[d.test_volume,
                                                         d.test_volume2])
        self.assertEqual(2, len(xms_data['consistency-group-volumes']))
        self.driver.update_consistencygroup(d.context, d.group,
                                            remove_volumes=[d.test_volume2])
        self.assertEqual(1, len(xms_data['consistency-group-volumes']))

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_create_cg(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.update_consistencygroup(d.context, d.group,
                                            add_volumes=[d.test_volume,
                                                         d.test_volume2])
        self.driver.db = mock.Mock()
        (self.driver.db.
         volume_get_all_by_group.return_value) = [mock.MagicMock()]
        res = self.driver.create_cgsnapshot(d.context, d.cgsnapshot,
                                            [snapshot_obj])
        self.assertEqual((None, None), res)

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_cg_delete(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.update_consistencygroup(d.context, d.group,
                                            add_volumes=[d.test_volume,
                                                         d.test_volume2])
        self.driver.db = mock.Mock()
        self.driver.create_cgsnapshot(d.context, d.cgsnapshot, [snapshot_obj])
        self.driver.delete_consistencygroup(d.context, d.group, [])

    def test_cg_delete_with_volume(self, req):
        req.side_effect = xms_request
        d = self.data
        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.create_volume(d.test_volume)
        self.driver.update_consistencygroup(d.context, d.group,
                                            add_volumes=[d.test_volume])
        self.driver.db = mock.Mock()

        results, volumes = \
            self.driver.delete_consistencygroup(d.context,
                                                d.group,
                                                [d.test_volume])

        self.assertTrue(all(volume['status'] == 'deleted' for volume in
                            volumes))

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_cg_snapshot(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.update_consistencygroup(d.context, d.group,
                                            add_volumes=[d.test_volume,
                                                         d.test_volume2])
        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot)
        self.assertEqual(snapset_name,
                         '192eb39b6c2f420cbae33cfd117f0345192eb39b6c2f420cbae'
                         '33cfd117f9876')
        snapset1 = {'ancestor-vol-id': ['', d.test_volume['id'], 2],
                    'consistencygroup_id': d.group['id'],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        res = self.driver.delete_cgsnapshot(d.context, d.cgsnapshot,
                                            [snapshot_obj])
        self.assertEqual((None, None), res)

    def test_delete_cgsnapshot(self, req):
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        self.driver.delete_cgsnapshot(d.context, d.cgsnapshot,
                                      [snapshot_obj])
        req.assert_called_once_with('snapshot-sets', 'DELETE', None,
                                    '192eb39b6c2f420cbae33cfd117f0345192eb39'
                                    'b6c2f420cbae33cfd117f9876', None, 'v2')

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_cg_from_src_snapshot(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data

        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        snapshot_obj.volume_id = d.test_volume['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]

        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.create_volume(d.test_volume)
        self.driver.create_cgsnapshot(d.context, d.cgsnapshot, [])
        xms_data['volumes'][2]['ancestor-vol-id'] = (xms_data['volumes'][1]
                                                     ['vol-id'])
        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot)

        snapset1 = {'vol-list': [xms_data['volumes'][2]['vol-id']],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        cg_obj = fake_cg.fake_consistencyobject_obj(d.context)
        new_vol1 = fake_volume_obj(d.context)
        snapshot1 = (fake_snapshot
                     .fake_snapshot_obj
                     (d.context, volume_id=d.test_volume['id']))
        res = self.driver.create_consistencygroup_from_src(d.context, cg_obj,
                                                           [new_vol1],
                                                           d.cgsnapshot,
                                                           [snapshot1])
        self.assertEqual((None, None), res)

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_cg_from_src_cg(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data

        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        snapshot_obj.volume_id = d.test_volume['id']
        get_all_for_cgsnapshot.return_value = [snapshot_obj]

        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.create_volume(d.test_volume)
        self.driver.create_cgsnapshot(d.context, d.cgsnapshot, [])
        xms_data['volumes'][2]['ancestor-vol-id'] = (xms_data['volumes'][1]
                                                     ['vol-id'])
        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot)

        snapset1 = {'vol-list': [xms_data['volumes'][2]['vol-id']],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        cg_obj = fake_cg.fake_consistencyobject_obj(d.context)
        new_vol1 = fake_volume_obj(d.context)
        new_cg_obj = fake_cg.fake_consistencyobject_obj(
            d.context, id=fake.CONSISTENCY_GROUP2_ID)
        snapset2_name = new_cg_obj.id
        new_vol1.id = '192eb39b-6c2f-420c-bae3-3cfd117f0001'
        new_vol2 = fake_volume_obj(d.context)
        snapset2 = {'vol-list': [xms_data['volumes'][2]['vol-id']],
                    'name': snapset2_name,
                    'index': 1}
        xms_data['snapshot-sets'].update({5: snapset2,
                                          snapset2_name: snapset2})
        self.driver.create_consistencygroup_from_src(d.context, new_cg_obj,
                                                     [new_vol2],
                                                     None, None,
                                                     cg_obj, [new_vol1])

    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_invalid_cg_from_src_input(self, get_all_for_cgsnapshot, req):
        req.side_effect = xms_request
        d = self.data

        self.assertRaises(exception.InvalidInput,
                          self.driver.create_consistencygroup_from_src,
                          d.context, d.group, [], None, None, None, None)

#   #### Groups ####
    def test_group_create(self, req):
        """Test group create."""

        req.side_effect = xms_request
        d = self.data

        self.driver.create_group(d.context, d.group)
        self.assertEqual(1, len(xms_data['consistency-groups']))

    def test_group_update(self, req):
        """Test group update."""

        req.side_effect = xms_request
        d = self.data

        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.update_consistencygroup(d.context, d.group,
                                            add_volumes=[d.test_volume,
                                                         d.test_volume2])
        self.assertEqual(2, len(xms_data['consistency-group-volumes']))
        self.driver.update_group(d.context, d.group,
                                 remove_volumes=[d.test_volume2])
        self.assertEqual(1, len(xms_data['consistency-group-volumes']))

    def test_create_group_snapshot(self, req):
        """Test create group snapshot."""

        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']

        self.driver.create_group(d.context, d.group)
        self.driver.update_group(d.context, d.group,
                                 add_volumes=[d.test_volume,
                                              d.test_volume2])

        res = self.driver.create_group_snapshot(d.context, d.cgsnapshot,
                                                [snapshot_obj])
        self.assertEqual((None, None), res)

    def test_group_delete(self, req):
        """"Test delete group."""
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        self.driver.create_group(d.context, d.group)
        self.driver.update_group(d.context, d.group,
                                 add_volumes=[d.test_volume,
                                              d.test_volume2])
        self.driver.db = mock.Mock()
        (self.driver.db.
         volume_get_all_by_group.return_value) = [mock.MagicMock()]
        self.driver.create_group_snapshot(d.context, d.cgsnapshot,
                                          [snapshot_obj])
        self.driver.delete_group(d.context, d.group, [])

    def test_group_delete_with_volume(self, req):
        req.side_effect = xms_request
        d = self.data
        self.driver.create_consistencygroup(d.context, d.group)
        self.driver.create_volume(d.test_volume)
        self.driver.update_consistencygroup(d.context, d.group,
                                            add_volumes=[d.test_volume])
        self.driver.db = mock.Mock()

        results, volumes = \
            self.driver.delete_group(d.context, d.group, [d.test_volume])

        self.assertTrue(all(volume['status'] == 'deleted' for volume in
                            volumes))

    def test_group_snapshot(self, req):
        """test group snapshot."""
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        self.driver.create_group(d.context, d.group)
        self.driver.update_group(d.context, d.group,
                                 add_volumes=[d.test_volume,
                                              d.test_volume2])

        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot)
        self.assertEqual(snapset_name,
                         '192eb39b6c2f420cbae33cfd117f0345192eb39b6c2f420cbae'
                         '33cfd117f9876')
        snapset1 = {'ancestor-vol-id': ['', d.test_volume['id'], 2],
                    'consistencygroup_id': d.group['id'],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        res = self.driver.delete_group_snapshot(d.context, d.cgsnapshot,
                                                [snapshot_obj])
        self.assertEqual((None, None), res)

    def test_group_snapshot_with_generic_group(self, req):
        """test group snapshot shot with generic group ."""
        req.side_effect = xms_request
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        self.driver.create_group(d.context, d.group)
        self.driver.update_group(d.context, d.group,
                                 add_volumes=[d.test_volume,
                                              d.test_volume2])

        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot_as_group_id)
        self.assertEqual(snapset_name,
                         '192eb39b6c2f420cbae33cfd117f0345192eb39b6c2f420cbae'
                         '33cfd117f9876')
        snapset1 = {'ancestor-vol-id': ['', d.test_volume['id'], 2],
                    'consistencygroup_id': d.group['id'],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        res = self.driver.delete_group_snapshot(d.context, d.cgsnapshot,
                                                [snapshot_obj])
        self.assertEqual((None, None), res)

    def test_delete_group_snapshot(self, req):
        """test delete group snapshot."""
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        self.driver.delete_group_snapshot(d.context, d.cgsnapshot,
                                          [snapshot_obj])
        req.assert_called_once_with('snapshot-sets', 'DELETE', None,
                                    '192eb39b6c2f420cbae33cfd117f0345192eb39'
                                    'b6c2f420cbae33cfd117f9876', None, 'v2')

    def test_delete_group_snapshot_with_generic_group(self, req):
        """test delete group snapshot."""
        d = self.data
        snapshot_obj = fake_snapshot.fake_snapshot_obj(d.context)
        snapshot_obj.consistencygroup_id = d.group['id']
        self.driver.delete_group_snapshot(d.context, d.cgsnapshot_as_group_id,
                                          [snapshot_obj])
        req.assert_called_once_with('snapshot-sets', 'DELETE', None,
                                    '192eb39b6c2f420cbae33cfd117f0345192eb39'
                                    'b6c2f420cbae33cfd117f9876', None, 'v2')

    def test_group_from_src_snapshot(self, req):
        """test group from source snapshot."""
        req.side_effect = xms_request
        d = self.data

        self.driver.create_group(d.context, d.group)
        self.driver.create_volume(d.test_volume)
        self.driver.create_group_snapshot(d.context, d.cgsnapshot, [])
        xms_data['volumes'][2]['ancestor-vol-id'] = (xms_data['volumes'][1]
                                                     ['vol-id'])
        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot)

        snapset1 = {'vol-list': [xms_data['volumes'][2]['vol-id']],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        cg_obj = fake_cg.fake_consistencyobject_obj(d.context)
        new_vol1 = fake_volume_obj(d.context)
        snapshot1 = (fake_snapshot
                     .fake_snapshot_obj
                     (d.context, volume_id=d.test_volume['id']))
        res = self.driver.create_group_from_src(d.context, cg_obj,
                                                [new_vol1],
                                                d.cgsnapshot,
                                                [snapshot1])
        self.assertEqual((None, None), res)

    def test_group_from_src_group(self, req):
        """test group from source group."""
        req.side_effect = xms_request
        d = self.data

        self.driver.create_group(d.context, d.group)
        self.driver.create_volume(d.test_volume)
        self.driver.create_group_snapshot(d.context, d.cgsnapshot, [])
        xms_data['volumes'][2]['ancestor-vol-id'] = (xms_data['volumes'][1]
                                                     ['vol-id'])
        snapset_name = self.driver._get_cgsnap_name(d.cgsnapshot)

        snapset1 = {'vol-list': [xms_data['volumes'][2]['vol-id']],
                    'name': snapset_name,
                    'index': 1}
        xms_data['snapshot-sets'] = {snapset_name: snapset1, 1: snapset1}
        cg_obj = fake_cg.fake_consistencyobject_obj(d.context)
        new_vol1 = fake_volume_obj(d.context)
        new_cg_obj = fake_cg.fake_consistencyobject_obj(
            d.context, id=fake.CONSISTENCY_GROUP2_ID)
        snapset2_name = new_cg_obj.id
        new_vol1.id = '192eb39b-6c2f-420c-bae3-3cfd117f0001'
        new_vol2 = fake_volume_obj(d.context)
        snapset2 = {'vol-list': [xms_data['volumes'][2]['vol-id']],
                    'name': snapset2_name,
                    'index': 1}
        xms_data['snapshot-sets'].update({5: snapset2,
                                          snapset2_name: snapset2})
        self.driver.create_group_from_src(d.context, new_cg_obj,
                                          [new_vol2],
                                          None, None,
                                          cg_obj, [new_vol1])

    def test_invalid_group_from_src_input(self, req):
        """test invalid group from source."""
        req.side_effect = xms_request
        d = self.data

        self.assertRaises(exception.InvalidInput,
                          self.driver.create_group_from_src,
                          d.context, d.group, [], None, None, None, None)


@mock.patch('requests.request')
class XtremIODriverTestCase(BaseXtremIODriverTestCase):
    # ##### XMS Client #####
    @mock.patch.object(time, 'sleep', mock.Mock(return_value=0))
    def test_retry_request(self, req):
        busy_response = mock.MagicMock()
        busy_response.status_code = 400
        busy_response.json.return_value = {
            "message": "system_is_busy",
            "error_code": 400
        }
        good_response = mock.MagicMock()
        good_response.status_code = 200

        XtremIODriverTestCase.req_count = 0

        def busy_request(*args, **kwargs):
            if XtremIODriverTestCase.req_count < 1:
                XtremIODriverTestCase.req_count += 1
                return busy_response
            return good_response

        req.side_effect = busy_request
        self.driver.create_volume(self.data.test_volume)

    def test_verify_cert(self, req):
        good_response = mock.MagicMock()
        good_response.status_code = 200

        def request_verify_cert(*args, **kwargs):
            self.assertEqual(kwargs['verify'], '/test/path/root_ca.crt')
            return good_response

        req.side_effect = request_verify_cert
        self.driver.client.req('volumes')


@mock.patch('cinder.volume.drivers.dell_emc.xtremio.XtremIOClient.req')
class XtremIODriverFCTestCase(BaseXtremIODriverTestCase):
    def setUp(self):
        super(XtremIODriverFCTestCase, self).setUp()
        self.driver = xtremio.XtremIOFCDriver(
            configuration=self.config)

# ##### Connection FC#####
    def test_initialize_connection(self, req):
        req.side_effect = xms_request

        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertEqual(1, map_data['data']['target_lun'])

    def test_terminate_connection(self, req):
        req.side_effect = xms_request

        self.driver.create_volume(self.data.test_volume)
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)
        for i1 in xms_data['initiators'].values():
            i1['ig-id'] = ['', i1['ig-id'], 1]
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)

    def test_force_terminate_connection(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)
        self.driver.initialize_connection(self.data.test_volume,
                                          self.data.connector)
        vol1 = xms_data['volumes'][1]
        # lun mapping list is a list of triplets (IG OID, TG OID, lun number)
        vol1['lun-mapping-list'] = [[['a91e8c81c2d14ae4865187ce4f866f8a',
                                      'iqn.1993-08.org.debian:01:222',
                                      1],
                                     ['', 'Default', 1],
                                    1]]
        self.driver.terminate_connection(self.data.test_volume, None)

    def test_initialize_existing_ig_connection(self, req):
        req.side_effect = xms_request
        self.driver.create_volume(self.data.test_volume)

        pre_existing = 'pre_existing_host'
        self.driver._create_ig(pre_existing)
        wwpns = self.driver._get_initiator_names(self.data.connector)
        for wwpn in wwpns:
            data = {'initiator-name': wwpn, 'ig-id': pre_existing,
                    'port-address': wwpn}
            self.driver.client.req('initiators', 'POST', data)

        def get_fake_initiator(wwpn):
            return {'port-address': wwpn, 'ig-id': ['', pre_existing, 1]}
        with mock.patch.object(self.driver.client, 'get_initiator',
                               side_effect=get_fake_initiator):
            map_data = self.driver.initialize_connection(self.data.test_volume,
                                                         self.data.connector)
        self.assertEqual(1, map_data['data']['target_lun'])
        self.assertEqual(1, len(xms_data['initiator-groups']))

    def test_get_initiator_igs_ver4(self, req):
        req.side_effect = xms_request
        wwpn1 = '11:22:33:44:55:66:77:88'
        wwpn2 = '11:22:33:44:55:66:77:89'
        port_addresses = [wwpn1, wwpn2]
        ig_id = ['', 'my_ig', 1]
        self.driver.client = xtremio.XtremIOClient4(self.config,
                                                    self.config
                                                    .xtremio_cluster_name)

        def get_fake_initiator(wwpn):
            return {'port-address': wwpn, 'ig-id': ig_id}
        with mock.patch.object(self.driver.client, 'get_initiator',
                               side_effect=get_fake_initiator):
            self.driver.client.get_initiators_igs(port_addresses)

    def test_get_free_lun(self, req):
        def lm_response(*args, **kwargs):
            return {'lun-maps': [{'lun': 1}]}
        req.side_effect = lm_response

        ig_names = ['test1', 'test2']
        self.driver._get_free_lun(ig_names)

    def test_race_on_terminate_connection(self, req):
        """Test for race conditions on num_of_mapped_volumes.

        This test confirms that num_of_mapped_volumes won't break even if we
        receive a NotFound exception when retrieving info on a specific
        mapping, as that specific mapping could have been deleted between
        the request to get the list of exiting mappings and the request to get
        the info on one of them.
        """
        req.side_effect = xms_request
        self.driver.client = xtremio.XtremIOClient3(
            self.config, self.config.xtremio_cluster_name)
        # We'll wrap num_of_mapped_volumes, we'll store here original method
        original_method = self.driver.client.num_of_mapped_volumes

        def fake_num_of_mapped_volumes(*args, **kwargs):
            # Add a nonexistent mapping
            mappings = [{'href': 'volumes/1'}, {'href': 'volumes/12'}]

            # Side effects will be: 1st call returns the list, then we return
            # data for existing mappings, and on the nonexistent one we added
            # we return NotFound
            side_effect = [{'lun-maps': mappings},
                           {'content': xms_data['lun-maps'][1]},
                           exception.NotFound]

            with mock.patch.object(self.driver.client, 'req',
                                   side_effect=side_effect):
                return original_method(*args, **kwargs)

        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertEqual(1, map_data['data']['target_lun'])
        with mock.patch.object(self.driver.client, 'num_of_mapped_volumes',
                               side_effect=fake_num_of_mapped_volumes):
            self.driver.terminate_connection(self.data.test_volume,
                                             self.data.connector)
        self.driver.delete_volume(self.data.test_volume)
