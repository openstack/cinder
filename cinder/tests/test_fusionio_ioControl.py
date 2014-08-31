# Copyright (c) 2014 Fusion-io, Inc.
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
import json

import mock
import requests

from cinder import context
from cinder.db.sqlalchemy.models import VolumeMetadata
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder.openstack.common import units
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.fusionio.ioControl import FIOconnection
from cinder.volume.drivers.fusionio.ioControl import FIOioControlDriver
from cinder.volume import qos_specs
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)

basic_net_response = [{"IsManagementPort": True,
                       "NetworkAddress": "10.10.1.82",
                       "IsReplicationPort": True, "OperationalState": "up",
                       "ControllerUID": "FakeControl1_UID",
                       "IfIndex": 2},
                      {"IsManagementPort": True,
                       "NetworkAddress": "10.10.1.83",
                       "IsReplicationPort": True, "OperationalState": "up",
                       "ControllerUID": "FakeControl1_UID",
                       "IfIndex": 3},
                      {"IsManagementPort": False,
                       "NetworkAddress": "",
                       "IsReplicationPort": False, "OperationalState": "down",
                       "ControllerUID": "FakeControl1_UID",
                       "IfIndex": 4},
                      {"IsManagementPort": True,
                       "NetworkAddress": "10.10.2.88",
                       "IsReplicationPort": True, "OperationalState": "up",
                       "ControllerUID": "FakeControl2_UID",
                       "IfIndex": 2},
                      {"IsManagementPort": False,
                       "NetworkAddress": "10.10.2.84",
                       "IsReplicationPort": False, "OperationalState": "up",
                       "ControllerUID": "FakeControl2_UID",
                       "IfIndex": 3},
                      {"IsManagementPort": False,
                       "NetworkAddress": "",
                       "IsReplicationPort": False, "OperationalState": "down",
                       "ControllerUID": "FakeControl2_UID",
                       "IfIndex": 4}]

basic_pools_response = [{"TotalMB": 5079, "Name": "PoolOwnerA",
                         "ExportedVolumeMB": 2049,
                         "basetype": "StoragePool", "UsedVolumeMB": 3,
                         "ObjectPath": "", "UsedMetaMB": 4, "UsedMB": 4,
                         "SizeMB": 68677278, "UsedSnapMB": 0,
                         "PagingUsedMB": 4,
                         "CurrentOwnerUUID": "FakeControl1_UID",
                         "TaskId": "", "PagingTotalMB": 5079, "Ready": True,
                         "id": "FakePoolA_id",
                         "Size": 72013345456128},
                        {"TotalMB": 5079, "Name": "PoolOwnerB",
                         "ExportedVolumeMB": 2049,
                         "basetype": "StoragePool", "UsedVolumeMB": 193,
                         "ObjectPath": "", "UsedMetaMB": 3, "UsedMB": 211,
                         "SizeMB": 68677278, "UsedSnapMB": 0,
                         "PagingUsedMB": 211,
                         "CurrentOwnerUUID": "FakeControl2_UID",
                         "TaskId": "", "PagingTotalMB": 5079, "Ready": True,
                         "id": "FakePoolB_id",
                         "Size": 72013345456128}
                        ]

basic_vol_response = [{"basetype": "Volume", "ObjectPath": "", "TaskId": "",
                       "id": "FakeBasicVolID",
                       "Name": "cinderVolumeID",
                       "IQN": "iqn.2010-11.com.ngs:Volume:FakeBasicVolID",
                       "Size": 1074266112, "SizeMB": 1024, "HighWaterMark": 0,
                       "HighWaterMarkMB": 0, "MetadataSize": 262144,
                       "MetadataSizeMB": 0, "DupedSize": 1074266112,
                       "DupedSizeMB": 1024, "FaultTolerance": 0,
                       "PathTolerance": 0,
                       "AllowedTierMask": 18446744073709551615,
                       "RequiredTierMask": 0, "NumberOfPagesPerChapter": 0,
                       "CreateDateTime": 1390837136,
                       "LayerId": "407115424bb9539c",
                       "ParentLayerId": "0", "Protocol": "iscsi",
                       "PoolUUID": "FakePoolB_id",
                       "PolicyUUID": "00000000-00000000-0000-000000000000",
                       "CurrentOwnerUUID": "FakeControl2_UID",
                       "AclGroupList": ["1"], "ReplicaPeerList": [],
                       "SnapshotRetention": 0}
                      ]

