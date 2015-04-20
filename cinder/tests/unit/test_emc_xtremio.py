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


import mock
from oslo_log import log as logging
import six

from cinder import exception
from cinder import test
from cinder.volume.drivers.emc import xtremio


LOG = logging.getLogger(__name__)

typ2id = {'volumes': 'vol-id',
          'snapshots': 'vol-id',
          'initiators': 'initiator-id',
          'initiator-groups': 'ig-id',
          'lun-maps': 'mapping-id'}

xms_data = {'xms': {1: {'version': '4.0.0'}},
            'clusters': {1: {'sys-sw-version': "3.0.0-devel_ba23ee5381eeab73",
                             'ud-ssd-space': '8146708710',
                             'ud-ssd-space-in-use': '708710',
                             'vol-size': '29884416',
                             'chap-authentication-mode': 'disabled',
                             'chap-discovery-mode': 'disabled',
                             "index": 1}},
            'target-groups': {'Default': {"index": 1, }},
            'iscsi-portals': {'10.205.68.5/16':
                              {"port-address":
                               "iqn.2008-05.com.xtremio:001e67939c34",
                               "ip-port": 3260,
                               "ip-addr": "10.205.68.5/16",
                               "name": "10.205.68.5/16",
                               "index": 1}},
            'targets': {'X1-SC2-fc1': {'index': 1, "name": "X1-SC2-fc1",
                                       "port-address":
                                       "21:00:00:24:ff:57:b2:36",
                                       'port-state': 'up'},
                        'X1-SC2-fc2': {'index': 2, "name": "X1-SC2-fc2",
                                       "port-address":
                                       "21:00:00:24:ff:57:b2:55",
                                       'port-state': 'up'}
                        },
            'volumes': {},
            'initiator-groups': {},
            'initiators': {},
            'lun-maps': {},
            }


def clean_xms_data():
    xms_data['volumes'] = {}
    xms_data['initiator-groups'] = {}
    xms_data['initiators'] = {}
    xms_data['lun-maps'] = {}


def fix_data(data, object_type):
    d = {}
    for key, value in data.items():
        if 'name' in key:
            key = 'name'
        d[key] = value

    if object_type == 'lun-maps':
        d['lun'] = 1

    d[typ2id[object_type]] = ["a91e8c81c2d14ae4865187ce4f866f8a",
                              d.get('name'),
                              len(xms_data[object_type]) + 1]
    d['index'] = len(xms_data[object_type]) + 1
    return d


def get_xms_obj_key(data):
    for key in data.keys():
        if 'name' in key:
            return key


def xms_request(object_type='volumes', request_typ='GET', data=None,
                name=None, idx=None):
    if object_type == 'snapshots':
        object_type = 'volumes'

    obj_key = name if name else idx
    if request_typ == 'GET':
        try:
            res = xms_data[object_type]
        except KeyError:
            raise exception.VolumeDriverException
        if name or idx:
            if obj_key not in res:
                raise exception.NotFound()
            return {"content": res[obj_key]}
        else:
            return {object_type: [{"href": "/%s/%d" % (object_type,
                                                       obj['index']),
                                   "name": obj.get('name')}
                                  for obj in res.values()]}
    elif request_typ == 'POST':
        data = fix_data(data, object_type)
        data['index'] = len(xms_data[object_type]) + 1
        xms_data[object_type][data['index']] = data
        # find the name key
        name_key = get_xms_obj_key(data)
        if object_type == 'lun-maps':
            data['ig-name'] = data['ig-id']
        if name_key:
            if data[name_key] in xms_data[object_type]:
                raise (exception
                       .VolumeBackendAPIException
                       ('Volume by this name already exists'))
            xms_data[object_type][data[name_key]] = data

        return {"links": [{"href": "/%s/%d" %
                          (object_type, data[typ2id[object_type]][2])}]}
    elif request_typ == 'DELETE':
        if obj_key in xms_data[object_type]:
            data = xms_data[object_type][obj_key]
            del xms_data[object_type][data['index']]
            del xms_data[object_type][data[typ2id[object_type]][1]]
        else:
            LOG.error('Trying to delete a missing object %s',
                      six.text_type(obj_key))
            raise exception.NotFound()
    elif request_typ == 'PUT':
        if obj_key in xms_data[object_type]:
            obj = xms_data[object_type][obj_key]
            obj.update(data)
            key = get_xms_obj_key(data)
            if key:
                xms_data[object_type][data[key]] = obj
        else:
            LOG.error('Trying to update a missing object %s',
                      six.text_type(obj_key))
            raise exception.NotFound()


def xms_bad_request(object_type='volumes', request_typ='GET', data=None,
                    name=None, idx=None):
    if request_typ == 'GET':
        raise exception.NotFound()
    elif request_typ == 'POST':
        raise exception.VolumeBackendAPIException('Failed to create ig')


class D(dict):
    def update(self, *args, **kwargs):
        self.__dict__.update(*args, **kwargs)
        return dict.update(self, *args, **kwargs)


