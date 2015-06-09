
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

import mock
from mox3 import mox
from oslo_utils import timeutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import solidfire
from cinder.volume import qos_specs
from cinder.volume import volume_types


def create_configuration():
    configuration = mox.MockObject(conf.Configuration)
    configuration.san_is_local = False
    configuration.append_config_values(mox.IgnoreArg())
    return configuration


class SolidFireVolumeTestCase(test.TestCase):
    def setUp(self):
        self.ctxt = context.get_admin_context()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.sf_allow_tenant_qos = True
        self.configuration.san_is_local = True
        self.configuration.sf_emulate_512 = True
        self.configuration.sf_account_prefix = 'cinder'
        self.configuration.reserved_percentage = 25
        self.configuration.iscsi_helper = None
        self.configuration.sf_template_account_name = 'openstack-vtemplate'
        self.configuration.sf_allow_template_caching = False

        super(SolidFireVolumeTestCase, self).setUp()
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(solidfire.SolidFireDriver,
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
        self.fake_image_service = 'null'

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

    def fake_issue_api_request(obj, method, params, version='1.0'):
        if method is 'GetClusterCapacity' and version == '1.0':
            data = {'result':
                    {'clusterCapacity': {'maxProvisionedSpace': 107374182400,
                                         'usedSpace': 1073741824,
                                         'compressionPercent': 100,
                                         'deDuplicationPercent': 100,
                                         'thinProvisioningPercent': 100}}}
            return data

        elif method is 'GetClusterInfo' and version == '1.0':
            results = {'result': {'clusterInfo':
                                  {'name': 'fake-cluster',
                                   'mvip': '1.1.1.1',
                                   'svip': '1.1.1.1',
                                   'uniqueID': 'unqid',
                                   'repCount': 2,
                                   'attributes': {}}}}
            return results

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
                             'totalSize': 1 * units.Gi,
                             'enable512e': True,
                             'access': "readWrite",
                             'status': "active",
                             'attributes': {},
                             'qos': None,
                             'iqn': test_name}]}}
            return result
        else:
            # Crap, unimplemented API call in Fake
            return None

    def fake_issue_api_request_fails(obj, method,
                                     params, version='1.0',
                                     endpoint=None):
        return {'error': {'code': 000,
                          'name': 'DummyError',
                          'message': 'This is a fake error response'},
                'id': 1}

    def fake_set_qos_by_volume_type(self, type_id, ctxt):
        return {'minIOPS': 500,
                'maxIOPS': 1000,
                'burstIOPS': 1000}

    def fake_volume_get(obj, key, default=None):
        return {'qos': 'fast'}

    def fake_update_cluster_status(self):
        return

    def fake_get_model_info(self, account, vid):
        return {'fake': 'fake-model'}

    def test_create_with_qos_type(self):
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_set_qos_by_volume_type',
                       self.fake_set_qos_by_volume_type)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': 'fast',
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        model_update = sfv.create_volume(testvol)
        self.assertIsNotNone(model_update)

    def test_create_volume(self):
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        model_update = sfv.create_volume(testvol)
        self.assertIsNotNone(model_update)
        self.assertIsNone(model_update.get('provider_geometry', None))

    def test_create_volume_non_512(self):
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        self.configuration.sf_emulate_512 = False
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        model_update = sfv.create_volume(testvol)
        self.assertEqual(model_update.get('provider_geometry', None),
                         '4096 4096')
        self.configuration.sf_emulate_512 = True

    def test_create_delete_snapshot(self):
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        testsnap = {'project_id': 'testprjid',
                    'name': 'testvol',
                    'volume_size': 1,
                    'id': 'b831c4d1-d1f0-11e1-9b23-0800200c9a66',
                    'volume_id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                    'volume_type_id': None,
                    'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.create_volume(testvol)
        sfv.create_snapshot(testsnap)
        with mock.patch.object(solidfire.SolidFireDriver,
                               '_get_sf_snapshots',
                               return_value=[{'snapshotID': '1',
                                              'name': 'testvol'}]):
            sfv.delete_snapshot(testsnap)

    def test_create_clone(self):
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_get_model_info',
                       self.fake_get_model_info)
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

        with mock.patch.object(solidfire.SolidFireDriver,
                               '_get_sf_snapshots',
                               return_value=[]):
            sfv = solidfire.SolidFireDriver(configuration=self.configuration)
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

    def test_create_volume_with_qos(self):
        preset_qos = {}
        preset_qos['qos'] = 'fast'
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)

        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'metadata': [preset_qos],
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        model_update = sfv.create_volume(testvol)
        self.assertIsNotNone(model_update)

    def test_create_volume_fails(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is inentional for this test
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_update_cluster_status',
                       self.fake_update_cluster_status)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request_fails)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        try:
            sfv.create_volume(testvol)
            self.fail("Should have thrown Error")
        except Exception:
            pass

    def test_create_sfaccount(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        account = sfv._create_sfaccount('project-id')
        self.assertIsNotNone(account)

    def test_create_sfaccount_fails(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request_fails)
        account = sfv._create_sfaccount('project-id')
        self.assertIsNone(account)

    def test_get_sfaccount_by_name(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        account = sfv._get_sfaccount_by_name('some-name')
        self.assertIsNotNone(account)

    def test_get_sfaccount_by_name_fails(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request_fails)
        account = sfv._get_sfaccount_by_name('some-name')
        self.assertIsNone(account)

    def test_delete_volume(self):
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv.delete_volume(testvol)

    def test_delete_volume_fails_no_volume(self):
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        try:
            sfv.delete_volume(testvol)
            self.fail("Should have thrown Error")
        except Exception:
            pass

    def test_delete_volume_fails_account_lookup(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is inentional for this test
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_update_cluster_status',
                       self.fake_update_cluster_status)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request_fails)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.assertRaises(exception.SolidFireAccountNotFound,
                          sfv.delete_volume,
                          testvol)

    def test_get_cluster_info(self):
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv._get_cluster_info()

    def test_get_cluster_info_fail(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is inentional for this test
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_update_cluster_status',
                       self.fake_update_cluster_status)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request_fails)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.assertRaises(exception.SolidFireAPIException,
                          sfv._get_cluster_info)

    def test_extend_volume(self):
        self.stubs.Set(solidfire.SolidFireDriver,
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
        self.stubs.Set(solidfire.SolidFireDriver,
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
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_update_cluster_status',
                       self.fake_update_cluster_status)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request_fails)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.assertRaises(exception.SolidFireAccountNotFound,
                          sfv.extend_volume,
                          testvol, 2)

    def test_set_by_qos_spec_with_scoping(self):
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
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'])
        self.assertEqual(qos, self.expected_qos_results)

    def test_set_by_qos_spec(self):
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
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'])
        self.assertEqual(qos, self.expected_qos_results)

    def test_set_by_qos_by_type_only(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:minIOPS": "100",
                                                 "qos:burstIOPS": "300",
                                                 "qos:maxIOPS": "200"})
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'])
        self.assertEqual(qos, {'minIOPS': 100,
                               'maxIOPS': 200,
                               'burstIOPS': 300})

    def test_accept_transfer(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        expected = {'provider_auth': 'CHAP cinder-new_project 123456789012'}
        self.assertEqual(sfv.accept_transfer(self.ctxt,
                                             testvol,
                                             'new_user', 'new_project'),
                         expected)

    def test_accept_transfer_volume_not_found_raises(self):
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(solidfire.SolidFireDriver,
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
        self.stubs.Set(solidfire.SolidFireDriver,
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

        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(volume_types, 'get_volume_type',
                       _fake_get_volume_type)
        self.stubs.Set(qos_specs, 'get_qos_specs',
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
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        sfv._update_cluster_status()
        self.assertEqual(sfv.cluster_stats['free_capacity_gb'], 99.0)
        self.assertEqual(sfv.cluster_stats['total_capacity_gb'], 100.0)

    def test_manage_existing_volume(self):
        external_ref = {'name': 'existing volume', 'source-id': 5}
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        model_update = sfv.manage_existing(testvol, external_ref)
        self.assertIsNotNone(model_update)
        self.assertIsNone(model_update.get('provider_geometry', None))

    def test_create_volume_for_migration(self):
        def _fake_do_v_create(self, project_id, params):
            return project_id, params

        self.stubs.Set(solidfire.SolidFireDriver,
                       '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(solidfire.SolidFireDriver,
                       '_do_volume_create', _fake_do_v_create)

        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'b830b3c0-d1f0-11e1-9b23-1900200c9a77',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow(),
                   'migration_status': 'target:'
                                       'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        proj_id, sf_vol_object = sfv.create_volume(testvol)
        self.assertEqual('a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                         sf_vol_object['attributes']['uuid'])
        self.assertEqual('b830b3c0-d1f0-11e1-9b23-1900200c9a77',
                         sf_vol_object['attributes']['migration_uuid'])
        self.assertEqual('UUID-a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                         sf_vol_object['name'])

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_image_volume')
    def test_verify_image_volume_out_of_date(self,
                                             _mock_create_image_volume,
                                             _mock_get_sf_volume,
                                             _mock_get_sfaccount,
                                             _mock_issue_api_request):
        fake_sf_vref = {
            'status': 'active', 'volumeID': 1,
            'attributes': {
                'image_info':
                    {'image_updated_at': '2014-12-17T00:16:23+00:00',
                     'image_id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                     'image_name': 'fake-image',
                     'image_created_at': '2014-12-17T00:16:23+00:00'}}}

        stats_data =\
            {'result':
                {'clusterCapacity': {'maxProvisionedSpace': 107374182400,
                                     'usedSpace': 1073741824,
                                     'compressionPercent': 100,
                                     'deDuplicationPercent': 100,
                                     'thinProvisioningPercent': 100}}}

        _mock_issue_api_request.return_value = stats_data
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
        _mock_issue_api_request.return_value = {'result': 'ok'}
        sfv._verify_image_volume(self.ctxt, image_meta, image_service)
        self.assertTrue(_mock_create_image_volume.called)

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sfaccount')
    @mock.patch.object(solidfire.SolidFireDriver, '_get_sf_volume')
    @mock.patch.object(solidfire.SolidFireDriver, '_create_image_volume')
    def test_verify_image_volume_ok(self,
                                    _mock_create_image_volume,
                                    _mock_get_sf_volume,
                                    _mock_get_sfaccount,
                                    _mock_issue_api_request):

        _mock_issue_api_request.return_value = self.mock_stats_data
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
        _mock_issue_api_request.return_value = {'result': 'ok'}

        sfv._verify_image_volume(self.ctxt, image_meta, image_service)
        self.assertFalse(_mock_create_image_volume.called)

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    def test_clone_image_not_configured(self, _mock_issue_api_request):
        _mock_issue_api_request.return_value = self.mock_stats_data

        sfv = solidfire.SolidFireDriver(configuration=self.configuration)
        self.assertEqual((None, False),
                         sfv.clone_image(self.ctxt,
                                         self.mock_volume,
                                         'fake',
                                         self.fake_image_meta,
                                         'fake'))

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    def test_clone_image_authorization(self, _mock_issue_api_request):
        _mock_issue_api_request.return_value = self.mock_stats_data
        self.configuration.sf_allow_template_caching = True
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        # Make sure if it's NOT public and we're NOT the owner it
        # doesn't try and cache
        _fake_image_meta = {'id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                            'updated_at': datetime.datetime(2013, 9,
                                                            28, 15,
                                                            27, 36,
                                                            325355),
                            'properties': {'virtual_size': 1},
                            'is_public': False,
                            'owner': 'wrong-owner'}
        self.assertEqual((None, False),
                         sfv.clone_image(self.ctxt,
                                         self.mock_volume,
                                         'fake',
                                         _fake_image_meta,
                                         'fake'))

        # And is_public False, but the correct owner does work
        # expect raise AccountNotFound as that's the next call after
        # auth checks
        _fake_image_meta['owner'] = 'testprjid'
        self.assertRaises(exception.SolidFireAccountNotFound,
                          sfv.clone_image, self.ctxt,
                          self.mock_volume, 'fake',
                          _fake_image_meta, 'fake')

        # And is_public True, even if not the correct owner
        _fake_image_meta['is_public'] = True
        _fake_image_meta['owner'] = 'wrong-owner'
        self.assertRaises(exception.SolidFireAccountNotFound,
                          sfv.clone_image, self.ctxt,
                          self.mock_volume, 'fake',
                          _fake_image_meta, 'fake')

    @mock.patch.object(solidfire.SolidFireDriver, '_issue_api_request')
    def test_clone_image_virt_size_not_set(self, _mock_issue_api_request):
        _mock_issue_api_request.return_value = self.mock_stats_data
        self.configuration.sf_allow_template_caching = True
        sfv = solidfire.SolidFireDriver(configuration=self.configuration)

        # Don't run clone_image if virtual_size property not on image
        _fake_image_meta = {'id': '17c550bb-a411-44c0-9aaf-0d96dd47f501',
                            'updated_at': datetime.datetime(2013, 9,
                                                            28, 15,
                                                            27, 36,
                                                            325355),
                            'is_public': True,
                            'owner': 'testprjid'}

        self.assertEqual((None, False),
                         sfv.clone_image(self.ctxt,
                                         self.mock_volume,
                                         'fake',
                                         _fake_image_meta,
                                         'fake'))