basic_policy_response = [{"id": "00000000-00000000-0000-000000000000",
                          "Name": "Policy 5", },
                         {"id": "00000000-00000000-0000-000000000002",
                          "Name": "Policy 4", },
                         {"id": "00000000-00000000-0000-000000000004",
                          "Name": "Policy 3", },
                         {"id": "00000000-00000000-0000-000000000008",
                          "Name": "Policy 2", },
                         {"id": "00000000-00000000-0000-000000000010",
                          "Name": "Policy 1", },
                         ]

basic_snapshot_response = [{"basetype": "Snapshot", "ObjectPath": "",
                            "TaskId": "", "id": "407115424bb9539c",
                            "Name": "cinderSnapshotID",
                            "VolumeUUID": "FakeBasicVolID",
                            "PoolUUID": "FakePoolB_id",
                            "ParentUUID": "0", "Size": 1074266112,
                            "SizeMB": 1024, "SizeUsed": 0, "SizeUsedMB": 0,
                            "SizeReclaimable": 0, "SizeReclaimableMB": 0,
                            "CreateDateTime": 1390952554, "ChildCount": 1,
                            "IsMounted": False, "IsHostConsistent": False,
                            "ReplicaInfoList": []}
                           ]

basic_acl_group_response = [{"id": 1,
                             "GroupName": "Deny Access",
                             "InitiatorList": [], },
                            {"id": 2,
                             "GroupName": "Allow Access",
                             "InitiatorList": ["iqn*"], },
                            {"id": 3,
                             "GroupName": "fake:01", "Description": "",
                             "InitiatorList": ["fake:01"], },
                            {"id": 4,
                             "GroupName": "iqn.1994-05.com.redhat:fake1",
                             "InitiatorList": ["iqn.1994-05.com.rhel:fake1"],
                             },
                            {"id": 5,
                             "GroupName": "MyGroup", "Description": "",
                             "InitiatorList": "iqn.1994-05.com.rhel:fake2", }
                            ]


def create_configuration():
    configuration = conf.Configuration(None)
    configuration.san_ip = "10.123.10.123"
    configuration.san_login = "fioTestUser"
    configuration.san_password = "fioTestUserPassword"
    # we can set targetdelay to 0 for testing
    configuration.fusionio_iocontrol_targetdelay = 0
    configuration.fusionio_iocontrol_retry = 3
    configuration.fusionio_iocontrol_verify_cert = True
    return configuration


class FIOFakeResponse(object):
    """Fake response to requests."""

    def __init__(self, code=None, text=None):
        self.status_code = code
        self.text = text

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code > 300:
            raise requests.exceptions.HTTPError