class CommonData(object):
    connector = {'ip': '10.0.0.2',
                 'initiator': 'iqn.1993-08.org.debian:01:222',
                 'wwpns': ["123456789012345", "123456789054321"],
                 'wwnns': ["223456789012345", "223456789054321"],
                 'host': 'fakehost'}

    test_volume = {'name': 'vol1',
                   'size': 1,
                   'volume_name': 'vol1',
                   'id': '192eb39b-6c2f-420c-bae3-3cfd117f0001',
                   'provider_auth': None,
                   'project_id': 'project',
                   'display_name': 'vol1',
                   'display_description': 'test volume',
                   'volume_type_id': None}
    test_snapshot = D()
    test_snapshot.update({'name': 'snapshot1',
                          'size': 1,
                          'id': '192eb39b-6c2f-420c-bae3-3cfd117f0002',
                          'volume_name': 'vol-vol1',
                          'volume_id': '192eb39b-6c2f-420c-bae3-3cfd117f0001',
                          'project_id': 'project'})
    test_snapshot.__dict__.update(test_snapshot)
    test_volume2 = {'name': 'vol2',
                    'size': 1,
                    'volume_name': 'vol2',
                    'id': '192eb39b-6c2f-420c-bae3-3cfd117f0004',
                    'provider_auth': None,
                    'project_id': 'project',
                    'display_name': 'vol2',
                    'display_description': 'test volume 2',
                    'volume_type_id': None}
    test_clone = {'name': 'clone1',
                  'size': 1,
                  'volume_name': 'vol3',
                  'id': '192eb39b-6c2f-420c-bae3-3cfd117f0003',
                  'provider_auth': None,
                  'project_id': 'project',
                  'display_name': 'clone1',
                  'display_description': 'volume created from snapshot',
                  'volume_type_id': None}
    unmanaged1 = {'id': 'unmanaged1',
                  'name': 'unmanaged1',
                  'size': 3}


@mock.patch('cinder.volume.drivers.emc.xtremio.XtremIOClient.req')
class EMCXIODriverISCSITestCase(test.TestCase):
    def setUp(self):
        super(EMCXIODriverISCSITestCase, self).setUp()

        configuration = mock.Mock()
        configuration.san_login = ''
        configuration.san_password = ''
        configuration.san_ip = ''
        configuration.xtremio_cluster_name = ''
        configuration.xtremio_provisioning_factor = 20.0

        def safe_get(key):
            getattr(configuration, key)

        configuration.safe_get = safe_get
        self.driver = xtremio.XtremIOISCSIDriver(configuration=configuration)

        self.data = CommonData()

    def test_check_for_setup_error(self, req):
        req.side_effect = xms_request
        xms = xms_data['xms']
        del xms_data['xms']
        self.driver.check_for_setup_error()
        xms_data['xms'] = xms
        self.driver.check_for_setup_error()

    def test_create_extend_delete_volume(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        self.driver.create_volume(self.data.test_volume)
        self.driver.extend_volume(self.data.test_volume, 5)
        self.driver.delete_volume(self.data.test_volume)

    def test_create_delete_snapshot(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.driver.delete_snapshot(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_volume_from_snapshot(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        xms_data['volumes'] = {}
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_snapshot(self.data.test_snapshot)
        self.driver.create_volume_from_snapshot(self.data.test_volume2,
                                                self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume2)
        self.driver.delete_volume(self.data.test_snapshot)
        self.driver.delete_volume(self.data.test_volume)

    def test_clone_volume(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        self.driver.create_volume(self.data.test_volume)
        self.driver.create_cloned_volume(self.data.test_clone,
                                         self.data.test_volume)
        self.driver.delete_volume(self.data.test_clone)
        self.driver.delete_volume(self.data.test_volume)

    def test_duplicate_volume(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        self.driver.create_volume(self.data.test_volume)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.data.test_volume)
        self.driver.delete_volume(self.data.test_volume)

    def test_initialize_terminate_connection(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertEqual(map_data['data']['target_lun'], 1)
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)

    def test_initialize_connection_bad_ig(self, req):
        req.side_effect = xms_bad_request
        clean_xms_data()
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.data.test_volume,
                          self.data.connector)
        self.driver.delete_volume(self.data.test_volume)

    def test_get_stats(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(stats['volume_backend_name'],
                         self.driver.backend_name)

    def test_manage_unmanage(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        xms_data['volumes'] = {'unmanaged1': {'vol-name': 'unmanaged1',
                                              'index': 'unmanaged1',
                                              'vol-size': '3'}}
        ref_vol = {"source-name": "unmanaged1"}
        invalid_ref = {"source-name": "invalid"}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          self.data.test_volume, invalid_ref)
        self.driver.manage_existing_get_size(self.data.test_volume, ref_vol)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          self.data.test_volume, invalid_ref)
        self.driver.manage_existing(self.data.test_volume, ref_vol)
        self.assertRaises(exception.VolumeNotFound, self.driver.unmanage,
                          self.data.test_volume2)
        self.driver.unmanage(self.data.test_volume)


@mock.patch('cinder.volume.drivers.emc.xtremio.XtremIOClient.req')
class EMCXIODriverFibreChannelTestCase(test.TestCase):
    def setUp(self):
        super(EMCXIODriverFibreChannelTestCase, self).setUp()

        configuration = mock.Mock()
        configuration.san_login = ''
        configuration.san_password = ''
        configuration.san_ip = ''
        configuration.xtremio_cluster_name = ''
        configuration.xtremio_provisioning_factor = 20.0
        self.driver = xtremio.XtremIOFibreChannelDriver(
            configuration=configuration)

        self.data = CommonData()

    def test_initialize_terminate_connection(self, req):
        req.side_effect = xms_request
        clean_xms_data()
        self.driver.create_volume(self.data.test_volume)
        map_data = self.driver.initialize_connection(self.data.test_volume,
                                                     self.data.connector)
        self.assertEqual(map_data['data']['target_lun'], 1)
        self.driver.terminate_connection(self.data.test_volume,
                                         self.data.connector)
        self.driver.delete_volume(self.data.test_volume)
