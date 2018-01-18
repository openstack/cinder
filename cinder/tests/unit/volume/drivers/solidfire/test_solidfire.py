
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

import ddt
import mock
from oslo_utils import timeutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import utils as test_utils
from cinder.volume import configuration as conf
from cinder.volume.drivers import solidfire
from cinder.volume import qos_specs
from cinder.volume import volume_types


@ddt.ddt
class SolidFireVolumeTestCase(test.TestCase):

    def setUp(self):
        self.ctxt = context.get_admin_context()
        self.configuration = conf.Configuration(None)
        self.configuration.sf_allow_tenant_qos = True
        self.configuration.san_is_local = True
        self.configuration.sf_emulate_512 = True
        self.configuration.sf_account_prefix = 'cinder'
        self.configuration.reserved_percentage = 25
        self.configuration.iscsi_helper = None
        self.configuration.sf_template_account_name = 'openstack-vtemplate'
        self.configuration.sf_allow_template_caching = False
        self.configuration.sf_svip = None
        self.configuration.sf_enable_volume_mapping = True
        self.configuration.sf_volume_prefix = 'UUID-'
        self.configuration.sf_enable_vag = False
        self.configuration.replication_device = []

        super(SolidFireVolumeTestCase, self).setUp()
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        self.mock_object(solidfire.SolidFireDriver,
                         '_build_endpoint_info',
                         self.fake_build_endpoint_info)

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
        self.mock_volume = {'project_id': 'testprjid',
                            'name': 'testvol',
                            'size': 1,
                            'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                            'volume_type_id': 'fast',
                            'created_at': timeutils.utcnow()}
        self.fake_image_meta = {'id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                                'updated_at': datetime.datetime(2013, 9,
                                                                28, 15,
                                                                27, 36,
                                                                325355),
                                'is_public': True,
                                'owner': 'testprjid'}
        self.fake_image_service = fake_image.FakeImageService()

    def fake_init_cluster_pairs(*args, **kwargs):
        return None

    def fake_build_endpoint_info(obj, **kwargs):
        endpoint = {}
        endpoint['mvip'] = '1.1.1.1'
        endpoint['login'] = 'admin'
        endpoint['passwd'] = 'admin'
        endpoint['port'] = '443'
        endpoint['url'] = '{scheme}://{mvip}'.format(mvip='%s:%s' %
                                                     (endpoint['mvip'],
                                                      endpoint['port']),
                                                     scheme='https')

        return endpoint

    def fake_issue_api_request(obj, method, params, version='1.0',
                               endpoint=None):
        if method is 'GetClusterCapacity' and version == '1.0':
            data = {'result':
                    {'clusterCapacity': {'maxProvisionedSpace': 107374182400,
                                         'usedSpace': 1073741824,
                                         'compressionPercent': 100,
                                         'deDuplicationPercent': 100,
                                         'thinProvisioningPercent': 100}}}
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
            return

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
                             'attributes': {},
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
        elif method is 'DeleteSnapshot':
            return {'result': {}}
        elif method is 'GetClusterVersionInfo':
            return {'result': {'clusterAPIVersion': '8.0'}}
        elif method is 'StartVolumePairing':
            return {'result': {'volumePairingKey': 'fake-pairing-key'}}
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
                            'name': 'testprjid',
                            'targetSecret': 'shhhh',
                            'username': 'john-wayne'}]

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
                            'name': 'testprjid',
                            'targetSecret': 'shhhh',
                            'username': 'john-wayne'}]

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
        fake_sfaccounts = [{'accountID': 5,
                            'name': 'testprjid',
                            'targetSecret': 'shhhh',
                            'username': 'john-wayne'}]

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
        testsnap = {'project_id': 'testprjid',
                    'name': 'testvol',
                    'volume_size': 1,
                    'id': 'b831c4d1-d1f0-11e1-9b23-0800200c9a66',
                    'volume_id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                    'volume_type_id': None,
                    'created_at': timeutils.utcnow(),
                    'provider_id': '8 99 None'}

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
                                                 'name': 'testprjid'}]):
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

        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        testvol_b = {'project_id': 'testprjid',
                     'name': 'testvol',
                     'size': 1,
                     'id': 'b831c4d1-d1f0-11e1-9b23-0800200c9a66',
                     'volume_type_id': None,
                     'created_at': timeutils.utcnow()}

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
        account = sfv._create_sfaccount('project-id')
        self.assertIsNotNone(account)

    def test_create_sfaccount_fails(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request_fails)
        self.assertRaises(exception.SolidFireAPIException,
                          sfv._create_sfaccount, 'project-id')

    def test_get_sfaccount_by_name(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        account = sfv._get_sfaccount_by_name('some-name')
        self.assertIsNotNone(account)

    def test_get_sfaccount_by_name_fails(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request_fails)
        self.assertRaises(exception.SolidFireAPIException,
                          sfv._get_sfaccount_by_name, 'some-name')

    def test_delete_volume(self):
        vol_id = 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'
        testvol = test_utils.create_volume(
            self.ctxt,
            id=vol_id,
            display_name='test_volume',
            provider_id='1 5 None',
            multiattach=True)

        fake_sfaccounts = [{'accountID': 5,
                            'name': 'testprjid',
                            'targetSecret': 'shhhh',
                            'username': 'john-wayne'}]

        get_vol_result = [{'volumeID': 5,
                           'name': 'test_volume',
                           'accountID': 25,
                           'sliceCount': 1,
                           'totalSize': 1 * units.Gi,
                           'enable512e': True,
                           'access': "readWrite",
                           'status': "active",
                           'attributes': {},
                           'qos': None,
                           'iqn': 'super_fake_iqn'}]

        mod_conf = self.configuration
        mod_conf.sf_enable_vag = True
        sfv = solidfire.SolidFireDriver(configuration=mod_conf)
        with mock.patch.object(sfv,
                               '_get_sfaccounts_for_tenant',
                               return_value=fake_sfaccounts), \
            mock.patch.object(sfv,
                              '_get_volumes_for_account',
                              return_value=get_vol_result), \
            mock.patch.object(sfv,
                              '_issue_api_request'), \
            mock.patch.object(sfv,
                              '_remove_volume_from_vags') as rem_vol:

            sfv.delete_volume(testvol)
            rem_vol.assert_called_with(get_vol_result[0]['volumeID'])

    def test_delete_volume_no_volume_on_backend(self):
        fake_sfaccounts = [{'accountID': 5,
                            'name': 'testprjid',
                            'targetSecret': 'shhhh',
                            'username': 'john-wayne'}]
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
                            'name': 'testprjid',
                            'targetSecret': 'shhhh',
                            'username': 'john-wayne'}]
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
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        self.assertTrue(sfv.retype(self.ctxt,
                                   testvol,
                                   type_ref, diff, host))

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
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.assertTrue(sfv.retype(self.ctxt,
                                   testvol,
                                   test_type, diff, host))

    def test_update_cluster_status(self):
        self.mock_object(solidfire.SolidFireDriver,
                         '_issue_api_request',
                         self.fake_issue_api_request)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv._update_cluster_status()
        self.assertEqual(99.0, sfv.cluster_stats['free_capacity_gb'])
        self.assertEqual(100.0, sfv.cluster_stats['total_capacity_gb'])

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
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
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
    def test_create_volume_for_migration(self,
                                         _mock_create_template_account,
                                         _mock_issue_api_request):
        _mock_issue_api_request.side_effect = self.fake_issue_api_request
        _mock_create_template_account.return_value = 1
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'b830b3c0-d1f0-11e1-9b23-1900200c9a77',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow(),
                   'migration_status': 'target:'
                                       'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        fake_sfaccounts = [{'accountID': 5,
                            'name': 'testprjid',
                            'targetSecret': 'shhhh',
                            'username': 'john-wayne'}]

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

            proj_id, sf_vol_object = sfv.create_volume(testvol)
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
            sfv.active_cluster_info['svip'] = configured_svip
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

        with mock.patch.object(
                sfv, '_issue_api_request', side_effect=_fake_issue_api_req):
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

        def _fake_issue_api_req(method, params, version=0):
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
                               '_base_get_vags',
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
        with mock.patch.object(sfv,
                               '_get_group_snapshot_by_name',
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
        name = (self.configuration.sf_volume_prefix
                + source.get('group_snapshot_id'))
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
        sfv.cluster_pairs = [{'cluster_id': 'fake-id', 'cluster_mvip':
                              'fake-mvip'}]
        ctxt = None
        type_id = '290edb2a-f5ea-11e5-9ce9-5e5517507c66'
        fake_type = {'extra_specs': {'replication': 'enabled'}}
        with mock.patch.object(volume_types,
                               'get_volume_type',
                               return_value=fake_type):
            self.assertEqual('fake-id', sfv._set_rep_by_volume_type(
                ctxt,
                type_id)['targets']['cluster_id'])

    def test_replicate_volume(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.cluster_pairs = (
            [{'uniqueID': 'lu9f', 'endpoint': {'passwd': 'admin', 'port':
                                               443, 'url':
                                               'https://192.168.139.102:443',
                                               'svip': '10.10.8.134', 'mvip':
                                               '192.168.139.102', 'login':
                                               'admin'}, 'name':
              'AutoTest2-6AjG-FOR-TEST-ONLY', 'clusterPairID': 33, 'uuid':
              '9c499d4b-8fff-48b4-b875-27601d5d9889', 'svip': '10.10.23.2',
              'mvipNodeID': 1, 'repCount': 1, 'encryptionAtRestState':
              'disabled', 'attributes': {}, 'mvip': '192.168.139.102',
              'ensemble': ['10.10.5.130'], 'svipNodeID': 1}])

        with mock.patch.object(sfv,
                               '_issue_api_request',
                               self.fake_issue_api_request),\
                mock.patch.object(sfv,
                                  '_get_sfaccount_by_name',
                                  return_value={'accountID': 1}),\
                mock.patch.object(sfv,
                                  '_do_volume_create',
                                  return_value={'provider_id': '1 2 xxxx'}):
            self.assertEqual({'provider_id': '1 2 xxxx'},
                             sfv._replicate_volume(
                                 {'project_id': 1, 'volumeID': 1},
                                 {'attributes': {}},
                                 {'initiatorSecret': 'shhh',
                                  'targetSecret': 'dont-tell'},
                                 {}))

    def test_pythons_try_except(self):
        def _fake_retrieve_rep(vol):
            raise exception.SolidFireAPIException

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        with mock.patch.object(sfv,
                               '_get_create_account',
                               return_value={'accountID': 5}),\
                mock.patch.object(sfv,
                                  '_retrieve_qos_setting',
                                  return_value=None),\
                mock.patch.object(sfv,
                                  '_do_volume_create',
                                  return_value={'provider_id': '1 2 xxxx'}),\
                mock.patch.object(sfv,
                                  '_retrieve_replication_settings',
                                  side_effect=_fake_retrieve_rep):
            self.assertRaises(exception.SolidFireAPIException,
                              sfv.create_volume,
                              self.mock_volume)