class FIOioControlConnectionTests(test.TestCase):

    VERSION = '1.0.0'
    fakeSessionID = '12345678'

    def setUp(self):
        super(FIOioControlConnectionTests, self).setUp()
        self.configuration = create_configuration()
        self.ctxt = context.get_admin_context()
        return_text = json.dumps({"Version": FIOconnection.APIVERSION})
        get_return = FIOFakeResponse(code=200,
                                     text=return_text)
        requests.get = mock.Mock(return_value=get_return)
        self.conn = FIOconnection(self.configuration.san_ip,
                                  self.configuration.san_login,
                                  self.configuration.san_password,
                                  self.configuration.fusionio_iocontrol_retry,
                                  (self.configuration.
                                   fusionio_iocontrol_verify_cert),)

    def test_conn_init_sucess(self):
        expected = [mock.call(url=("https://" +
                                   self.configuration.san_ip +
                                   "/AUTH/Version"),
                              headers=self.conn.defhdrs,
                              verify=True)]
        requests.get.assert_has_calls(expected)

    def test_wrong_version(self):
        expected = json.dumps({"Version": (FIOconnection.APIVERSION + ".1")})
        get_return = FIOFakeResponse(code=200,
                                     text=expected)
        requests.get = mock.Mock(return_value=get_return)
        self.assertRaises(exception.VolumeDriverException,
                          FIOconnection,
                          self.configuration.san_ip,
                          self.configuration.san_login,
                          self.configuration.san_password,
                          self.configuration.fusionio_iocontrol_retry,
                          self.configuration.fusionio_iocontrol_verify_cert,)

    def test_create_session_sucess(self):
        expected_text = json.dumps({"id": self.fakeSessionID})
        post_return = FIOFakeResponse(code=201,
                                      text=expected_text)
        put_return = FIOFakeResponse(code=201,
                                     text=json.dumps({"Status": 1}))
        requests.post = mock.Mock(return_value=post_return)
        requests.put = mock.Mock(return_value=put_return)
        result = self.conn._create_session()
        expectedhdr = copy.deepcopy(self.conn.defhdrs)
        expectedhdr["Cookie"] = 'session=' + self.fakeSessionID
        assert result == expectedhdr

    def test_create_session_auth_fail(self):
        expected_text = json.dumps({"id": self.fakeSessionID})
        post_return = FIOFakeResponse(code=201,
                                      text=expected_text)
        put_return = FIOFakeResponse(code=201,
                                     text=json.dumps({"Status": (-1)}))
        requests.post = mock.Mock(return_value=post_return)
        requests.put = mock.Mock(return_value=put_return)
        requests.delete = mock.Mock()
        self.assertRaises(exception.VolumeDriverException,
                          self.conn._create_session,)

    def test_delete_session_sucess(self):
        requests.delete = mock.Mock(return_value=True)
        hdrs = copy.deepcopy(self.conn.defhdrs)
        hdrs["Cookie"] = 'session=' + self.fakeSessionID
        self.conn._delete_session(hdrs)
        expected = [mock.call(url=("https://" +
                                   self.configuration.san_ip +
                                   "/AUTH/SESSION/" + self.fakeSessionID),
                              headers=self.conn.defhdrs,
                              verify=True), ]
        requests.delete.assert_has_calls(expected)

    def test_put_sucess(self):
        put_return = FIOFakeResponse(code=201,
                                     text=json.dumps({"Status": 1}))
        requests.put = mock.Mock(return_value=put_return)
        expectedhdr = copy.deepcopy(self.conn.defhdrs)
        expectedhdr["Cookie"] = 'session=' + self.fakeSessionID
        self.conn._create_session = mock.Mock(return_value=expectedhdr)
        self.conn._delete_session = mock.Mock()
        testurl = '/test/url/'
        testcontent = {'testdict': 'testvalue'}
        self.conn.put(testurl, testcontent)
        self.conn.post(testurl, testcontent)
        expected = [mock.call(), ]
        self.conn._create_session.assert_has_calls(expected)
        expected = [mock.call(expectedhdr), ]
        self.conn._delete_session.assert_has_calls(expected)
        expected = [mock.call(url=self.conn._complete_uri(testurl),
                              data=json.dumps(testcontent, sort_keys=True),
                              headers=expectedhdr, verify=True), ]
        requests.put.assert_has_calls(expected)

    def test_post_sucess(self):
        expected_text = json.dumps({"id": self.fakeSessionID})
        post_return = FIOFakeResponse(code=201,
                                      text=expected_text)
        requests.post = mock.Mock(return_value=post_return)
        expectedhdr = copy.deepcopy(self.conn.defhdrs)
        expectedhdr["Cookie"] = 'session=' + self.fakeSessionID
        self.conn._create_session = mock.Mock(return_value=expectedhdr)
        self.conn._delete_session = mock.Mock()
        testurl = '/test/url/'
        testcontent = {'testdict': 'testvalue'}
        self.conn.post(testurl, testcontent)
        expected = [mock.call(), ]
        self.conn._create_session.assert_has_calls(expected)
        expected = [mock.call(expectedhdr), ]
        self.conn._delete_session.assert_has_calls(expected)
        expected = [mock.call(url=self.conn._complete_uri(testurl),
                              data=json.dumps(testcontent, sort_keys=True),
                              headers=expectedhdr, verify=True), ]
        requests.post.assert_has_calls(expected)

    def test_delete_sucess(self):
        del_return = FIOFakeResponse(code=201, text=json.dumps({}))
        requests.delete = mock.Mock(return_value=del_return)
        expectedhdr = copy.deepcopy(self.conn.defhdrs)
        expectedhdr["Cookie"] = 'session=' + self.fakeSessionID
        self.conn._create_session = mock.Mock(return_value=expectedhdr)
        self.conn._delete_session = mock.Mock()
        testurl = '/test/url/'
        self.conn.delete(testurl,)
        expected = [mock.call(), ]
        self.conn._create_session.assert_has_calls(expected)
        expected = [mock.call(expectedhdr), ]
        self.conn._delete_session.assert_has_calls(expected)
        expected = [mock.call(url=self.conn._complete_uri(testurl),
                              headers=expectedhdr, verify=True), ]
        requests.delete.assert_has_calls(expected)

    def test_get_sucess(self):
        get_return = FIOFakeResponse(code=200,
                                     text=json.dumps(basic_acl_group_response))
        expectedhdr = copy.deepcopy(self.conn.defhdrs)
        expectedhdr["Cookie"] = 'session=' + self.fakeSessionID
        self.conn._create_session = mock.Mock(return_value=expectedhdr)
        self.conn._delete_session = mock.Mock()
        requests.get = mock.Mock(return_value=get_return)
        testurl = '/test/url/'
        result = self.conn.get(testurl,)
        expected = [mock.call(), ]
        self.conn._create_session.assert_has_calls(expected)
        expected = [mock.call(expectedhdr), ]
        self.conn._delete_session.assert_has_calls(expected)
        expected = [mock.call(url=self.conn._complete_uri(testurl),
                              headers=expectedhdr, verify=True), ]
        requests.get.assert_has_calls(expected)
        assert result == basic_acl_group_response

    def test_get_bad_json_once(self):
        expectedhdr = copy.deepcopy(self.conn.defhdrs)
        expectedhdr["Cookie"] = 'session=' + self.fakeSessionID
        self.conn._create_session = mock.Mock(return_value=expectedhdr)
        self.conn._delete_session = mock.Mock()
        expected_text = json.dumps(basic_acl_group_response)
        jsonErrEffect = [FIOFakeResponse(code=200,
                                         text='{"badjson":"bad",,}'),
                         FIOFakeResponse(code=200,
                                         text=expected_text)]
        requests.get = mock.Mock(side_effect=jsonErrEffect)
        testurl = '/test/url/'
        result = self.conn.get(testurl,)
        expected = [mock.call(), ]
        self.conn._create_session.assert_has_calls(expected)
        expected = [mock.call(expectedhdr), ]
        self.conn._delete_session.assert_has_calls(expected)
        expected = [mock.call(url=self.conn._complete_uri(testurl),
                              headers=expectedhdr, verify=True), ]
        requests.get.assert_has_calls(expected)
        assert result == basic_acl_group_response

    def test_get_bad_json_retry_expire(self):
        get_return = FIOFakeResponse(code=200, text='{"badjson":"bad",,}')
        expectedhdr = copy.deepcopy(self.conn.defhdrs)
        expectedhdr["Cookie"] = 'session=' + self.fakeSessionID
        self.conn._create_session = mock.Mock(return_value=expectedhdr)
        self.conn._delete_session = mock.Mock()
        requests.get = mock.Mock(return_value=get_return)
        testurl = '/test/url/'
        self.assertRaises(exception.VolumeDriverException,
                          self.conn.get, testurl)
        expected = [mock.call(), ]
        self.conn._create_session.assert_has_calls(expected)
        expected = [mock.call(expectedhdr), ]
        self.conn._delete_session.assert_has_calls(expected)
        expected = [mock.call(url=self.conn._complete_uri(testurl),
                              headers=expectedhdr, verify=True),
                    mock.call(url=self.conn._complete_uri(testurl),
                              headers=expectedhdr, verify=True),
                    mock.call(url=self.conn._complete_uri(testurl),
                              headers=expectedhdr, verify=True), ]
        requests.get.assert_has_calls(expected)

    def test_get_failed_http_response(self):
        get_return = FIOFakeResponse(code=404,
                                     text=json.dumps(basic_acl_group_response))
        expectedhdr = copy.deepcopy(self.conn.defhdrs)
        expectedhdr["Cookie"] = 'session=' + self.fakeSessionID
        self.conn._create_session = mock.Mock(return_value=expectedhdr)
        self.conn._delete_session = mock.Mock()
        requests.get = mock.Mock(return_value=get_return)
        testurl = '/test/url/'
        self.assertRaises(requests.exceptions.HTTPError,
                          self.conn.get, testurl)
        expected = [mock.call(), ]
        self.conn._create_session.assert_has_calls(expected)
        expected = [mock.call(expectedhdr), ]
        self.conn._delete_session.assert_has_calls(expected)
        expected = [mock.call(url=self.conn._complete_uri(testurl),
                              headers=expectedhdr, verify=True), ]
        requests.get.assert_has_calls(expected)


