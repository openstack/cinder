#
# Copyright 2012 OpenStack Foundation
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

import datetime
import re
import six

import ddt
import mock
from oslo_utils import timeutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_group_snapshot
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import utils as test_utils
from cinder.volume import configuration as conf
from cinder.volume.drivers import solidfire
from cinder.volume import qos_specs
from cinder.volume import volume_types


class mock_vref(object):
    def __init__(self):
        self._name_id = None
        self.admin_metadata = {}
        self.attach_status = 'detached'
        self.id = '262b9ce2-a71a-4fbe-830c-c20c5596caea'
        self.project_id = '52423d9394ad4c67b3b9034da58cedbc'
        self.provider_id = '5 4 6ecebf5d-5521-4ce1-80f3-358ebc1b9cdc'
        self.size = 20

    def __setitem__(self, item, value):
        self.__dict__[item] = value

    def __getitem__(self, item):
        return self.__dict__[item]

    def get(self, item, arg2 = None):
        return self.__dict__[item]

f_uuid = ['262b9ce2-a71a-4fbe-830c-c20c5596caea',
          '362b9ce2-a71a-4fbe-830c-c20c5596caea']


@ddt.ddt
class SolidFireVolumeTestCase(test.TestCase):

    EXPECTED_QOS = {'minIOPS': 110, 'burstIOPS': 1530, 'maxIOPS': 1020}

    def setUp(self):
        self.ctxt = context.get_admin_context()
        self.configuration = conf.BackendGroupConfiguration(
            [], conf.SHARED_CONF_GROUP)
        self.configuration.sf_allow_tenant_qos = True
        self.configuration.san_is_local = True
        self.configuration.sf_emulate_512 = True
        self.configuration.sf_account_prefix = 'cinder'
        self.configuration.reserved_percentage = 25
        self.configuration.target_helper = None
        self.configuration.sf_template_account_name = 'openstack-vtemplate'
        self.configuration.sf_allow_template_caching = False
        self.configuration.sf_svip = None
        self.configuration.sf_volume_prefix = 'UUID-'
        self.configuration.sf_enable_vag = False
        self.configuration.replication_device = []
        self.configuration.max_over_subscription_ratio = 2

        super(SolidFireVolumeTestCase, self).setUp()
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)

        self.expected_qos_results = {'minIOPS': 1000,
                                     'maxIOPS': 10000,
                                     'burstIOPS': 20000}
        self.mock_stats_data =\
            {'result':
                {'clusterCapacity': {'maxProvisionedSpace': 107374182400,
                                     'usedSpace': 1073741824,
                                     'compressionPercent': 100,
                                     'deDuplicationPercent': 100,
                                     'thinProvisioningPercent': 100}}}
        vol_updates = {'project_id': 'testprjid',
                       'name': 'testvol',
                       'size': 1,
                       'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                       'volume_type_id': 'fast',
                       'created_at': timeutils.utcnow(),
                       'attributes':
                           {'uuid': '262b9ce2-a71a-4fbe-830c-c20c5596caea'}}
        ctx = context.get_admin_context()
        self.mock_volume = fake_volume.fake_volume_obj(ctx, **vol_updates)

        self.fake_image_meta = {'id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                                'updated_at': datetime.datetime(2013, 9,
                                                                28, 15,
                                                                27, 36,
                                                                325355),
                                'is_public': True,
                                'owner': 'testprjid'}
        self.fake_image_service = fake_image.FakeImageService()

        self.vol = test_utils.create_volume(
            self.ctxt, volume_id='b831c4d1-d1f0-11e1-9b23-0800200c9a66')
        self.snap = test_utils.create_snapshot(
            self.ctxt, volume_id=self.vol.id)

        self.fake_sfaccount = {'accountID': 25,
                               'targetSecret': 'shhhh',
                               'username': 'prefix-testprjid',
                               'volumes': [6, 7, 20]}

        self.fake_sfvol = {'volumeID': 6,
                           'name': 'test_volume',
                           'accountID': 25,
                           'sliceCount': 1,
                           'totalSize': 1 * units.Gi,
                           'enable512e': True,
                           'access': "readWrite",
                           'status': "active",
                           'attributes': {'uuid': f_uuid[0]},
                           'qos': None,
                           'iqn': 'super_fake_iqn'}

        self.cluster_pairs = (
            [{'uniqueID': 'lu9f',
              'endpoint': {'passwd': 'admin', 'port': 443,
                           'url': 'https://192.168.139.102:443',
                           'svip': '10.10.8.134',
                           'mvip': '192.168.139.102',
                           'login': 'admin'},
              'name': 'AutoTest2-6AjG-FOR-TEST-ONLY',
              'clusterPairID': 33,
              'uuid': '9c499d4b-8fff-48b4-b875-27601d5d9889',
              'svip': '10.10.23.2',
              'mvipNodeID': 1,
              'repCount': 1,
              'encryptionAtRestState': 'disabled',
              'attributes': {},
              'mvip': '192.168.139.102',
              'ensemble': ['10.10.5.130'],
              'svipNodeID': 1}])

        self.mvip = '192.168.139.102'
        self.svip = '10.10.8.134'

        self.fake_sfsnap_name = '%s%s' % (self.configuration.sf_volume_prefix,
                                          self.snap.id)
        self.fake_sfsnaps = [{'snapshotID': '5',
                              'name': self.fake_sfsnap_name,
                              'volumeID': 6}]

    def fake_init_cluster_pairs(*args, **kwargs):
        return None

    def fake_issue_api_request(obj, method, params, version='1.0',
                               endpoint=None):
        if method is 'GetClusterCapacity' and version == '1.0':
            data = {'result':
                    {'clusterCapacity': {'maxProvisionedSpace': 107374182400,
                                         'usedSpace': 1073741824,
                                         'compressionPercent': 100,
                                         'deDuplicationPercent': 100,
                                         'thinProvisioningPercent': 100,
                                         'maxUsedSpace': 53687091200}}}
            return data

        elif method is 'GetClusterInfo':
            results = {
                'result':
                    {'clusterInfo':
                        {'name': 'fake-cluster',
                         'mvip': '1.1.1.1',
                         'svip': '1.1.1.1',
                         'uniqueID': 'unqid',
                         'repCount': 2,
                         'uuid': '53c8be1e-89e2-4f7f-a2e3-7cb84c47e0ec',
                         'attributes': {}}}}
            return results

        elif method is 'GetClusterVersionInfo':
            return {'id': None, 'result': {'softwareVersionInfo':
                                           {'pendingVersion': '8.2.1.4',
                                            'packageName': '',
                                            'currentVersion': '8.2.1.4',
                                            'nodeID': 0, 'startTime': ''},
                                           'clusterVersion': '8.2.1.4',
                                           'clusterAPIVersion': '8.2'}}

        elif method is 'AddAccount' and version == '1.0':
            return {'result': {'accountID': 25}, 'id': 1}

        elif method is 'GetAccountByName' and version == '1.0':
            results = {'result': {'account':
                                  {'accountID': 25,
                                   'username': params['username'],
                                   'status': 'active',
                                   'initiatorSecret': '123456789012',
                                   'targetSecret': '123456789012',
                                   'attributes': {},
                                   'volumes': [6, 7, 20]}},
                       "id": 1}
            return results

        elif method is 'CreateVolume' and version == '1.0':
            return {'result': {'volumeID': 5}, 'id': 1}

        elif method is 'CreateSnapshot' and version == '6.0':
            return {'result': {'snapshotID': 5}, 'id': 1}

        elif method is 'DeleteVolume' and version == '1.0':
            return {'result': {}, 'id': 1}

        elif method is 'ModifyVolume' and version == '5.0':
            return {'result': {}, 'id': 1}

        elif method is 'CloneVolume':
            return {'result': {'volumeID': 6}, 'id': 2}

        elif method is 'ModifyVolume':
            return {'result': {}, 'id': 1}

        elif method is 'ListVolumesForAccount' and version == '1.0':
            test_name = 'OS-VOLID-a720b3c0-d1f0-11e1-9b23-0800200c9a66'
            result = {'result': {
                'volumes': [{'volumeID': 5,
                             'name': test_name,
                             'accountID': 25,
                             'sliceCount': 1,
                             'totalSize': 1 * units.Gi,
                             'enable512e': True,
                             'access': "readWrite",
                             'status': "active",
                             'attributes': {'uuid': f_uuid[0]},
                             'qos': None,
                             'iqn': test_name}]}}
            return result

        elif method is 'ListActiveVolumes':
            test_name = "existing_volume"
            result = {'result': {
                'volumes': [{'volumeID': 5,
                             'name': test_name,
                             'accountID': 8,
                             'sliceCount': 1,
                             'totalSize': int(1.75 * units.Gi),
                             'enable512e': True,
                             'access': "readWrite",
                             'status': "active",
                             'attributes': {},
                             'qos': None,
                             'iqn': test_name}]}}
            return result
        elif method is 'ListVolumes':
            test_name = "get_sfvol_by_cinder"
            result = {'result': {
                'volumes': [{'volumeID': 5,
                             'name': test_name,
                             'accountID': 8,
                             'sliceCount': 1,
                             'totalSize': int(1.75 * units.Gi),
                             'enable512e': True,
                             'access': "readWrite",
                             'status': "active",
                             'attributes': {'uuid': f_uuid[0]},
                             'qos': None,
                             'iqn': test_name},
                            {'volumeID': 15,
                             'name': test_name,
                             'accountID': 8,
                             'sliceCount': 1,
                             'totalSize': int(1.75 * units.Gi),
                             'enable512e': True,
                             'access': "readWrite",
                             'status': "active",
                             'attributes': {'uuid': f_uuid[1]},
                             'qos': None,
                             'iqn': test_name}]}}
            if params and params['startVolumeID']:
                volumes = result['result']['volumes']
                selected_volumes = [v for v in volumes if v.get('volumeID')
                                    != params['startVolumeID']]
                result['result']['volumes'] = selected_volumes
            return result
        elif method is 'DeleteSnapshot':
            return {'result': {}}
        elif method is 'GetClusterVersionInfo':
            return {'result': {'clusterAPIVersion': '8.0'}}
        elif method is 'StartVolumePairing':
            return {'result': {'volumePairingKey': 'fake-pairing-key'}}
        elif method is 'RollbackToSnapshot':
            return {
                "id": 1,
                "result": {
                    "checksum": "0x0",
                    "snapshot": {
                        "attributes": {},
                        "checksum": "0x0",
                        "createTime": "2016-04-04T17:27:32Z",
                        "enableRemoteReplication": "false",
                        "expirationReason": "None",
                        "expirationTime": "null",
                        "groupID": 0,
                        "groupSnapshotUUID": f_uuid[0],
                        "name": "test1-copy",
                        "snapshotID": 1,
                        "snapshotUUID": f_uuid[1],
                        "status": "done",
                        "totalSize": 5000658944,
                        "virtualVolumeID": "null",
                        "volumeID": 1
                    },
                    "snapshotID": 1
                }
            }
        elif method is 'ListAccounts':
            return {
                'result': {
                    'accounts': [{
                        'accountID': 5,
                        'targetSecret': 'shhhh',
                        'username': 'prefix-testprjid'
                    }]
                }
            }
        else:
            # Crap, unimplemented API call in Fake
            return None

    def fake_issue_api_request_fails(obj, method,
                                     params, version='1.0',
                                     endpoint=None):
        response = {'error': {'code': 000,
                              'name': 'DummyError',
                              'message': 'This is a fake error response'},
                    'id': 1}
        msg = ('Error (%s) encountered during '
               'SolidFire API call.' % response['error']['name'])
        raise exception.SolidFireAPIException(message=msg)

    def fake_set_qos_by_volume_type(self, type_id, ctxt):
        return {'minIOPS': 500,
                'maxIOPS': 1000,
                'burstIOPS': 1000}

    def fake_volume_get(obj, key, default=None):
        return {'qos': 'fast'}

    def fake_update_cluster_status(self):
        return

    def fake_get_cluster_version_info(self):
        return

    def fake_get_model_info(self, account, vid, endpoint=None):
        return {'fake': 'fake-model'}

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_template_account')
    def test_create_volume_with_qos_type(self,
                                         _mock_create_template_account,
                                         _mock_issue_api_request):
        _mock_issue_api_request.side_effect = self.fake_issue_api_request
        _mock_create_template_account.return_value = 1
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': 'fast',
                   'created_at': timeutils.utcnow()}

        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'}]

        test_type = {'name': 'sf-1',
                     'qos_specs_id': 'fb0576d7-b4b5-4cad-85dc-ca92e6a497d1',
                     'deleted': False,
                     'created_at': '2014-02-06 04:58:11',
                     'updated_at': None,
                     'extra_specs': {},
                     'deleted_at': None,
                     'id': 'e730e97b-bc7d-4af3-934a-32e59b218e81'}

        test_qos_spec = {'id': 'asdfafdasdf',
                         'specs': {'minIOPS': '1000',
                                   'maxIOPS': '2000',
                                   'burstIOPS': '3000'}}

        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx, **testvol)

        def _fake_get_volume_type(ctxt, type_id):
            return test_type

        def _fake_get_qos_spec(ctxt, spec_id):
            return test_qos_spec

        def _fake_do_volume_create(account, params):
            params['provider_location'] = '1.1.1.1 iqn 0'
            return params

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
                mock.patch.object(sfv,
                                  '_get_account_create_availability',
                                  return_value=fake_sfaccounts[0]), \
                mock.patch.object(sfv,
                                  '_do_volume_create',
                                  side_effect=_fake_do_volume_create), \
                mock.patch.object(volume_types,
                                  'get_volume_type',
                                  side_effect=_fake_get_volume_type), \
                mock.patch.object(qos_specs,
                                  'get_qos_specs',
                                  side_effect=_fake_get_qos_spec):

            self.assertEqual({'burstIOPS': 3000,
                              'minIOPS': 1000,
                              'maxIOPS': 2000},
                             sfv.create_volume(testvol)['qos'])

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_template_account')
    def test_create_volume(self,
                           _mock_create_template_account,
                           _mock_issue_api_request):
        _mock_issue_api_request.side_effect = self.fake_issue_api_request
        _mock_create_template_account.return_value = 1
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}
        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'}]

        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx, **testvol)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
            mock.patch.object(sfv,
                              '_get_account_create_availability',
                              return_value=fake_sfaccounts[0]):

            model_update = sfv.create_volume(testvol)
            self.assertIsNotNone(model_update)
            self.assertIsNone(model_update.get('provider_geometry', None))

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_template_account')
    def test_create_volume_non_512e(self,
                                    _mock_create_template_account,
                                    _mock_issue_api_request):
        _mock_issue_api_request.side_effect = self.fake_issue_api_request
        _mock_create_template_account.return_value = 1
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx, **testvol)

        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'}]

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
            mock.patch.object(sfv,
                              '_issue_api_request',
                              side_effect=self.fake_issue_api_request), \
            mock.patch.object(sfv,
                              '_get_account_create_availability',
                              return_value=fake_sfaccounts[0]):

            self.configuration.sf_emulate_512 = False
            model_update = sfv.create_volume(testvol)
            self.configuration.sf_emulate_512 = True
            self.assertEqual('4096 4096',
                             model_update.get('provider_geometry', None))

    def test_create_delete_snapshot(self):
        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx)

        testsnap_dict = {'project_id': 'testprjid',
                         'name': testvol.name,
                         'volume_size': testvol.size,
                         'id': 'b831c4d1-d1f0-11e1-9b23-0800200c9a66',
                         'volume_id': testvol.id,
                         'volume_type_id': None,
                         'created_at': timeutils.utcnow(),
                         'provider_id': '8 99 None',
                         'volume': testvol}
        testsnap = fake_snapshot.fake_snapshot_obj(ctx, **testsnap_dict)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        fake_uuid = 'UUID-b831c4d1-d1f0-11e1-9b23-0800200c9a66'
        with mock.patch.object(
                solidfire.SolidFireDriver,
                '_get_sf_snapshots',
                return_value=[{'snapshotID': '5',
                               'name': fake_uuid,
                               'volumeID': 5}]), \
                mock.patch.object(sfv,
                                  '_get_sfaccounts_for_tenant',
                                  return_value=[{'accountID': 5,
                                                 'username':
                                                 'prefix-testprjid'}]),\
                mock.patch.object(sfv, '_retrieve_replication_settings',
                                  return_value=["Async", {}]),\
                mock.patch.object(sfv, '_get_sf_volume',
                                  return_value={'volumeID': 33}):
            sfv.create_snapshot(testsnap)
            sfv.delete_snapshot(testsnap)

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_template_account')
    def test_create_clone(self,
                          _mock_create_template_account,
                          _mock_issue_api_request):
        _mock_issue_api_request.side_effect = self.fake_issue_api_request
        _mock_create_template_account.return_value = 1
        _fake_get_snaps = [{'snapshotID': 5, 'name': 'testvol'}]
        _fake_get_volume = (
            {'volumeID': 99,
             'name': 'UUID-a720b3c0-d1f0-11e1-9b23-0800200c9a66',
             'attributes': {}})

        updates_vol_a = {'project_id': 'testprjid',
                         'name': 'testvol',
                         'size': 1,
                         'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                         'volume_type_id': None,
                         'created_at': timeutils.utcnow()}

        updates_vol_b = {'project_id': 'testprjid',
                         'name': 'testvol',
                         'size': 1,
                         'id': 'b831c4d1-d1f0-11e1-9b23-0800200c9a66',
                         'volume_type_id': None,
                         'created_at': timeutils.utcnow()}

        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx, **updates_vol_a)
        testvol_b = fake_volume.fake_volume_obj(ctx, **updates_vol_b)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sf_snapshots',
                               return_value=_fake_get_snaps), \
                mock.patch.object(sfv,
                                  '_get_sf_volume',
                                  return_value=_fake_get_volume), \
                mock.patch.object(sfv,
                                  '_issue_api_request',
                                  side_effect=self.fake_issue_api_request), \
                mock.patch.object(sfv,
                                  '_get_sfaccounts_for_tenant',
                                  return_value=[]), \
                mock.patch.object(sfv,
                                  '_get_model_info',
                                  return_value={}):
            sfv.create_cloned_volume(testvol_b, testvol)

    def test_initialize_connector_with_blocksizes(self):
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'provider_location': '10.10.7.1:3260 iqn.2010-01.com.'
                                        'solidfire:87hg.uuid-2cc06226-cc'
                                        '74-4cb7-bd55-14aed659a0cc.4060 0',
                   'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                                    'c76370d66b 2FE0CQ8J196R',
                   'provider_geometry': '4096 4096',
                   'created_at': timeutils.utcnow(),
                   }

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        properties = sfv.initialize_connection(testvol, connector)
        self.assertEqual('4096', properties['data']['physical_block_size'])
        self.assertEqual('4096', properties['data']['logical_block_size'])
        self.assertTrue(properties['data']['discard'])

    def test_create_volume_fails(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is inentional for this test
        self.mock_object(solidfire.SolidFireDriver,
                         '_update_cluster_status',
                         self.fake_update_cluster_status)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request_fails)
        try:
            sfv.create_volume(testvol)
            self.fail("Should have thrown Error")
        except Exception:
            pass

    def test_create_sfaccount(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        account = sfv._create_sfaccount('some-name')
        self.assertIsNotNone(account)

    def test_create_sfaccount_fails(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request_fails)
        self.assertRaises(exception.SolidFireAPIException,
                          sfv._create_sfaccount, 'project-id')

    def test_get_sfaccounts_for_tenant(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        accounts = sfv._get_sfaccounts_for_tenant('some-name')
        self.assertIsNotNone(accounts)

    def test_get_sfaccounts_for_tenant_fails(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request_fails)
        self.assertRaises(exception.SolidFireAPIException,
                          sfv._get_sfaccounts_for_tenant, 'some-name')

    def test_get_sfaccount_by_name(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        account = sfv._get_sfaccount_by_name('some-name')
        self.assertIsNotNone(account)

    def test_get_account_create_availability_no_account(self):
        fake_sfaccounts = []
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfaccount = sfv._get_account_create_availability(fake_sfaccounts)
        self.assertIsNone(sfaccount)

    def test_get_account_create_availability(self):
        fake_sfaccounts = [{'accountID': 29,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid',
                            'volumes': [6, 7, 20]}]
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfaccount = sfv._get_account_create_availability(fake_sfaccounts)
        self.assertIsNotNone(sfaccount)
        self.assertEqual(sfaccount['accountID'],
                         fake_sfaccounts[0]['accountID'])

    def test_get_account_create_availability_primary_full(self):
        fake_sfaccounts = [{'accountID': 30,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'}]
        get_sfaccount_result = {'accountID': 31,
                                'targetSecret': 'shhhh',
                                'username': 'prefix-testprjid_'}
        get_vol_result = list(range(1, 2001))
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
                mock.patch.object(sfv,
                                  '_get_volumes_for_account',
                                  return_value=get_vol_result):
            sfaccount = sfv._get_account_create_availability(fake_sfaccounts)
            self.assertIsNotNone(sfaccount)
            self.assertEqual(sfaccount['username'],
                             get_sfaccount_result['username'])

    def test_get_account_create_availability_both_full(self):
        fake_sfaccounts = [{'accountID': 32,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'},
                           {'accountID': 33,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid_'}]
        get_vol_result = list(range(1, 2001))
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
                mock.patch.object(sfv,
                                  '_get_volumes_for_account',
                                  return_value=get_vol_result):
            sfaccount = sfv._get_account_create_availability(fake_sfaccounts)
            self.assertIsNone(sfaccount)

    def test_get_create_account(self):
        fake_sfaccounts = [{'accountID': 34,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'},
                           {'accountID': 35,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid_'}]
        get_vol_result = list(range(1, 2001))
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
                mock.patch.object(sfv,
                                  '_get_volumes_for_account',
                                  return_value=get_vol_result):
            sfaccount = sfv._get_account_create_availability(fake_sfaccounts)
            self.assertRaises(exception.SolidFireDriverException,
                              sfv._get_create_account, sfaccount)

    def test_get_sfaccount_by_name_fails(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request_fails)
        self.assertRaises(exception.SolidFireAPIException,
                          sfv._get_sfaccount_by_name, 'some-name')

    def test_get_sfvol_by_cinder_vref_no_provider_id(self):
        fake_sfaccounts = [{'accountID': 25,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid',
                            'volumes': [6, 7, 20]}]
        self.mock_vref = mock_vref()

        vol_result = {'volumeID': 5,
                      'name': 'test_volume',
                      'accountID': 25,
                      'sliceCount': 1,
                      'totalSize': 1 * units.Gi,
                      'enable512e': True,
                      'access': "readWrite",
                      'status': "active",
                      'attributes': {'uuid': f_uuid[0]},
                      'qos': None,
                      'iqn': 'super_fake_iqn'}

        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value = fake_sfaccounts), \
                mock.patch.object(sfv, '_issue_api_request',
                                  side_effect = self.fake_issue_api_request):
            self.mock_vref['provider_id'] = None
            sfvol = sfv._get_sfvol_by_cinder_vref(self.mock_vref)
            self.assertIsNotNone(sfvol)
            self.assertEqual(sfvol['attributes']['uuid'],
                             vol_result['attributes']['uuid'])
            self.assertEqual(sfvol['volumeID'], vol_result['volumeID'])

    def test_get_sfvol_by_cinder_vref_no_provider_id_nomatch(self):
        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid',
                            'volumes': [5, 6, 7, 8]}]

        self.mock_vref = mock_vref()
        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True

        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value = fake_sfaccounts), \
                mock.patch.object(sfv, '_issue_api_request',
                                  side_effect = self.fake_issue_api_request):
            self.mock_vref['provider_id'] = None
            self.mock_vref['id'] = '142b9c32-a71A-4fbe-830c-c20c5596caea'
            sfvol = sfv._get_sfvol_by_cinder_vref(self.mock_vref)
            self.assertIsNone(sfvol)

    def test_get_sfvol_by_cinder_vref_nomatch(self):
        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid',
                            'volumes': [5, 6, 7, 8]}]

        self.mock_vref = mock_vref()
        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value = fake_sfaccounts), \
                mock.patch.object(sfv, '_issue_api_request',
                                  side_effect = self.fake_issue_api_request):
            p_i = '324 8 6ecebf5d-5521-4ce1-80f3-358ebc1b9cdc'
            self.mock_vref['provider_id'] = p_i
            self.mock_vref['id'] = '142b9c32-a71A-4fbe-830c-c20c5596caea'
            sfvol = sfv._get_sfvol_by_cinder_vref(self.mock_vref)
            self.assertIsNone(sfvol)

    def test_get_sfvol_by_cinder_vref(self):
        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid',
                            'volumes': [5, 6, 7, 8]}]

        self.mock_vref = mock_vref()

        get_vol_result = {'volumeID': 5,
                          'name': 'test_volume',
                          'accountID': 25,
                          'sliceCount': 1,
                          'totalSize': 1 * units.Gi,
                          'enable512e': True,
                          'access': "readWrite",
                          'status': "active",
                          'attributes': {'uuid': f_uuid[0]},
                          'qos': None,
                          'iqn': 'super_fake_iqn'}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv, '_get_sfaccounts_for_tenant',
                               return_value = fake_sfaccounts), \
                mock.patch.object(sfv, '_issue_api_request',
                                  side_effect = self.fake_issue_api_request):

            sfvol = sfv._get_sfvol_by_cinder_vref(self.mock_vref)
            self.assertIsNotNone(sfvol)
            self.assertEqual(get_vol_result['volumeID'], sfvol['volumeID'])

    def test_delete_volume(self):
        vol_id = 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'
        testvol = test_utils.create_volume(
            self.ctxt,
            id=vol_id,
            display_name='test_volume',
            provider_id='1 5 None',
            multiattach=False)

        fake_sfaccounts = [{'accountID': 5,
                            'name': 'testprjid',
                            'targetSecret': 'shhhh',
                            'username': 'john-wayne'}]

        get_vol_result = {'volumeID': 5,
                          'name': 'test_volume',
                          'accountID': 25,
                          'sliceCount': 1,
                          'totalSize': 1 * units.Gi,
                          'enable512e': True,
                          'access': "readWrite",
                          'status': "active",
                          'attributes': {},
                          'qos': None,
                          'iqn': 'super_fake_iqn'}

        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
            mock.patch.object(sfv,
                              '_get_sfvol_by_cinder_vref',
                              return_value=get_vol_result), \
            mock.patch.object(sfv,
                              '_issue_api_request'), \
            mock.patch.object(sfv,
                              '_remove_volume_from_vags') as rem_vol:

            sfv.delete_volume(testvol)
            rem_vol.not_called(get_vol_result['volumeID'])

    def test_delete_multiattach_volume(self):
        vol_id = 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'
        testvol = test_utils.create_volume(
            self.ctxt,
            id=vol_id,
            display_name='test_volume',
            provider_id='1 5 None',
            multiattach=True)

        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'}]

        get_vol_result = {'volumeID': 5,
                          'name': 'test_volume',
                          'accountID': 25,
                          'sliceCount': 1,
                          'totalSize': 1 * units.Gi,
                          'enable512e': True,
                          'access': "readWrite",
                          'status': "active",
                          'attributes': {},
                          'qos': None,
                          'iqn': 'super_fake_iqn'}

        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
            mock.patch.object(sfv,
                              '_get_sfvol_by_cinder_vref',
                              return_value=get_vol_result), \
            mock.patch.object(sfv,
                              '_issue_api_request'), \
            mock.patch.object(sfv,
                              '_remove_volume_from_vags') as rem_vol:

            sfv.delete_volume(testvol)
            rem_vol.assert_called_with(get_vol_result['volumeID'])

    def test_delete_volume_no_volume_on_backend(self):
        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'}]
        fake_no_volumes = []
        testvol = test_utils.create_volume(self.ctxt)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
            mock.patch.object(sfv,
                              '_get_volumes_for_account',
                              return_value=fake_no_volumes):
            sfv.delete_volume(testvol)

    def test_delete_snapshot_no_snapshot_on_backend(self):
        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'}]
        fake_no_volumes = []
        testvol = test_utils.create_volume(
            self.ctxt,
            volume_id='b831c4d1-d1f0-11e1-9b23-0800200c9a66')
        testsnap = test_utils.create_snapshot(
            self.ctxt,
            volume_id=testvol.id)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
            mock.patch.object(sfv,
                              '_get_volumes_for_account',
                              return_value=fake_no_volumes):
            sfv.delete_snapshot(testsnap)

    def fake_ext_qos_issue_api_request(obj, method, params, version='1.0',
                                       endpoint=None):
        EXPECTED_SIZE = 2 << 30  # 2147483648 size + increase

        if method == 'ModifyVolume':
            response = {'error': {'code': 0,
                                  'name': 'Extend Volume',
                                  'message': 'extend fail, size/scale-iops'},
                        'id': 1}
            if params.get('totalSize', None) != EXPECTED_SIZE:
                msg = ('Error (%s) encountered during '
                       'SolidFire API call.' % response['error']['name'])
                raise exception.SolidFireAPIException(message=msg)

            if params.get('qos', None) != SolidFireVolumeTestCase.EXPECTED_QOS:
                msg = ('Error (%s) encountered during '
                       'SolidFire API call.' % response['error']['name'])
                raise exception.SolidFireAPIException(message=msg)

            return {'result': {}, 'id': 1}

        elif method == 'GetAccountByName' and version == '1.0':
            results = {'result': {'account':
                                  {'accountID': 25,
                                   'username': params['username'],
                                   'status': 'active',
                                   'initiatorSecret': '123456789012',
                                   'targetSecret': '123456789012',
                                   'attributes': {},
                                   'volumes': [6, 7, 20]}},
                       "id": 1}
            return results

        elif method == 'ListVolumesForAccount' and version == '1.0':
            test_name = 'OS-VOLID-a720b3c0-d1f0-11e1-9b23-0800200c9a66'
            result = {'result': {
                'volumes': [{'volumeID': 5,
                             'name': test_name,
                             'accountID': 25,
                             'sliceCount': 1,
                             'totalSize': 1 * units.Gi,
                             'enable512e': True,
                             'access': "readWrite",
                             'status': "active",
                             'attributes': {},
                             'qos': None,
                             'iqn': test_name}]}}
            return result

        else:
            return None

    def test_extend_volume(self):
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.extend_volume(testvol, 2)

    def test_extend_volume_with_scaled_qos(self):
        size = 1
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        qos_ref = qos_specs.create(self.ctxt,
                                   'qos-specs-1', {'minIOPS': '100',
                                                   'maxIOPS': '1000',
                                                   'burstIOPS': '1500',
                                                   'scaledIOPS': 'True',
                                                   'scaleMin': '10',
                                                   'scaleMax': '20',
                                                   'scaleBurst': '30'})
        type_ref = volume_types.create(self.ctxt, "type1",
                                       {'qos:minIOPS': '1000',
                                        'qos:maxIOPS': '10000',
                                        'qos:burstIOPS': '20000'})
        qos_specs.associate_qos_with_type(self.ctxt,
                                          qos_ref['id'],
                                          type_ref['id'])
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'], size + 1)
        self.assertEqual(SolidFireVolumeTestCase.EXPECTED_QOS, qos)

    def test_extend_volume_fails_no_volume(self):
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'not-found'}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.assertRaises(exception.VolumeNotFound,
                          sfv.extend_volume,
                          testvol, 2)

    def test_extend_volume_fails_account_lookup(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is intentional for this test
        self.mock_object(solidfire.SolidFireDriver,
                         '_update_cluster_status',
                         self.fake_update_cluster_status)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request_fails)
        self.assertRaises(exception.SolidFireAPIException,
                          sfv.extend_volume,
                          testvol, 2)

    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_retrieve_qos_setting')
    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver,
                       '_retrieve_replication_settings')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_cluster_reference')
    def test_extend_replicated_volume(self, mock_create_cluster_reference,
                                      mock_retrieve_replication_settings,
                                      mock_issue_api_request,
                                      mock_retrieve_qos_setting,
                                      mock_get_sf_volume,
                                      mock_get_sfaccount):

        mock_create_cluster_reference.return_value = {
            'mvip': self.mvip,
            'svip': self.svip}

        mock_retrieve_replication_settings.return_value = "Async"
        mock_retrieve_qos_setting.return_value = None
        self.fake_sfvol['volumePairs'] = [{'remoteVolumeID': 26}]
        mock_get_sf_volume.return_value = self.fake_sfvol
        mock_get_sfaccount.return_value = self.fake_sfaccount

        ctx = context.get_admin_context()
        utc_now = timeutils.utcnow().isoformat()
        vol_fields = {
            'id': f_uuid,
            'created_at': utc_now
        }
        vol = fake_volume.fake_volume_obj(ctx, **vol_fields)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = True
        sfv.cluster_pairs = self.cluster_pairs
        sfv.active_cluster['mvip'] = self.mvip
        sfv.active_cluster['svip'] = self.svip

        mock_issue_api_request.reset_mock()
        updates = sfv.extend_volume(vol, vol.size + 10)
        self.assertIsNone(updates)

        modify_params = {
            'volumeID': self.fake_sfvol['volumeID'],
            'totalSize': int((vol.size + 10) * units.Gi),
            'qos': None
        }
        modify_params2 = modify_params.copy()
        modify_params2['volumeID'] = 26

        expected_calls = [
            mock.call("ModifyVolume", modify_params, version='5.0'),
            mock.call("ModifyVolume", modify_params2, version='5.0',
                      endpoint=self.cluster_pairs[0]['endpoint'])
        ]

        mock_issue_api_request.assert_has_calls(expected_calls)
        mock_create_cluster_reference.assert_called()
        mock_retrieve_replication_settings.assert_called_with(vol)
        mock_retrieve_qos_setting.assert_called_with(vol, vol.size + 10)
        mock_get_sf_volume.assert_called_with(
            vol.id, {'accountID': self.fake_sfaccount['accountID']})
        mock_get_sfaccount.assert_called_with(vol.project_id)

    def test_set_by_qos_spec_with_scoping(self):
        size = 1
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        qos_ref = qos_specs.create(self.ctxt,
                                   'qos-specs-1', {'qos:minIOPS': '1000',
                                                   'qos:maxIOPS': '10000',
                                                   'qos:burstIOPS': '20000'})
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:minIOPS": "100",
                                                 "qos:burstIOPS": "300",
                                                 "qos:maxIOPS": "200"})
        qos_specs.associate_qos_with_type(self.ctxt,
                                          qos_ref['id'],
                                          type_ref['id'])
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'], size)
        self.assertEqual(self.expected_qos_results, qos)

    def test_set_by_qos_spec(self):
        size = 1
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        qos_ref = qos_specs.create(self.ctxt,
                                   'qos-specs-1', {'minIOPS': '1000',
                                                   'maxIOPS': '10000',
                                                   'burstIOPS': '20000'})
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:minIOPS": "100",
                                                 "qos:burstIOPS": "300",
                                                 "qos:maxIOPS": "200"})
        qos_specs.associate_qos_with_type(self.ctxt,
                                          qos_ref['id'],
                                          type_ref['id'])
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'], size)
        self.assertEqual(self.expected_qos_results, qos)

    @ddt.file_data("scaled_iops_test_data.json")
    @ddt.unpack
    def test_scaled_qos_spec_by_type(self, argument):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        size = argument[0].pop('size')
        type_ref = volume_types.create(self.ctxt, "type1", argument[0])
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'], size)
        self.assertEqual(argument[1], qos)

    @ddt.file_data("scaled_iops_invalid_data.json")
    @ddt.unpack
    def test_set_scaled_qos_by_type_invalid(self, inputs):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        size = inputs[0].pop('size')
        type_ref = volume_types.create(self.ctxt, "type1", inputs[0])
        self.assertRaises(exception.InvalidQoSSpecs,
                          sfv._set_qos_by_volume_type,
                          self.ctxt,
                          type_ref['id'],
                          size)

    def test_accept_transfer(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        expected = {'provider_auth': 'CHAP cinder-new_project 123456789012'}
        self.assertEqual(expected,
                         sfv.accept_transfer(self.ctxt,
                                             testvol,
                                             'new_user', 'new_project'))

    def test_accept_transfer_volume_not_found_raises(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                   'created_at': timeutils.utcnow()}
        self.assertRaises(exception.VolumeNotFound,
                          sfv.accept_transfer,
                          self.ctxt,
                          testvol,
                          'new_user',
                          'new_project')

    def test_retype(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:minIOPS": "500",
                                                 "qos:burstIOPS": "2000",
                                                 "qos:maxIOPS": "1000"})
        diff = {'encryption': {}, 'qos_specs': {},
                'extra_specs': {'qos:burstIOPS': ('10000', u'2000'),
                                'qos:minIOPS': ('1000', u'500'),
                                'qos:maxIOPS': ('10000', u'1000')}}
        host = None
        updates = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx, **updates)

        migrated, updates = sfv.retype(self.ctxt, testvol, type_ref,
                                       diff, host)
        self.assertTrue(migrated)
        self.assertEqual({}, updates)

    def test_retype_with_qos_spec(self):
        test_type = {'name': 'sf-1',
                     'qos_specs_id': 'fb0576d7-b4b5-4cad-85dc-ca92e6a497d1',
                     'deleted': False,
                     'created_at': '2014-02-06 04:58:11',
                     'updated_at': None,
                     'extra_specs': {},
                     'deleted_at': None,
                     'id': 'e730e97b-bc7d-4af3-934a-32e59b218e81'}

        test_qos_spec = {'id': 'asdfafdasdf',
                         'specs': {'minIOPS': '1000',
                                   'maxIOPS': '2000',
                                   'burstIOPS': '3000'}}

        def _fake_get_volume_type(ctxt, type_id):
            return test_type

        def _fake_get_qos_spec(ctxt, spec_id):
            return test_qos_spec

        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        self.mock_object(volume_types, 'get_volume_type',
                         _fake_get_volume_type)
        self.mock_object(qos_specs, 'get_qos_specs',
                         _fake_get_qos_spec)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        diff = {'encryption': {}, 'extra_specs': {},
                'qos_specs': {'burstIOPS': ('10000', '2000'),
                              'minIOPS': ('1000', '500'),
                              'maxIOPS': ('10000', '1000')}}
        host = None
        updates = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx, **updates)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        migrated, updates = sfv.retype(self.ctxt, testvol, test_type,
                                       diff, host)
        self.assertTrue(migrated)
        self.assertEqual({}, updates)

    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_set_rep_by_volume_type')
    @mock.patch.object(solidfire.SolidFireDriver,
                       '_retrieve_replication_settings')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_default_volume_params')
    @mock.patch.object(solidfire.SolidFireDriver, '_replicate_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_disable_replication')
    @mock.patch.object(solidfire.SolidFireDriver, '_set_qos_by_volume_type')
    def test_retype_replicated(self,
                               mock_set_qos_by_volume_type,
                               mock_disable_replication,
                               mock_replicate_volume,
                               mock_get_default_volume_params,
                               mock_retrieve_replication_settings,
                               mock_set_rep_by_volume_type,
                               mock_get_sf_volume,
                               mock_get_sfaccount):

        all_mocks = locals()
        mock_get_sf_volume.return_value = None
        mock_get_sfaccount.return_value = self.fake_sfaccount
        mock_retrieve_replication_settings.return_value = 'Async'

        ctx = context.get_admin_context()
        type_fields = {'extra_specs': {'replication_enabled': '<is> True'},
                       'id': fakes.get_fake_uuid()}
        src_vol_type = fake_volume.fake_volume_type_obj(ctx, **type_fields)

        fake_provider_id = "%s %s %s" % (
            self.fake_sfvol['volumeID'],
            fakes.FAKE_UUID,
            self.cluster_pairs[0]['uuid'])
        utc_now = timeutils.utcnow().isoformat()
        vol_fields = {
            'id': fakes.FAKE_UUID,
            'created_at': utc_now,
            'volume_type': src_vol_type,
            'volume_type_id': src_vol_type.id,
            'provider_id': fake_provider_id
        }

        vol = fake_volume.fake_volume_obj(ctx, **vol_fields)
        dst_vol_type = fake_volume.fake_volume_type_obj(ctx)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = True
        sfv.cluster_pairs = self.cluster_pairs
        sfv.active_cluster['mvip'] = self.mvip
        sfv.active_cluster['svip'] = self.svip

        self.assertRaises(exception.VolumeNotFound,
                          sfv.retype, ctx, vol, dst_vol_type, None, None)
        mock_get_sfaccount.assert_called_once_with(vol.project_id)
        mock_get_sf_volume.assert_called_once_with(
            vol.id, {'accountID': self.fake_sfaccount['accountID']})

        mock_get_sfaccount.reset_mock()
        mock_get_sf_volume.reset_mock()
        expected = {"key": "value"}
        mock_get_sf_volume.return_value = self.fake_sfvol
        mock_replicate_volume.return_value = expected
        mock_set_rep_by_volume_type.side_effect = [src_vol_type, dst_vol_type]

        retyped, updates = sfv.retype(ctx, vol, dst_vol_type, None, None)
        self.assertDictEqual(expected, updates)

        mock_get_sfaccount.assert_called_once_with(vol.project_id)
        mock_get_sf_volume.assert_called_once_with(
            vol.id, {'accountID': self.fake_sfaccount['accountID']})
        mock_get_default_volume_params.assert_called()
        mock_disable_replication.assert_not_called()
        mock_replicate_volume.assert_called_once()
        mock_retrieve_replication_settings.assert_called_once()
        mock_set_qos_by_volume_type.assert_called_once()

        expected = {}
        for mk in all_mocks.values():
            if isinstance(mk, mock.MagicMock):
                mk.reset_mock()

        mock_set_rep_by_volume_type.side_effect = [src_vol_type, None]
        retyped, updates = sfv.retype(ctx, vol, dst_vol_type, None, None)
        self.assertDictEqual(expected, updates)
        mock_get_sfaccount.assert_called_once_with(vol.project_id)
        mock_get_sf_volume.assert_called_once_with(
            vol.id, {'accountID': self.fake_sfaccount['accountID']})
        mock_get_default_volume_params.assert_not_called()
        mock_disable_replication.assert_called_with(vol)
        mock_replicate_volume.assert_not_called()
        mock_retrieve_replication_settings.assert_not_called()
        mock_set_qos_by_volume_type.assert_called_once()

    def test_update_cluster_status(self):
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv._update_cluster_status()
        self.assertEqual(99.0, sfv.cluster_stats['free_capacity_gb'])
        self.assertEqual(100.0, sfv.cluster_stats['total_capacity_gb'])

        sfv.configuration.sf_provisioning_calc = 'usedSpace'
        sfv._update_cluster_status()
        self.assertEqual(49.0, sfv.cluster_stats['free_capacity_gb'])
        self.assertEqual(50.0, sfv.cluster_stats['total_capacity_gb'])
        self.assertTrue(sfv.cluster_stats['thin_provisioning_support'])
        self.assertEqual(self.configuration.max_over_subscription_ratio,
                         sfv.cluster_stats['max_over_subscription_ratio'])

    def test_get_provisioned_capacity(self):
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        prov_cap = sfv._get_provisioned_capacity()
        # Sum of totalSize of the volumes mocked is
        # (int(1.75 * units.Gi)) * 2 = 3758096384
        self.assertEqual(3758096384, prov_cap)

    def test_update_cluster_status_mvip_unreachable(self):
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=self.fake_issue_api_request_fails):
            sfv._update_cluster_status()
            self.assertEqual(0, sfv.cluster_stats['free_capacity_gb'])
            self.assertEqual(0, sfv.cluster_stats['total_capacity_gb'])

    def test_manage_existing_volume(self):
        external_ref = {'name': 'existing volume', 'source-id': 5}
        updates = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx, **updates)

        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        model_update = sfv.manage_existing(testvol, external_ref)
        self.assertIsNotNone(model_update)
        self.assertIsNone(model_update.get('provider_geometry', None))

    def test_manage_existing_get_size(self):
        external_ref = {'name': 'existing volume', 'source-id': 5}
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        mock_issue_api_request = self.mock_object(solidfire.SolidFireDriver,
                                                  '_issue_api_request')
        mock_issue_api_request.side_effect = self.fake_issue_api_request
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        size = sfv.manage_existing_get_size(testvol, external_ref)
        self.assertEqual(2, size)

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_template_account')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_create_account')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_default_volume_params')
    @mock.patch.object(solidfire.SolidFireDriver,
                       '_retrieve_replication_settings')
    @mock.patch.object(solidfire.SolidFireDriver, '_replicate_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_model_info')
    @mock.patch.object(solidfire.SolidFireDriver, '_update_cluster_status')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_cluster_reference')
    def test_manage_existing_replicated_fail(
            self,
            mock_create_cluster_reference,
            mock_update_cluster_status,
            mock_get_model_info,
            mock_replicate_volume,
            mock_retrieve_replication_settings,
            mock_get_default_volume_params,
            mock_get_create_account,
            mock_create_template_account,
            mock_issue_api_request):

        mock_retrieve_replication_settings.return_value = 'Async'
        mock_get_default_volume_params.return_value = {'totalSize': 50}
        mock_get_create_account.return_value = self.fake_sfaccount
        mock_replicate_volume.side_effect = solidfire.SolidFireAPIException

        ctx = context.get_admin_context()
        type_fields = {'extra_specs': {'replication_enabled': '<is> True'},
                       'id': fakes.get_fake_uuid()}
        vol_type = fake_volume.fake_volume_type_obj(ctx, **type_fields)

        fake_provider_id = "%s %s %s" % (
            self.fake_sfvol['volumeID'],
            fakes.FAKE_UUID,
            self.cluster_pairs[0]['uuid'])
        utc_now = timeutils.utcnow().isoformat()
        vol_fields = {
            'id': fakes.FAKE_UUID,
            'created_at': utc_now,
            'volume_type': vol_type,
            'volume_type_id': vol_type.id,
            'provider_id': fake_provider_id
        }

        vol = fake_volume.fake_volume_obj(ctx, **vol_fields)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = True
        sfv.active_cluster['mvip'] = self.mvip
        sfv.active_cluster['svip'] = self.svip

        external_ref = {}
        self.assertRaises(solidfire.SolidFireAPIException,
                          sfv.manage_existing, vol, external_ref)

        self.fake_sfvol['volumePairs'] = [{'remoteVolumeID': 26}]
        mock_issue_api_request.return_value = {
            'result': {'volumes': [self.fake_sfvol]}}
        external_ref = {'source-id': 6, 'name': 'new-being-managed'}
        self.assertRaises(solidfire.SolidFireDriverException,
                          sfv.manage_existing, vol, external_ref)

        mock_get_default_volume_params.return_value = {'totalSize': 50}
        self.fake_sfvol['volumePairs'] = []
        mock_issue_api_request.return_value = {
            'result': {'volumes': [self.fake_sfvol]}}
        self.assertRaises(solidfire.SolidFireAPIException,
                          sfv.manage_existing, vol, external_ref)

        modify_attributes = {'uuid': vol.id,
                             'is_clone': 'False',
                             'os_imported_at': utc_now + "+00:00",
                             'old_name': 'new-being-managed'}
        modify_params1 = {'volumeID': self.fake_sfvol['volumeID'],
                          'attributes': modify_attributes}
        modify_params2 = {'volumeID': self.fake_sfvol['volumeID'],
                          'attributes': self.fake_sfvol['attributes']}
        calls = [mock.call('ListActiveVolumes',
                           {'startVolumeID': self.fake_sfvol['volumeID'],
                            'limit': 1}),
                 mock.call('ModifyVolume', modify_params1, version='5.0'),
                 mock.call('ModifyVolume', modify_params2, version='5.0')]

        mock_issue_api_request.assert_has_calls(calls)
        mock_get_model_info.assert_not_called()
        mock_create_cluster_reference.assert_called_once()
        mock_update_cluster_status.assert_called_once()
        mock_replicate_volume.assert_called()
        mock_retrieve_replication_settings.assert_called_with(vol)
        mock_get_default_volume_params.assert_called_with(vol)
        mock_get_create_account.assert_called_with(vol.project_id)

    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_set_rep_by_volume_type')
    @mock.patch.object(solidfire.SolidFireDriver,
                       '_retrieve_replication_settings')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_default_volume_params')
    @mock.patch.object(solidfire.SolidFireDriver, '_replicate_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_disable_replication')
    @mock.patch.object(solidfire.SolidFireDriver, '_set_qos_by_volume_type')
    def test_manage_existing_replicated(
            self,
            mock_set_qos_by_volume_type,
            mock_disable_replication,
            mock_replicate_volume,
            mock_get_default_volume_params,
            mock_retrieve_replication_settings,
            mock_set_rep_by_volume_type,
            mock_get_sf_volume,
            mock_get_sfaccount):

        mock_get_sf_volume.return_value = None
        mock_get_sfaccount.return_value = self.fake_sfaccount
        mock_retrieve_replication_settings.return_value = 'Async'

        ctx = context.get_admin_context()
        type_fields = {'extra_specs': {'replication_enabled': '<is> True'},
                       'id': fakes.get_fake_uuid()}
        src_vol_type = fake_volume.fake_volume_type_obj(ctx, **type_fields)

        fake_provider_id = "%s %s %s" % (
            self.fake_sfvol['volumeID'],
            fakes.FAKE_UUID,
            self.cluster_pairs[0]['uuid'])
        utc_now = timeutils.utcnow().isoformat()
        vol_fields = {
            'id': fakes.FAKE_UUID,
            'created_at': utc_now,
            'volume_type': src_vol_type,
            'volume_type_id': src_vol_type.id,
            'provider_id': fake_provider_id
        }

        vol = fake_volume.fake_volume_obj(ctx, **vol_fields)
        dst_vol_type = fake_volume.fake_volume_type_obj(ctx)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = True
        sfv.cluster_pairs = self.cluster_pairs
        sfv.active_cluster['mvip'] = self.mvip
        sfv.active_cluster['svip'] = self.svip

        self.assertRaises(exception.VolumeNotFound,
                          sfv.retype, ctx, vol, dst_vol_type, None, None)
        mock_get_sfaccount.assert_called_once_with(vol.project_id)
        mock_get_sf_volume.assert_called_once_with(
            vol.id, {'accountID': self.fake_sfaccount['accountID']})

        mock_get_sfaccount.reset_mock()
        mock_get_sf_volume.reset_mock()
        expected = {"key": "value"}
        mock_get_sf_volume.return_value = self.fake_sfvol
        mock_replicate_volume.return_value = expected
        mock_set_rep_by_volume_type.side_effect = [src_vol_type, dst_vol_type]

        retyped, updates = sfv.retype(ctx, vol, dst_vol_type, None, None)
        self.assertDictEqual(expected, updates)

        mock_get_sfaccount.assert_called_once_with(vol.project_id)
        mock_get_sf_volume.assert_called_once_with(
            vol.id, {'accountID': self.fake_sfaccount['accountID']})
        mock_get_default_volume_params.assert_called()
        mock_disable_replication.assert_not_called()
        mock_replicate_volume.assert_called_once()
        mock_retrieve_replication_settings.assert_called_once()
        mock_set_qos_by_volume_type.assert_called_once()
        mock_set_rep_by_volume_type.assert_called()

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_template_account')
    def test_create_volume_for_migration(self,
                                         _mock_create_template_account,
                                         _mock_issue_api_request):
        _mock_issue_api_request.side_effect = self.fake_issue_api_request
        _mock_create_template_account.return_value = 1
        testvol = {'project_id': 'testpsrjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'b830b3c0-d1f0-11e1-9b23-1900200c9a77',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow(),
                   'migration_status': 'target:'
                                       'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        ctx = context.get_admin_context()
        testvol = fake_volume.fake_volume_obj(ctx, **testvol)
        fake_sfaccounts = [{'accountID': 5,
                            'targetSecret': 'shhhh',
                            'username': 'prefix-testprjid'}]

        def _fake_do_v_create(project_id, params):
            return project_id, params

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
                mock.patch.object(sfv,
                                  '_get_account_create_availability',
                                  return_value=fake_sfaccounts[0]), \
                mock.patch.object(sfv,
                                  '_do_volume_create',
                                  side_effect=_fake_do_v_create):

            project_id, sf_vol_object = sfv.create_volume(testvol)
            self.assertEqual('a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                             sf_vol_object['attributes']['uuid'])
            self.assertEqual('b830b3c0-d1f0-11e1-9b23-1900200c9a77',
                             sf_vol_object['attributes']['migration_uuid'])
            self.assertEqual('UUID-a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                             sf_vol_object['name'])

    @mock.patch.object(solidfire.SolidFireDriver, '_update_cluster_status')
    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_image_volume')
    def test_verify_image_volume_out_of_date(self,
                                             _mock_create_image_volume,
                                             _mock_get_sf_volume,
                                             _mock_get_sfaccount,
                                             _mock_issue_api_request,
                                             _mock_update_cluster_status):
        fake_sf_vref = {
            'status': 'active', 'volumeID': 1,
            'attributes': {
                'image_info':
                    {'image_updated_at': '2014-12-17T00:16:23+00:00',
                     'image_id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                     'image_name': 'fake-image',
                     'image_created_at': '2014-12-17T00:16:23+00:00'}}}

        _mock_update_cluster_status.return_value = None
        _mock_issue_api_request.side_effect = (
            self.fake_issue_api_request)
        _mock_get_sfaccount.return_value = {'username': 'openstack-vtemplate',
                                            'accountID': 7777}
        _mock_get_sf_volume.return_value = fake_sf_vref
        _mock_create_image_volume.return_value = fake_sf_vref

        image_meta = {'id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                      'updated_at': datetime.datetime(2013, 9, 28,
                                                      15, 27, 36,
                                                      325355)}
        image_service = 'null'

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv._verify_image_volume(self.ctxt, image_meta, image_service)
        self.assertTrue(_mock_create_image_volume.called)

    @mock.patch.object(solidfire.SolidFireDriver, '_update_cluster_status')
    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_image_volume')
    def test_verify_image_volume_ok(self,
                                    _mock_create_image_volume,
                                    _mock_get_sf_volume,
                                    _mock_get_sfaccount,
                                    _mock_issue_api_request,
                                    _mock_update_cluster_status):

        _mock_issue_api_request.side_effect = self.fake_issue_api_request
        _mock_update_cluster_status.return_value = None
        _mock_get_sfaccount.return_value = {'username': 'openstack-vtemplate',
                                            'accountID': 7777}
        _mock_get_sf_volume.return_value =\
            {'status': 'active', 'volumeID': 1,
             'attributes': {
                 'image_info':
                     {'image_updated_at': '2013-09-28T15:27:36.325355',
                      'image_id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                      'image_name': 'fake-image',
                      'image_created_at': '2014-12-17T00:16:23+00:00'}}}
        _mock_create_image_volume.return_value = None

        image_meta = {'id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                      'updated_at': datetime.datetime(2013, 9, 28,
                                                      15, 27, 36,
                                                      325355)}
        image_service = 'null'

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        sfv._verify_image_volume(self.ctxt, image_meta, image_service)
        self.assertFalse(_mock_create_image_volume.called)

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    def test_clone_image_not_configured(self, _mock_issue_api_request):
        _mock_issue_api_request.side_effect = self.fake_issue_api_request

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.assertEqual((None, False),
                         sfv.clone_image(self.ctxt,
                                         self.mock_volume,
                                         'fake',
                                         self.fake_image_meta,
                                         'fake'))

    @mock.patch.object(solidfire.SolidFireDriver, '_create_template_account')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_image_volume')
    def test_clone_image_authorization(self,
                                       _mock_create_image_volume,
                                       _mock_create_template_account):
        fake_sf_vref = {
            'status': 'active', 'volumeID': 1,
            'attributes': {
                'image_info':
                    {'image_updated_at': '2014-12-17T00:16:23+00:00',
                     'image_id': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                     'image_name': 'fake-image',
                     'image_created_at': '2014-12-17T00:16:23+00:00'}}}
        _mock_create_image_volume.return_value = fake_sf_vref
        _mock_create_template_account.return_value = 1

        self.configuration.sf_allow_template_caching = True
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        # Make sure if it's NOT public and we're NOT the owner it
        # doesn't try and cache
        timestamp = datetime.datetime(2011, 1, 1, 1, 2, 3)
        _fake_image_meta = {
            'id': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
            'name': 'fakeimage123456',
            'created_at': timestamp,
            'updated_at': timestamp,
            'deleted_at': None,
            'deleted': False,
            'status': 'active',
            'visibility': 'private',
            'protected': False,
            'container_format': 'raw',
            'disk_format': 'raw',
            'owner': 'wrong-owner',
            'properties': {'kernel_id': 'nokernel',
                           'ramdisk_id': 'nokernel',
                           'architecture': 'x86_64'}}

        with mock.patch.object(sfv, '_do_clone_volume',
                               return_value=('fe', 'fi', 'fo')):
            self.assertEqual((None, False),
                             sfv.clone_image(self.ctxt,
                                             self.mock_volume,
                                             'fake',
                                             _fake_image_meta,
                                             self.fake_image_service))

            # And is_public False, but the correct owner does work
            _fake_image_meta['owner'] = 'testprjid'
            self.assertEqual(
                ('fo', True),
                sfv.clone_image(
                    self.ctxt,
                    self.mock_volume,
                    'fake',
                    _fake_image_meta,
                    self.fake_image_service))

            # And is_public True, even if not the correct owner
            _fake_image_meta['is_public'] = True
            _fake_image_meta['owner'] = 'wrong-owner'
            self.assertEqual(
                ('fo', True),
                sfv.clone_image(self.ctxt,
                                self.mock_volume,
                                'fake',
                                _fake_image_meta,
                                self.fake_image_service))
            # And using the new V2 visibility tag
            _fake_image_meta['visibility'] = 'public'
            _fake_image_meta['owner'] = 'wrong-owner'
            self.assertEqual(
                ('fo', True),
                sfv.clone_image(self.ctxt,
                                self.mock_volume,
                                'fake',
                                _fake_image_meta,
                                self.fake_image_service))

    def test_create_template_no_account(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        def _fake_issue_api_req(method, params, version=0):
            if 'GetAccountByName' in method:
                raise exception.SolidFireAPIException
            return {'result': {'accountID': 1}}

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=_fake_issue_api_req):
            self.assertEqual(1,
                             sfv._create_template_account('foo'))

    def test_configured_svip(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        def _fake_get_volumes(account_id, endpoint=None):
            return [{'volumeID': 1,
                     'iqn': ''}]

        def _fake_get_cluster_info():
            return {'clusterInfo': {'svip': '10.10.10.10',
                                    'mvip': '1.1.1.1'}}

        with mock.patch.object(sfv,
                               '_get_volumes_by_sfaccount',
                               side_effect=_fake_get_volumes),\
                mock.patch.object(sfv,
                                  '_issue_api_request',
                                  side_effect=self.fake_issue_api_request):

            sfaccount = {'targetSecret': 'yakitiyak',
                         'accountID': 5,
                         'username': 'bobthebuilder'}
            v = sfv._get_model_info(sfaccount, 1)
            self.assertEqual('1.1.1.1:3260  0', v['provider_location'])

            configured_svip = '9.9.9.9:6500'
            sfv.active_cluster['svip'] = configured_svip
            v = sfv._get_model_info(sfaccount, 1)
            self.assertEqual('%s  0' % configured_svip, v['provider_location'])

    def test_init_volume_mappings(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        vid_1 = 'c9125d6d-22ff-4cc3-974d-d4e350df9c91'
        vid_2 = '79883868-6933-47a1-a362-edfbf8d55a18'
        sid_1 = 'e3caa4fa-485e-45ca-970e-1d3e693a2520'
        project_1 = 'e6fb073c-11f0-4f4c-897c-90e7c7c4bcf8'
        project_2 = '4ff32607-305c-4a6b-a51a-0dd33124eecf'

        vrefs = [{'id': vid_1,
                  'project_id': project_1,
                  'provider_id': None},
                 {'id': vid_2,
                  'project_id': project_2,
                  'provider_id': 22}]
        snaprefs = [{'id': sid_1,
                     'project_id': project_1,
                     'provider_id': None,
                     'volume_id': vid_1}]
        sf_vols = [{'volumeID': 99,
                    'name': 'UUID-' + vid_1,
                    'accountID': 100},
                   {'volumeID': 22,
                    'name': 'UUID-' + vid_2,
                    'accountID': 200}]
        sf_snaps = [{'snapshotID': 1,
                     'name': 'UUID-' + sid_1,
                     'volumeID': 99}]

        def _fake_issue_api_req(method, params, version=0):
            if 'ListActiveVolumes' in method:
                return {'result': {'volumes': sf_vols}}
            if 'ListSnapshots'in method:
                return {'result': {'snapshots': sf_snaps}}

        with mock.patch.object(sfv, '_issue_api_request',
                               side_effect=_fake_issue_api_req):
            volume_updates, snapshot_updates = sfv.update_provider_info(
                vrefs, snaprefs)
            self.assertEqual('99 100 53c8be1e-89e2-4f7f-a2e3-7cb84c47e0ec',
                             volume_updates[0]['provider_id'])
            self.assertEqual(1, len(volume_updates))

            self.assertEqual('1 99 53c8be1e-89e2-4f7f-a2e3-7cb84c47e0ec',
                             snapshot_updates[0]['provider_id'])
            self.assertEqual(1, len(snapshot_updates))

    def test_get_sf_volume_missing_attributes(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        test_name = "existing_volume"
        fake_response = {'result': {
            'volumes': [{'volumeID': 5,
                         'name': test_name,
                         'accountID': 8,
                         'sliceCount': 1,
                         'totalSize': 1 * units.Gi,
                         'enable512e': True,
                         'access': "readWrite",
                         'status': "active",
                         'qos': None,
                         'iqn': test_name}]}}

        def _fake_issue_api_req(method, params, version=0, endpoint=None):
            return fake_response

        with mock.patch.object(
                sfv, '_issue_api_request', side_effect=_fake_issue_api_req):
            self.assertEqual(5, sfv._get_sf_volume(test_name, 8)['volumeID'])

    def test_sf_init_conn_with_vag(self):
        # Verify with the _enable_vag conf set that we correctly create a VAG.
        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'provider_location': '10.10.7.1:3260 iqn.2010-01.com.'
                                        'solidfire:87hg.uuid-2cc06226-cc'
                                        '74-4cb7-bd55-14aed659a0cc.4060 0',
                   'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                                    'c76370d66b 2FE0CQ8J196R',
                   'provider_geometry': '4096 4096',
                   'created_at': timeutils.utcnow(),
                   'provider_id': "1 1 1"
                   }
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        provider_id = testvol['provider_id']
        vol_id = int(provider_id.split()[0])
        vag_id = 1

        with mock.patch.object(sfv,
                               '_safe_create_vag',
                               return_value=vag_id) as create_vag, \
            mock.patch.object(sfv,
                              '_add_volume_to_vag') as add_vol:
            sfv._sf_initialize_connection(testvol, connector)
            create_vag.assert_called_with(connector['initiator'],
                                          vol_id)
            add_vol.assert_called_with(vol_id,
                                       connector['initiator'],
                                       vag_id)

    def test_sf_term_conn_with_vag_rem_vag(self):
        # Verify we correctly remove an empty VAG on detach.
        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'provider_location': '10.10.7.1:3260 iqn.2010-01.com.'
                                        'solidfire:87hg.uuid-2cc06226-cc'
                                        '74-4cb7-bd55-14aed659a0cc.4060 0',
                   'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                                    'c76370d66b 2FE0CQ8J196R',
                   'provider_geometry': '4096 4096',
                   'created_at': timeutils.utcnow(),
                   'provider_id': "1 1 1",
                   'multiattach': False
                   }
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        vag_id = 1
        vags = [{'attributes': {},
                 'deletedVolumes': [],
                 'initiators': [connector['initiator']],
                 'name': 'fakeiqn',
                 'volumeAccessGroupID': vag_id,
                 'volumes': [1],
                 'virtualNetworkIDs': []}]

        with mock.patch.object(sfv,
                               '_get_vags_by_name',
                               return_value=vags), \
            mock.patch.object(sfv,
                              '_remove_vag') as rem_vag:
            sfv._sf_terminate_connection(testvol, connector, False)
            rem_vag.assert_called_with(vag_id)

    def test_sf_term_conn_with_vag_rem_vol(self):
        # Verify we correctly remove a the volume from a non-empty VAG.
        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'provider_location': '10.10.7.1:3260 iqn.2010-01.com.'
                                        'solidfire:87hg.uuid-2cc06226-cc'
                                        '74-4cb7-bd55-14aed659a0cc.4060 0',
                   'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                                    'c76370d66b 2FE0CQ8J196R',
                   'provider_geometry': '4096 4096',
                   'created_at': timeutils.utcnow(),
                   'provider_id': "1 1 1",
                   'multiattach': False
                   }
        provider_id = testvol['provider_id']
        vol_id = int(provider_id.split()[0])
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        vag_id = 1
        vags = [{'attributes': {},
                 'deletedVolumes': [],
                 'initiators': [connector['initiator']],
                 'name': 'fakeiqn',
                 'volumeAccessGroupID': vag_id,
                 'volumes': [1, 2],
                 'virtualNetworkIDs': []}]

        with mock.patch.object(sfv,
                               '_get_vags_by_name',
                               return_value=vags), \
            mock.patch.object(sfv,
                              '_remove_volume_from_vag') as rem_vag:
            sfv._sf_terminate_connection(testvol, connector, False)
            rem_vag.assert_called_with(vol_id, vag_id)

    def test_sf_term_conn_without_connector(self):
        # Verify we correctly force the deletion of a volume.
        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'provider_location': '10.10.7.1:3260 iqn.2010-01.com.'
                                        'solidfire:87hg.uuid-2cc06226-cc'
                                        '74-4cb7-bd55-14aed659a0cc.4060 0',
                   'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                                    'c76370d66b 2FE0CQ8J196R',
                   'provider_geometry': '4096 4096',
                   'created_at': timeutils.utcnow(),
                   'provider_id': "1 1 1",
                   'multiattach': False
                   }
        provider_id = testvol['provider_id']
        vol_id = int(provider_id.split()[0])
        vag_id = 1
        vags = [{'attributes': {},
                 'deletedVolumes': [],
                 'initiators': ['iqn.2012-07.org.fake:01'],
                 'name': 'fakeiqn',
                 'volumeAccessGroupID': vag_id,
                 'volumes': [1, 2],
                 'virtualNetworkIDs': []}]

        with mock.patch.object(sfv,
                               '_get_vags_by_volume',
                               return_value=vags), \
            mock.patch.object(sfv,
                              '_remove_volume_from_vags') as rem_vags:
            sfv._sf_terminate_connection(testvol, None, False)
            rem_vags.assert_called_with(vol_id)

    def test_safe_create_vag_simple(self):
        # Test the sunny day call straight into _create_vag.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'fake_iqn'
        vol_id = 1

        with mock.patch.object(sfv,
                               '_get_vags_by_name',
                               return_value=[]), \
            mock.patch.object(sfv,
                              '_create_vag') as mock_create_vag:
            sfv._safe_create_vag(iqn, vol_id)
            mock_create_vag.assert_called_with(iqn, vol_id)

    def test_safe_create_vag_matching_vag(self):
        # Vag exists, resuse.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'TESTIQN'
        vags = [{'attributes': {},
                 'deletedVolumes': [],
                 'initiators': [iqn],
                 'name': iqn,
                 'volumeAccessGroupID': 1,
                 'volumes': [1, 2],
                 'virtualNetworkIDs': []}]

        with mock.patch.object(sfv,
                               '_get_vags_by_name',
                               return_value=vags), \
            mock.patch.object(sfv,
                              '_create_vag') as create_vag, \
            mock.patch.object(sfv,
                              '_add_initiator_to_vag') as add_iqn:
            vag_id = sfv._safe_create_vag(iqn, None)
            self.assertEqual(vag_id, vags[0]['volumeAccessGroupID'])
            create_vag.assert_not_called()
            add_iqn.assert_not_called()

    def test_safe_create_vag_reuse_vag(self):
        # Reuse a matching vag.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'TESTIQN'
        vags = [{'attributes': {},
                 'deletedVolumes': [],
                 'initiators': [],
                 'name': iqn,
                 'volumeAccessGroupID': 1,
                 'volumes': [1, 2],
                 'virtualNetworkIDs': []}]
        vag_id = vags[0]['volumeAccessGroupID']

        with mock.patch.object(sfv,
                               '_get_vags_by_name',
                               return_value=vags), \
            mock.patch.object(sfv,
                              '_add_initiator_to_vag',
                              return_value=vag_id) as add_init:
            res_vag_id = sfv._safe_create_vag(iqn, None)
            self.assertEqual(res_vag_id, vag_id)
            add_init.assert_called_with(iqn, vag_id)

    def test_create_vag_iqn_fail(self):
        # Attempt to create a VAG with an already in-use initiator.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'TESTIQN'
        vag_id = 1
        vol_id = 42

        def throw_request(method, params, version):
            msg = 'xExceededLimit: {}'.format(params['initiators'][0])
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request), \
            mock.patch.object(sfv,
                              '_safe_create_vag',
                              return_value=vag_id) as create_vag, \
            mock.patch.object(sfv,
                              '_purge_vags') as purge_vags:
            res_vag_id = sfv._create_vag(iqn, vol_id)
            self.assertEqual(res_vag_id, vag_id)
            create_vag.assert_called_with(iqn, vol_id)
            purge_vags.assert_not_called()

    def test_create_vag_limit_fail(self):
        # Attempt to create a VAG with VAG limit reached.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'TESTIQN'
        vag_id = 1
        vol_id = 42

        def throw_request(method, params, version):
            msg = 'xExceededLimit'
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request), \
            mock.patch.object(sfv,
                              '_safe_create_vag',
                              return_value=vag_id) as create_vag, \
            mock.patch.object(sfv,
                              '_purge_vags') as purge_vags:
            res_vag_id = sfv._create_vag(iqn, vol_id)
            self.assertEqual(res_vag_id, vag_id)
            create_vag.assert_called_with(iqn, vol_id)
            purge_vags.assert_called_with()

    def test_add_initiator_duplicate(self):
        # Thrown exception should yield vag_id.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'TESTIQN'
        vag_id = 1

        def throw_request(method, params, version):
            msg = 'xAlreadyInVolumeAccessGroup'
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request):
            res_vag_id = sfv._add_initiator_to_vag(iqn, vag_id)
            self.assertEqual(vag_id, res_vag_id)

    def test_add_initiator_missing_vag(self):
        # Thrown exception should result in create_vag call.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'TESTIQN'
        vag_id = 1

        def throw_request(method, params, version):
            msg = 'xVolumeAccessGroupIDDoesNotExist'
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request), \
            mock.patch.object(sfv,
                              '_safe_create_vag',
                              return_value=vag_id) as mock_create_vag:
            res_vag_id = sfv._add_initiator_to_vag(iqn, vag_id)
            self.assertEqual(vag_id, res_vag_id)
            mock_create_vag.assert_called_with(iqn)

    def test_add_volume_to_vag_duplicate(self):
        # Thrown exception should yield vag_id
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'TESTIQN'
        vag_id = 1
        vol_id = 42

        def throw_request(method, params, version):
            msg = 'xAlreadyInVolumeAccessGroup'
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request):
            res_vag_id = sfv._add_volume_to_vag(vol_id, iqn, vag_id)
            self.assertEqual(res_vag_id, vag_id)

    def test_add_volume_to_vag_missing_vag(self):
        # Thrown exception should yield vag_id
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        iqn = 'TESTIQN'
        vag_id = 1
        vol_id = 42

        def throw_request(method, params, version):
            msg = 'xVolumeAccessGroupIDDoesNotExist'
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request), \
            mock.patch.object(sfv,
                              '_safe_create_vag',
                              return_value=vag_id) as mock_create_vag:
            res_vag_id = sfv._add_volume_to_vag(vol_id, iqn, vag_id)
            self.assertEqual(res_vag_id, vag_id)
            mock_create_vag.assert_called_with(iqn, vol_id)

    def test_remove_volume_from_vag_missing_volume(self):
        # Volume not in VAG, throws.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        vag_id = 1
        vol_id = 42

        def throw_request(method, params, version):
            msg = 'xNotInVolumeAccessGroup'
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request):
            sfv._remove_volume_from_vag(vol_id, vag_id)

    def test_remove_volume_from_vag_missing_vag(self):
        # Volume not in VAG, throws.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        vag_id = 1
        vol_id = 42

        def throw_request(method, params, version):
            msg = 'xVolumeAccessGroupIDDoesNotExist'
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request):
            sfv._remove_volume_from_vag(vol_id, vag_id)

    def test_remove_volume_from_vag_unknown_exception(self):
        # Volume not in VAG, throws.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        vag_id = 1
        vol_id = 42

        def throw_request(method, params, version):
            msg = 'xUnknownException'
            raise exception.SolidFireAPIException(message=msg)

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               side_effect=throw_request):
            self.assertRaises(exception.SolidFireAPIException,
                              sfv._remove_volume_from_vag,
                              vol_id,
                              vag_id)

    def test_remove_volume_from_vags(self):
        # Remove volume from several VAGs.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        vol_id = 42
        vags = [{'volumeAccessGroupID': 1,
                 'volumes': [vol_id]},
                {'volumeAccessGroupID': 2,
                 'volumes': [vol_id, 43]}]

        with mock.patch.object(sfv,
                               '_get_vags_by_volume',
                               return_value=vags), \
            mock.patch.object(sfv,
                              '_remove_volume_from_vag') as rem_vol:
            sfv._remove_volume_from_vags(vol_id)
            self.assertEqual(len(vags), rem_vol.call_count)

    def test_purge_vags(self):
        # Remove subset of VAGs.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        vags = [{'initiators': [],
                 'volumeAccessGroupID': 1,
                 'deletedVolumes': [],
                 'volumes': [],
                 'attributes': {'openstack': True}},
                {'initiators': [],
                 'volumeAccessGroupID': 2,
                 'deletedVolumes': [],
                 'volumes': [],
                 'attributes': {'openstack': False}},
                {'initiators': [],
                 'volumeAccessGroupID': 3,
                 'deletedVolumes': [1],
                 'volumes': [],
                 'attributes': {'openstack': True}},
                {'initiators': [],
                 'volumeAccessGroupID': 4,
                 'deletedVolumes': [],
                 'volumes': [1],
                 'attributes': {'openstack': True}},
                {'initiators': ['fakeiqn'],
                 'volumeAccessGroupID': 5,
                 'deletedVolumes': [],
                 'volumes': [],
                 'attributes': {'openstack': True}}]
        with mock.patch.object(sfv,
                               '_base_get_vags',
                               return_value=vags), \
            mock.patch.object(sfv,
                              '_remove_vag') as rem_vag:
            sfv._purge_vags()
            # Of the vags provided there is only one that is valid for purge
            # based on the limits of no initiators, volumes, deleted volumes,
            # and features the openstack attribute.
            self.assertEqual(1, rem_vag.call_count)
            rem_vag.assert_called_with(1)

    def test_sf_create_group_snapshot(self):
        # Sunny day group snapshot creation.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        name = 'great_gsnap_name'
        sf_volumes = [{'volumeID': 1}, {'volumeID': 42}]
        expected_params = {'name': name,
                           'volumes': [1, 42]}
        fake_result = {'result': 'contrived_test'}
        with mock.patch.object(sfv,
                               '_issue_api_request',
                               return_value=fake_result) as fake_api:
            res = sfv._sf_create_group_snapshot(name, sf_volumes)
            self.assertEqual('contrived_test', res)
            fake_api.assert_called_with('CreateGroupSnapshot',
                                        expected_params,
                                        version='7.0')

    def test_group_snapshot_creator_sunny(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        gsnap_name = 'great_gsnap_name'
        prefix = sfv.configuration.sf_volume_prefix
        vol_uuids = ['one', 'two', 'three']
        active_vols = [{'name': prefix + 'one'},
                       {'name': prefix + 'two'},
                       {'name': prefix + 'three'}]
        with mock.patch.object(sfv,
                               '_get_all_active_volumes',
                               return_value=active_vols),\
            mock.patch.object(sfv,
                              '_sf_create_group_snapshot',
                              return_value=None) as create:
            sfv._group_snapshot_creator(gsnap_name, vol_uuids)
            create.assert_called_with(gsnap_name,
                                      active_vols)

    def test_group_snapshot_creator_rainy(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        gsnap_name = 'great_gsnap_name'
        prefix = sfv.configuration.sf_volume_prefix
        vol_uuids = ['one', 'two', 'three']
        active_vols = [{'name': prefix + 'one'},
                       {'name': prefix + 'two'}]
        with mock.patch.object(sfv,
                               '_get_all_active_volumes',
                               return_value=active_vols):
            self.assertRaises(exception.SolidFireDriverException,
                              sfv._group_snapshot_creator,
                              gsnap_name,
                              vol_uuids)

    def test_create_temp_group_snapshot(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        cg = {'id': 'great_gsnap_name'}
        prefix = sfv.configuration.sf_volume_prefix
        tmp_name = prefix + cg['id'] + '-tmp'
        vols = [{'id': 'one'},
                {'id': 'two'},
                {'id': 'three'}]
        with mock.patch.object(sfv,
                               '_group_snapshot_creator',
                               return_value=None) as create:
            sfv._create_temp_group_snapshot(cg, vols)
            create.assert_called_with(tmp_name, ['one', 'two', 'three'])

    def test_list_group_snapshots(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        res = {'result': {'groupSnapshots': 'a_thing'}}
        with mock.patch.object(sfv,
                               '_issue_api_request',
                               return_value=res):
            result = sfv._list_group_snapshots()
            self.assertEqual('a_thing', result)

    def test_get_group_snapshot_by_name(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        fake_snaps = [{'name': 'a_fantastic_name'}]
        with mock.patch.object(sfv,
                               '_list_group_snapshots',
                               return_value=fake_snaps):
            result = sfv._get_group_snapshot_by_name('a_fantastic_name')
            self.assertEqual(fake_snaps[0], result)

    def test_delete_group_snapshot(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        gsnap_id = 1
        with mock.patch.object(sfv,
                               '_issue_api_request') as api_req:
            sfv._delete_group_snapshot(gsnap_id)
            api_req.assert_called_with('DeleteGroupSnapshot',
                                       {'groupSnapshotID': gsnap_id},
                                       version='7.0')

    def test_delete_cgsnapshot_by_name(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        fake_gsnap = {'groupSnapshotID': 42}
        with mock.patch.object(sfv,
                               '_get_group_snapshot_by_name',
                               return_value=fake_gsnap),\
            mock.patch.object(sfv,
                              '_delete_group_snapshot') as del_stuff:
            sfv._delete_cgsnapshot_by_name('does not matter')
            del_stuff.assert_called_with(fake_gsnap['groupSnapshotID'])

    def test_delete_cgsnapshot_by_name_rainy(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv, '_get_group_snapshot_by_name',
                               return_value=None):
            self.assertRaises(exception.SolidFireDriverException,
                              sfv._delete_cgsnapshot_by_name,
                              'does not matter')

    def test_find_linked_snapshot(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_snap = {'members': [{'volumeID': 1}, {'volumeID': 2}]}
        source_vol = {'volumeID': 1}
        with mock.patch.object(sfv,
                               '_get_sf_volume',
                               return_value=source_vol) as get_vol:
            res = sfv._find_linked_snapshot('fake_uuid', group_snap)
            self.assertEqual(source_vol, res)
            get_vol.assert_called_with('fake_uuid')

    def test_create_consisgroup_from_src_cgsnapshot(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        ctxt = None
        group = {}
        volumes = [{'id': 'one'}, {'id': 'two'}, {'id': 'three'}]
        cgsnapshot = {'id': 'great_uuid'}
        snapshots = [{'id': 'snap_id_1', 'volume_id': 'one'},
                     {'id': 'snap_id_2', 'volume_id': 'two'},
                     {'id': 'snap_id_3', 'volume_id': 'three'}]
        source_cg = None
        source_vols = None
        group_snap = {}
        name = sfv.configuration.sf_volume_prefix + cgsnapshot['id']
        kek = (None, None, {})
        with mock.patch.object(sfv,
                               '_get_group_snapshot_by_name',
                               return_value=group_snap) as get_snap,\
            mock.patch.object(sfv,
                              '_find_linked_snapshot'),\
            mock.patch.object(sfv,
                              '_do_clone_volume',
                              return_value=kek):
            model, vol_models = sfv._create_consistencygroup_from_src(
                ctxt, group, volumes,
                cgsnapshot, snapshots,
                source_cg, source_vols)
            get_snap.assert_called_with(name)
            self.assertEqual(
                {'status': fields.GroupStatus.AVAILABLE}, model)

    def test_create_consisgroup_from_src_source_cg(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        ctxt = None
        group = {}
        volumes = [{'id': 'one', 'source_volid': 'source_one'},
                   {'id': 'two', 'source_volid': 'source_two'},
                   {'id': 'three', 'source_volid': 'source_three'}]
        cgsnapshot = {'id': 'great_uuid'}
        snapshots = None
        source_cg = {'id': 'fantastic_cg'}
        source_vols = [1, 2, 3]
        source_snap = None
        group_snap = {}
        kek = (None, None, {})
        with mock.patch.object(sfv,
                               '_create_temp_group_snapshot',
                               return_value=source_cg['id']),\
            mock.patch.object(sfv,
                              '_get_group_snapshot_by_name',
                              return_value=group_snap) as get_snap,\
            mock.patch.object(sfv,
                              '_find_linked_snapshot',
                              return_value=source_snap),\
            mock.patch.object(sfv,
                              '_do_clone_volume',
                              return_value=kek),\
            mock.patch.object(sfv,
                              '_delete_cgsnapshot_by_name'):
            model, vol_models = sfv._create_consistencygroup_from_src(
                ctxt, group, volumes,
                cgsnapshot, snapshots,
                source_cg,
                source_vols)
            get_snap.assert_called_with(source_cg['id'])
            self.assertEqual(
                {'status': fields.GroupStatus.AVAILABLE}, model)

    def test_create_cgsnapshot(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        ctxt = None
        cgsnapshot = {'id': 'acceptable_cgsnap_id'}
        snapshots = [{'volume_id': 'one'},
                     {'volume_id': 'two'}]
        pfx = sfv.configuration.sf_volume_prefix
        active_vols = [{'name': pfx + 'one'},
                       {'name': pfx + 'two'}]
        with mock.patch.object(sfv,
                               '_get_all_active_volumes',
                               return_value=active_vols),\
            mock.patch.object(sfv,
                              '_sf_create_group_snapshot') as create_gsnap:
            sfv._create_cgsnapshot(ctxt, cgsnapshot, snapshots)
            create_gsnap.assert_called_with(pfx + cgsnapshot['id'],
                                            active_vols)

    def test_create_cgsnapshot_rainy(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        ctxt = None
        cgsnapshot = {'id': 'acceptable_cgsnap_id'}
        snapshots = [{'volume_id': 'one'},
                     {'volume_id': 'two'}]
        pfx = sfv.configuration.sf_volume_prefix
        active_vols = [{'name': pfx + 'one'}]
        with mock.patch.object(sfv,
                               '_get_all_active_volumes',
                               return_value=active_vols),\
            mock.patch.object(sfv,
                              '_sf_create_group_snapshot'):
            self.assertRaises(exception.SolidFireDriverException,
                              sfv._create_cgsnapshot,
                              ctxt,
                              cgsnapshot,
                              snapshots)

    def test_create_vol_from_cgsnap(self):
        # cgsnaps on the backend yield numerous identically named snapshots.
        # create_volume_from_snapshot now searches for the correct snapshot.
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        source = {'group_snapshot_id': 'typical_cgsnap_id',
                  'volume_id': 'typical_vol_id',
                  'id': 'no_id_4_u'}
        name = (self.configuration.sf_volume_prefix +
                source.get('group_snapshot_id'))
        with mock.patch.object(sfv,
                               '_get_group_snapshot_by_name',
                               return_value={}) as get,\
            mock.patch.object(sfv,
                              '_create_clone_from_sf_snapshot',
                              return_value='model'):
            result = sfv.create_volume_from_snapshot({}, source)
            get.assert_called_once_with(name)
            self.assertEqual('model', result)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_cg(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = True
        group = mock.MagicMock()
        result = sfv.create_group(self.ctxt, group)
        self.assertEqual(result,
                         {'status': fields.GroupStatus.AVAILABLE})
        group_cg_test.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_delete_group_snap_cg(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = True
        cgsnapshot = fake_group_snapshot.fake_group_snapshot_obj(
            mock.MagicMock())
        snapshots = fake_snapshot.fake_snapshot_obj(mock.MagicMock())

        with mock.patch.object(sfv, '_delete_cgsnapshot',
                               return_value={}) as _del_mock:
            model_update = sfv.delete_group_snapshot(self.ctxt,
                                                     cgsnapshot, snapshots)
            _del_mock.assert_called_once_with(self.ctxt, cgsnapshot, snapshots)
            self.assertEqual({}, model_update)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_delete_group_snap(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = False
        cgsnapshot = fake_group_snapshot.fake_group_snapshot_obj(
            mock.MagicMock())
        snapshots = fake_snapshot.fake_snapshot_obj(mock.MagicMock())

        with mock.patch.object(sfv, '_delete_cgsnapshot',
                               return_value={}) as _del_mock:

            self.assertRaises(NotImplementedError, sfv.delete_group_snapshot,
                              self.ctxt, cgsnapshot, snapshots)
            _del_mock.assert_not_called()

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_rainy(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = False
        group = mock.MagicMock()
        self.assertRaises(NotImplementedError,
                          sfv.create_group,
                          self.ctxt, group)
        group_cg_test.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_from_src_rainy(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = False
        group = mock.MagicMock()
        volumes = [mock.MagicMock()]
        self.assertRaises(NotImplementedError,
                          sfv.create_group_from_src,
                          self.ctxt, group, volumes)
        group_cg_test.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_from_src_cg(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = True
        group = mock.MagicMock()
        volumes = [mock.MagicMock()]
        ret = 'things'
        with mock.patch.object(sfv,
                               '_create_consistencygroup_from_src',
                               return_value=ret):
            result = sfv.create_group_from_src(self.ctxt,
                                               group,
                                               volumes)
            self.assertEqual(ret, result)
            group_cg_test.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_snapshot_rainy(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = False
        group_snapshot = mock.MagicMock()
        snapshots = [mock.MagicMock()]
        self.assertRaises(NotImplementedError,
                          sfv.create_group_snapshot,
                          self.ctxt,
                          group_snapshot,
                          snapshots)
        group_cg_test.assert_called_once_with(group_snapshot)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_create_group_snapshot(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = True
        group_snapshot = mock.MagicMock()
        snapshots = [mock.MagicMock()]
        ret = 'things'
        with mock.patch.object(sfv,
                               '_create_cgsnapshot',
                               return_value=ret):
            result = sfv.create_group_snapshot(self.ctxt,
                                               group_snapshot,
                                               snapshots)
            self.assertEqual(ret, result)
        group_cg_test.assert_called_once_with(group_snapshot)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_delete_group_rainy(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = False
        group = mock.MagicMock()
        volumes = [mock.MagicMock()]
        self.assertRaises(NotImplementedError,
                          sfv.delete_group,
                          self.ctxt,
                          group,
                          volumes)
        group_cg_test.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_delete_group(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = True
        group = mock.MagicMock()
        volumes = [mock.MagicMock()]
        ret = 'things'
        with mock.patch.object(sfv,
                               '_delete_consistencygroup',
                               return_value=ret):
            result = sfv.delete_group(self.ctxt,
                                      group,
                                      volumes)
            self.assertEqual(ret, result)
        group_cg_test.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_update_group_rainy(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = False
        group = mock.MagicMock()
        self.assertRaises(NotImplementedError,
                          sfv.update_group,
                          self.ctxt,
                          group)
        group_cg_test.assert_called_once_with(group)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type')
    def test_update_group(self, group_cg_test):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        group_cg_test.return_value = True
        group = mock.MagicMock()
        ret = 'things'
        with mock.patch.object(sfv,
                               '_update_consistencygroup',
                               return_value=ret):
            result = sfv.update_group(self.ctxt,
                                      group)
            self.assertEqual(ret, result)
        group_cg_test.assert_called_once_with(group)

    def test_getattr_failure(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        try:
            sfv.foo()
            self.fail("Should have thrown Error")
        except Exception:
            pass

    def test_set_rep_by_volume_type(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.cluster_pairs = self.cluster_pairs
        ctxt = None
        type_id = '290edb2a-f5ea-11e5-9ce9-5e5517507c66'
        fake_type = {'extra_specs': {'replication_enabled': '<is> True'}}
        with mock.patch.object(volume_types,
                               'get_volume_type',
                               return_value=fake_type):
            self.assertEqual('Async', sfv._set_rep_by_volume_type(
                ctxt, type_id))

    def test_replicate_volume(self):
        replication_status = fields.ReplicationStatus.ENABLED
        fake_vol = {'project_id': 1, 'volumeID': 1, 'size': 1}
        params = {'attributes': {}}
        sf_account = {'initiatorSecret': 'shhh', 'targetSecret': 'dont-tell'}
        model_update = {'provider_id': '1 2 xxxx'}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.cluster_pairs = self.cluster_pairs

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               self.fake_issue_api_request),\
                mock.patch.object(sfv,
                                  '_get_sfaccount_by_name',
                                  return_value={'accountID': 1}),\
                mock.patch.object(sfv,
                                  '_do_volume_create',
                                  return_value=model_update):
            self.assertEqual({'replication_status': replication_status},
                             sfv._replicate_volume(fake_vol, params,
                                                   sf_account, {}))

    def test_pythons_try_except(self):
        def _fake_retrieve_rep(vol):
            raise exception.SolidFireAPIException

        fake_type = {'extra_specs': {}}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_create_account',
                               return_value={'accountID': 5}),\
                mock.patch.object(sfv,
                                  '_retrieve_qos_setting',
                                  return_value=None), \
                mock.patch.object(sfv,
                                  '_do_volume_create',
                                  return_value={'provider_id': '1 2 xxxx'}),\
                mock.patch.object(volume_types,
                                  'get_volume_type',
                                  return_value=fake_type), \
                mock.patch.object(sfv,
                                  '_retrieve_replication_settings',
                                  side_effect=_fake_retrieve_rep):
            self.assertRaises(exception.SolidFireAPIException,
                              sfv.create_volume,
                              self.mock_volume)

    def test_extract_sf_attributes_from_extra_specs(self):
        type_id = '290edb2a-f5ea-11e5-9ce9-5e5517507c66'
        fake_type = {'extra_specs': {'SFAttribute:foo': 'bar',
                                     'SFAttribute:biz': 'baz'}}
        expected = [{'foo': 'bar'}, {'biz': 'baz'}]
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(volume_types, 'get_volume_type',
                               return_value=fake_type):
            res = sfv._extract_sf_attributes_from_extra_specs(type_id)
            six.assertCountEqual(self, expected, res)

    def test_build_endpoint_with_kwargs(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        expected_ep = {'passwd': 'nunyabiz',
                       'port': 888,
                       'url': 'https://1.2.3.4:888',
                       'svip': None,
                       'mvip': '1.2.3.4',
                       'login': 'JohnWayne'}
        ep = sfv._build_endpoint_info(mvip='1.2.3.4', login='JohnWayne',
                                      password='nunyabiz', port=888)
        self.assertEqual(expected_ep, ep)

        # Make sure we pick up defaults for those not specified
        expected_ep = {'passwd': 'nunyabiz',
                       'url': 'https://1.2.3.4:443',
                       'svip': None,
                       'mvip': '1.2.3.4',
                       'login': 'admin',
                       'port': 443}
        ep = sfv._build_endpoint_info(mvip='1.2.3.4', password='nunyabiz')
        self.assertEqual(expected_ep, ep)

    def test_generate_random_string(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        a = sfv._generate_random_string(12)
        self.assertEqual(len(a), 12)
        self.assertIsNotNone(re.match(r'[A-Z0-9]{12}', a), a)

    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_snapshots')
    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    def test_revert_to_snapshot_success(self, mock_issue_api_request,
                                        mock_get_sf_snapshots,
                                        mock_get_sf_volume,
                                        mock_get_sfaccount):
        mock_issue_api_request.side_effect = self.fake_issue_api_request

        mock_get_sfaccount.return_value = self.fake_sfaccount
        mock_get_sf_volume.return_value = self.fake_sfvol
        mock_get_sf_snapshots.return_value = self.fake_sfsnaps

        expected_params = {'accountID': 25,
                           'volumeID': 6,
                           'snapshotID': '5',
                           'saveCurrentState': 'false'}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        # Success path
        sfv.revert_to_snapshot(self.ctxt, self.vol, self.snap)
        mock_issue_api_request.assert_called_with(
            'RollbackToSnapshot', expected_params, version='6.0')

    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_snapshots')
    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    def test_revert_to_snapshot_fail_vol_not_found(
            self, mock_issue_api_request, mock_get_sf_snapshots,
            mock_get_sf_volume, mock_get_sfaccount):
        mock_issue_api_request.side_effect = self.fake_issue_api_request

        mock_get_sfaccount.return_value = self.fake_sfaccount
        mock_get_sf_volume.return_value = None
        mock_get_sf_snapshots.return_value = []

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        # Volume not found
        mock_get_sf_volume.return_value = None
        self.assertRaises(exception.VolumeNotFound,
                          sfv.revert_to_snapshot,
                          self.ctxt, self.vol, self.snap)

    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_snapshots')
    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    def test_revert_to_snapshot_fail_snap_not_found(
            self, mock_issue_api_request, mock_get_sf_snapshots,
            mock_get_sf_volume, mock_get_sfaccount):
        mock_issue_api_request.side_effect = self.fake_issue_api_request

        mock_get_sfaccount.return_value = self.fake_sfaccount
        mock_get_sf_volume.return_value = self.fake_sfvol
        mock_get_sf_snapshots.return_value = []

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        # Snapshot not found
        mock_get_sf_snapshots.return_value = []
        self.assertRaises(exception.VolumeSnapshotNotFound,
                          sfv.revert_to_snapshot,
                          self.ctxt, self.vol, self.snap)

    @mock.patch.object(solidfire.SolidFireDriver, '_get_create_account')
    @mock.patch.object(solidfire.SolidFireDriver, '_set_cluster_pairs')
    @mock.patch.object(solidfire.SolidFireDriver, '_snapshot_discovery')
    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_model_info')
    @mock.patch.object(solidfire.SolidFireDriver, '_update_attributes')
    @mock.patch.object(solidfire.SolidFireDriver, '_update_cluster_status')
    @mock.patch.object(solidfire.SolidFireDriver, '_set_cluster_pairs')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_default_volume_params')
    @mock.patch.object(solidfire.SolidFireDriver,
                       '_retrieve_replication_settings')
    @mock.patch.object(solidfire.SolidFireDriver, '_replicate_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_cluster_reference')
    def test_do_clone_volume_rep_disabled(self,
                                          mock_create_cluster_reference,
                                          mock_replicate_volume,
                                          mock_retrieve_replication_settings,
                                          mock_get_default_volume_params,
                                          mock_set_cluster_pairs,
                                          mock_update_cluster_status,
                                          mock_update_attributes,
                                          mock_get_model_info,
                                          mock_issue_api_request,
                                          mock_snapshot_discovery,
                                          mock_test_set_cluster_pairs,
                                          mock_get_create_account):

        all_mocks = locals()

        def reset_mocks():
            for mk in all_mocks.values():
                if isinstance(mk, mock.MagicMock):
                    mk.reset_mock()

        sf_volume_params = {'volumeID': 1, 'snapshotID': 2, 'newSize': 3}
        mock_snapshot_discovery.return_value = (sf_volume_params, True,
                                                self.fake_sfvol)
        mock_get_create_account.return_value = self.fake_sfaccount

        ctx = context.get_admin_context()
        vol_fields = {'updated_at': timeutils.utcnow(),
                      'created_at': timeutils.utcnow()}
        src_vol = fake_volume.fake_volume_obj(ctx)
        dst_vol = fake_volume.fake_volume_obj(ctx, **vol_fields)

        mock_create_cluster_reference.return_value = {
            'mvip': self.mvip,
            'svip': self.svip}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = False

        reset_mocks()
        mock_issue_api_request.return_value = {
            'error': {'code': 000, 'name': 'DummyError',
                      'message': 'This is a fake error response'},
            'id': 1}

        self.assertRaises(solidfire.SolidFireAPIException,
                          sfv._do_clone_volume, src_vol.id,
                          dst_vol, sf_src_snap=self.fake_sfsnaps[0])

        clone_vol_params = {
            'snapshotID': self.fake_sfsnaps[0]['snapshotID'],
            'volumeID': self.fake_sfsnaps[0]['volumeID'],
            'newSize': dst_vol.size * units.Gi,
            'name': '%(prefix)s%(id)s' % {
                'prefix': self.configuration.sf_volume_prefix,
                    'id': dst_vol.id},
            'newAccountID': self.fake_sfaccount['accountID']}

        mock_get_create_account.assert_called_with(dst_vol.project_id)
        mock_issue_api_request.assert_called_once_with(
            'CloneVolume', clone_vol_params, version='6.0')
        mock_test_set_cluster_pairs.assert_not_called()
        mock_update_attributes.assert_not_called()
        mock_get_model_info.assert_not_called()
        mock_snapshot_discovery.assert_not_called()

        reset_mocks()
        mock_issue_api_request.side_effect = self.fake_issue_api_request
        mock_get_default_volume_params.return_value = {}
        mock_get_model_info.return_value = None
        self.assertRaises(solidfire.SolidFireAPIException,
                          sfv._do_clone_volume, src_vol.id,
                          dst_vol, sf_src_snap=self.fake_sfsnaps[0])

        mock_get_create_account.assert_called_with(dst_vol.project_id)
        calls = [mock.call('CloneVolume', clone_vol_params, version='6.0'),
                 mock.call('ModifyVolume', {'volumeID': 6})]
        mock_issue_api_request.assert_has_calls(calls)
        mock_test_set_cluster_pairs.assert_not_called()
        mock_update_attributes.assert_not_called()
        mock_get_model_info.assert_called_once()
        mock_snapshot_discovery.assert_not_called()

        reset_mocks()
        mock_retrieve_replication_settings.return_value = 'Async'
        update = {'replication_status': fields.ReplicationStatus.ENABLED}
        mock_replicate_volume.side_effect = solidfire.SolidFireDriverException
        mock_update_attributes.return_value = {'result': {}, 'id': 1}
        mock_get_model_info.return_value = {
            'provider_location': '1.1.1.1 iqn 0',
            'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2c76370d66b '
                             '2FE0CQ8J196R',
            'provider_id': '%s %s cluster-id-01' % (
                self.fake_sfvol['volumeID'],
                self.fake_sfaccount['accountID'])
        }

        data, account, updates = sfv._do_clone_volume(
            src_vol.id, dst_vol, sf_src_snap=self.fake_sfsnaps[0])

        self.assertEqual({'result': {}, 'id': 1}, data)
        self.assertEqual(25, account['accountID'])
        self.assertEqual(self.fake_sfvol['volumeID'],
                         int(updates['provider_id'].split()[0]))

        mock_get_create_account.assert_called_with(dst_vol.project_id)
        calls = [mock.call('CloneVolume', clone_vol_params, version='6.0'),
                 mock.call('ModifyVolume', {'volumeID': 6})]

        mock_issue_api_request.assert_has_calls(calls)
        mock_test_set_cluster_pairs.assert_not_called()
        mock_update_attributes.assert_not_called()
        mock_get_model_info.assert_called_once()
        mock_snapshot_discovery.assert_not_called()

    @mock.patch.object(solidfire.SolidFireDriver, '_get_create_account')
    @mock.patch.object(solidfire.SolidFireDriver, '_retrieve_qos_setting')
    @mock.patch.object(solidfire.SolidFireDriver,
                       '_extract_sf_attributes_from_extra_specs')
    def test_get_default_volume_params(
            self, mock_extract_sf_attributes_from_extra_specs,
            mock_retrieve_qos_setting, mock_get_create_account):

        mock_extract_sf_attributes_from_extra_specs.return_value = [{
            'key1': 'value1',
            'key2': 'value2'
        }]
        mock_retrieve_qos_setting.return_value = None
        mock_get_create_account.return_value = self.fake_sfaccount

        ctx = context.get_admin_context()
        type_fields = {'extra_specs': {'replication_enabled': '<is> True'}}
        vol_type = fake_volume.fake_volume_type_obj(ctx, **type_fields)
        utc_now = timeutils.utcnow().isoformat()
        vol_fields = {
            'id': fakes.FAKE_UUID,
            'created_at': utc_now,
            'volume_type': vol_type,
            'volume_type_id': vol_type.id
        }

        vol = fake_volume.fake_volume_obj(ctx, **vol_fields)

        vol_name = '%s%s' % (self.configuration.sf_volume_prefix, vol.id)
        expected_attr = {
            'uuid': vol.id,
            'is_clone': False,
            'created_at': utc_now + "+00:00",
            'cinder-name': vol.get('display_name', ""),
            'key1': 'value1',
            'key2': 'value2',
        }

        expected_params = {
            'name': vol_name,
            'accountID': self.fake_sfaccount['accountID'],
            'sliceCount': 1,
            'totalSize': int(vol.size * units.Gi),
            'enable512e': self.configuration.sf_emulate_512,
            'attributes': expected_attr,
            'qos': None
        }

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = True

        params = sfv._get_default_volume_params(vol, False)

        self.assertDictEqual(expected_params, params)
        mock_extract_sf_attributes_from_extra_specs.assert_called()
        mock_retrieve_qos_setting.assert_called()
        mock_get_create_account.assert_called()

    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfvol_by_cinder_vref')
    def test_disable_replication_fail(self, mock_get_sfvol_by_cinder_vref):

        self.fake_sfvol['volumePairs'] = []
        mock_get_sfvol_by_cinder_vref.return_value = self.fake_sfvol

        ctx = context.get_admin_context()
        utc_now = timeutils.utcnow().isoformat()
        vol_fields = {
            'id': f_uuid,
            'created_at': utc_now
        }
        vol = fake_volume.fake_volume_obj(ctx, **vol_fields)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = True
        sfv.cluster_pairs = self.cluster_pairs

        expected = {'replication_status': fields.ReplicationStatus.DISABLED}
        updates = sfv._disable_replication(vol)

        self.assertDictEqual(expected, updates)

    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfvol_by_cinder_vref')
    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_cluster_reference')
    def test_disable_replication(self, mock_create_cluster_reference,
                                 mock_issue_api_request,
                                 mock_get_sfvol_by_cinder_vref):

        mock_create_cluster_reference.return_value = {
            'mvip': self.mvip,
            'svip': self.svip}

        self.fake_sfvol['volumePairs'] = [{"remoteVolumeID": 26}]
        mock_get_sfvol_by_cinder_vref.return_value = self.fake_sfvol

        ctx = context.get_admin_context()
        utc_now = timeutils.utcnow().isoformat()
        vol_fields = {
            'id': f_uuid,
            'created_at': utc_now
        }
        vol = fake_volume.fake_volume_obj(ctx, **vol_fields)

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = True
        sfv.cluster_pairs = self.cluster_pairs
        sfv.active_cluster['mvip'] = self.mvip
        sfv.active_cluster['svip'] = self.svip

        expected = {'replication_status': fields.ReplicationStatus.DISABLED}
        mock_issue_api_request.reset_mock()
        updates = sfv._disable_replication(vol)

        self.assertDictEqual(expected, updates)

        expected = [
            mock.call("RemoveVolumePair",
                      {'volumeID': self.fake_sfvol['volumeID']}, '8.0'),
            mock.call("RemoveVolumePair", {'volumeID': 26}, '8.0',
                      endpoint=sfv.cluster_pairs[0]['endpoint']),
            mock.call("DeleteVolume", {'volumeID': 26},
                      endpoint=sfv.cluster_pairs[0]['endpoint']),
            mock.call("PurgeDeletedVolume", {'volumeID': 26},
                      endpoint=sfv.cluster_pairs[0]['endpoint'])
        ]

        mock_issue_api_request.assert_has_calls(expected)
        mock_create_cluster_reference.assert_called()
        mock_get_sfvol_by_cinder_vref.assert_called()

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_cluster_reference')
    @mock.patch.object(solidfire.SolidFireDriver, '_set_cluster_pairs')
    @mock.patch.object(solidfire.SolidFireDriver, '_update_cluster_status')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_cluster_info')
    @mock.patch.object(solidfire.SolidFireDriver, '_map_sf_volumes')
    @mock.patch.object(solidfire.SolidFireDriver, '_failover_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_create_account')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_remote_info_by_id')
    def test_failover_host(self, mock_get_remote_info_by_id,
                           mock_get_create_account,
                           mock_failover_volume,
                           mock_map_sf_volumes,
                           mock_get_cluster_info,
                           mock_update_cluster_status,
                           mock_set_cluster_pairs,
                           mock_create_cluster_reference,
                           mock_issue_api_request):

        all_mocks = locals()

        def reset_mocks():
            for mk in all_mocks.values():
                if isinstance(mk, mock.MagicMock):
                    mk.reset_mock()

        ctx = context.get_admin_context()
        vol_fields = {'updated_at': timeutils.utcnow(),
                      'created_at': timeutils.utcnow()}

        cinder_vols = []
        sf_vols = []
        for i in range(1, 6):
            vol = fake_volume.fake_volume_obj(ctx, **vol_fields)
            sf_vol = self.fake_sfvol.copy()
            sf_vol['volumeID'] = i
            sf_vol['name'] = '%s%s' % (self.configuration.sf_volume_prefix,
                                       vol.id)
            sf_vol['access'] = 'replicationTarget'
            sf_vol['attributes'] = {'uuid': vol.id}
            sf_vol['cinder_id'] = vol.id

            sf_vols.append(sf_vol)
            cinder_vols.append(vol)

        mock_map_sf_volumes.return_value = sf_vols
        mock_create_cluster_reference.return_value = self.cluster_pairs[0]

        fake_replication_device = {'backend_id': 'fake',
                                   'mvip': '0.0.0.0',
                                   'login': 'fake_login',
                                   'password': 'fake_pwd'}

        self.configuration.replication_device = [fake_replication_device]

        reset_mocks()
        drv_args = {'active_backend_id': None}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration,
                                        **drv_args)
        self.assertRaises(exception.InvalidReplicationTarget,
                          sfv.failover_host, ctx, cinder_vols, 'default', None)
        mock_map_sf_volumes.assert_not_called()

        reset_mocks()
        drv_args = {'active_backend_id': 'default'}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration,
                                        **drv_args)
        self.assertRaises(exception.UnableToFailOver,
                          sfv.failover_host, ctx, cinder_vols, 'default', None)
        mock_map_sf_volumes.assert_not_called()

        reset_mocks()
        drv_args = {'active_backend_id': None}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration,
                                        **drv_args)
        self.assertRaises(exception.InvalidReplicationTarget,
                          sfv.failover_host, ctx, cinder_vols,
                          secondary_id='not_fake_id', groups=None)
        mock_map_sf_volumes.assert_not_called()

        reset_mocks()
        drv_args = {'active_backend_id': None}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration,
                                        **drv_args)
        sfv.cluster_pairs = [None]
        self.assertRaises(exception.UnableToFailOver,
                          sfv.failover_host, ctx, cinder_vols,
                          secondary_id='fake', groups=None)
        mock_map_sf_volumes.assert_not_called()

        reset_mocks()
        drv_args = {'active_backend_id': None}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration,
                                        **drv_args)
        sfv.cluster_pairs = self.cluster_pairs
        sfv.cluster_pairs[0]['backend_id'] = 'fake'
        sfv.replication_enabled = True
        cluster_id, updates, _ = sfv.failover_host(
            ctx, cinder_vols, secondary_id='fake', groups=None)
        self.assertEqual(5, len(updates))
        for update in updates:
            self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                             update['updates']['replication_status'])

        self.assertEqual('fake', cluster_id)
        mock_get_create_account.assert_called()
        mock_failover_volume.assert_called()
        mock_map_sf_volumes.assert_called()
        mock_get_cluster_info.assert_not_called()
        mock_update_cluster_status.assert_called()
        mock_set_cluster_pairs.assert_called()
        mock_create_cluster_reference.assert_called()
        mock_issue_api_request.assert_not_called()

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_cluster_reference')
    @mock.patch.object(solidfire.SolidFireDriver, '_update_cluster_status')
    def test_failover_volume(self, mock_update_cluster_status,
                             mock_create_cluster_reference,
                             mock_issue_api_request):

        all_mocks = locals()

        def reset_mocks():
            for mk in all_mocks.values():
                if isinstance(mk, mock.MagicMock):
                    mk.reset_mock()

        mock_issue_api_request.return_value = self.fake_sfaccount

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.replication_enabled = True

        fake_src_sfvol = {'volumeID': 600,
                          'name': 'test_volume',
                          'accountID': 25,
                          'sliceCount': 1,
                          'totalSize': 1 * units.Gi,
                          'enable512e': True,
                          'access': "replicationTarget",
                          'status': "active",
                          'attributes': {'uuid': f_uuid[0]},
                          'qos': None,
                          'iqn': 'super_fake_iqn'}

        expected_src_params = {'volumeID': fake_src_sfvol['volumeID'],
                               'access': 'replicationTarget'}

        expected_tgt_params = {'volumeID': self.fake_sfvol['volumeID'],
                               'access': 'readWrite'}

        sfv._failover_volume(self.fake_sfvol, self.cluster_pairs[0],
                             fake_src_sfvol)

        mock_issue_api_request.assert_has_calls(
            [mock.call("ModifyVolume", expected_src_params),
             mock.call("ModifyVolume", expected_tgt_params,
                       endpoint=self.cluster_pairs[0]['endpoint'])]
        )
        reset_mocks()

        sfv._failover_volume(self.fake_sfvol, self.cluster_pairs[0])

        mock_issue_api_request.assert_called_with(
            "ModifyVolume",
            expected_tgt_params,
            endpoint=self.cluster_pairs[0]['endpoint']
        )