@mock.patch('cinder.volume.drivers.fusionio.ioControl.FIOconnection',
            autospec=True)
class FIOioControlTestCases(test.TestCase):

    VERSION = '1.0.0'
    policyTable = {'Policy 4': '00000000-00000000-0000-000000000002',
                   'Policy 5': '00000000-00000000-0000-000000000000',
                   'Policy 2': '00000000-00000000-0000-000000000008',
                   'Policy 3': '00000000-00000000-0000-000000000004',
                   'Policy 1': '00000000-00000000-0000-000000000010'}

    def setUp(self):
        super(FIOioControlTestCases, self).setUp()
        self.configuration = create_configuration()
        self.ctxt = context.get_admin_context()
        self.drv = FIOioControlDriver(configuration=self.configuration)
        self.drv.fio_qos_dict = self.policyTable

    def test_do_setup_sucess(self, connmock):
        # erase policy table, then make sure drv.do_setup builds it
        self.drv.fio_qos_dict = {}
        instance = connmock.return_value
        instance.get.return_value = basic_policy_response
        self.drv.do_setup(context="")
        self.assertEqual(self.policyTable, self.drv.fio_qos_dict,
                         "wrong policy table built")

    def test_create_volume_simple_success_poolA(self, connmock):
        self.drv.conn = connmock.return_value
        bPoolResponse = copy.deepcopy(basic_pools_response)
        bPoolResponse[1]['ExportedVolumeMB'] = 5009
        self.drv.conn.get.return_value = bPoolResponse
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}
        self.drv.create_volume(testvol)
        cmd = {"Size": int(testvol['size']) * units.Gi,
               "PolicyUUID": '00000000-00000000-0000-000000000000',
               "PoolUUID": "FakePoolA_id",
               "Name": testvol['id'], }
        expected = [mock.call.get('TierStore/Pools/by-id/'),
                    mock.call.post('TierStore/Volumes/by-id/', cmd)]
        self.drv.conn.assert_has_calls(expected)

    def test_create_volume_simple_success_poolB(self, connmock):
        self.drv.conn = connmock.return_value
        bPoolResponse = copy.deepcopy(basic_pools_response)
        bPoolResponse[0]['ExportedVolumeMB'] = 5009
        self.drv.conn.get.return_value = bPoolResponse
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}
        self.drv.create_volume(testvol)
        cmd = {"Size": int(testvol['size']) * units.Gi,
               "PolicyUUID": '00000000-00000000-0000-000000000000',
               "PoolUUID": "FakePoolB_id",
               "Name": testvol['id'], }
        expected = [mock.call.get('TierStore/Pools/by-id/'),
                    mock.call.post('TierStore/Volumes/by-id/', cmd)]
        self.drv.conn.assert_has_calls(expected)

    def test_delete_volume_sucess(self, connmock):
        self.drv.conn = connmock.return_value
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}
        self.drv.conn.get.return_value = basic_vol_response
        self.drv.delete_volume(testvol)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.delete('TierStore/Volumes/by-id/FakeBasicVolID')]
        self.drv.conn.assert_has_calls(expected)

    def test_create_snapshot_sucess(self, connmock):
        self.drv.conn = connmock.return_value
        snapshot = {'volume_id': 'cinderVolumeID',
                    'id': 'a720b3c0-d1f0-11e1-9b23-1234500cab39', }
        self.drv.conn.get.return_value = basic_vol_response
        cmd = {"VolumeUUID": "FakeBasicVolID",
               "Name": snapshot['id'], }
        self.drv.create_snapshot(snapshot)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.post('TierStore/Snapshots/by-id/', cmd), ]
        self.drv.conn.assert_has_calls(expected)

    def test_delete_snapshot_sucess(self, connmock):
        self.drv.conn = connmock.return_value
        snapshot = {'volume_id': '1dead3c0-d1f0-beef-9b23-1274500cab58',
                    'id': 'cinderSnapshotID'}
        self.drv.conn.get.return_value = basic_snapshot_response
        self.drv.delete_snapshot(snapshot)
        expected = [mock.call.get('TierStore/Snapshots/by-id/'),
                    mock.call.delete(
                                    ('TierStore/Snapshots/by-id/' +
                                     '407115424bb9539c')), ]
        self.drv.conn.assert_has_calls(expected)

    def test_create_volume_from_snapshot_simple_sucess(self, connmock):
        self.drv.conn = connmock.return_value
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}
        snapshot = {'volume_id': testvol['id'],
                    'id': 'cinderSnapshotID'}
        self.drv.conn.get.return_value = basic_snapshot_response
        cmd = {"ParentLayerId": "407115424bb9539c",
               "Name": testvol['id'],
               "PolicyUUID": '00000000-00000000-0000-000000000000'}
        self.drv.create_volume_from_snapshot(testvol, snapshot)
        expected = [mock.call.get('TierStore/Snapshots/by-id/'),
                    mock.call.put(
                        'TierStore/Snapshots/functions/CloneSnapshot', cmd), ]
        self.drv.conn.assert_has_calls(expected)

    def test_initialize_connection_no_usable_Networks_fail(self, connmock):
        self.drv.conn = connmock.return_value
        connector = {'initiator': 'fake:01'}
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow(),
                   'provider_auth': {}}
        cmd = {"GroupName": "fake:01",
               "InitiatorList": ["fake:01"]}
        cmd2 = {"AclGroupList": ["3"], }
        netResponse = copy.deepcopy(basic_net_response)
        netResponse[4]['OperationalState'] = "down"
        get_effect = [basic_vol_response,
                      basic_acl_group_response,
                      basic_vol_response,
                      netResponse, ]
        self.drv.conn.get.side_effect = get_effect
        self.assertRaises(exception.VolumeDriverException,
                          self.drv.initialize_connection, testvol,
                          connector)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.post('TierStore/ACLGroup/by-id/', cmd),
                    mock.call.get('TierStore/ACLGroup/by-id/'),
                    mock.call.put('TierStore/Volumes/by-id/FakeBasicVolID',
                                  cmd2),
                    mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.get('System/Network/by-id/'), ]
        self.drv.conn.assert_has_calls(expected)

    def test_initialize_connection_simple_sucess(self, connmock):
        self.drv.conn = connmock.return_value
        connector = {'initiator': 'fake:01'}
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow(),
                   'provider_auth': {}}
        cmd = {"GroupName": "fake:01",
               "InitiatorList": ["fake:01"]}
        cmd2 = {"AclGroupList": ["3"], }
        netResponse = copy.deepcopy(basic_net_response)
        netResponse[2]['OperationalState'] = "up"
        get_effect = [basic_vol_response,
                      basic_acl_group_response,
                      basic_vol_response,
                      netResponse, ]
        self.drv.conn.get.side_effect = get_effect
        result = self.drv.initialize_connection(testvol, connector)
        expected = {'driver_volume_type': 'iscsi',
                    'data': {'target_lun': 0,
                             'target_portal': u'10.10.2.84:3260',
                             'target_iqn': (
                                 'iqn.2010-11.com.ngs:Volume:FakeBasicVolID'),
                             'target_discovered': False,
                             'volume_id': 'cinderVolumeID'}}
        self.assertEqual(result, expected, "wrong result from init connection")
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.post('TierStore/ACLGroup/by-id/', cmd),
                    mock.call.get('TierStore/ACLGroup/by-id/'),
                    mock.call.put('TierStore/Volumes/by-id/FakeBasicVolID',
                                  cmd2),
                    mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.get('System/Network/by-id/'), ]
        self.drv.conn.assert_has_calls(expected)

    def test_terminate_connection_single_delete_sucess(self, connmock):
        self.drv.conn = connmock.return_value
        connector = {'initiator': 'fake:01'}
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow(),
                   'provider_auth': {}}
        cmd = {"AclGroupList": ["1"], }
        get_effect = [basic_vol_response,
                      basic_acl_group_response,
                      basic_acl_group_response,
                      basic_vol_response, ]
        self.drv.conn.get.side_effect = get_effect
        self.drv.terminate_connection(testvol, connector)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.get('TierStore/ACLGroup/by-id/'),
                    mock.call.put('TierStore/Volumes/by-id/FakeBasicVolID',
                                  cmd),
                    mock.call.get('TierStore/ACLGroup/by-id/'),
                    mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.delete('TierStore/ACLGroup/by-id/3')]
        self.drv.conn.assert_has_calls(expected)

    def test_terminate_connection_multiple_no_delete(self, connmock):
        self.drv.conn = connmock.return_value
        connector = {'initiator': 'fake:01'}
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow(),
                   'provider_auth': {}}
        cmd = {"AclGroupList": ["1"], }
        return2vol = copy.deepcopy(basic_vol_response)
        return2vol.append(copy.deepcopy(basic_vol_response[0]))
        return2vol[1]['AclGroupList'] = ["3"]
        get_effect = [basic_vol_response,
                      basic_acl_group_response,
                      basic_acl_group_response,
                      return2vol, ]
        self.drv.conn.get.side_effect = get_effect
        self.drv.terminate_connection(testvol, connector)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.get('TierStore/ACLGroup/by-id/'),
                    mock.call.put('TierStore/Volumes/by-id/FakeBasicVolID',
                                  cmd),
                    mock.call.get('TierStore/ACLGroup/by-id/'),
                    mock.call.get('TierStore/Volumes/by-id/')]
        self.drv.conn.assert_has_calls(expected)

    def test_terminate_connection_multiple_delete(self, connmock):
        self.drv.conn = connmock.return_value
        connector = {'initiator': 'fake:01'}
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow(),
                   'provider_auth': {}}
        cmd = {"AclGroupList": ["1"], }
        return2vol = copy.deepcopy(basic_vol_response)
        return2vol.append(copy.deepcopy(basic_vol_response[0]))
        get_effect = [basic_vol_response,
                      basic_acl_group_response,
                      basic_acl_group_response,
                      return2vol, ]
        self.drv.conn.get.side_effect = get_effect
        self.drv.terminate_connection(testvol, connector)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.get('TierStore/ACLGroup/by-id/'),
                    mock.call.put('TierStore/Volumes/by-id/FakeBasicVolID',
                                  cmd),
                    mock.call.get('TierStore/ACLGroup/by-id/'),
                    mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.delete('TierStore/ACLGroup/by-id/3')]
        self.drv.conn.assert_has_calls(expected)

    def test_create_cloned_volume_simple_sucess(self, connmock):
        self.drv.conn = connmock.return_value
        srcvol = {'id': 'cinderVolumeID'}
        dstvol = {'project_id': 'testproject',
                  'name': 'cinderVolumeName',
                  'size': 1,
                  'id': 'cinderVolumeID-dst',
                  'volume_type_id': None,
                  'created_at': timeutils.utcnow()}
        cmd = {'VolumeUUID': 'FakeBasicVolID',
               'Name': 'mockedFakeUUID'}
        # also mock _getSnapshotByName because of the random snapshotname.
        self.drv._get_snapshot_by_name = mock.MagicMock()
        self.drv._get_snapshot_by_name.return_value = \
            basic_snapshot_response[0]
        cmd2 = {"ParentLayerId": "407115424bb9539c",
                "Name": "cinderVolumeID-dst",
                "PolicyUUID": "00000000-00000000-0000-000000000000"}
        get_effect = [basic_vol_response, ]
        self.drv.conn.get.side_effect = get_effect

        with mock.patch('cinder.volume.drivers.fusionio.ioControl.uuid',
                        autospec=True) as uuidmock:
            uuidmock.uuid4.return_value = cmd['Name']
            self.drv.create_cloned_volume(dstvol, srcvol)

        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.post('TierStore/Snapshots/by-id/', cmd),
                    mock.call.put(('TierStore/Snapshots/functions/' +
                                   'CloneSnapshot'), cmd2), ]
        self.drv.conn.assert_has_calls(expected)

    def test_create_cloned_volume_snapfails(self, connmock):
        self.drv.conn = connmock.return_value
        # this operation is a 2 part process, snap, then clone.
        # This tests for the snap failing
        srcvol = {'id': 'cinderVolumeID'}
        dstvol = {'project_id': 'testproject',
                  'name': 'cinderVolumeName',
                  'size': 1,
                  'id': 'cinderVolumeID-dst',
                  'volume_type_id': None,
                  'created_at': timeutils.utcnow()}
        cmd = {'VolumeUUID': 'FakeBasicVolID',
               'Name': 'mockedFakeUUID'}
        get_effect = [basic_vol_response, ]
        self.drv.conn.get.side_effect = get_effect
        self.drv.conn.post.side_effect = requests.exceptions.HTTPError
        with mock.patch('cinder.volume.drivers.fusionio.ioControl.uuid',
                        autospec=True) as uuidmock:
            uuidmock.uuid4.return_value = cmd['Name']
            self.assertRaises(requests.exceptions.HTTPError,
                              self.drv.create_cloned_volume,
                              dstvol, srcvol)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.post('TierStore/Snapshots/by-id/', cmd), ]
        self.drv.conn.assert_has_calls(expected)

    def test_create_cloned_volume_clonefails(self, connmock):
        self.drv.conn = connmock.return_value
        srcvol = {'id': 'cinderVolumeID'}
        dstvol = {'project_id': 'testproject',
                  'name': 'cinderVolumeName',
                  'size': 1,
                  'id': 'cinderVolumeID-dst',
                  'volume_type_id': None,
                  'created_at': timeutils.utcnow()}
        get_effect = [basic_vol_response,
                      basic_snapshot_response[0], ]
        self.drv.conn.get.side_effect = get_effect
        # also mock _getSnapshotByName because of the random snapshotname.
        self.drv._get_snapshot_by_name = mock.MagicMock()
        self.drv._get_snapshot_by_name.return_value = \
            basic_snapshot_response[0]
        cmd = {'VolumeUUID': 'FakeBasicVolID',
               'Name': 'mockedFakeUUID'}
        cmd2 = {"ParentLayerId": "407115424bb9539c",
                "Name": "cinderVolumeID-dst",
                "PolicyUUID": "00000000-00000000-0000-000000000000"}
        self.drv.conn.put.side_effect = requests.exceptions.HTTPError
        with mock.patch('cinder.volume.drivers.fusionio.ioControl.uuid',
                        autospec=True) as uuidmock:
                uuidmock.uuid4.return_value = cmd['Name']
                self.assertRaises(requests.exceptions.HTTPError,
                                  self.drv.create_cloned_volume,
                                  dstvol, srcvol)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.post('TierStore/Snapshots/by-id/', cmd),
                    mock.call.put(('TierStore/Snapshots/functions/' +
                                   'CloneSnapshot'), cmd2),
                    mock.call.delete(('TierStore/Snapshots/by-id/' +
                                      cmd2['ParentLayerId'])), ]
        self.drv.conn.assert_has_calls(expected)

    def test_get_volume_stats_simple_sucess(self, connmock):
        self.drv.conn = connmock.return_value
        self.drv.conn.get.side_effect = [basic_pools_response, ]
        result = self.drv.get_volume_stats(refresh=True)
        self.assertEqual(basic_pools_response[0]['PagingTotalMB'] +
                         basic_pools_response[1]['PagingTotalMB'],
                         result['total_capacity_gb'],
                         "capacity calc wrong")
        self.assertEqual(self.VERSION, result['driver_version'],
                         "Driver/Test version Mismatch")

    def test_create_volume_QoS_by_presets(self, connmock):
        preset_qos = VolumeMetadata(key='fio-qos', value='Policy 2')
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_metadata': [preset_qos],
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        expected_qos_result = '00000000-00000000-0000-000000000008'  # Policy 2
        qos = self.drv._set_qos_presets(testvol)
        self.assertEqual(qos, expected_qos_result)

    def test_create_volume_Qos_by_volumeType_QoSspec(self, connmock):
        qos_ref = qos_specs.create(self.ctxt,
                                   'qos-specs-1', {'fio-qos': 'Policy 2'})
        type_ref = volume_types.create(self.ctxt,
                                       "type1",
                                       {"volume_backend_name": "fio-ioControl",
                                        "qos:fio-qos": "Policy 4"}
                                       )
        qos_specs.associate_qos_with_type(self.ctxt,
                                          qos_ref['id'],
                                          type_ref['id'])
        expected_qos_result = '00000000-00000000-0000-000000000008'  # Policy 2
        qos = self.drv._set_qos_by_volume_type(type_ref['id'])
        self.assertEqual(qos, expected_qos_result)

    def test_create_volume_Qos_by_volumeType_extraSpec(self, connmock):
        type_ref = volume_types.create(self.ctxt,
                                       "type1",
                                       {"volume_backend_name": "fio-ioControl",
                                        "qos:fio-qos": "Policy 4"}
                                       )
        expected_qos_result = '00000000-00000000-0000-000000000002'  # Policy 4
        qos = self.drv._set_qos_by_volume_type(type_ref['id'])
        self.assertEqual(qos, expected_qos_result)

    def test_extend_volume_simple_success(self, connmock):
        self.drv.conn = connmock.return_value
        testvol = {'project_id': 'testproject',
                   'name': 'cinderVolumeName',
                   'size': 1,
                   'id': 'cinderVolumeID',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}
        new_size = 10
        cmd = {"Size": int(new_size) * units.Gi}
        self.drv.conn.get.side_effect = [basic_vol_response, ]
        self.drv.extend_volume(testvol, new_size)
        expected = [mock.call.get('TierStore/Volumes/by-id/'),
                    mock.call.put('TierStore/Volumes/by-id/FakeBasicVolID',
                                  cmd)]
        self.drv.conn.assert_has_calls(expected)
