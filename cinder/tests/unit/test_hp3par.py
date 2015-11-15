#
#    (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""Unit tests for OpenStack Cinder volume drivers."""

import mock

import ast

from oslo_config import cfg
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_hp_3par_client as hp3parclient
from cinder.volume.drivers.san.hp import hp_3par_common as hpcommon
from cinder.volume.drivers.san.hp import hp_3par_fc as hpfcdriver
from cinder.volume.drivers.san.hp import hp_3par_iscsi as hpdriver
from cinder.volume import qos_specs
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types

hpexceptions = hp3parclient.hpexceptions

CONF = cfg.CONF

HP3PAR_CPG = 'OpenStackCPG'
HP3PAR_CPG2 = 'fakepool'
HP3PAR_CPG_QOS = 'qospool'
HP3PAR_CPG_SNAP = 'OpenStackCPGSnap'
HP3PAR_USER_NAME = 'testUser'
HP3PAR_USER_PASS = 'testPassword'
HP3PAR_SAN_IP = '2.2.2.2'
HP3PAR_SAN_SSH_PORT = 999
HP3PAR_SAN_SSH_CON_TIMEOUT = 44
HP3PAR_SAN_SSH_PRIVATE = 'foobar'
GOODNESS_FUNCTION = \
    "stats.capacity_utilization < 0.6? 100:25"
FILTER_FUNCTION = \
    "stats.total_volumes < 400 && stats.capacity_utilization < 0.8"

CHAP_USER_KEY = "HPQ-cinder-CHAP-name"
CHAP_PASS_KEY = "HPQ-cinder-CHAP-secret"

FLASH_CACHE_ENABLED = 1
FLASH_CACHE_DISABLED = 2

# Input/output (total read/write) operations per second.
THROUGHPUT = 'throughput'
# Data processed (total read/write) per unit time: kilobytes per second.
BANDWIDTH = 'bandwidth'
# Response time (total read/write): microseconds.
LATENCY = 'latency'
# IO size (total read/write): kilobytes.
IO_SIZE = 'io_size'
# Queue length for processing IO requests
QUEUE_LENGTH = 'queue_length'
# Average busy percentage
AVG_BUSY_PERC = 'avg_busy_perc'


class HP3PARBaseDriver(object):

    class CommentMatcher(object):
        def __init__(self, f, expect):
            self.assertEqual = f
            self.expect = expect

        def __eq__(self, actual):
            actual_as_dict = dict(ast.literal_eval(actual))
            self.assertEqual(self.expect, actual_as_dict)
            return True

    VOLUME_ID = 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'
    CLONE_ID = 'd03338a9-9115-48a3-8dfc-000000000000'
    VOLUME_TYPE_ID_DEDUP = 'd03338a9-9115-48a3-8dfc-11111111111'
    VOLUME_TYPE_ID_FLASH_CACHE = 'd03338a9-9115-48a3-8dfc-22222222222'
    VOLUME_NAME = 'volume-' + VOLUME_ID
    VOLUME_NAME_3PAR = 'osv-0DM4qZEVSKON-DXN-NwVpw'
    SNAPSHOT_ID = '2f823bdc-e36e-4dc8-bd15-de1c7a28ff31'
    SNAPSHOT_NAME = 'snapshot-2f823bdc-e36e-4dc8-bd15-de1c7a28ff31'
    VOLUME_3PAR_NAME = 'osv-0DM4qZEVSKON-DXN-NwVpw'
    SNAPSHOT_3PAR_NAME = 'oss-L4I73ONuTci9Fd4ceij-MQ'
    CONSIS_GROUP_ID = '6044fedf-c889-4752-900f-2039d247a5df'
    CONSIS_GROUP_NAME = 'vvs-YET.38iJR1KQDyA50kel3w'
    CGSNAPSHOT_ID = 'e91c5ed5-daee-4e84-8724-1c9e31e7a1f2'
    CGSNAPSHOT_BASE_NAME = 'oss-6Rxe1druToSHJByeMeeh8g'
    # fake host on the 3par
    FAKE_HOST = 'fakehost'
    FAKE_CINDER_HOST = 'fakehost@foo#' + HP3PAR_CPG
    USER_ID = '2689d9a913974c008b1d859013f23607'
    PROJECT_ID = 'fac88235b9d64685a3530f73e490348f'
    VOLUME_ID_SNAP = '761fc5e5-5191-4ec7-aeba-33e36de44156'
    FAKE_DESC = 'test description name'
    FAKE_FC_PORTS = [{'portPos': {'node': 7, 'slot': 1, 'cardPort': 1},
                      'portWWN': '0987654321234',
                      'protocol': 1,
                      'mode': 2,
                      'linkState': 4},
                     {'portPos': {'node': 6, 'slot': 1, 'cardPort': 1},
                      'portWWN': '123456789000987',
                      'protocol': 1,
                      'mode': 2,
                      'linkState': 4}]
    QOS = {'qos:maxIOPS': '1000', 'qos:maxBWS': '50',
           'qos:minIOPS': '100', 'qos:minBWS': '25',
           'qos:latency': '25', 'qos:priority': 'low'}
    QOS_SPECS = {'maxIOPS': '1000', 'maxBWS': '50',
                 'minIOPS': '100', 'minBWS': '25',
                 'latency': '25', 'priority': 'low'}
    VVS_NAME = "myvvs"
    FAKE_ISCSI_PORT = {'portPos': {'node': 8, 'slot': 1, 'cardPort': 1},
                       'protocol': 2,
                       'mode': 2,
                       'IPAddr': '1.1.1.2',
                       'iSCSIName': ('iqn.2000-05.com.3pardata:'
                                     '21810002ac00383d'),
                       'linkState': 4}
    volume = {'name': VOLUME_NAME,
              'id': VOLUME_ID,
              'display_name': 'Foo Volume',
              'size': 2,
              'host': FAKE_CINDER_HOST,
              'volume_type': None,
              'volume_type_id': None}

    volume_encrypted = {'name': VOLUME_NAME,
                        'id': VOLUME_ID,
                        'display_name': 'Foo Volume',
                        'size': 2,
                        'host': FAKE_CINDER_HOST,
                        'volume_type': None,
                        'volume_type_id': None,
                        'encryption_key_id': 'fake_key'}

    volume_dedup = {'name': VOLUME_NAME,
                    'id': VOLUME_ID,
                    'display_name': 'Foo Volume',
                    'size': 2,
                    'host': FAKE_CINDER_HOST,
                    'volume_type': 'dedup',
                    'volume_type_id': VOLUME_TYPE_ID_DEDUP}

    volume_pool = {'name': VOLUME_NAME,
                   'id': VOLUME_ID,
                   'display_name': 'Foo Volume',
                   'size': 2,
                   'host': volume_utils.append_host(FAKE_HOST, HP3PAR_CPG2),
                   'volume_type': None,
                   'volume_type_id': None}

    volume_qos = {'name': VOLUME_NAME,
                  'id': VOLUME_ID,
                  'display_name': 'Foo Volume',
                  'size': 2,
                  'host': FAKE_CINDER_HOST,
                  'volume_type': None,
                  'volume_type_id': 'gold'}

    volume_flash_cache = {'name': VOLUME_NAME,
                          'id': VOLUME_ID,
                          'display_name': 'Foo Volume',
                          'size': 2,
                          'host': FAKE_CINDER_HOST,
                          'volume_type': None,
                          'volume_type_id': VOLUME_TYPE_ID_FLASH_CACHE}

    snapshot = {'name': SNAPSHOT_NAME,
                'id': SNAPSHOT_ID,
                'user_id': USER_ID,
                'project_id': PROJECT_ID,
                'volume_id': VOLUME_ID_SNAP,
                'volume_name': VOLUME_NAME,
                'status': 'creating',
                'progress': '0%',
                'volume_size': 2,
                'display_name': 'fakesnap',
                'display_description': FAKE_DESC}

    wwn = ["123456789012345", "123456789054321"]

    connector = {'ip': '10.0.0.2',
                 'initiator': 'iqn.1993-08.org.debian:01:222',
                 'wwpns': [wwn[0], wwn[1]],
                 'wwnns': ["223456789012345", "223456789054321"],
                 'host': FAKE_HOST,
                 'multipath': False}

    connector_multipath_enabled = {'ip': '10.0.0.2',
                                   'initiator': ('iqn.1993-08.org'
                                                 '.debian:01:222'),
                                   'wwpns': [wwn[0], wwn[1]],
                                   'wwnns': ["223456789012345",
                                             "223456789054321"],
                                   'host': FAKE_HOST,
                                   'multipath': True}

    volume_type = {'name': 'gold',
                   'deleted': False,
                   'updated_at': None,
                   'extra_specs': {'cpg': HP3PAR_CPG2,
                                   'qos:maxIOPS': '1000',
                                   'qos:maxBWS': '50',
                                   'qos:minIOPS': '100',
                                   'qos:minBWS': '25',
                                   'qos:latency': '25',
                                   'qos:priority': 'low'},
                   'deleted_at': None,
                   'id': 'gold'}

    volume_type_dedup = {'name': 'dedup',
                         'deleted': False,
                         'updated_at': None,
                         'extra_specs': {'cpg': HP3PAR_CPG2,
                                         'provisioning': 'dedup'},
                         'deleted_at': None,
                         'id': VOLUME_TYPE_ID_DEDUP}

    volume_type_flash_cache = {'name': 'flash-cache-on',
                               'deleted': False,
                               'updated_at': None,
                               'extra_specs': {'cpg': HP3PAR_CPG2,
                                               'hp3par:flash_cache': 'true'},
                               'deleted_at': None,
                               'id': VOLUME_TYPE_ID_FLASH_CACHE}

    flash_cache_3par_keys = {'flash_cache': 'true'}

    cpgs = [
        {'SAGrowth': {'LDLayout': {'diskPatterns': [{'diskType': 2}]},
                      'incrementMiB': 8192},
         'SAUsage': {'rawTotalMiB': 24576,
                     'rawUsedMiB': 768,
                     'totalMiB': 8192,
                     'usedMiB': 256},
         'SDGrowth': {'LDLayout': {'RAIDType': 4,
                      'diskPatterns': [{'diskType': 2}]},
                      'incrementMiB': 32768},
         'SDUsage': {'rawTotalMiB': 49152,
                     'rawUsedMiB': 1023,
                     'totalMiB': 36864,
                     'usedMiB': 1024 * 1},
         'UsrUsage': {'rawTotalMiB': 57344,
                      'rawUsedMiB': 43349,
                      'totalMiB': 43008,
                      'usedMiB': 1024 * 20},
         'additionalStates': [],
         'degradedStates': [],
         'failedStates': [],
         'id': 5,
         'name': HP3PAR_CPG,
         'numFPVVs': 2,
         'numTPVVs': 0,
         'numTDVVs': 1,
         'state': 1,
         'uuid': '29c214aa-62b9-41c8-b198-543f6cf24edf'}]

    cgsnapshot = {'consistencygroup_id': CONSIS_GROUP_ID,
                  'description': 'cgsnapshot',
                  'id': CGSNAPSHOT_ID,
                  'readOnly': False}

    TASK_DONE = 1
    TASK_ACTIVE = 2
    STATUS_DONE = {'status': 1}
    STATUS_ACTIVE = {'status': 2}

    mock_client_conf = {
        'PORT_MODE_TARGET': 2,
        'PORT_STATE_READY': 4,
        'PORT_PROTO_ISCSI': 2,
        'PORT_PROTO_FC': 1,
        'TASK_DONE': TASK_DONE,
        'TASK_ACTIVE': TASK_ACTIVE,
        'HOST_EDIT_ADD': 1,
        'CHAP_INITIATOR': 1,
        'CHAP_TARGET': 2,
        'getPorts.return_value': {
            'members': FAKE_FC_PORTS + [FAKE_ISCSI_PORT]
        }
    }

    RETYPE_VVS_NAME = "yourvvs"

    RETYPE_HOST = {
        u'host': u'mark-stack1@3parfc',
        u'capabilities': {
            'QoS_support': True,
            u'location_info': u'HP3PARDriver:1234567:MARK_TEST_CPG',
            u'timestamp': u'2014-06-04T19:03:32.485540',
            u'allocated_capacity_gb': 0,
            u'volume_backend_name': u'3parfc',
            u'free_capacity_gb': u'infinite',
            u'driver_version': u'2.0.3',
            u'total_capacity_gb': u'infinite',
            u'reserved_percentage': 0,
            u'vendor_name': u'Hewlett-Packard',
            u'storage_protocol': u'FC'
        }
    }

    RETYPE_HOST_NOT3PAR = {
        u'host': u'mark-stack1@3parfc',
        u'capabilities': {
            u'location_info': u'XXXDriverXXX:1610771:MARK_TEST_CPG',
        }
    }

    RETYPE_QOS_SPECS = {'maxIOPS': '1000', 'maxBWS': '50',
                        'minIOPS': '100', 'minBWS': '25',
                        'latency': '25', 'priority': 'high'}

    RETYPE_VOLUME_TYPE_ID = "FakeVolId"

    RETYPE_VOLUME_TYPE_0 = {
        'name': 'red',
        'id': RETYPE_VOLUME_TYPE_ID,
        'extra_specs': {
            'cpg': HP3PAR_CPG,
            'snap_cpg': HP3PAR_CPG_SNAP,
            'vvs': RETYPE_VVS_NAME,
            'qos': RETYPE_QOS_SPECS,
            'tpvv': True,
            'tdvv': False,
            'volume_type': volume_type
        }
    }

    RETYPE_VOLUME_TYPE_1 = {
        'name': 'white',
        'id': RETYPE_VOLUME_TYPE_ID,
        'extra_specs': {
            'cpg': HP3PAR_CPG,
            'snap_cpg': HP3PAR_CPG_SNAP,
            'vvs': VVS_NAME,
            'qos': QOS,
            'tpvv': True,
            'tdvv': False,
            'volume_type': volume_type
        }
    }

    RETYPE_VOLUME_TYPE_2 = {
        'name': 'blue',
        'id': RETYPE_VOLUME_TYPE_ID,
        'extra_specs': {
            'cpg': HP3PAR_CPG_QOS,
            'snap_cpg': HP3PAR_CPG_SNAP,
            'vvs': RETYPE_VVS_NAME,
            'qos': RETYPE_QOS_SPECS,
            'tpvv': True,
            'tdvv': False,
            'volume_type': volume_type
        }
    }

    RETYPE_VOLUME_TYPE_3 = {
        'name': 'purple',
        'id': RETYPE_VOLUME_TYPE_ID,
        'extra_specs': {
            'cpg': HP3PAR_CPG_QOS,
            'snap_cpg': HP3PAR_CPG_SNAP,
            'vvs': RETYPE_VVS_NAME,
            'qos': RETYPE_QOS_SPECS,
            'tpvv': False,
            'tdvv': True,
            'volume_type': volume_type
        }
    }
    RETYPE_VOLUME_TYPE_BAD_PERSONA = {
        'name': 'bad_persona',
        'id': 'any_id',
        'extra_specs': {
            'hp3par:persona': '99 - invalid'
        }
    }

    RETYPE_VOLUME_TYPE_BAD_CPG = {
        'name': 'bad_cpg',
        'id': 'any_id',
        'extra_specs': {
            'cpg': 'bogus',
            'snap_cpg': 'bogus',
            'hp3par:persona': '2 - Generic-ALUA'
        }
    }

    MANAGE_VOLUME_INFO = {
        'userCPG': 'testUserCpg0',
        'snapCPG': 'testSnapCpg0',
        'provisioningType': 1,
        'comment': "{'display_name': 'Foo Volume'}"
    }

    MV_INFO_WITH_NO_SNAPCPG = {
        'userCPG': 'testUserCpg0',
        'provisioningType': 1,
        'comment': "{'display_name': 'Foo Volume'}"
    }

    RETYPE_TEST_COMMENT = "{'retype_test': 'test comment'}"

    RETYPE_VOLUME_INFO_0 = {
        'name': VOLUME_NAME,
        'id': VOLUME_ID,
        'display_name': 'Retype Vol0',
        'size': 1,
        'host': RETYPE_HOST,
        'userCPG': 'testUserCpg0',
        'snapCPG': 'testSnapCpg0',
        'provisioningType': 1,
        'comment': RETYPE_TEST_COMMENT
    }

    RETYPE_TEST_COMMENT_1 = "{'retype_test': 'test comment 1'}"

    RETYPE_VOLUME_INFO_1 = {
        'name': VOLUME_NAME,
        'id': VOLUME_ID,
        'display_name': 'Retype Vol1',
        'size': 1,
        'host': RETYPE_HOST,
        'userCPG': HP3PAR_CPG,
        'snapCPG': HP3PAR_CPG_SNAP,
        'provisioningType': 1,
        'comment': RETYPE_TEST_COMMENT
    }

    RETYPE_TEST_COMMENT_2 = "{'retype_test': 'test comment 2'}"

    RETYPE_VOLUME_INFO_2 = {
        'name': VOLUME_NAME,
        'id': VOLUME_ID,
        'display_name': 'Retype Vol2',
        'size': 1,
        'host': RETYPE_HOST,
        'userCPG': HP3PAR_CPG,
        'snapCPG': HP3PAR_CPG_SNAP,
        'provisioningType': 3,
        'comment': RETYPE_TEST_COMMENT
    }
    # Test for when we don't get a snapCPG.
    RETYPE_VOLUME_INFO_NO_SNAP = {
        'name': VOLUME_NAME,
        'id': VOLUME_ID,
        'display_name': 'Retype Vol2',
        'size': 1,
        'host': RETYPE_HOST,
        'userCPG': 'testUserCpg2',
        'provisioningType': 1,
        'comment': '{}'
    }

    RETYPE_CONF = {
        'TASK_ACTIVE': TASK_ACTIVE,
        'TASK_DONE': TASK_DONE,
        'getTask.return_value': STATUS_DONE,
        'getStorageSystemInfo.return_value': {'serialNumber': '1234567'},
        'getVolume.return_value': RETYPE_VOLUME_INFO_0,
        'modifyVolume.return_value': ("anyResponse", {'taskid': 1})
    }

    # 3PAR retype currently doesn't use the diff.  Existing code and fresh info
    # from the array work better for the most part.  Some use of the diff was
    # intentionally removed to make _retype more usable for other use cases.
    RETYPE_DIFF = None

    wsapi_version_312 = {'major': 1,
                         'build': 30102422,
                         'minor': 3,
                         'revision': 1}

    wsapi_version_for_dedup = {'major': 1,
                               'build': 30201120,
                               'minor': 4,
                               'revision': 1}

    wsapi_version_for_flash_cache = {'major': 1,
                                     'build': 30201200,
                                     'minor': 4,
                                     'revision': 2}

    # Use this to point to latest version of wsapi
    wsapi_version_latest = wsapi_version_for_flash_cache

    standard_login = [
        mock.call.login(HP3PAR_USER_NAME, HP3PAR_USER_PASS),
        mock.call.setSSHOptions(
            HP3PAR_SAN_IP,
            HP3PAR_USER_NAME,
            HP3PAR_USER_PASS,
            missing_key_policy='AutoAddPolicy',
            privatekey=HP3PAR_SAN_SSH_PRIVATE,
            known_hosts_file=mock.ANY,
            port=HP3PAR_SAN_SSH_PORT,
            conn_timeout=HP3PAR_SAN_SSH_CON_TIMEOUT)]

    standard_logout = [
        mock.call.logout()]

    def setup_configuration(self):
        configuration = mock.Mock()
        configuration.hp3par_debug = False
        configuration.hp3par_username = HP3PAR_USER_NAME
        configuration.hp3par_password = HP3PAR_USER_PASS
        configuration.hp3par_api_url = 'https://1.1.1.1/api/v1'
        configuration.hp3par_cpg = [HP3PAR_CPG, HP3PAR_CPG2]
        configuration.hp3par_cpg_snap = HP3PAR_CPG_SNAP
        configuration.iscsi_ip_address = '1.1.1.2'
        configuration.iscsi_port = '1234'
        configuration.san_ip = HP3PAR_SAN_IP
        configuration.san_login = HP3PAR_USER_NAME
        configuration.san_password = HP3PAR_USER_PASS
        configuration.san_ssh_port = HP3PAR_SAN_SSH_PORT
        configuration.ssh_conn_timeout = HP3PAR_SAN_SSH_CON_TIMEOUT
        configuration.san_private_key = HP3PAR_SAN_SSH_PRIVATE
        configuration.hp3par_snapshot_expiration = ""
        configuration.hp3par_snapshot_retention = ""
        configuration.hp3par_iscsi_ips = []
        configuration.hp3par_iscsi_chap_enabled = False
        configuration.goodness_function = GOODNESS_FUNCTION
        configuration.filter_function = FILTER_FUNCTION
        configuration.image_volume_cache_enabled = False
        return configuration

    @mock.patch(
        'hp3parclient.client.HP3ParClient',
        spec=True,
    )
    def setup_mock_client(self, _m_client, driver, conf=None, m_conf=None):

        _m_client = _m_client.return_value

        # Configure the base constants, defaults etc...
        _m_client.configure_mock(**self.mock_client_conf)

        # If m_conf, drop those over the top of the base_conf.
        if m_conf is not None:
            _m_client.configure_mock(**m_conf)

        if conf is None:
            conf = self.setup_configuration()
        self.driver = driver(configuration=conf)
        self.driver.do_setup(None)
        return _m_client

    @mock.patch('hp3parclient.version', "3.0.9")
    def test_unsupported_client_version(self):

        self.assertRaises(exception.InvalidInput,
                          self.setup_driver)

    @mock.patch('hp3parclient.version', "3.1.2")
    def test_ssh_options(self):

        expected_hosts_key_file = "test_hosts_key_file"
        orig_ssh_hosts_key_file = CONF.ssh_hosts_key_file
        orig_strict_ssh_host_key_policy = CONF.strict_ssh_host_key_policy
        CONF.ssh_hosts_key_file = expected_hosts_key_file
        CONF.strict_ssh_host_key_policy = False

        self.ctxt = context.get_admin_context()
        mock_client = self.setup_mock_client(driver=hpfcdriver.HP3PARFCDriver)

        CONF.ssh_hosts_key_file = orig_ssh_hosts_key_file
        CONF.strict_ssh_host_key_policy = orig_strict_ssh_host_key_policy

        expected = [
            mock.call.login(HP3PAR_USER_NAME, HP3PAR_USER_PASS),
            mock.call.setSSHOptions(
                HP3PAR_SAN_IP,
                HP3PAR_USER_NAME,
                HP3PAR_USER_PASS,
                privatekey=HP3PAR_SAN_SSH_PRIVATE,
                known_hosts_file=expected_hosts_key_file,
                missing_key_policy="AutoAddPolicy",
                port=HP3PAR_SAN_SSH_PORT,
                conn_timeout=HP3PAR_SAN_SSH_CON_TIMEOUT),
            mock.call.getCPG(HP3PAR_CPG),
            mock.call.getCPG(HP3PAR_CPG2)]
        mock_client.assert_has_calls(
            expected +
            self.standard_logout)

    @mock.patch('hp3parclient.version', "3.1.2")
    def test_ssh_options_strict(self):

        expected_hosts_key_file = "test_hosts_key_file"
        orig_ssh_hosts_key_file = CONF.ssh_hosts_key_file
        orig_strict_ssh_host_key_policy = CONF.strict_ssh_host_key_policy
        CONF.ssh_hosts_key_file = expected_hosts_key_file
        CONF.strict_ssh_host_key_policy = True

        self.ctxt = context.get_admin_context()
        mock_client = self.setup_mock_client(driver=hpfcdriver.HP3PARFCDriver)

        CONF.ssh_hosts_key_file = orig_ssh_hosts_key_file
        CONF.strict_ssh_host_key_policy = orig_strict_ssh_host_key_policy

        expected = [
            mock.call.login(HP3PAR_USER_NAME, HP3PAR_USER_PASS),
            mock.call.setSSHOptions(
                HP3PAR_SAN_IP,
                HP3PAR_USER_NAME,
                HP3PAR_USER_PASS,
                privatekey=HP3PAR_SAN_SSH_PRIVATE,
                known_hosts_file=expected_hosts_key_file,
                missing_key_policy="RejectPolicy",
                port=HP3PAR_SAN_SSH_PORT,
                conn_timeout=HP3PAR_SAN_SSH_CON_TIMEOUT),
            mock.call.getCPG(HP3PAR_CPG),
            mock.call.getCPG(HP3PAR_CPG2)]
        mock_client.assert_has_calls(expected + self.standard_logout)

    def test_task_waiter(self):

        task_statuses = [self.STATUS_ACTIVE, self.STATUS_ACTIVE]

        def side_effect(*args):
            return task_statuses and task_statuses.pop(0) or self.STATUS_DONE

        conf = {'getTask.side_effect': side_effect}
        mock_client = self.setup_driver(mock_conf=conf)

        task_id = 1234
        interval = .001

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            waiter = common.TaskWaiter(mock_client, task_id, interval)
            status = waiter.wait_for_task()

            expected = [
                mock.call.getTask(task_id),
                mock.call.getTask(task_id),
                mock.call.getTask(task_id)
            ]
            mock_client.assert_has_calls(expected)
            self.assertEqual(self.STATUS_DONE, status)

    def test_create_volume(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.create_volume(self.volume)
            comment = (
                '{"display_name": "Foo Volume", "type": "OpenStack",'
                ' "name": "volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7",'
                ' "volume_id": "d03338a9-9115-48a3-8dfc-35cdfcdc15a7"}')
            expected = [
                mock.call.createVolume(
                    self.VOLUME_3PAR_NAME,
                    HP3PAR_CPG,
                    2048, {
                        'comment': comment,
                        'tpvv': True,
                        'tdvv': False,
                        'snapCPG': HP3PAR_CPG_SNAP})]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_create_volume_in_pool(self):

        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client

            return_model = self.driver.create_volume(self.volume_pool)
            comment = (
                '{"display_name": "Foo Volume", "type": "OpenStack",'
                ' "name": "volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7",'
                ' "volume_id": "d03338a9-9115-48a3-8dfc-35cdfcdc15a7"}')
            expected = [
                mock.call.createVolume(
                    self.VOLUME_3PAR_NAME,
                    HP3PAR_CPG2,
                    2048, {
                        'comment': comment,
                        'tpvv': True,
                        'tdvv': False,
                        'snapCPG': HP3PAR_CPG_SNAP})]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(None, return_model)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_unsupported_dedup_volume_type(self, _mock_volume_types):

        mock_client = self.setup_driver(wsapi_version=self.wsapi_version_312)
        _mock_volume_types.return_value = {
            'name': 'dedup',
            'extra_specs': {
                'cpg': HP3PAR_CPG_QOS,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': self.VVS_NAME,
                'qos': self.QOS,
                'provisioning': 'dedup',
                'volume_type': self.volume_type_dedup}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            self.assertRaises(exception.InvalidInput,
                              common.get_volume_settings_from_type_id,
                              self.VOLUME_TYPE_ID_DEDUP,
                              "mock")

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_snap_cpg_from_volume_type(self, _mock_volume_types):

        mock_client = self.setup_driver()
        expected_type_snap_cpg = "type_snap_cpg"
        _mock_volume_types.return_value = {
            'name': 'gold',
            'extra_specs': {
                'cpg': HP3PAR_CPG,
                'snap_cpg': expected_type_snap_cpg,
                'volume_type': self.volume_type}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            result = common.get_volume_settings_from_type_id(
                "mock", self.driver.configuration.hp3par_cpg)

            self.assertEqual(expected_type_snap_cpg, result['snap_cpg'])

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_snap_cpg_from_volume_type_cpg(self, _mock_volume_types):

        mock_client = self.setup_driver()
        expected_cpg = 'use_extra_specs_cpg'
        _mock_volume_types.return_value = {
            'name': 'gold',
            'extra_specs': {
                'cpg': expected_cpg,
                'volume_type': self.volume_type}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            result = common.get_volume_settings_from_type_id(
                "mock", self.driver.configuration.hp3par_cpg)

            self.assertEqual(self.driver.configuration.hp3par_cpg_snap,
                             result['snap_cpg'])

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_snap_cpg_from_volume_type_conf_snap_cpg(
            self, _mock_volume_types):
        _mock_volume_types.return_value = {
            'name': 'gold',
            'extra_specs': {
                'volume_type': self.volume_type}}

        conf = self.setup_configuration()
        expected_snap_cpg = conf.hp3par_cpg_snap
        mock_client = self.setup_driver(config=conf)
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            result = common.get_volume_settings_from_type_id(
                "mock", self.driver.configuration.hp3par_cpg)

        self.assertEqual(expected_snap_cpg, result['snap_cpg'])

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_snap_cpg_from_volume_type_conf_cpg(
            self, _mock_volume_types):
        _mock_volume_types.return_value = {
            'name': 'gold',
            'extra_specs': {
                'volume_type': self.volume_type}}

        conf = self.setup_configuration()
        conf.hp3par_cpg_snap = None
        expected_cpg = conf.hp3par_cpg
        mock_client = self.setup_driver(config=conf)
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            result = common.get_volume_settings_from_type_id(
                "mock", self.driver.configuration.hp3par_cpg)

            self.assertEqual(expected_cpg, result['snap_cpg'])

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_qos(self, _mock_volume_types):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        _mock_volume_types.return_value = {
            'name': 'gold',
            'extra_specs': {
                'cpg': HP3PAR_CPG_QOS,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': self.VVS_NAME,
                'qos': self.QOS,
                'tpvv': True,
                'tdvv': False,
                'volume_type': self.volume_type}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client

            return_model = self.driver.create_volume(self.volume_qos)
            comment = (
                '{"volume_type_name": "gold", "display_name": "Foo Volume"'
                ', "name": "volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7'
                '", "volume_type_id": "gold", "volume_id": "d03338a9-91'
                '15-48a3-8dfc-35cdfcdc15a7", "qos": {}, "type": "OpenStack"}')

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolume(
                    self.VOLUME_3PAR_NAME,
                    HP3PAR_CPG,
                    2048, {
                        'comment': comment,
                        'tpvv': True,
                        'tdvv': False,
                        'snapCPG': HP3PAR_CPG_SNAP})]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(None, return_model)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_dedup(self, _mock_volume_types):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        _mock_volume_types.return_value = {
            'name': 'dedup',
            'extra_specs': {
                'cpg': HP3PAR_CPG_QOS,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': self.VVS_NAME,
                'qos': self.QOS,
                'provisioning': 'dedup',
                'volume_type': self.volume_type_dedup}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client

            return_model = self.driver.create_volume(self.volume_dedup)
            comment = (
                '{"volume_type_name": "dedup", "display_name": "Foo Volume"'
                ', "name": "volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7'
                '", "volume_type_id": "d03338a9-9115-48a3-8dfc-11111111111"'
                ', "volume_id": "d03338a9-9115-48a3-8dfc-35cdfcdc15a7"'
                ', "qos": {}, "type": "OpenStack"}')

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolume(
                    self.VOLUME_3PAR_NAME,
                    HP3PAR_CPG,
                    2048, {
                        'comment': comment,
                        'tpvv': False,
                        'tdvv': True,
                        'snapCPG': HP3PAR_CPG_SNAP})]
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(None, return_model)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_flash_cache(self, _mock_volume_types):
        # Setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        _mock_volume_types.return_value = {
            'name': 'flash-cache-on',
            'extra_specs': {
                'cpg': HP3PAR_CPG2,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': self.VVS_NAME,
                'qos': self.QOS,
                'tpvv': True,
                'tdvv': False,
                'hp3par:flash_cache': 'true',
                'volume_type': self.volume_type_flash_cache}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            mock_client.getCPG.return_value = {'domain': None}
            mock_client.FLASH_CACHE_ENABLED = FLASH_CACHE_ENABLED
            mock_client.FLASH_CACHE_DISABLED = FLASH_CACHE_DISABLED

            return_model = self.driver.create_volume(self.volume_flash_cache)
            comment = (
                '{"volume_type_name": "flash-cache-on", '
                '"display_name": "Foo Volume", '
                '"name": "volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7", '
                '"volume_type_id": "d03338a9-9115-48a3-8dfc-22222222222", '
                '"volume_id": "d03338a9-9115-48a3-8dfc-35cdfcdc15a7", '
                '"qos": {}, "type": "OpenStack"}')

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolume(
                    self.VOLUME_3PAR_NAME,
                    HP3PAR_CPG,
                    2048, {
                        'comment': comment,
                        'tpvv': True,
                        'tdvv': False,
                        'snapCPG': HP3PAR_CPG_SNAP}),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolumeSet('vvs-0DM4qZEVSKON-DXN-NwVpw', None),
                mock.call.createQoSRules(
                    'vvs-0DM4qZEVSKON-DXN-NwVpw',
                    {'priority': 2}
                ),
                mock.call.modifyVolumeSet(
                    'vvs-0DM4qZEVSKON-DXN-NwVpw', flashCachePolicy=1),
                mock.call.addVolumeToVolumeSet(
                    'vvs-0DM4qZEVSKON-DXN-NwVpw',
                    'osv-0DM4qZEVSKON-DXN-NwVpw')]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(None, return_model)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_unsupported_flash_cache_volume(self, _mock_volume_types):

        mock_client = self.setup_driver(wsapi_version=self.wsapi_version_312)
        _mock_volume_types.return_value = {
            'name': 'flash-cache-on',
            'extra_specs': {
                'cpg': HP3PAR_CPG2,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': self.VVS_NAME,
                'qos': self.QOS,
                'tpvv': True,
                'tdvv': False,
                'hp3par:flash_cache': 'true',
                'volume_type': self.volume_type_flash_cache}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            self.assertRaises(exception.InvalidInput,
                              common.get_flash_cache_policy,
                              self.flash_cache_3par_keys)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_not_3par(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.assertRaises(exception.InvalidHost,
                              self.driver.retype,
                              self.ctxt,
                              self.RETYPE_VOLUME_INFO_0,
                              self.RETYPE_VOLUME_TYPE_1,
                              self.RETYPE_DIFF,
                              self.RETYPE_HOST_NOT3PAR)

            expected = [mock.call.getVolume(self.VOLUME_3PAR_NAME)]
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_volume_not_found(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)
        mock_client.getVolume.side_effect = hpexceptions.HTTPNotFound

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.assertRaises(hpexceptions.HTTPNotFound,
                              self.driver.retype,
                              self.ctxt,
                              self.RETYPE_VOLUME_INFO_0,
                              self.RETYPE_VOLUME_TYPE_1,
                              self.RETYPE_DIFF,
                              self.RETYPE_HOST)

            expected = [mock.call.getVolume(self.VOLUME_3PAR_NAME)]
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_specs_error_reverts_snap_cpg(self, _mock_volume_types):
        _mock_volume_types.side_effect = [
            self.RETYPE_VOLUME_TYPE_1, self.RETYPE_VOLUME_TYPE_0]
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)
        mock_client.getVolume.return_value = self.RETYPE_VOLUME_INFO_0

        # Fail the QOS setting to test the revert of the snap CPG rename.
        mock_client.addVolumeToVolumeSet.side_effect = \
            hpexceptions.HTTPForbidden

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.assertRaises(hpexceptions.HTTPForbidden,
                              self.driver.retype,
                              self.ctxt,
                              {'id': self.VOLUME_ID},
                              self.RETYPE_VOLUME_TYPE_0,
                              self.RETYPE_DIFF,
                              self.RETYPE_HOST)

            old_settings = {
                'snapCPG': self.RETYPE_VOLUME_INFO_0['snapCPG'],
                'comment': self.RETYPE_VOLUME_INFO_0['comment']}
            new_settings = {
                'snapCPG': (
                    self.RETYPE_VOLUME_TYPE_1['extra_specs']['snap_cpg']),
                'comment': mock.ANY}

            expected = [
                mock.call.modifyVolume(self.VOLUME_3PAR_NAME, new_settings)
            ]
            mock_client.assert_has_calls(expected)
            expected = [
                mock.call.modifyVolume(self.VOLUME_3PAR_NAME, old_settings)
            ]
            mock_client.assert_has_calls(expected + self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_revert_comment(self, _mock_volume_types):
        _mock_volume_types.side_effect = [
            self.RETYPE_VOLUME_TYPE_2, self.RETYPE_VOLUME_TYPE_1]
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)
        mock_client.getVolume.return_value = self.RETYPE_VOLUME_INFO_1

        # Fail the QOS setting to test the revert of the snap CPG rename.
        mock_client.deleteVolumeSet.side_effect = hpexceptions.HTTPForbidden

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.assertRaises(hpexceptions.HTTPForbidden,
                              self.driver.retype,
                              self.ctxt,
                              {'id': self.VOLUME_ID},
                              self.RETYPE_VOLUME_TYPE_2,
                              self.RETYPE_DIFF,
                              self.RETYPE_HOST)

            original = {
                'snapCPG': self.RETYPE_VOLUME_INFO_1['snapCPG'],
                'comment': self.RETYPE_VOLUME_INFO_1['comment']}

            expected = [
                mock.call.modifyVolume('osv-0DM4qZEVSKON-DXN-NwVpw', original)]
            mock_client.assert_has_calls(expected + self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_different_array(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        mock_client.getStorageSystemInfo.return_value = {
            'serialNumber': 'XXXXXXX'}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.assertRaises(exception.InvalidHost,
                              self.driver.retype,
                              self.ctxt,
                              self.RETYPE_VOLUME_INFO_0,
                              self.RETYPE_VOLUME_TYPE_1,
                              self.RETYPE_DIFF,
                              self.RETYPE_HOST)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getStorageSystemInfo()]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_across_cpg_domains(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        mock_client.getCPG.side_effect = [
            {'domain': 'domain1'},
            {'domain': 'domain2'},
        ]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.assertRaises(exception.Invalid3PARDomain,
                              self.driver.retype,
                              self.ctxt,
                              self.RETYPE_VOLUME_INFO_0,
                              self.RETYPE_VOLUME_TYPE_1,
                              self.RETYPE_DIFF,
                              self.RETYPE_HOST)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getStorageSystemInfo(),
                mock.call.getCPG(self.RETYPE_VOLUME_INFO_0['userCPG']),
                mock.call.getCPG(
                    self.RETYPE_VOLUME_TYPE_1['extra_specs']['cpg'])
            ]
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_across_snap_cpg_domains(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        mock_client.getCPG.side_effect = [
            {'domain': 'cpg_domain'},
            {'domain': 'cpg_domain'},
            {'domain': 'snap_cpg_domain_1'},
        ]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.assertRaises(exception.Invalid3PARDomain,
                              self.driver.retype,
                              self.ctxt,
                              self.RETYPE_VOLUME_INFO_0,
                              self.RETYPE_VOLUME_TYPE_1,
                              self.RETYPE_DIFF,
                              self.RETYPE_HOST)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getStorageSystemInfo(),
                mock.call.getCPG(self.RETYPE_VOLUME_INFO_0['userCPG']),
                mock.call.getCPG(
                    self.RETYPE_VOLUME_TYPE_1['extra_specs']['cpg']),
                mock.call.getCPG(
                    self.RETYPE_VOLUME_TYPE_1['extra_specs']['snap_cpg'])
            ]
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_to_bad_persona(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_BAD_PERSONA
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.assertRaises(exception.InvalidInput,
                              self.driver.retype,
                              self.ctxt,
                              self.RETYPE_VOLUME_INFO_0,
                              self.RETYPE_VOLUME_TYPE_BAD_PERSONA,
                              self.RETYPE_DIFF,
                              self.RETYPE_HOST)

            expected = [mock.call.getVolume(self.VOLUME_3PAR_NAME)]
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_tune(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        qos_ref = qos_specs.create(self.ctxt, 'qos-specs-1', self.QOS)
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:maxIOPS": "100",
                                                 "qos:maxBWS": "50",
                                                 "qos:minIOPS": "10",
                                                 "qos:minBWS": "20",
                                                 "qos:latency": "5",
                                                 "qos:priority": "high"})
        qos_specs.associate_qos_with_type(self.ctxt,
                                          qos_ref['id'],
                                          type_ref['id'])

        type_ref = volume_types.get_volume_type(self.ctxt, type_ref['id'])

        volume = {'id': HP3PARBaseDriver.CLONE_ID}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client

            retyped = self.driver.retype(
                self.ctxt, volume, type_ref, None, self.RETYPE_HOST)
            self.assertTrue(retyped)

            expected = [
                mock.call.modifyVolume('osv-0DM4qZEVSKON-AAAAAAAAA',
                                       {'comment': mock.ANY,
                                        'snapCPG': 'OpenStackCPGSnap'}),
                mock.call.deleteVolumeSet('vvs-0DM4qZEVSKON-AAAAAAAAA'),
                mock.call.addVolumeToVolumeSet('myvvs',
                                               'osv-0DM4qZEVSKON-AAAAAAAAA'),
                mock.call.modifyVolume('osv-0DM4qZEVSKON-AAAAAAAAA',
                                       {'action': 6,
                                        'userCPG': 'OpenStackCPG',
                                        'conversionOperation': 1,
                                        'tuneOperation': 1}),
                mock.call.getTask(1)
            ]
            mock_client.assert_has_calls(expected + self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_qos_spec(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        cpg = "any_cpg"
        snap_cpg = "any_cpg"

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            common._retype(self.volume,
                           HP3PARBaseDriver.VOLUME_3PAR_NAME,
                           "old_type", "old_type_id",
                           HP3PARBaseDriver.RETYPE_HOST,
                           None, cpg, cpg, snap_cpg, snap_cpg,
                           True, False, False, True, None, None,
                           self.QOS_SPECS, self.RETYPE_QOS_SPECS,
                           None, None,
                           "{}")

            expected = [
                mock.call.createVolumeSet('vvs-0DM4qZEVSKON-DXN-NwVpw', None),
                mock.call.createQoSRules(
                    'vvs-0DM4qZEVSKON-DXN-NwVpw',
                    {'ioMinGoal': 100, 'ioMaxLimit': 1000,
                     'bwMinGoalKB': 25600, 'bwMaxLimitKB': 51200,
                     'priority': 3,
                     'latencyGoal': 25}
                ),
                mock.call.addVolumeToVolumeSet(
                    'vvs-0DM4qZEVSKON-DXN-NwVpw',
                    'osv-0DM4qZEVSKON-DXN-NwVpw')]
            mock_client.assert_has_calls(expected)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_retype_dedup(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_3
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        cpg = "any_cpg"
        snap_cpg = "any_cpg"
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            common._retype(self.volume,
                           HP3PARBaseDriver.VOLUME_3PAR_NAME,
                           "old_type", "old_type_id",
                           HP3PARBaseDriver.RETYPE_HOST,
                           None, cpg, cpg, snap_cpg, snap_cpg,
                           True, False, False, True, None, None,
                           self.QOS_SPECS, self.RETYPE_QOS_SPECS,
                           None, None,
                           "{}")

            expected = [
                mock.call.modifyVolume('osv-0DM4qZEVSKON-DXN-NwVpw',
                                       {'action': 6,
                                        'userCPG': 'any_cpg',
                                        'conversionOperation': 3,
                                        'tuneOperation': 1}),
                mock.call.getTask(1)]
        mock_client.assert_has_calls(expected)

    def test_delete_volume(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.delete_volume(self.volume)

            expected = [mock.call.deleteVolume(self.VOLUME_3PAR_NAME)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_create_cloned_volume(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.copyVolume.return_value = {'taskid': 1}
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client

            volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                      'id': HP3PARBaseDriver.CLONE_ID,
                      'display_name': 'Foo Volume',
                      'size': 2,
                      'host': volume_utils.append_host(self.FAKE_HOST,
                                                       HP3PAR_CPG2),
                      'source_volid': HP3PARBaseDriver.VOLUME_ID}
            src_vref = {'id': HP3PARBaseDriver.VOLUME_ID}
            model_update = self.driver.create_cloned_volume(volume, src_vref)
            self.assertIsNone(model_update)

            expected = [
                mock.call.copyVolume(
                    self.VOLUME_3PAR_NAME,
                    'osv-0DM4qZEVSKON-AAAAAAAAA',
                    HP3PAR_CPG2,
                    {'snapCPG': 'OpenStackCPGSnap', 'tpvv': True,
                     'tdvv': False, 'online': True})]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_cloned_qos_volume(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_2
        mock_client = self.setup_driver()
        mock_client.copyVolume.return_value = {'taskid': 1}
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client

            src_vref = {'id': HP3PARBaseDriver.CLONE_ID}
            volume = self.volume_qos.copy()
            host = "TEST_HOST"
            pool = "TEST_POOL"
            volume_host = volume_utils.append_host(host, pool)
            expected_cpg = pool
            volume['id'] = HP3PARBaseDriver.VOLUME_ID
            volume['host'] = volume_host
            volume['source_volid'] = HP3PARBaseDriver.CLONE_ID
            model_update = self.driver.create_cloned_volume(volume, src_vref)
            self.assertEqual(None, model_update)

            expected = [
                mock.call.getCPG(expected_cpg),
                mock.call.copyVolume(
                    'osv-0DM4qZEVSKON-AAAAAAAAA',
                    self.VOLUME_3PAR_NAME,
                    expected_cpg,
                    {'snapCPG': 'OpenStackCPGSnap', 'tpvv': True,
                     'tdvv': False, 'online': True})]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_migrate_volume(self):

        conf = {
            'getStorageSystemInfo.return_value': {
                'serialNumber': '1234'},
            'getTask.return_value': {
                'status': 1},
            'getCPG.return_value': {},
            'copyVolume.return_value': {'taskid': 1},
            'getVolume.return_value': self.RETYPE_VOLUME_INFO_1
        }

        mock_client = self.setup_driver(mock_conf=conf)

        mock_client.getVolume.return_value = self.MANAGE_VOLUME_INFO
        mock_client.modifyVolume.return_value = ("anyResponse", {'taskid': 1})
        mock_client.getTask.return_value = self.STATUS_DONE

        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': 'Foo Volume',
                  'volume_type_id': None,
                  'size': 2,
                  'status': 'available',
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            volume_name_3par = common._encode_name(volume['id'])

            loc_info = 'HP3PARDriver:1234:CPG-FC1'
            host = {'host': 'stack@3parfc1#CPG-FC1',
                    'capabilities': {'location_info': loc_info}}

            result = self.driver.migrate_volume(context.get_admin_context(),
                                                volume, host)
            self.assertIsNotNone(result)
            self.assertEqual((True, None), result)

            osv_matcher = 'osv-' + volume_name_3par

            expected = [
                mock.call.modifyVolume(
                    osv_matcher,
                    {'comment': '{"qos": {}, "display_name": "Foo Volume"}',
                     'snapCPG': HP3PAR_CPG_SNAP}),
                mock.call.modifyVolume(osv_matcher,
                                       {'action': 6,
                                        'userCPG': 'CPG-FC1',
                                        'conversionOperation': 1,
                                        'tuneOperation': 1}),
                mock.call.getTask(mock.ANY)
            ]

            mock_client.assert_has_calls(expected + self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_migrate_volume_with_type(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_2

        conf = {
            'getStorageSystemInfo.return_value': {
                'serialNumber': '1234'},
            'getTask.return_value': {
                'status': 1},
            'getCPG.return_value': {},
            'copyVolume.return_value': {'taskid': 1},
            'getVolume.return_value': self.RETYPE_VOLUME_INFO_1
        }

        mock_client = self.setup_driver(mock_conf=conf)

        mock_client.getVolume.return_value = self.MANAGE_VOLUME_INFO
        mock_client.modifyVolume.return_value = ("anyResponse", {'taskid': 1})
        mock_client.getTask.return_value = self.STATUS_DONE

        display_name = 'Foo Volume'
        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': display_name,
                  "volume_type_id": self.RETYPE_VOLUME_TYPE_2['id'],
                  'size': 2,
                  'status': 'available',
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            volume_name_3par = common._encode_name(volume['id'])

            loc_info = 'HP3PARDriver:1234:CPG-FC1'
            instance_host = 'stack@3parfc1#CPG-FC1'
            host = {'host': instance_host,
                    'capabilities': {'location_info': loc_info}}

            result = self.driver.migrate_volume(context.get_admin_context(),
                                                volume, host)
            self.assertIsNotNone(result)
            # when the host and pool are the same we'll get None
            self.assertEqual((True, None), result)

            osv_matcher = 'osv-' + volume_name_3par

            expected_comment = {
                "display_name": display_name,
                "volume_type_id": self.RETYPE_VOLUME_TYPE_2['id'],
                "volume_type_name": self.RETYPE_VOLUME_TYPE_2['name'],
                "vvs": self.RETYPE_VOLUME_TYPE_2['extra_specs']['vvs']
            }
            expected = [
                mock.call.modifyVolume(
                    osv_matcher,
                    {'comment': self.CommentMatcher(self.assertEqual,
                                                    expected_comment),
                     'snapCPG': self.RETYPE_VOLUME_TYPE_2
                     ['extra_specs']['snap_cpg']}),
                mock.call.modifyVolume(
                    osv_matcher,
                    {'action': 6,
                     'userCPG': 'CPG-FC1',
                     'conversionOperation': 1,
                     'tuneOperation': 1}),
                mock.call.getTask(mock.ANY)
            ]

            mock_client.assert_has_calls(
                expected +
                self.standard_logout)

    def test_migrate_volume_diff_host(self):
        conf = {
            'getStorageSystemInfo.return_value': {
                'serialNumber': 'different'},
        }

        mock_client = self.setup_driver(mock_conf=conf)

        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': 'Foo Volume',
                  'volume_type_id': None,
                  'size': 2,
                  'status': 'available',
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}

        loc_info = 'HP3PARDriver:1234:CPG-FC1'
        host = {'host': 'stack@3parfc1',
                'capabilities': {'location_info': loc_info}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            result = self.driver.migrate_volume(context.get_admin_context(),
                                                volume, host)
            self.assertIsNotNone(result)
            self.assertEqual((False, None), result)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_migrate_volume_diff_domain(self, _mock_volume_types):
        _mock_volume_types.return_value = self.volume_type

        conf = {
            'getStorageSystemInfo.return_value': {
                'serialNumber': '1234'},
            'getTask.return_value': {
                'status': 1},
            'getCPG.return_value': {},
            'copyVolume.return_value': {'taskid': 1},
            'getVolume.return_value': self.RETYPE_VOLUME_INFO_1
        }

        mock_client = self.setup_driver(mock_conf=conf)

        mock_client.getVolume.return_value = self.MANAGE_VOLUME_INFO
        mock_client.modifyVolume.return_value = ("anyResponse", {'taskid': 1})
        mock_client.getTask.return_value = self.STATUS_DONE

        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': 'Foo Volume',
                  'volume_type_id': None,
                  'size': 2,
                  'status': 'available',
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            volume_name_3par = common._encode_name(volume['id'])

            loc_info = 'HP3PARDriver:1234:CPG-FC1'
            host = {'host': 'stack@3parfc1#CPG-FC1',
                    'capabilities': {'location_info': loc_info}}

            result = self.driver.migrate_volume(context.get_admin_context(),
                                                volume, host)
            self.assertIsNotNone(result)
            self.assertEqual((True, None), result)

            osv_matcher = 'osv-' + volume_name_3par

            expected = [
                mock.call.modifyVolume(
                    osv_matcher,
                    {'comment': '{"qos": {}, "display_name": "Foo Volume"}',
                     'snapCPG': HP3PAR_CPG_SNAP}),
                mock.call.modifyVolume(osv_matcher,
                                       {'action': 6,
                                        'userCPG': 'CPG-FC1',
                                        'conversionOperation': 1,
                                        'tuneOperation': 1}),
                mock.call.getTask(mock.ANY),
            ]

            mock_client.assert_has_calls(expected + self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_migrate_volume_attached(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'volume_type_id': None,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': 'Foo Volume',
                  'size': 2,
                  'status': 'in-use',
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            volume_name_3par = common._encode_name(volume['id'])
            osv_matcher = 'osv-' + volume_name_3par

            loc_info = 'HP3PARDriver:1234567:CPG-FC1'

            protocol = "FC"
            if self.properties['driver_volume_type'] == "iscsi":
                protocol = "iSCSI"

            host = {'host': 'stack@3parfc1',
                    'capabilities': {'location_info': loc_info,
                                     'storage_protocol': protocol}}

            result = self.driver.migrate_volume(context.get_admin_context(),
                                                volume, host)

            new_comment = {"qos": {},
                           "retype_test": "test comment"}
            expected = [
                mock.call.modifyVolume(osv_matcher,
                                       {'comment': self.CommentMatcher(
                                           self.assertEqual, new_comment),
                                        'snapCPG': 'OpenStackCPGSnap'}),
                mock.call.modifyVolume(osv_matcher,
                                       {'action': 6,
                                        'userCPG': 'OpenStackCPG',
                                        'conversionOperation': 1,
                                        'tuneOperation': 1}),
                mock.call.getTask(1),
                mock.call.logout()
            ]
            mock_client.assert_has_calls(expected)

            self.assertIsNotNone(result)
            self.assertEqual((True, {'host': 'stack@3parfc1#OpenStackCPG'}),
                             result)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_migrate_volume_attached_diff_protocol(self, _mock_volume_types):
        _mock_volume_types.return_value = self.RETYPE_VOLUME_TYPE_1
        mock_client = self.setup_driver(mock_conf=self.RETYPE_CONF)

        protocol = "OTHER"

        volume = {'name': HP3PARBaseDriver.VOLUME_NAME,
                  'volume_type_id': None,
                  'id': HP3PARBaseDriver.CLONE_ID,
                  'display_name': 'Foo Volume',
                  'size': 2,
                  'status': 'in-use',
                  'host': HP3PARBaseDriver.FAKE_HOST,
                  'source_volid': HP3PARBaseDriver.VOLUME_ID}

        loc_info = 'HP3PARDriver:1234567:CPG-FC1'
        host = {'host': 'stack@3parfc1',
                'capabilities': {'location_info': loc_info,
                                 'storage_protocol': protocol}}

        result = self.driver.migrate_volume(context.get_admin_context(),
                                            volume, host)

        self.assertIsNotNone(result)
        self.assertEqual((False, None), result)
        expected = []
        mock_client.assert_has_calls(expected)

    def test_update_migrated_volume(self):
        mock_client = self.setup_driver()
        fake_old_volume = {'id': self.VOLUME_ID}
        provider_location = 'foo'
        fake_new_volume = {'id': self.CLONE_ID,
                           '_name_id': self.CLONE_ID,
                           'provider_location': provider_location}
        original_volume_status = 'available'
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            actual_update = self.driver.update_migrated_volume(
                context.get_admin_context(), fake_old_volume,
                fake_new_volume, original_volume_status)

            expected_update = {'_name_id': None,
                               'provider_location': None}
            self.assertEqual(expected_update, actual_update)

    def test_update_migrated_volume_attached(self):
        mock_client = self.setup_driver()
        fake_old_volume = {'id': self.VOLUME_ID}
        provider_location = 'foo'
        fake_new_volume = {'id': self.CLONE_ID,
                           '_name_id': self.CLONE_ID,
                           'provider_location': provider_location}
        original_volume_status = 'in-use'

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            actual_update = self.driver.update_migrated_volume(
                context.get_admin_context(), fake_old_volume,
                fake_new_volume, original_volume_status)

            expected_update = {'_name_id': fake_new_volume['_name_id'],
                               'provider_location': provider_location}
            self.assertEqual(expected_update, actual_update)

    def test_attach_volume(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.attach_volume(context.get_admin_context(),
                                      self.volume,
                                      'abcdef',
                                      'newhost',
                                      '/dev/vdb')

            expected = [
                mock.call.setVolumeMetaData(
                    self.VOLUME_3PAR_NAME,
                    'HPQ-CS-instance_uuid',
                    'abcdef')]

            mock_client.assert_has_calls(expected)

            # test the exception
            mock_client.setVolumeMetaData.side_effect = Exception('Custom ex')
            self.assertRaises(exception.CinderException,
                              self.driver.attach_volume,
                              context.get_admin_context(),
                              self.volume,
                              'abcdef',
                              'newhost',
                              '/dev/vdb')

    def test_detach_volume(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.detach_volume(context.get_admin_context(), self.volume,
                                      None)
            expected = [
                mock.call.removeVolumeMetaData(
                    self.VOLUME_3PAR_NAME,
                    'HPQ-CS-instance_uuid')]

            mock_client.assert_has_calls(expected)

            # test the exception
            mock_client.removeVolumeMetaData.side_effect = Exception(
                'Custom ex')
            self.assertRaises(exception.CinderException,
                              self.driver.detach_volume,
                              context.get_admin_context(),
                              self.volume, None)

    def test_create_snapshot(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.create_snapshot(self.snapshot)

            comment = (
                '{"volume_id": "761fc5e5-5191-4ec7-aeba-33e36de44156",'
                ' "display_name": "fakesnap",'
                ' "description": "test description name",'
                ' "volume_name":'
                ' "volume-d03338a9-9115-48a3-8dfc-35cdfcdc15a7"}')

            expected = [
                mock.call.createSnapshot(
                    'oss-L4I73ONuTci9Fd4ceij-MQ',
                    'osv-dh-F5VGRTseuujPjbeRBVg',
                    {
                        'comment': comment,
                        'readOnly': True})]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_delete_snapshot(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.delete_snapshot(self.snapshot)

            expected = [
                mock.call.deleteVolume('oss-L4I73ONuTci9Fd4ceij-MQ')]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_delete_snapshot_in_use(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.create_snapshot(self.snapshot)
            self.driver.create_volume_from_snapshot(self.volume, self.snapshot)

            ex = hpexceptions.HTTPConflict("In use")
            mock_client.deleteVolume = mock.Mock(side_effect=ex)

            # Deleting the snapshot that a volume is dependent on should fail
            self.assertRaises(exception.SnapshotIsBusy,
                              self.driver.delete_snapshot,
                              self.snapshot)

    def test_delete_snapshot_not_found(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.create_snapshot(self.snapshot)

            try:
                ex = hpexceptions.HTTPNotFound("not found")
                mock_client.deleteVolume = mock.Mock(side_effect=ex)
                self.driver.delete_snapshot(self.snapshot)
            except Exception:
                self.fail("Deleting a snapshot that is missing should act "
                          "as if it worked.")

    def test_create_volume_from_snapshot(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client

            model_update = self.driver.create_volume_from_snapshot(
                self.volume,
                self.snapshot)
            self.assertIsNone(model_update)

            comment = (
                '{"snapshot_id": "2f823bdc-e36e-4dc8-bd15-de1c7a28ff31",'
                ' "display_name": "Foo Volume",'
                ' "volume_id": "d03338a9-9115-48a3-8dfc-35cdfcdc15a7"}')

            expected = [
                mock.call.createSnapshot(
                    self.VOLUME_3PAR_NAME,
                    'oss-L4I73ONuTci9Fd4ceij-MQ',
                    {
                        'comment': comment,
                        'readOnly': False})]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            volume = self.volume.copy()
            volume['size'] = 1
            self.assertRaises(exception.InvalidInput,
                              self.driver.create_volume_from_snapshot,
                              volume, self.snapshot)

    def test_create_volume_from_snapshot_and_extend(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        conf = {
            'getTask.return_value': {
                'status': 1},
            'copyVolume.return_value': {'taskid': 1},
            'getVolume.return_value': {}
        }

        mock_client = self.setup_driver(mock_conf=conf)
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            volume = self.volume.copy()
            volume['size'] = self.volume['size'] + 10
            model_update = self.driver.create_volume_from_snapshot(
                volume,
                self.snapshot)
            self.assertEqual(None, model_update)

            comment = (
                '{"snapshot_id": "2f823bdc-e36e-4dc8-bd15-de1c7a28ff31",'
                ' "display_name": "Foo Volume",'
                ' "volume_id": "d03338a9-9115-48a3-8dfc-35cdfcdc15a7"}')

            volume_name_3par = common._encode_name(volume['id'])
            osv_matcher = 'osv-' + volume_name_3par
            omv_matcher = 'omv-' + volume_name_3par

            expected = [
                mock.call.createSnapshot(
                    self.VOLUME_3PAR_NAME,
                    'oss-L4I73ONuTci9Fd4ceij-MQ',
                    {
                        'comment': comment,
                        'readOnly': False}),
                mock.call.copyVolume(
                    osv_matcher, omv_matcher, HP3PAR_CPG, mock.ANY),
                mock.call.getTask(mock.ANY),
                mock.call.getVolume(osv_matcher),
                mock.call.deleteVolume(osv_matcher),
                mock.call.modifyVolume(omv_matcher, {'newName': osv_matcher}),
                mock.call.growVolume(osv_matcher, 10 * 1024)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot_and_extend_with_qos(
            self, _mock_volume_types):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        conf = {
            'getTask.return_value': {
                'status': 1},
            'copyVolume.return_value': {'taskid': 1},
            'getVolume.return_value': {}
        }

        mock_client = self.setup_driver(mock_conf=conf)
        _mock_volume_types.return_value = {
            'name': 'gold',
            'extra_specs': {
                'cpg': HP3PAR_CPG_QOS,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': self.VVS_NAME,
                'qos': self.QOS,
                'tpvv': True,
                'tdvv': False,
                'volume_type': self.volume_type}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            volume = self.volume_qos.copy()
            volume['size'] = self.volume['size'] + 10
            model_update = self.driver.create_volume_from_snapshot(
                volume,
                self.snapshot)
            self.assertEqual(None, model_update)

            comment = (
                '{"snapshot_id": "2f823bdc-e36e-4dc8-bd15-de1c7a28ff31",'
                ' "display_name": "Foo Volume",'
                ' "volume_id": "d03338a9-9115-48a3-8dfc-35cdfcdc15a7"}')

            volume_name_3par = common._encode_name(volume['id'])
            osv_matcher = 'osv-' + volume_name_3par
            omv_matcher = 'omv-' + volume_name_3par

            expected = [
                mock.call.createSnapshot(
                    self.VOLUME_3PAR_NAME,
                    'oss-L4I73ONuTci9Fd4ceij-MQ',
                    {
                        'comment': comment,
                        'readOnly': False}),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.copyVolume(
                    osv_matcher, omv_matcher, HP3PAR_CPG, mock.ANY),
                mock.call.getTask(mock.ANY),
                mock.call.getVolume(osv_matcher),
                mock.call.deleteVolume(osv_matcher),
                mock.call.modifyVolume(omv_matcher, {'newName': osv_matcher}),
                mock.call.growVolume(osv_matcher, 10 * 1024)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_create_volume_from_snapshot_and_extend_copy_fail(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        conf = {
            'getTask.return_value': {
                'status': 4,
                'failure message': 'out of disk space'},
            'copyVolume.return_value': {'taskid': 1},
            'getVolume.return_value': {}
        }

        mock_client = self.setup_driver(mock_conf=conf)

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            volume = self.volume.copy()
            volume['size'] = self.volume['size'] + 10

            self.assertRaises(exception.CinderException,
                              self.driver.create_volume_from_snapshot,
                              volume, self.snapshot)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_create_volume_from_snapshot_qos(self, _mock_volume_types):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            _mock_volume_types.return_value = {
                'name': 'gold',
                'extra_specs': {
                    'cpg': HP3PAR_CPG,
                    'snap_cpg': HP3PAR_CPG_SNAP,
                    'vvs_name': self.VVS_NAME,
                    'qos': self.QOS,
                    'tpvv': True,
                    'tdvv': False,
                    'volume_type': self.volume_type}}
            self.driver.create_volume_from_snapshot(
                self.volume_qos,
                self.snapshot)

            comment = (
                '{"snapshot_id": "2f823bdc-e36e-4dc8-bd15-de1c7a28ff31",'
                ' "display_name": "Foo Volume",'
                ' "volume_id": "d03338a9-9115-48a3-8dfc-35cdfcdc15a7"}')

            expected = [
                mock.call.createSnapshot(
                    self.VOLUME_3PAR_NAME,
                    'oss-L4I73ONuTci9Fd4ceij-MQ', {
                        'comment': comment,
                        'readOnly': False})]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            volume = self.volume.copy()
            volume['size'] = 1
            self.assertRaises(exception.InvalidInput,
                              self.driver.create_volume_from_snapshot,
                              volume, self.snapshot)

    def test_terminate_connection(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getHostVLUNs.return_value = [
            {'active': True,
             'volumeName': self.VOLUME_3PAR_NAME,
             'lun': None, 'type': 0}]

        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver.terminate_connection(
                self.volume,
                self.connector,
                force=True)

            expected = [
                mock.call.queryHost(iqns=[self.connector['initiator']]),
                mock.call.getHostVLUNs(self.FAKE_HOST),
                mock.call.deleteVLUN(
                    self.VOLUME_3PAR_NAME,
                    None,
                    self.FAKE_HOST),
                mock.call.getHostVLUNs(self.FAKE_HOST),
                mock.call.deleteHost(self.FAKE_HOST),
                mock.call.removeVolumeMetaData(
                    self.VOLUME_3PAR_NAME, CHAP_USER_KEY),
                mock.call.removeVolumeMetaData(
                    self.VOLUME_3PAR_NAME, CHAP_PASS_KEY)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_update_volume_key_value_pair(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        key = 'a'
        value = 'b'

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            common.update_volume_key_value_pair(
                self.volume,
                key,
                value)

            expected = [
                mock.call.setVolumeMetaData(self.VOLUME_3PAR_NAME, key, value)]

            mock_client.assert_has_calls(expected)

            # check exception
            mock_client.setVolumeMetaData.side_effect = Exception('fake')
            self.assertRaises(exception.VolumeBackendAPIException,
                              common.update_volume_key_value_pair,
                              self.volume,
                              None,
                              'b')

    def test_clear_volume_key_value_pair(self):

        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            key = 'a'
            common = self.driver._login()
            common.clear_volume_key_value_pair(self.volume, key)

            expected = [
                mock.call.removeVolumeMetaData(self.VOLUME_3PAR_NAME, key)]

            mock_client.assert_has_calls(expected)

            # check the exception
            mock_client.removeVolumeMetaData.side_effect = Exception('fake')
            self.assertRaises(exception.VolumeBackendAPIException,
                              common.clear_volume_key_value_pair,
                              self.volume,
                              None)

    def test_extend_volume(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            grow_size = 3
            old_size = self.volume['size']
            new_size = old_size + grow_size
            self.driver.extend_volume(self.volume, str(new_size))
            growth_size_mib = grow_size * units.Ki

            expected = [
                mock.call.growVolume(self.VOLUME_3PAR_NAME, growth_size_mib)]

            mock_client.assert_has_calls(expected)

    def test_extend_volume_non_base(self):
        extend_ex = hpexceptions.HTTPForbidden(error={'code': 150})
        conf = {
            'getTask.return_value': {
                'status': 1},
            'getCPG.return_value': {},
            'copyVolume.return_value': {'taskid': 1},
            'getVolume.return_value': {},
            # Throw an exception first time only
            'growVolume.side_effect': [extend_ex,
                                       None],
        }

        mock_client = self.setup_driver(mock_conf=conf)
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            grow_size = 3
            old_size = self.volume['size']
            new_size = old_size + grow_size
            self.driver.extend_volume(self.volume, str(new_size))

            self.assertEqual(2, mock_client.growVolume.call_count)

    def test_extend_volume_non_base_failure(self):
        extend_ex = hpexceptions.HTTPForbidden(error={'code': 150})
        conf = {
            'getTask.return_value': {
                'status': 1},
            'getCPG.return_value': {},
            'copyVolume.return_value': {'taskid': 1},
            'getVolume.return_value': {},
            # Always fail
            'growVolume.side_effect': extend_ex
        }

        mock_client = self.setup_driver(mock_conf=conf)
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            grow_size = 3
            old_size = self.volume['size']
            new_size = old_size + grow_size
            self.assertRaises(hpexceptions.HTTPForbidden,
                              self.driver.extend_volume,
                              self.volume,
                              str(new_size))

    def test_get_ports(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getPorts.return_value = {
            'members': [
                {'portPos': {'node': 0, 'slot': 8, 'cardPort': 2},
                 'protocol': 2,
                 'IPAddr': '10.10.120.252',
                 'linkState': 4,
                 'device': [],
                 'iSCSIName': 'iqn.2000-05.com.3pardata:21810002ac00383d',
                 'mode': 2,
                 'HWAddr': '2C27D75375D2',
                 'type': 8},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'protocol': 2,
                 'IPAddr': '10.10.220.253',
                 'linkState': 4,
                 'device': [],
                 'iSCSIName': 'iqn.2000-05.com.3pardata:21810002ac00383d',
                 'mode': 2,
                 'HWAddr': '2C27D75375D6',
                 'type': 8},
                {'portWWN': '20210002AC00383D',
                 'protocol': 1,
                 'linkState': 4,
                 'mode': 2,
                 'device': ['cage2'],
                 'nodeWWN': '20210002AC00383D',
                 'type': 2,
                 'portPos': {'node': 0, 'slot': 6, 'cardPort': 3}}]}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            ports = common.get_ports()['members']
            self.assertEqual(3, len(ports))

    def test_get_by_qos_spec_with_scoping(self):
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            qos_ref = qos_specs.create(self.ctxt, 'qos-specs-1', self.QOS)
            type_ref = volume_types.create(self.ctxt,
                                           "type1", {"qos:maxIOPS": "100",
                                                     "qos:maxBWS": "50",
                                                     "qos:minIOPS": "10",
                                                     "qos:minBWS": "20",
                                                     "qos:latency": "5",
                                                     "qos:priority": "high"})
            qos_specs.associate_qos_with_type(self.ctxt,
                                              qos_ref['id'],
                                              type_ref['id'])
            type_ref = volume_types.get_volume_type(self.ctxt, type_ref['id'])
            qos = common._get_qos_by_volume_type(type_ref)
            self.assertEqual({'maxIOPS': '1000', 'maxBWS': '50',
                              'minIOPS': '100', 'minBWS': '25',
                              'latency': '25', 'priority': 'low'}, qos)

    def test_get_by_qos_spec(self):
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            qos_ref = qos_specs.create(
                self.ctxt,
                'qos-specs-1',
                self.QOS_SPECS)
            type_ref = volume_types.create(self.ctxt,
                                           "type1", {"qos:maxIOPS": "100",
                                                     "qos:maxBWS": "50",
                                                     "qos:minIOPS": "10",
                                                     "qos:minBWS": "20",
                                                     "qos:latency": "5",
                                                     "qos:priority": "high"})
            qos_specs.associate_qos_with_type(self.ctxt,
                                              qos_ref['id'],
                                              type_ref['id'])
            type_ref = volume_types.get_volume_type(self.ctxt, type_ref['id'])
            qos = common._get_qos_by_volume_type(type_ref)
            self.assertEqual({'maxIOPS': '1000', 'maxBWS': '50',
                              'minIOPS': '100', 'minBWS': '25',
                              'latency': '25', 'priority': 'low'}, qos)

    def test_get_by_qos_by_type_only(self):
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            type_ref = volume_types.create(self.ctxt,
                                           "type1", {"qos:maxIOPS": "100",
                                                     "qos:maxBWS": "50",
                                                     "qos:minIOPS": "10",
                                                     "qos:minBWS": "20",
                                                     "qos:latency": "5",
                                                     "qos:priority": "high"})
            type_ref = volume_types.get_volume_type(self.ctxt, type_ref['id'])
            qos = common._get_qos_by_volume_type(type_ref)
            self.assertEqual({'maxIOPS': '100', 'maxBWS': '50',
                              'minIOPS': '10', 'minBWS': '20',
                              'latency': '5', 'priority': 'high'}, qos)

    def test_create_vlun(self):
        host = 'fake-host'
        lun_id = 11
        nsp = '1:2:3'
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            location = ("%(name)s,%(lunid)s,%(host)s,%(nsp)s" %
                        {'name': self.VOLUME_NAME,
                         'lunid': lun_id,
                         'host': host,
                         'nsp': nsp})
            mock_client.createVLUN.return_value = location

            expected_info = {'volume_name': self.VOLUME_NAME,
                             'lun_id': lun_id,
                             'host_name': host,
                             'nsp': nsp}
            common = self.driver._login()
            vlun_info = common._create_3par_vlun(
                self.VOLUME_NAME,
                host,
                nsp)
            self.assertEqual(expected_info, vlun_info)

            location = ("%(name)s,%(lunid)s,%(host)s" %
                        {'name': self.VOLUME_NAME,
                         'lunid': lun_id,
                         'host': host})
            mock_client.createVLUN.return_value = location
            expected_info = {'volume_name': self.VOLUME_NAME,
                             'lun_id': lun_id,
                             'host_name': host}
            vlun_info = common._create_3par_vlun(
                self.VOLUME_NAME,
                host,
                None)
            self.assertEqual(expected_info, vlun_info)

    def test__get_existing_volume_ref_name(self):
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            unm_matcher = common._get_3par_unm_name(self.volume['id'])

            existing_ref = {'source-name': unm_matcher}
            result = common._get_existing_volume_ref_name(existing_ref)
            self.assertEqual(unm_matcher, result)

            existing_ref = {'source-id': self.volume['id']}
            result = common._get_existing_volume_ref_name(existing_ref)
            self.assertEqual(unm_matcher, result)

            existing_ref = {'bad-key': 'foo'}
            self.assertRaises(
                exception.ManageExistingInvalidReference,
                common._get_existing_volume_ref_name,
                existing_ref)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_manage_existing(self, _mock_volume_types):
        _mock_volume_types.return_value = self.volume_type
        mock_client = self.setup_driver()

        new_comment = {"display_name": "Foo Volume",
                       "name": "volume-007dbfce-7579-40bc-8f90-a20b3902283e",
                       "volume_id": "007dbfce-7579-40bc-8f90-a20b3902283e",
                       "type": "OpenStack"}

        volume = {'display_name': None,
                  'host': self.FAKE_CINDER_HOST,
                  'volume_type': 'gold',
                  'volume_type_id': 'acfa9fa4-54a0-4340-a3d8-bfcf19aea65e',
                  'id': '007dbfce-7579-40bc-8f90-a20b3902283e'}

        mock_client.getVolume.return_value = self.MANAGE_VOLUME_INFO
        mock_client.modifyVolume.return_value = ("anyResponse", {'taskid': 1})
        mock_client.getTask.return_value = self.STATUS_DONE

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            osv_matcher = common._get_3par_vol_name(volume['id'])
            vvs_matcher = common._get_3par_vvs_name(volume['id'])
            existing_ref = {'source-name': unm_matcher}

            expected_obj = {'display_name': 'Foo Volume'}

            obj = self.driver.manage_existing(volume, existing_ref)

            expected_manage = [
                mock.call.getVolume(existing_ref['source-name']),
                mock.call.modifyVolume(existing_ref['source-name'],
                                       {'newName': osv_matcher,
                                        'comment': self.CommentMatcher(
                                            self.assertEqual, new_comment)}),
            ]

            retype_comment_qos = {
                "display_name": "Foo Volume",
                "volume_type_name": self.volume_type['name'],
                "volume_type_id": self.volume_type['id'],
                "qos": {
                    'maxIOPS': '1000',
                    'maxBWS': '50',
                    'minIOPS': '100',
                    'minBWS': '25',
                    'latency': '25',
                    'priority': 'low'
                }
            }

            expected_snap_cpg = HP3PAR_CPG_SNAP
            expected_retype_modify = [
                mock.call.modifyVolume(osv_matcher,
                                       {'comment': self.CommentMatcher(
                                           self.assertEqual,
                                           retype_comment_qos),
                                        'snapCPG': expected_snap_cpg}),
                mock.call.deleteVolumeSet(vvs_matcher),
            ]

            expected_retype_specs = [
                mock.call.createVolumeSet(vvs_matcher, None),
                mock.call.createQoSRules(
                    vvs_matcher,
                    {'ioMinGoal': 100, 'ioMaxLimit': 1000,
                     'bwMinGoalKB': 25600, 'priority': 1, 'latencyGoal': 25,
                     'bwMaxLimitKB': 51200}),
                mock.call.addVolumeToVolumeSet(vvs_matcher, osv_matcher),
                mock.call.modifyVolume(
                    osv_matcher,
                    {'action': 6,
                     'userCPG': HP3PAR_CPG,
                     'conversionOperation': 1, 'tuneOperation': 1}),
                mock.call.getTask(1)
            ]

            mock_client.assert_has_calls(self.standard_login + expected_manage)
            mock_client.assert_has_calls(expected_retype_modify)
            mock_client.assert_has_calls(
                expected_retype_specs +
                self.standard_logout)
            self.assertEqual(expected_obj, obj)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_manage_existing_with_no_snap_cpg(self, _mock_volume_types):
        _mock_volume_types.return_value = self.volume_type
        mock_client = self.setup_driver()

        new_comment = {"display_name": "Foo Volume",
                       "name": "volume-007dbfce-7579-40bc-8f90-a20b3902283e",
                       "volume_id": "007dbfce-7579-40bc-8f90-a20b3902283e",
                       "type": "OpenStack"}

        volume = {'display_name': None,
                  'host': 'my-stack1@3parxxx#CPGNOTUSED',
                  'volume_type': 'gold',
                  'volume_type_id': 'acfa9fa4-54a0-4340-a3d8-bfcf19aea65e',
                  'id': '007dbfce-7579-40bc-8f90-a20b3902283e'}

        mock_client.getVolume.return_value = self.MV_INFO_WITH_NO_SNAPCPG
        mock_client.modifyVolume.return_value = ("anyResponse", {'taskid': 1})
        mock_client.getTask.return_value = self.STATUS_DONE

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            osv_matcher = common._get_3par_vol_name(volume['id'])
            existing_ref = {'source-name': unm_matcher}

            expected_obj = {'display_name': 'Foo Volume'}

            obj = self.driver.manage_existing(volume, existing_ref)

            expected_manage = [
                mock.call.getVolume(existing_ref['source-name']),
                mock.call.modifyVolume(
                    existing_ref['source-name'],
                    {'newName': osv_matcher,
                     'comment': self.CommentMatcher(self.assertEqual,
                                                    new_comment),
                     # manage_existing() should be setting
                     # blank snapCPG to the userCPG
                     'snapCPG': 'testUserCpg0'})
            ]

            mock_client.assert_has_calls(self.standard_login + expected_manage)
            self.assertEqual(expected_obj, obj)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_manage_existing_vvs(self, _mock_volume_types):
        test_volume_type = self.RETYPE_VOLUME_TYPE_2
        vvs = test_volume_type['extra_specs']['vvs']
        _mock_volume_types.return_value = test_volume_type
        mock_client = self.setup_driver()

        mock_client.getVolume.return_value = self.MANAGE_VOLUME_INFO
        mock_client.modifyVolume.return_value = ("anyResponse", {'taskid': 1})
        mock_client.getTask.return_value = self.STATUS_DONE

        id = '007abcde-7579-40bc-8f90-a20b3902283e'
        new_comment = {"display_name": "Test Volume",
                       "name": ("volume-%s" % id),
                       "volume_id": id,
                       "type": "OpenStack"}

        volume = {'display_name': 'Test Volume',
                  'host': 'my-stack1@3parxxx#CPGNOTUSED',
                  'volume_type': 'gold',
                  'volume_type_id': 'acfa9fa4-54a0-4340-a3d8-bfcf19aea65e',
                  'id': id}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            osv_matcher = common._get_3par_vol_name(volume['id'])
            vvs_matcher = common._get_3par_vvs_name(volume['id'])

            existing_ref = {'source-name': unm_matcher}

            obj = self.driver.manage_existing(volume, existing_ref)

            expected_obj = {'display_name': 'Test Volume'}
            expected_manage = [
                mock.call.getVolume(existing_ref['source-name']),
                mock.call.modifyVolume(existing_ref['source-name'],
                                       {'newName': osv_matcher,
                                        'comment': self.CommentMatcher(
                                            self.assertEqual, new_comment)})
            ]

            retype_comment_vvs = {
                "display_name": "Foo Volume",
                "volume_type_name": test_volume_type['name'],
                "volume_type_id": test_volume_type['id'],
                "vvs": vvs
            }

            expected_retype = [
                mock.call.modifyVolume(osv_matcher,
                                       {'comment': self.CommentMatcher(
                                           self.assertEqual,
                                           retype_comment_vvs),
                                        'snapCPG': 'OpenStackCPGSnap'}),
                mock.call.deleteVolumeSet(vvs_matcher),
                mock.call.addVolumeToVolumeSet(vvs, osv_matcher),
                mock.call.modifyVolume(osv_matcher,
                                       {'action': 6,
                                        'userCPG': 'CPGNOTUSED',
                                        'conversionOperation': 1,
                                        'tuneOperation': 1}),
                mock.call.getTask(1)
            ]

            mock_client.assert_has_calls(self.standard_login + expected_manage)
            mock_client.assert_has_calls(
                expected_retype +
                self.standard_logout)
            self.assertEqual(expected_obj, obj)

    def test_manage_existing_no_volume_type(self):
        mock_client = self.setup_driver()

        comment = (
            '{"display_name": "Foo Volume"}')
        new_comment = (
            '{"type": "OpenStack",'
            ' "display_name": "Foo Volume",'
            ' "name": "volume-007dbfce-7579-40bc-8f90-a20b3902283e",'
            ' "volume_id": "007dbfce-7579-40bc-8f90-a20b3902283e"}')
        volume = {'display_name': None,
                  'volume_type': None,
                  'volume_type_id': None,
                  'id': '007dbfce-7579-40bc-8f90-a20b3902283e'}

        mock_client.getVolume.return_value = {'comment': comment,
                                              'userCPG': 'testUserCpg0'}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            osv_matcher = common._get_3par_vol_name(volume['id'])
            existing_ref = {'source-name': unm_matcher}

            obj = self.driver.manage_existing(volume, existing_ref)

            expected_obj = {'display_name': 'Foo Volume'}
            expected = [
                mock.call.getVolume(existing_ref['source-name']),
                mock.call.modifyVolume(existing_ref['source-name'],
                                       {'newName': osv_matcher,
                                        'comment': new_comment,
                                        # manage_existing() should be setting
                                        # blank snapCPG to the userCPG
                                        'snapCPG': 'testUserCpg0'})
            ]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(expected_obj, obj)

            volume['display_name'] = 'Test Volume'

            obj = self.driver.manage_existing(volume, existing_ref)

            expected_obj = {'display_name': 'Test Volume'}
            expected = [
                mock.call.getVolume(existing_ref['source-name']),
                mock.call.modifyVolume(existing_ref['source-name'],
                                       {'newName': osv_matcher,
                                        'comment': new_comment,
                                        # manage_existing() should be setting
                                        # blank snapCPG to the userCPG
                                        'snapCPG': 'testUserCpg0'})
            ]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(expected_obj, obj)

            mock_client.getVolume.return_value = {'userCPG': 'testUserCpg0'}
            volume['display_name'] = None
            common = self.driver._login()

            obj = self.driver.manage_existing(volume, existing_ref)

            expected_obj = {'display_name': None}
            expected = [
                mock.call.getVolume(existing_ref['source-name']),
                mock.call.modifyVolume(existing_ref['source-name'],
                                       {'newName': osv_matcher,
                                        'comment': new_comment,
                                        # manage_existing() should be setting
                                        # blank snapCPG to the userCPG
                                        'snapCPG': 'testUserCpg0'})
            ]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(expected_obj, obj)

    def test_manage_existing_invalid_input(self):
        mock_client = self.setup_driver()

        volume = {'display_name': None,
                  'volume_type': None,
                  'id': '007dbfce-7579-40bc-8f90-a20b3902283e'}

        mock_client.getVolume.side_effect = hpexceptions.HTTPNotFound('fake')

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            existing_ref = {'source-name': unm_matcher}

            self.assertRaises(exception.InvalidInput,
                              self.driver.manage_existing,
                              volume=volume,
                              existing_ref=existing_ref)

            expected = [mock.call.getVolume(existing_ref['source-name'])]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_manage_existing_volume_type_exception(self):
        mock_client = self.setup_driver()

        comment = (
            '{"display_name": "Foo Volume"}')
        volume = {'display_name': None,
                  'volume_type': 'gold',
                  'volume_type_id': 'bcfa9fa4-54a0-4340-a3d8-bfcf19aea65e',
                  'id': '007dbfce-7579-40bc-8f90-a20b3902283e'}

        mock_client.getVolume.return_value = {'comment': comment}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            existing_ref = {'source-name': unm_matcher}

            self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                              self.driver.manage_existing,
                              volume=volume,
                              existing_ref=existing_ref)

            expected = [mock.call.getVolume(existing_ref['source-name'])]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_manage_existing_retype_exception(self, _mock_volume_types):
        mock_client = self.setup_driver()
        _mock_volume_types.return_value = {
            'name': 'gold',
            'id': 'gold-id',
            'extra_specs': {
                'cpg': HP3PAR_CPG,
                'snap_cpg': HP3PAR_CPG_SNAP,
                'vvs_name': self.VVS_NAME,
                'qos': self.QOS,
                'tpvv': True,
                'tdvv': False,
                'volume_type': self.volume_type}}

        volume = {'display_name': None,
                  'host': 'stack1@3pariscsi#POOL1',
                  'volume_type': 'gold',
                  'volume_type_id': 'bcfa9fa4-54a0-4340-a3d8-bfcf19aea65e',
                  'id': '007dbfce-7579-40bc-8f90-a20b3902283e'}

        mock_client.getVolume.return_value = self.MANAGE_VOLUME_INFO
        mock_client.modifyVolume.return_value = ("anyResponse", {'taskid': 1})
        mock_client.getTask.return_value = self.STATUS_DONE
        mock_client.getCPG.side_effect = [
            {'domain': 'domain1'},
            {'domain': 'domain2'},
            {'domain': 'domain3'},
        ]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            osv_matcher = common._get_3par_vol_name(volume['id'])

            existing_ref = {'source-name': unm_matcher}

            self.assertRaises(exception.Invalid3PARDomain,
                              self.driver.manage_existing,
                              volume=volume,
                              existing_ref=existing_ref)

            expected = [

                mock.call.getVolume(unm_matcher),
                mock.call.modifyVolume(
                    unm_matcher, {
                        'newName': osv_matcher,
                        'comment': mock.ANY}),
                mock.call.getCPG('POOL1'),
                mock.call.getVolume(osv_matcher),
                mock.call.getCPG('testUserCpg0'),
                mock.call.getCPG('POOL1'),
                mock.call.modifyVolume(
                    osv_matcher, {'newName': unm_matcher,
                                  'comment': self.MANAGE_VOLUME_INFO
                                  ['comment']})
            ]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_manage_existing_get_size(self):
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'sizeMiB': 2048}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            volume = {}
            existing_ref = {'source-name': unm_matcher}

            size = self.driver.manage_existing_get_size(volume, existing_ref)

            expected_size = 2
            expected = [mock.call.getVolume(existing_ref['source-name'])]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(expected_size, size)

    def test_manage_existing_get_size_invalid_reference(self):
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            volume = {}
            existing_ref = {'source-name': self.VOLUME_3PAR_NAME}

            self.assertRaises(exception.ManageExistingInvalidReference,
                              self.driver.manage_existing_get_size,
                              volume=volume,
                              existing_ref=existing_ref)

            mock_client.assert_has_calls(
                self.standard_login +
                self.standard_logout)

            existing_ref = {}

            self.assertRaises(exception.ManageExistingInvalidReference,
                              self.driver.manage_existing_get_size,
                              volume=volume,
                              existing_ref=existing_ref)

            mock_client.assert_has_calls(
                self.standard_login +
                self.standard_logout)

    def test_manage_existing_get_size_invalid_input(self):
        mock_client = self.setup_driver()
        mock_client.getVolume.side_effect = hpexceptions.HTTPNotFound('fake')

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            unm_matcher = common._get_3par_unm_name(self.volume['id'])
            volume = {}
            existing_ref = {'source-name': unm_matcher}

            self.assertRaises(exception.InvalidInput,
                              self.driver.manage_existing_get_size,
                              volume=volume,
                              existing_ref=existing_ref)

            expected = [mock.call.getVolume(existing_ref['source-name'])]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_unmanage(self):
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            self.driver.unmanage(self.volume)

            osv_matcher = common._get_3par_vol_name(self.volume['id'])
            unm_matcher = common._get_3par_unm_name(self.volume['id'])

            expected = [
                mock.call.modifyVolume(osv_matcher, {'newName': unm_matcher})
            ]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test__safe_hostname(self):
        long_hostname = "abc123abc123abc123abc123abc123abc123"
        fixed_hostname = "abc123abc123abc123abc123abc123a"
        common = hpcommon.HP3PARCommon(None)
        safe_host = common._safe_hostname(long_hostname)
        self.assertEqual(fixed_hostname, safe_host)

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_create_consistency_group(self):
        class fake_consitencygroup_object(object):
            volume_type_id = '49fa96b5-828e-4653-b622-873a1b7e6f1c'
            name = 'cg_name'
            cgsnapshot_id = None
            host = self.FAKE_CINDER_HOST
            id = self.CONSIS_GROUP_ID
            description = 'consistency group'

        mock_client = self.setup_driver()

        comment = (
            "{'display_name': 'cg_name',"
            " 'consistency_group_id':"
            " '" + self.CONSIS_GROUP_ID + "',"
            " 'description': 'consistency group'}")

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            mock_client.getCPG.return_value = {'domain': None}
            # create a consistency group
            group = fake_consitencygroup_object()
            self.driver.create_consistencygroup(context.get_admin_context(),
                                                group)

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    domain=None,
                    comment=comment)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_create_consistency_group_from_src(self):
        class fake_consitencygroup_object(object):
            volume_type_id = '49fa96b5-828e-4653-b622-873a1b7e6f1c'
            name = 'cg_name'
            cgsnapshot_id = None
            host = self.FAKE_CINDER_HOST
            id = self.CONSIS_GROUP_ID
            description = 'consistency group'

        mock_client = self.setup_driver()
        volume = self.volume

        cgsnap_optional = (
            {'comment': '{"consistency_group_id":'
             ' "6044fedf-c889-4752-900f-2039d247a5df",'
             ' "description": "cgsnapshot",'
             ' "cgsnapshot_id": "e91c5ed5-daee-4e84-8724-1c9e31e7a1f2"}',
             'readOnly': False})

        cg_comment = (
            "{'display_name': 'cg_name',"
            " 'consistency_group_id':"
            " '" + self.CONSIS_GROUP_ID + "',"
            " 'description': 'consistency group'}")

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            mock_client.getCPG.return_value = {'domain': None}

            # create a consistency group
            group = fake_consitencygroup_object()
            self.driver.create_consistencygroup(context.get_admin_context(),
                                                group)

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    domain=None,
                    comment=cg_comment)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # add a volume to the consistency group
            self.driver.update_consistencygroup(context.get_admin_context(),
                                                group,
                                                add_volumes=[volume],
                                                remove_volumes=[])

            expected = [
                mock.call.addVolumeToVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    self.VOLUME_NAME_3PAR)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # create a snapshot of the consistency group
            self.driver.create_cgsnapshot(context.get_admin_context(),
                                          self.cgsnapshot)

            expected = [
                mock.call.createSnapshotOfVolumeSet(
                    self.CGSNAPSHOT_BASE_NAME + "-@count@",
                    self.CONSIS_GROUP_NAME,
                    optional=cgsnap_optional)]

            # create a consistency group from the cgsnapshot
            self.driver.create_consistencygroup_from_src(
                context.get_admin_context(), group,
                [volume], cgsnapshot=self.cgsnapshot,
                snapshots=[self.snapshot])

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_delete_consistency_group(self):
        class fake_consitencygroup_object(object):
            volume_type_id = '49fa96b5-828e-4653-b622-873a1b7e6f1c'
            name = 'cg_name'
            cgsnapshot_id = None
            host = self.FAKE_CINDER_HOST
            id = self.CONSIS_GROUP_ID
            description = 'consistency group'

        mock_client = self.setup_driver()

        comment = (
            "{'display_name': 'cg_name',"
            " 'consistency_group_id':"
            " '" + self.CONSIS_GROUP_ID + "',"
            " 'description': 'consistency group'}")

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            mock_client.getCPG.return_value = {'domain': None}

            # create a consistency group
            group = fake_consitencygroup_object()
            self.driver.create_consistencygroup(context.get_admin_context(),
                                                group)

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    domain=None,
                    comment=comment)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # remove the consistency group
            group.status = 'deleting'
            self.driver.delete_consistencygroup(context.get_admin_context(),
                                                group)

            expected = [
                mock.call.deleteVolumeSet(
                    self.CONSIS_GROUP_NAME)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_update_consistency_group_add_vol(self):
        class fake_consitencygroup_object(object):
            volume_type_id = '49fa96b5-828e-4653-b622-873a1b7e6f1c'
            name = 'cg_name'
            cgsnapshot_id = None
            host = self.FAKE_CINDER_HOST
            id = self.CONSIS_GROUP_ID
            description = 'consistency group'

        mock_client = self.setup_driver()
        volume = self.volume

        comment = (
            "{'display_name': 'cg_name',"
            " 'consistency_group_id':"
            " '" + self.CONSIS_GROUP_ID + "',"
            " 'description': 'consistency group'}")

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            mock_client.getCPG.return_value = {'domain': None}

            # create a consistency group
            group = fake_consitencygroup_object()
            self.driver.create_consistencygroup(context.get_admin_context(),
                                                group)

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    domain=None,
                    comment=comment)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # add a volume to the consistency group
            self.driver.update_consistencygroup(context.get_admin_context(),
                                                group,
                                                add_volumes=[volume],
                                                remove_volumes=[])

            expected = [
                mock.call.addVolumeToVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    self.VOLUME_NAME_3PAR)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_update_consistency_group_remove_vol(self):
        class fake_consitencygroup_object(object):
            volume_type_id = '49fa96b5-828e-4653-b622-873a1b7e6f1c'
            name = 'cg_name'
            cgsnapshot_id = None
            host = self.FAKE_CINDER_HOST
            id = self.CONSIS_GROUP_ID
            description = 'consistency group'

        mock_client = self.setup_driver()
        volume = self.volume

        comment = (
            "{'display_name': 'cg_name',"
            " 'consistency_group_id':"
            " '" + self.CONSIS_GROUP_ID + "',"
            " 'description': 'consistency group'}")

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            mock_client.getCPG.return_value = {'domain': None}

            # create a consistency group
            group = fake_consitencygroup_object()
            self.driver.create_consistencygroup(context.get_admin_context(),
                                                group)

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    domain=None,
                    comment=comment)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # add a volume to the consistency group
            self.driver.update_consistencygroup(context.get_admin_context(),
                                                group,
                                                add_volumes=[volume],
                                                remove_volumes=[])

            expected = [
                mock.call.addVolumeToVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    self.VOLUME_NAME_3PAR)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # remove the volume from the consistency group
            self.driver.update_consistencygroup(context.get_admin_context(),
                                                group,
                                                add_volumes=[],
                                                remove_volumes=[volume])

            expected = [
                mock.call.removeVolumeFromVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    self.VOLUME_NAME_3PAR)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_create_cgsnapshot(self):
        class fake_consitencygroup_object(object):
            volume_type_id = '49fa96b5-828e-4653-b622-873a1b7e6f1c'
            name = 'cg_name'
            cgsnapshot_id = None
            host = self.FAKE_CINDER_HOST
            id = self.CONSIS_GROUP_ID
            description = 'consistency group'

        mock_client = self.setup_driver()
        volume = self.volume

        cg_comment = (
            "{'display_name': 'cg_name',"
            " 'consistency_group_id':"
            " '" + self.CONSIS_GROUP_ID + "',"
            " 'description': 'consistency group'}")

        cgsnap_optional = (
            {'comment': '{"consistency_group_id":'
             ' "6044fedf-c889-4752-900f-2039d247a5df",'
             ' "description": "cgsnapshot",'
             ' "cgsnapshot_id": "e91c5ed5-daee-4e84-8724-1c9e31e7a1f2"}',
             'readOnly': False})

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            mock_client.getCPG.return_value = {'domain': None}

            # create a consistency group
            group = fake_consitencygroup_object()
            self.driver.create_consistencygroup(context.get_admin_context(),
                                                group)

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    domain=None,
                    comment=cg_comment)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # add a volume to the consistency group
            self.driver.update_consistencygroup(context.get_admin_context(),
                                                group,
                                                add_volumes=[volume],
                                                remove_volumes=[])

            expected = [
                mock.call.addVolumeToVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    self.VOLUME_NAME_3PAR)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # create a snapshot of the consistency group
            self.driver.create_cgsnapshot(context.get_admin_context(),
                                          self.cgsnapshot)

            expected = [
                mock.call.createSnapshotOfVolumeSet(
                    self.CGSNAPSHOT_BASE_NAME + "-@count@",
                    self.CONSIS_GROUP_NAME,
                    optional=cgsnap_optional)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_delete_cgsnapshot(self):
        class fake_consitencygroup_object(object):
            volume_type_id = '49fa96b5-828e-4653-b622-873a1b7e6f1c'
            name = 'cg_name'
            cgsnapshot_id = None
            host = self.FAKE_CINDER_HOST
            id = self.CONSIS_GROUP_ID
            description = 'consistency group'

        mock_client = self.setup_driver()
        volume = self.volume
        cgsnapshot = self.cgsnapshot

        cg_comment = (
            "{'display_name': 'cg_name',"
            " 'consistency_group_id':"
            " '" + self.CONSIS_GROUP_ID + "',"
            " 'description': 'consistency group'}")

        cgsnap_optional = (
            {'comment': '{"consistency_group_id":'
             ' "6044fedf-c889-4752-900f-2039d247a5df",'
             ' "description": "cgsnapshot",'
             ' "cgsnapshot_id": "e91c5ed5-daee-4e84-8724-1c9e31e7a1f2"}',
             'readOnly': False})

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            mock_client.getCPG.return_value = {'domain': None}

            # create a consistency group
            group = fake_consitencygroup_object()
            self.driver.create_consistencygroup(context.get_admin_context(),
                                                group)

            expected = [
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.createVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    domain=None,
                    comment=cg_comment)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # add a volume to the consistency group
            self.driver.update_consistencygroup(context.get_admin_context(),
                                                group,
                                                add_volumes=[volume],
                                                remove_volumes=[])

            expected = [
                mock.call.addVolumeToVolumeSet(
                    self.CONSIS_GROUP_NAME,
                    self.VOLUME_NAME_3PAR)]

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()

            # create a snapshot of the consistency group
            self.driver.create_cgsnapshot(context.get_admin_context(),
                                          cgsnapshot)

            expected = [
                mock.call.createSnapshotOfVolumeSet(
                    self.CGSNAPSHOT_BASE_NAME + "-@count@",
                    self.CONSIS_GROUP_NAME,
                    optional=cgsnap_optional)]

            # delete the snapshot of the consistency group
            cgsnapshot['status'] = 'deleting'
            self.driver.delete_cgsnapshot(context.get_admin_context(),
                                          cgsnapshot)

            mock_client.assert_has_calls(
                [mock.call.getWsApiVersion()] +
                self.standard_login +
                expected +
                self.standard_logout)


class TestHP3PARFCDriver(HP3PARBaseDriver, test.TestCase):

    properties = {
        'driver_volume_type': 'fibre_channel',
        'data': {
            'encrypted': False,
            'target_lun': 90,
            'target_wwn': ['0987654321234', '123456789000987'],
            'target_discovered': True,
            'initiator_target_map': {'123456789012345':
                                     ['0987654321234', '123456789000987'],
                                     '123456789054321':
                                     ['0987654321234', '123456789000987'],
                                     }}}

    def setup_driver(self, config=None, mock_conf=None, wsapi_version=None):

        self.ctxt = context.get_admin_context()
        mock_client = self.setup_mock_client(
            conf=config,
            m_conf=mock_conf,
            driver=hpfcdriver.HP3PARFCDriver)

        if wsapi_version:
            mock_client.getWsApiVersion.return_value = (
                wsapi_version)
        else:
            mock_client.getWsApiVersion.return_value = (
                self.wsapi_version_latest)

        expected = [
            mock.call.getCPG(HP3PAR_CPG),
            mock.call.getCPG(HP3PAR_CPG2)]
        mock_client.assert_has_calls(
            self.standard_login +
            expected +
            self.standard_logout)
        mock_client.reset_mock()
        return mock_client

    def test_initialize_connection(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST,
                'FCPaths': [{'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 1,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': self.wwn[0]},
                            {'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 0,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': self.wwn[1]}]}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        mock_client.getHostVLUNs.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            [{'active': True,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': 90, 'type': 0}]]

        location = ("%(volume_name)s,%(lun_id)s,%(host)s,%(nsp)s" %
                    {'volume_name': self.VOLUME_3PAR_NAME,
                     'lun_id': 90,
                     'host': self.FAKE_HOST,
                     'nsp': 'something'})
        mock_client.createVLUN.return_value = location

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            result = self.driver.initialize_connection(
                self.volume,
                self.connector)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(wwns=['123456789012345',
                                          '123456789054321']),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.getPorts(),
                mock.call.getHostVLUNs(self.FAKE_HOST),
                mock.call.createVLUN(
                    self.VOLUME_3PAR_NAME,
                    auto=True,
                    hostname=self.FAKE_HOST),
                mock.call.getHostVLUNs(self.FAKE_HOST)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            self.assertDictMatch(result, self.properties)

    @mock.patch('cinder.zonemanager.utils.create_lookup_service')
    def test_initialize_connection_with_lookup_single_nsp(self, mock_lookup):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        class fake_lookup_object(object):
            def get_device_mapping_from_network(self, connector, target_wwns):
                fake_map = {
                    'FAB_1': {
                        'target_port_wwn_list': ['0987654321234'],
                        'initiator_port_wwn_list': ['123456789012345']
                    }
                }
                return fake_map
        mock_lookup.return_value = fake_lookup_object()
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST,
                'FCPaths': [{'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 1,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': self.wwn[0]}]}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        mock_client.getHostVLUNs.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            [{'active': True,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': 90, 'type': 0,
              'portPos': {'cardPort': 1, 'node': 7, 'slot': 1}, }]]

        location = ("%(volume_name)s,%(lun_id)s,%(host)s,%(nsp)s" %
                    {'volume_name': self.VOLUME_3PAR_NAME,
                     'lun_id': 90,
                     'host': self.FAKE_HOST,
                     'nsp': 'something'})
        mock_client.createVLUN.return_value = location

        connector = {'ip': '10.0.0.2',
                     'initiator': 'iqn.1993-08.org.debian:01:222',
                     'wwpns': [self.wwn[0]],
                     'wwnns': ["223456789012345"],
                     'host': self.FAKE_HOST}

        expected_properties = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'encrypted': False,
                'target_lun': 90,
                'target_wwn': ['0987654321234'],
                'target_discovered': True,
                'initiator_target_map': {'123456789012345':
                                         ['0987654321234']
                                         }}}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            result = self.driver.initialize_connection(self.volume, connector)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.ANY,
                mock.call.getHost(self.FAKE_HOST),
                mock.call.getPorts(),
                mock.call.getHostVLUNs(self.FAKE_HOST),
                mock.call.getPorts(),
                mock.call.createVLUN(
                    self.VOLUME_3PAR_NAME,
                    auto=True,
                    hostname=self.FAKE_HOST,
                    portPos={'node': 7, 'slot': 1, 'cardPort': 1}),
                mock.call.getHostVLUNs(self.FAKE_HOST)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            self.assertDictMatch(result, expected_properties)

    def test_initialize_connection_encrypted(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST,
                'FCPaths': [{'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 1,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': self.wwn[0]},
                            {'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 0,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': self.wwn[1]}]}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        mock_client.getHostVLUNs.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            [{'active': True,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': 90, 'type': 0}]]

        location = ("%(volume_name)s,%(lun_id)s,%(host)s,%(nsp)s" %
                    {'volume_name': self.VOLUME_3PAR_NAME,
                     'lun_id': 90,
                     'host': self.FAKE_HOST,
                     'nsp': 'something'})
        mock_client.createVLUN.return_value = location

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            result = self.driver.initialize_connection(
                self.volume_encrypted,
                self.connector)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(wwns=['123456789012345',
                                          '123456789054321']),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.getPorts(),
                mock.call.getHostVLUNs(self.FAKE_HOST),
                mock.call.createVLUN(
                    self.VOLUME_3PAR_NAME,
                    auto=True,
                    hostname=self.FAKE_HOST),
                mock.call.getHostVLUNs(self.FAKE_HOST)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            expected_properties = self.properties
            expected_properties['data']['encrypted'] = True
            self.assertDictMatch(result, expected_properties)

    def test_terminate_connection(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        effects = [
            [{'active': True, 'volumeName': self.VOLUME_3PAR_NAME,
              'lun': None, 'type': 0}],
            hpexceptions.HTTPNotFound,
            hpexceptions.HTTPNotFound]

        mock_client.getHostVLUNs.side_effect = effects

        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        expected = [
            mock.call.queryHost(wwns=['123456789012345', '123456789054321']),
            mock.call.getHostVLUNs(self.FAKE_HOST),
            mock.call.deleteVLUN(
                self.VOLUME_3PAR_NAME,
                None,
                self.FAKE_HOST),
            mock.call.getHostVLUNs(self.FAKE_HOST),
            mock.call.deleteHost(self.FAKE_HOST),
            mock.call.getHostVLUNs(self.FAKE_HOST),
            mock.call.getPorts()]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            conn_info = self.driver.terminate_connection(self.volume,
                                                         self.connector)
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertIn('data', conn_info)
            self.assertIn('initiator_target_map', conn_info['data'])
            mock_client.reset_mock()

            mock_client.getHostVLUNs.side_effect = effects

            # mock some deleteHost exceptions that are handled
            delete_with_vlun = hpexceptions.HTTPConflict(
                error={'message': "has exported VLUN"})
            delete_with_hostset = hpexceptions.HTTPConflict(
                error={'message': "host is a member of a set"})
            mock_client.deleteHost = mock.Mock(
                side_effect=[delete_with_vlun, delete_with_hostset])

            conn_info = self.driver.terminate_connection(self.volume,
                                                         self.connector)
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()
            mock_client.getHostVLUNs.side_effect = effects

            conn_info = self.driver.terminate_connection(self.volume,
                                                         self.connector)
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('cinder.zonemanager.utils.create_lookup_service')
    def test_terminate_connection_with_lookup(self, mock_lookup):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        class fake_lookup_object(object):
            def get_device_mapping_from_network(self, connector, target_wwns):
                fake_map = {
                    'FAB_1': {
                        'target_port_wwn_list': ['0987654321234'],
                        'initiator_port_wwn_list': ['123456789012345']
                    }
                }
                return fake_map
        mock_lookup.return_value = fake_lookup_object()
        mock_client = self.setup_driver()

        effects = [
            [{'active': True, 'volumeName': self.VOLUME_3PAR_NAME,
              'lun': None, 'type': 0}],
            hpexceptions.HTTPNotFound,
            hpexceptions.HTTPNotFound]

        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        mock_client.getHostVLUNs.side_effect = effects

        expected = [
            mock.call.queryHost(wwns=['123456789012345', '123456789054321']),
            mock.call.getHostVLUNs(self.FAKE_HOST),
            mock.call.deleteVLUN(
                self.VOLUME_3PAR_NAME,
                None,
                self.FAKE_HOST),
            mock.call.getHostVLUNs(self.FAKE_HOST),
            mock.call.deleteHost(self.FAKE_HOST),
            mock.call.getHostVLUNs(self.FAKE_HOST),
            mock.call.getPorts()]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            conn_info = self.driver.terminate_connection(self.volume,
                                                         self.connector)
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertIn('data', conn_info)
            self.assertIn('initiator_target_map', conn_info['data'])
            mock_client.reset_mock()

            mock_client.getHostVLUNs.side_effect = effects

            # mock some deleteHost exceptions that are handled
            delete_with_vlun = hpexceptions.HTTPConflict(
                error={'message': "has exported VLUN"})
            delete_with_hostset = hpexceptions.HTTPConflict(
                error={'message': "host is a member of a set"})
            mock_client.deleteHost = mock.Mock(
                side_effect=[delete_with_vlun, delete_with_hostset])

            conn_info = self.driver.terminate_connection(self.volume,
                                                         self.connector)
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            mock_client.reset_mock()
            mock_client.getHostVLUNs.side_effect = effects

            conn_info = self.driver.terminate_connection(self.volume,
                                                         self.connector)
            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_terminate_connection_more_vols(self):
        mock_client = self.setup_driver()
        # mock more than one vlun on the host (don't even try to remove host)
        mock_client.getHostVLUNs.return_value = \
            [
                {'active': True,
                 'volumeName': self.VOLUME_3PAR_NAME,
                 'lun': None, 'type': 0},
                {'active': True,
                 'volumeName': 'there-is-another-volume',
                 'lun': None, 'type': 0},
            ]

        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        expect_less = [
            mock.call.queryHost(wwns=['123456789012345', '123456789054321']),
            mock.call.getHostVLUNs(self.FAKE_HOST),
            mock.call.deleteVLUN(
                self.VOLUME_3PAR_NAME,
                None,
                self.FAKE_HOST),
            mock.call.getHostVLUNs(self.FAKE_HOST),
            mock.call.getHostVLUNs(self.FAKE_HOST)]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            conn_info = self.driver.terminate_connection(self.volume,
                                                         self.connector)
            mock_client.assert_has_calls(
                self.standard_login +
                expect_less +
                self.standard_logout)
            self.assertNotIn('initiator_target_map', conn_info['data'])

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_get_volume_stats1(self):
        # setup_mock_client drive with the configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.filter_function = FILTER_FUNCTION
        config.goodness_function = GOODNESS_FUNCTION
        mock_client = self.setup_driver(config=config)
        mock_client.getCPG.return_value = self.cpgs[0]
        mock_client.getStorageSystemInfo.return_value = {
            'serialNumber': '1234'
        }

        # cpg has no limit
        mock_client.getCPGAvailableSpace.return_value = {
            "capacityEfficiency": {u'compaction': 594.4},
            "rawFreeMiB": 1024.0 * 6,
            "usableFreeMiB": 1024.0 * 3
        }
        stat_capabilities = {
            THROUGHPUT: 0,
            BANDWIDTH: 0,
            LATENCY: 0,
            IO_SIZE: 0,
            QUEUE_LENGTH: 0,
            AVG_BUSY_PERC: 0
        }

        mock_client.getCPGStatData.return_value = stat_capabilities

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            stats = self.driver.get_volume_stats(True)
            const = 0.0009765625
            self.assertEqual('FC', stats['storage_protocol'])
            self.assertTrue(stats['pools'][0]['thin_provisioning_support'])
            self.assertTrue(stats['pools'][0]['thick_provisioning_support'])
            self.assertEqual(86.0,
                             stats['pools'][0]['provisioned_capacity_gb'])
            self.assertEqual(24.0, stats['pools'][0]['total_capacity_gb'])
            self.assertEqual(3.0, stats['pools'][0]['free_capacity_gb'])
            self.assertEqual(87.5, stats['pools'][0]['capacity_utilization'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(stat_capabilities[THROUGHPUT],
                             stats['pools'][0][THROUGHPUT])
            self.assertEqual(stat_capabilities[BANDWIDTH],
                             stats['pools'][0][BANDWIDTH])
            self.assertEqual(stat_capabilities[LATENCY],
                             stats['pools'][0][LATENCY])
            self.assertEqual(stat_capabilities[IO_SIZE],
                             stats['pools'][0][IO_SIZE])
            self.assertEqual(stat_capabilities[QUEUE_LENGTH],
                             stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(stat_capabilities[AVG_BUSY_PERC],
                             stats['pools'][0][AVG_BUSY_PERC])

            expected = [
                mock.call.getStorageSystemInfo(),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getCPGStatData(HP3PAR_CPG, 'daily', '7d'),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG),
                mock.call.getCPG(HP3PAR_CPG2),
                mock.call.getCPGStatData(HP3PAR_CPG2, 'daily', '7d'),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG2)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            stats = self.driver.get_volume_stats(True)
            self.assertEqual('FC', stats['storage_protocol'])
            self.assertTrue(stats['pools'][0]['thin_provisioning_support'])
            self.assertTrue(stats['pools'][0]['thick_provisioning_support'])
            self.assertEqual(86.0,
                             stats['pools'][0]['provisioned_capacity_gb'])
            self.assertEqual(24.0, stats['pools'][0]['total_capacity_gb'])
            self.assertEqual(3.0, stats['pools'][0]['free_capacity_gb'])
            self.assertEqual(87.5, stats['pools'][0]['capacity_utilization'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(stat_capabilities[THROUGHPUT],
                             stats['pools'][0][THROUGHPUT])
            self.assertEqual(stat_capabilities[BANDWIDTH],
                             stats['pools'][0][BANDWIDTH])
            self.assertEqual(stat_capabilities[LATENCY],
                             stats['pools'][0][LATENCY])
            self.assertEqual(stat_capabilities[IO_SIZE],
                             stats['pools'][0][IO_SIZE])
            self.assertEqual(stat_capabilities[QUEUE_LENGTH],
                             stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(stat_capabilities[AVG_BUSY_PERC],
                             stats['pools'][0][AVG_BUSY_PERC])

            cpg2 = self.cpgs[0].copy()
            cpg2.update({'SDGrowth': {'limitMiB': 8192}})
            mock_client.getCPG.return_value = cpg2

            stats = self.driver.get_volume_stats(True)
            self.assertEqual('FC', stats['storage_protocol'])
            self.assertTrue(stats['pools'][0]['thin_provisioning_support'])
            self.assertTrue(stats['pools'][0]['thick_provisioning_support'])
            total_capacity_gb = 8192 * const
            self.assertEqual(total_capacity_gb,
                             stats['pools'][0]['total_capacity_gb'])
            free_capacity_gb = int(
                (8192 - (self.cpgs[0]['UsrUsage']['usedMiB'] +
                         self.cpgs[0]['SDUsage']['usedMiB'])) * const)
            self.assertEqual(free_capacity_gb,
                             stats['pools'][0]['free_capacity_gb'])
            provisioned_capacity_gb = int(
                (self.cpgs[0]['UsrUsage']['totalMiB'] +
                 self.cpgs[0]['SAUsage']['totalMiB'] +
                 self.cpgs[0]['SDUsage']['totalMiB']) * const)
            self.assertEqual(provisioned_capacity_gb,
                             stats['pools'][0]['provisioned_capacity_gb'])
            cap_util = (float(total_capacity_gb - free_capacity_gb) /
                        float(total_capacity_gb)) * 100
            self.assertEqual(cap_util,
                             stats['pools'][0]['capacity_utilization'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(stat_capabilities[THROUGHPUT],
                             stats['pools'][0][THROUGHPUT])
            self.assertEqual(stat_capabilities[BANDWIDTH],
                             stats['pools'][0][BANDWIDTH])
            self.assertEqual(stat_capabilities[LATENCY],
                             stats['pools'][0][LATENCY])
            self.assertEqual(stat_capabilities[IO_SIZE],
                             stats['pools'][0][IO_SIZE])
            self.assertEqual(stat_capabilities[QUEUE_LENGTH],
                             stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(stat_capabilities[AVG_BUSY_PERC],
                             stats['pools'][0][AVG_BUSY_PERC])
            common.client.deleteCPG(HP3PAR_CPG)
            common.client.createCPG(HP3PAR_CPG, {})

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_get_volume_stats2(self):
        # Testing when the API_VERSION is incompatible with getCPGStatData
        srstatld_api_version = 30201200
        pre_srstatld_api_version = srstatld_api_version - 1
        wsapi = {'build': pre_srstatld_api_version}
        config = self.setup_configuration()
        config.filter_function = FILTER_FUNCTION
        config.goodness_function = GOODNESS_FUNCTION
        mock_client = self.setup_driver(config=config, wsapi_version=wsapi)
        mock_client.getCPG.return_value = self.cpgs[0]
        mock_client.getStorageSystemInfo.return_value = {
            'serialNumber': '1234'
        }

        # cpg has no limit
        mock_client.getCPGAvailableSpace.return_value = {
            "capacityEfficiency": {u'compaction': 594.4},
            "rawFreeMiB": 1024.0 * 6,
            "usableFreeMiB": 1024.0 * 3
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver._login()

            stats = self.driver.get_volume_stats(True)
            self.assertEqual('FC', stats['storage_protocol'])
            self.assertEqual(24.0, stats['pools'][0]['total_capacity_gb'])
            self.assertEqual(3.0, stats['pools'][0]['free_capacity_gb'])
            self.assertEqual(87.5, stats['pools'][0]['capacity_utilization'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(None, stats['pools'][0][THROUGHPUT])
            self.assertEqual(None, stats['pools'][0][BANDWIDTH])
            self.assertEqual(None, stats['pools'][0][LATENCY])
            self.assertEqual(None, stats['pools'][0][IO_SIZE])
            self.assertEqual(None, stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(None, stats['pools'][0][AVG_BUSY_PERC])

            expected = [
                mock.call.getStorageSystemInfo(),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG),
                mock.call.getCPG(HP3PAR_CPG2),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG2)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('hp3parclient.version', "3.2.1")
    def test_get_volume_stats3(self):
        # Testing when the client version is incompatible with getCPGStatData
        # setup_mock_client drive with the configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.filter_function = FILTER_FUNCTION
        config.goodness_function = GOODNESS_FUNCTION
        mock_client = self.setup_driver(config=config)
        mock_client.getCPG.return_value = self.cpgs[0]
        mock_client.getStorageSystemInfo.return_value = {
            'serialNumber': '1234'
        }

        # cpg has no limit
        mock_client.getCPGAvailableSpace.return_value = {
            "capacityEfficiency": {u'compaction': 594.4},
            "rawFreeMiB": 1024.0 * 6,
            "usableFreeMiB": 1024.0 * 3
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver._login()

            stats = self.driver.get_volume_stats(True)
            self.assertEqual('FC', stats['storage_protocol'])
            self.assertEqual(24.0, stats['pools'][0]['total_capacity_gb'])
            self.assertEqual(3.0, stats['pools'][0]['free_capacity_gb'])
            self.assertEqual(87.5, stats['pools'][0]['capacity_utilization'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(None, stats['pools'][0][THROUGHPUT])
            self.assertEqual(None, stats['pools'][0][BANDWIDTH])
            self.assertEqual(None, stats['pools'][0][LATENCY])
            self.assertEqual(None, stats['pools'][0][IO_SIZE])
            self.assertEqual(None, stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(None, stats['pools'][0][AVG_BUSY_PERC])

            expected = [
                mock.call.getStorageSystemInfo(),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG),
                mock.call.getCPG(HP3PAR_CPG2),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG2)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_create_host(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST,
                'FCPaths': [{'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 1,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': self.wwn[0]},
                            {'driverVersion': None,
                             'firmwareVersion': None,
                             'hostSpeed': 0,
                             'model': None,
                             'portPos': {'cardPort': 1, 'node': 0,
                                         'slot': 2},
                             'vendor': None,
                             'wwn': self.wwn[1]}]}]
        mock_client.queryHost.return_value = None
        mock_client.getVLUN.return_value = {'lun': 186}
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host = self.driver._create_host(
                common,
                self.volume,
                self.connector)
            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(wwns=['123456789012345',
                                          '123456789054321']),
                mock.call.createHost(
                    self.FAKE_HOST,
                    FCWwns=['123456789012345', '123456789054321'],
                    optional={'domain': None, 'persona': 2}),
                mock.call.getHost(self.FAKE_HOST)]

            mock_client.assert_has_calls(expected)

            self.assertEqual(self.FAKE_HOST, host['name'])

    def test_create_invalid_host(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('Host not found.'), {
                'name': 'fakehost.foo',
                'FCPaths': [{'wwn': '123456789012345'}, {
                    'wwn': '123456789054321'}]}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': 'fakehost.foo'
            }]
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host = self.driver._create_host(
                common,
                self.volume,
                self.connector)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost('fakehost'),
                mock.call.queryHost(wwns=['123456789012345',
                                          '123456789054321']),
                mock.call.getHost('fakehost.foo')]

            mock_client.assert_has_calls(expected)

            self.assertEqual('fakehost.foo', host['name'])

    def test_create_modify_host(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [{
            'name': self.FAKE_HOST, 'FCPaths': []},
            {'name': self.FAKE_HOST,
                'FCPaths': [{'wwn': '123456789012345'}, {
                    'wwn': '123456789054321'}]}]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host = self.driver._create_host(
                common,
                self.volume,
                self.connector)
            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost('fakehost'),
                mock.call.modifyHost(
                    'fakehost', {
                        'FCWWNs': ['123456789012345', '123456789054321'],
                        'pathOperation': 1}),
                mock.call.getHost('fakehost')]

            mock_client.assert_has_calls(expected)

            self.assertEqual(self.FAKE_HOST, host['name'])
            self.assertEqual(2, len(host['FCPaths']))

    def test_modify_host_with_new_wwn(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        getHost_ret1 = {
            'name': self.FAKE_HOST,
            'FCPaths': [{'wwn': '123456789054321'}]}
        getHost_ret2 = {
            'name': self.FAKE_HOST,
            'FCPaths': [{'wwn': '123456789012345'},
                        {'wwn': '123456789054321'}]}
        mock_client.getHost.side_effect = [getHost_ret1, getHost_ret2]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host = self.driver._create_host(
                common,
                self.volume,
                self.connector)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost('fakehost'),
                mock.call.modifyHost(
                    'fakehost', {
                        'FCWWNs': ['123456789012345'], 'pathOperation': 1}),
                mock.call.getHost('fakehost')]

            mock_client.assert_has_calls(expected)

            self.assertEqual(self.FAKE_HOST, host['name'])
            self.assertEqual(2, len(host['FCPaths']))

    def test_modify_host_with_unknown_wwn_and_new_wwn(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        getHost_ret1 = {
            'name': self.FAKE_HOST,
            'FCPaths': [{'wwn': '123456789054321'},
                        {'wwn': 'xxxxxxxxxxxxxxx'}]}
        getHost_ret2 = {
            'name': self.FAKE_HOST,
            'FCPaths': [{'wwn': '123456789012345'},
                        {'wwn': '123456789054321'},
                        {'wwn': 'xxxxxxxxxxxxxxx'}]}
        mock_client.getHost.side_effect = [getHost_ret1, getHost_ret2]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host = self.driver._create_host(
                common,
                self.volume,
                self.connector)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost('fakehost'),
                mock.call.modifyHost(
                    'fakehost', {
                        'FCWWNs': ['123456789012345'], 'pathOperation': 1}),
                mock.call.getHost('fakehost')]

            mock_client.assert_has_calls(expected)

            self.assertEqual(self.FAKE_HOST, host['name'])
            self.assertEqual(3, len(host['FCPaths']))


class TestHP3PARISCSIDriver(HP3PARBaseDriver, test.TestCase):

    TARGET_IQN = 'iqn.2000-05.com.3pardata:21810002ac00383d'
    TARGET_LUN = 186

    properties = {
        'driver_volume_type': 'iscsi',
        'data':
        {'encrypted': False,
            'target_discovered': True,
            'target_iqn': TARGET_IQN,
            'target_lun': TARGET_LUN,
            'target_portal': '1.1.1.2:1234'}}

    multipath_properties = {
        'driver_volume_type': 'iscsi',
        'data':
        {'encrypted': False,
            'target_discovered': True,
            'target_iqns': [TARGET_IQN],
            'target_luns': [TARGET_LUN],
            'target_portals': ['1.1.1.2:1234']}}

    def setup_driver(self, config=None, mock_conf=None, wsapi_version=None):

        self.ctxt = context.get_admin_context()

        mock_client = self.setup_mock_client(
            conf=config,
            m_conf=mock_conf,
            driver=hpdriver.HP3PARISCSIDriver)

        if wsapi_version:
            mock_client.getWsApiVersion.return_value = (
                wsapi_version)
        else:
            mock_client.getWsApiVersion.return_value = (
                self.wsapi_version_latest)

        expected_get_cpgs = [
            mock.call.getCPG(HP3PAR_CPG),
            mock.call.getCPG(HP3PAR_CPG2)]
        expected_get_ports = [mock.call.getPorts()]
        mock_client.assert_has_calls(
            self.standard_login +
            expected_get_cpgs +
            self.standard_logout +
            self.standard_login +
            expected_get_ports +
            self.standard_logout)
        mock_client.reset_mock()

        return mock_client

    def test_initialize_connection(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        mock_client.getHostVLUNs.side_effect = [
            [{'hostname': self.FAKE_HOST,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': self.TARGET_LUN,
              'portPos': {'node': 8, 'slot': 1, 'cardPort': 1}}],
            [{'active': True,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': self.TARGET_LUN, 'type': 0}]]

        location = ("%(volume_name)s,%(lun_id)s,%(host)s,%(nsp)s" %
                    {'volume_name': self.VOLUME_3PAR_NAME,
                     'lun_id': self.TARGET_LUN,
                     'host': self.FAKE_HOST,
                     'nsp': 'something'})
        mock_client.createVLUN.return_value = location

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            result = self.driver.initialize_connection(
                self.volume,
                self.connector)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(iqns=['iqn.1993-08.org.debian:01:222']),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.getHostVLUNs(self.FAKE_HOST)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            self.assertDictMatch(result, self.properties)

    def test_initialize_connection_multipath(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        mock_client.getHostVLUNs.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            [{'active': True,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': self.TARGET_LUN, 'type': 0,
              'portPos': {'node': 8, 'slot': 1, 'cardPort': 1}}]]

        location = ("%(volume_name)s,%(lun_id)s,%(host)s,%(nsp)s" %
                    {'volume_name': self.VOLUME_3PAR_NAME,
                     'lun_id': self.TARGET_LUN,
                     'host': self.FAKE_HOST,
                     'nsp': 'something'})
        mock_client.createVLUN.return_value = location

        mock_client.getiSCSIPorts.return_value = [{
            'IPAddr': '1.1.1.2',
            'iSCSIName': self.TARGET_IQN,
        }]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            result = self.driver.initialize_connection(
                self.volume,
                self.connector_multipath_enabled)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(iqns=['iqn.1993-08.org.debian:01:222']),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.getiSCSIPorts(
                    state=self.mock_client_conf['PORT_STATE_READY']),
                mock.call.getHostVLUNs(self.FAKE_HOST),
                mock.call.createVLUN(
                    self.VOLUME_3PAR_NAME,
                    auto=True,
                    hostname=self.FAKE_HOST,
                    portPos=self.FAKE_ISCSI_PORT['portPos']),
                mock.call.getHostVLUNs(self.FAKE_HOST)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            self.assertDictMatch(self.multipath_properties, result)

    def test_initialize_connection_multipath_existing_nsp(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        mock_client.getHostVLUNs.side_effect = [
            [{'hostname': self.FAKE_HOST,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': self.TARGET_LUN,
              'portPos': {'node': 8, 'slot': 1, 'cardPort': 1}}],
            [{'active': True,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': self.TARGET_LUN, 'type': 0}]]

        mock_client.getiSCSIPorts.return_value = [{
            'IPAddr': '1.1.1.2',
            'iSCSIName': self.TARGET_IQN,
        }]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            result = self.driver.initialize_connection(
                self.volume,
                self.connector_multipath_enabled)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(iqns=['iqn.1993-08.org.debian:01:222']),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.getiSCSIPorts(
                    state=self.mock_client_conf['PORT_STATE_READY']),
                mock.call.getHostVLUNs(self.FAKE_HOST)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            self.assertDictMatch(self.multipath_properties, result)

    def test_initialize_connection_encrypted(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': self.FAKE_HOST
            }]
        }

        mock_client.getHostVLUNs.side_effect = [
            [{'hostname': self.FAKE_HOST,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': self.TARGET_LUN,
              'portPos': {'node': 8, 'slot': 1, 'cardPort': 1}}],
            [{'active': True,
              'volumeName': self.VOLUME_3PAR_NAME,
              'lun': self.TARGET_LUN, 'type': 0}]]

        location = ("%(volume_name)s,%(lun_id)s,%(host)s,%(nsp)s" %
                    {'volume_name': self.VOLUME_3PAR_NAME,
                     'lun_id': self.TARGET_LUN,
                     'host': self.FAKE_HOST,
                     'nsp': 'something'})
        mock_client.createVLUN.return_value = location

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            result = self.driver.initialize_connection(
                self.volume_encrypted,
                self.connector)

            expected = [
                mock.call.getVolume(self.VOLUME_3PAR_NAME),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(iqns=['iqn.1993-08.org.debian:01:222']),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.getHostVLUNs(self.FAKE_HOST)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            expected_properties = self.properties
            expected_properties['data']['encrypted'] = True
            self.assertDictMatch(result, self.properties)

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_get_volume_stats(self):
        # setup_mock_client drive with the configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.filter_function = FILTER_FUNCTION
        config.goodness_function = GOODNESS_FUNCTION
        mock_client = self.setup_driver(config=config)
        mock_client.getCPG.return_value = self.cpgs[0]
        mock_client.getStorageSystemInfo.return_value = {
            'serialNumber': '1234'
        }
        # cpg has no limit
        mock_client.getCPGAvailableSpace.return_value = {
            "capacityEfficiency": {u'compaction': 594.4},
            "rawFreeMiB": 1024.0 * 6,
            "usableFreeMiB": 1024.0 * 3
        }
        stat_capabilities = {
            THROUGHPUT: 0,
            BANDWIDTH: 0,
            LATENCY: 0,
            IO_SIZE: 0,
            QUEUE_LENGTH: 0,
            AVG_BUSY_PERC: 0
        }
        mock_client.getCPGStatData.return_value = stat_capabilities

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client

            stats = self.driver.get_volume_stats(True)
            const = 0.0009765625
            self.assertEqual('iSCSI', stats['storage_protocol'])
            self.assertTrue(stats['pools'][0]['thin_provisioning_support'])
            self.assertTrue(stats['pools'][0]['thick_provisioning_support'])
            self.assertEqual(24.0, stats['pools'][0]['total_capacity_gb'])
            self.assertEqual(3.0, stats['pools'][0]['free_capacity_gb'])
            self.assertEqual(86.0,
                             stats['pools'][0]['provisioned_capacity_gb'])
            self.assertEqual(87.5, stats['pools'][0]['capacity_utilization'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(stat_capabilities[THROUGHPUT],
                             stats['pools'][0][THROUGHPUT])
            self.assertEqual(stat_capabilities[BANDWIDTH],
                             stats['pools'][0][BANDWIDTH])
            self.assertEqual(stat_capabilities[LATENCY],
                             stats['pools'][0][LATENCY])
            self.assertEqual(stat_capabilities[IO_SIZE],
                             stats['pools'][0][IO_SIZE])
            self.assertEqual(stat_capabilities[QUEUE_LENGTH],
                             stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(stat_capabilities[AVG_BUSY_PERC],
                             stats['pools'][0][AVG_BUSY_PERC])

            expected = [
                mock.call.getStorageSystemInfo(),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getCPGStatData(HP3PAR_CPG, 'daily', '7d'),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG),
                mock.call.getCPG(HP3PAR_CPG2),
                mock.call.getCPGStatData(HP3PAR_CPG2, 'daily', '7d'),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG2)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

            cpg2 = self.cpgs[0].copy()
            cpg2.update({'SDGrowth': {'limitMiB': 8192}})
            mock_client.getCPG.return_value = cpg2

            stats = self.driver.get_volume_stats(True)
            self.assertEqual('iSCSI', stats['storage_protocol'])
            self.assertTrue(stats['pools'][0]['thin_provisioning_support'])
            self.assertTrue(stats['pools'][0]['thick_provisioning_support'])
            total_capacity_gb = 8192 * const
            self.assertEqual(total_capacity_gb,
                             stats['pools'][0]['total_capacity_gb'])
            free_capacity_gb = int(
                (8192 - (self.cpgs[0]['UsrUsage']['usedMiB'] +
                         self.cpgs[0]['SDUsage']['usedMiB'])) * const)
            self.assertEqual(free_capacity_gb,
                             stats['pools'][0]['free_capacity_gb'])
            cap_util = (float(total_capacity_gb - free_capacity_gb) /
                        float(total_capacity_gb)) * 100
            self.assertEqual(cap_util,
                             stats['pools'][0]['capacity_utilization'])
            provisioned_capacity_gb = int(
                (self.cpgs[0]['UsrUsage']['totalMiB'] +
                 self.cpgs[0]['SAUsage']['totalMiB'] +
                 self.cpgs[0]['SDUsage']['totalMiB']) * const)
            self.assertEqual(provisioned_capacity_gb,
                             stats['pools'][0]['provisioned_capacity_gb'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(stat_capabilities[THROUGHPUT],
                             stats['pools'][0][THROUGHPUT])
            self.assertEqual(stat_capabilities[BANDWIDTH],
                             stats['pools'][0][BANDWIDTH])
            self.assertEqual(stat_capabilities[LATENCY],
                             stats['pools'][0][LATENCY])
            self.assertEqual(stat_capabilities[IO_SIZE],
                             stats['pools'][0][IO_SIZE])
            self.assertEqual(stat_capabilities[QUEUE_LENGTH],
                             stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(stat_capabilities[AVG_BUSY_PERC],
                             stats['pools'][0][AVG_BUSY_PERC])

    @mock.patch('hp3parclient.version', "3.2.2")
    def test_get_volume_stats2(self):
        # Testing when the API_VERSION is incompatible with getCPGStatData
        srstatld_api_version = 30201200
        pre_srstatld_api_version = srstatld_api_version - 1
        wsapi = {'build': pre_srstatld_api_version}
        config = self.setup_configuration()
        config.filter_function = FILTER_FUNCTION
        config.goodness_function = GOODNESS_FUNCTION
        mock_client = self.setup_driver(config=config, wsapi_version=wsapi)
        mock_client.getCPG.return_value = self.cpgs[0]
        mock_client.getStorageSystemInfo.return_value = {
            'serialNumber': '1234'
        }

        # cpg has no limit
        mock_client.getCPGAvailableSpace.return_value = {
            "capacityEfficiency": {u'compaction': 594.4},
            "rawFreeMiB": 1024.0 * 6,
            "usableFreeMiB": 1024.0 * 3
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver._login()

            stats = self.driver.get_volume_stats(True)
            self.assertEqual('iSCSI', stats['storage_protocol'])
            self.assertEqual(24.0, stats['pools'][0]['total_capacity_gb'])
            self.assertEqual(3.0, stats['pools'][0]['free_capacity_gb'])
            self.assertEqual(87.5, stats['pools'][0]['capacity_utilization'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(None, stats['pools'][0][THROUGHPUT])
            self.assertEqual(None, stats['pools'][0][BANDWIDTH])
            self.assertEqual(None, stats['pools'][0][LATENCY])
            self.assertEqual(None, stats['pools'][0][IO_SIZE])
            self.assertEqual(None, stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(None, stats['pools'][0][AVG_BUSY_PERC])

            expected = [
                mock.call.getStorageSystemInfo(),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG),
                mock.call.getCPG(HP3PAR_CPG2),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG2)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    @mock.patch('hp3parclient.version', "3.2.1")
    def test_get_volume_stats3(self):
        # Testing when the client version is incompatible with getCPGStatData
        # setup_mock_client drive with the configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.filter_function = FILTER_FUNCTION
        config.goodness_function = GOODNESS_FUNCTION
        mock_client = self.setup_driver(config=config)
        mock_client.getCPG.return_value = self.cpgs[0]
        mock_client.getStorageSystemInfo.return_value = {
            'serialNumber': '1234'
        }

        # cpg has no limit
        mock_client.getCPGAvailableSpace.return_value = {
            "capacityEfficiency": {u'compaction': 594.4},
            "rawFreeMiB": 1024.0 * 6,
            "usableFreeMiB": 1024.0 * 3
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            self.driver._login()

            stats = self.driver.get_volume_stats(True)
            self.assertEqual('iSCSI', stats['storage_protocol'])
            self.assertEqual(24.0, stats['pools'][0]['total_capacity_gb'])
            self.assertEqual(3.0, stats['pools'][0]['free_capacity_gb'])
            self.assertEqual(87.5, stats['pools'][0]['capacity_utilization'])
            self.assertEqual(3, stats['pools'][0]['total_volumes'])
            self.assertEqual(GOODNESS_FUNCTION,
                             stats['pools'][0]['goodness_function'])
            self.assertEqual(FILTER_FUNCTION,
                             stats['pools'][0]['filter_function'])
            self.assertEqual(None, stats['pools'][0][THROUGHPUT])
            self.assertEqual(None, stats['pools'][0][BANDWIDTH])
            self.assertEqual(None, stats['pools'][0][LATENCY])
            self.assertEqual(None, stats['pools'][0][IO_SIZE])
            self.assertEqual(None, stats['pools'][0][QUEUE_LENGTH])
            self.assertEqual(None, stats['pools'][0][AVG_BUSY_PERC])

            expected = [
                mock.call.getStorageSystemInfo(),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG),
                mock.call.getCPG(HP3PAR_CPG2),
                mock.call.getCPGAvailableSpace(HP3PAR_CPG2)]

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)

    def test_create_host(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST}]
        mock_client.queryHost.return_value = None
        mock_client.getVLUN.return_value = {'lun': self.TARGET_LUN}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host, auth_username, auth_password = self.driver._create_host(
                common, self.volume, self.connector)
            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(iqns=['iqn.1993-08.org.debian:01:222']),
                mock.call.createHost(
                    self.FAKE_HOST,
                    optional={'domain': None, 'persona': 2},
                    iscsiNames=['iqn.1993-08.org.debian:01:222']),
                mock.call.getHost(self.FAKE_HOST)]

            mock_client.assert_has_calls(expected)

            self.assertEqual(self.FAKE_HOST, host['name'])
            self.assertEqual(None, auth_username)
            self.assertEqual(None, auth_password)

    def test_create_host_chap_enabled(self):
        # setup_mock_client drive with CHAP enabled configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.hp3par_iscsi_chap_enabled = True
        mock_client = self.setup_driver(config=config)

        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('fake'),
            {'name': self.FAKE_HOST}]
        mock_client.queryHost.return_value = None
        mock_client.getVLUN.return_value = {'lun': self.TARGET_LUN}

        expected_mod_request = {
            'chapOperation': mock_client.HOST_EDIT_ADD,
            'chapOperationMode': mock_client.CHAP_INITIATOR,
            'chapName': 'test-user',
            'chapSecret': 'test-pass'
        }

        def get_side_effect(*args):
            data = {'value': None}
            if args[1] == CHAP_USER_KEY:
                data['value'] = 'test-user'
            elif args[1] == CHAP_PASS_KEY:
                data['value'] = 'test-pass'
            return data

        mock_client.getVolumeMetaData.side_effect = get_side_effect

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host, auth_username, auth_password = self.driver._create_host(
                common, self.volume, self.connector)
            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getVolumeMetaData(
                    'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_USER_KEY),
                mock.call.getVolumeMetaData(
                    'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(iqns=['iqn.1993-08.org.debian:01:222']),
                mock.call.createHost(
                    self.FAKE_HOST,
                    optional={'domain': None, 'persona': 2},
                    iscsiNames=['iqn.1993-08.org.debian:01:222']),
                mock.call.modifyHost(
                    'fakehost',
                    expected_mod_request),
                mock.call.getHost(self.FAKE_HOST)
            ]

            mock_client.assert_has_calls(expected)

            self.assertEqual(self.FAKE_HOST, host['name'])
            self.assertEqual('test-user', auth_username)
            self.assertEqual('test-pass', auth_password)

    def test_create_invalid_host(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('Host not found.'),
            {'name': 'fakehost.foo'}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': 'fakehost.foo'
            }]
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host, auth_username, auth_password = self.driver._create_host(
                common, self.volume, self.connector)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(iqns=['iqn.1993-08.org.debian:01:222']),
                mock.call.getHost('fakehost.foo')]

            mock_client.assert_has_calls(expected)

            self.assertEqual('fakehost.foo', host['name'])
            self.assertEqual(None, auth_username)
            self.assertEqual(None, auth_password)

    def test_create_invalid_host_chap_enabled(self):
        # setup_mock_client drive with CHAP enabled configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.hp3par_iscsi_chap_enabled = True
        mock_client = self.setup_driver(config=config)

        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            hpexceptions.HTTPNotFound('Host not found.'),
            {'name': 'fakehost.foo'}]
        mock_client.queryHost.return_value = {
            'members': [{
                'name': 'fakehost.foo'
            }]
        }

        def get_side_effect(*args):
            data = {'value': None}
            if args[1] == CHAP_USER_KEY:
                data['value'] = 'test-user'
            elif args[1] == CHAP_PASS_KEY:
                data['value'] = 'test-pass'
            return data

        mock_client.getVolumeMetaData.side_effect = get_side_effect

        expected_mod_request = {
            'chapOperation': mock_client.HOST_EDIT_ADD,
            'chapOperationMode': mock_client.CHAP_INITIATOR,
            'chapName': 'test-user',
            'chapSecret': 'test-pass'
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host, auth_username, auth_password = self.driver._create_host(
                common, self.volume, self.connector)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getVolumeMetaData(
                    'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_USER_KEY),
                mock.call.getVolumeMetaData(
                    'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.queryHost(iqns=['iqn.1993-08.org.debian:01:222']),
                mock.call.modifyHost(
                    'fakehost.foo',
                    expected_mod_request),
                mock.call.getHost('fakehost.foo')
            ]

            mock_client.assert_has_calls(expected)

            self.assertEqual('fakehost.foo', host['name'])
            self.assertEqual('test-user', auth_username)
            self.assertEqual('test-pass', auth_password)

    def test_create_modify_host(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            {'name': self.FAKE_HOST, 'FCPaths': []},
            {'name': self.FAKE_HOST,
             'FCPaths': [{'wwn': '123456789012345'},
                         {'wwn': '123456789054321'}]}]

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host, auth_username, auth_password = self.driver._create_host(
                common, self.volume, self.connector)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.modifyHost(
                    self.FAKE_HOST,
                    {'pathOperation': 1,
                        'iSCSINames': ['iqn.1993-08.org.debian:01:222']}),
                mock.call.getHost(self.FAKE_HOST)]

            mock_client.assert_has_calls(expected)

            self.assertEqual(self.FAKE_HOST, host['name'])
            self.assertEqual(None, auth_username)
            self.assertEqual(None, auth_password)
            self.assertEqual(2, len(host['FCPaths']))

    def test_create_modify_host_chap_enabled(self):
        # setup_mock_client drive with CHAP enabled configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.hp3par_iscsi_chap_enabled = True
        mock_client = self.setup_driver(config=config)

        mock_client.getVolume.return_value = {'userCPG': HP3PAR_CPG}
        mock_client.getCPG.return_value = {}
        mock_client.getHost.side_effect = [
            {'name': self.FAKE_HOST, 'FCPaths': []},
            {'name': self.FAKE_HOST,
             'FCPaths': [{'wwn': '123456789012345'},
                         {'wwn': '123456789054321'}]}]

        def get_side_effect(*args):
            data = {'value': None}
            if args[1] == CHAP_USER_KEY:
                data['value'] = 'test-user'
            elif args[1] == CHAP_PASS_KEY:
                data['value'] = 'test-pass'
            return data

        mock_client.getVolumeMetaData.side_effect = get_side_effect

        expected_mod_request = {
            'chapOperation': mock_client.HOST_EDIT_ADD,
            'chapOperationMode': mock_client.CHAP_INITIATOR,
            'chapName': 'test-user',
            'chapSecret': 'test-pass'
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            host, auth_username, auth_password = self.driver._create_host(
                common, self.volume, self.connector)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getCPG(HP3PAR_CPG),
                mock.call.getVolumeMetaData(
                    'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_USER_KEY),
                mock.call.getVolumeMetaData(
                    'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY),
                mock.call.getHost(self.FAKE_HOST),
                mock.call.modifyHost(
                    self.FAKE_HOST,
                    {'pathOperation': 1,
                        'iSCSINames': ['iqn.1993-08.org.debian:01:222']}),
                mock.call.modifyHost(
                    self.FAKE_HOST,
                    expected_mod_request
                ),
                mock.call.getHost(self.FAKE_HOST)]

            mock_client.assert_has_calls(expected)

            self.assertEqual(self.FAKE_HOST, host['name'])
            self.assertEqual('test-user', auth_username)
            self.assertEqual('test-pass', auth_password)
            self.assertEqual(2, len(host['FCPaths']))

    def test_get_least_used_nsp_for_host_single(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        mock_client.getPorts.return_value = PORTS_RET
        mock_client.getVLUNs.return_value = VLUNS1_RET

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            # Setup a single ISCSI IP
            iscsi_ips = ["10.10.220.253"]
            self.driver.configuration.hp3par_iscsi_ips = iscsi_ips

            self.driver.initialize_iscsi_ports(common)

            nsp = self.driver._get_least_used_nsp_for_host(common, 'newhost')
            self.assertEqual("1:8:1", nsp)

    def test_get_least_used_nsp_for_host_new(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        mock_client.getPorts.return_value = PORTS_RET
        mock_client.getVLUNs.return_value = VLUNS1_RET

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            # Setup two ISCSI IPs
            iscsi_ips = ["10.10.220.252", "10.10.220.253"]
            self.driver.configuration.hp3par_iscsi_ips = iscsi_ips

            self.driver.initialize_iscsi_ports(common)

            # Host 'newhost' does not yet have any iscsi paths,
            # so the 'least used' is returned
            nsp = self.driver._get_least_used_nsp_for_host(common, 'newhost')
            self.assertEqual("1:8:2", nsp)

    def test_get_least_used_nsp_for_host_reuse(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        mock_client.getPorts.return_value = PORTS_RET
        mock_client.getVLUNs.return_value = VLUNS1_RET

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            # Setup two ISCSI IPs
            iscsi_ips = ["10.10.220.252", "10.10.220.253"]
            self.driver.configuration.hp3par_iscsi_ips = iscsi_ips

            self.driver.initialize_iscsi_ports(common)

            # hosts 'foo' and 'bar' already have active iscsi paths
            # the same one should be used
            nsp = self.driver._get_least_used_nsp_for_host(common, 'foo')
            self.assertEqual("1:8:2", nsp)

            nsp = self.driver._get_least_used_nsp_for_host(common, 'bar')
            self.assertEqual("1:8:1", nsp)

    def test_get_least_used_nps_for_host_fc(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        mock_client.getPorts.return_value = PORTS1_RET
        mock_client.getVLUNs.return_value = VLUNS5_RET

        # Setup two ISCSI IPs
        iscsi_ips = ["10.10.220.252", "10.10.220.253"]
        self.driver.configuration.hp3par_iscsi_ips = iscsi_ips

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            self.driver.initialize_iscsi_ports(common)

            nsp = self.driver._get_least_used_nsp_for_host(common, 'newhost')
            self.assertNotEqual("0:6:3", nsp)
            self.assertEqual("1:8:1", nsp)

    def test_invalid_iscsi_ip(self):
        config = self.setup_configuration()
        config.hp3par_iscsi_ips = ['10.10.220.250', '10.10.220.251']
        config.iscsi_ip_address = '10.10.10.10'
        mock_conf = {
            'getPorts.return_value': {
                'members': [
                    {'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                     'protocol': 2,
                     'IPAddr': '10.10.220.252',
                     'linkState': 4,
                     'device': [],
                     'iSCSIName': self.TARGET_IQN,
                     'mode': 2,
                     'HWAddr': '2C27D75375D2',
                     'type': 8},
                    {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                     'protocol': 2,
                     'IPAddr': '10.10.220.253',
                     'linkState': 4,
                     'device': [],
                     'iSCSIName': self.TARGET_IQN,
                     'mode': 2,
                     'HWAddr': '2C27D75375D6',
                     'type': 8}]}}

        # no valid ip addr should be configured.
        self.assertRaises(exception.InvalidInput,
                          self.setup_driver,
                          config=config,
                          mock_conf=mock_conf)

    def test_get_least_used_nsp(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()
        ports = [
            {'portPos': {'node': 1, 'slot': 8, 'cardPort': 2}, 'active': True},
            {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1}, 'active': True},
            {'portPos': {'node': 1, 'slot': 8, 'cardPort': 2}, 'active': True},
            {'portPos': {'node': 0, 'slot': 2, 'cardPort': 2}, 'active': True},
            {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1}, 'active': True},
            {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1}, 'active': True},
            {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1}, 'active': True},
            {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1}, 'active': True}]
        mock_client.getVLUNs.return_value = {'members': ports}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            # in use count
            vluns = common.client.getVLUNs()
            nsp = self.driver._get_least_used_nsp(common, vluns['members'],
                                                  ['0:2:1', '1:8:1'])
            self.assertEqual('1:8:1', nsp)

            ports = [
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True}]

            mock_client.getVLUNs.return_value = {'members': ports}

            # in use count
            common = self.driver._login()
            vluns = common.client.getVLUNs()
            nsp = self.driver._get_least_used_nsp(common, vluns['members'],
                                                  ['0:2:1', '1:2:1'])
            self.assertEqual('1:2:1', nsp)

            ports = [
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True},
                {'portPos': {'node': 0, 'slot': 2, 'cardPort': 1},
                 'active': True}]

            mock_client.getVLUNs.return_value = {'members': ports}

            # in use count
            common = self.driver._login()
            vluns = common.client.getVLUNs()
            nsp = self.driver._get_least_used_nsp(common, vluns['members'],
                                                  ['1:1:1', '1:2:1'])
            self.assertEqual('1:1:1', nsp)

    def test_set_3par_chaps(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            expected = []
            self.driver._set_3par_chaps(
                common, 'test-host', 'test-vol', 'test-host', 'pass')
            mock_client.assert_has_calls(expected)

        # setup_mock_client drive with CHAP enabled configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.hp3par_iscsi_chap_enabled = True
        mock_client = self.setup_driver(config=config)

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            expected_mod_request = {
                'chapOperation': mock_client.HOST_EDIT_ADD,
                'chapOperationMode': mock_client.CHAP_INITIATOR,
                'chapName': 'test-host',
                'chapSecret': 'fake'
            }

            expected = [
                mock.call.modifyHost('test-host', expected_mod_request)
            ]
            self.driver._set_3par_chaps(
                common, 'test-host', 'test-vol', 'test-host', 'fake')
            mock_client.assert_has_calls(expected)

    @mock.patch('cinder.volume.utils.generate_password')
    def test_do_export(self, mock_utils):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        volume = {'host': 'test-host@3pariscsi',
                  'id': 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'}
        mock_utils.return_value = 'random-pass'
        mock_client.getHostVLUNs.return_value = [
            {'active': True,
             'volumeName': self.VOLUME_3PAR_NAME,
             'lun': None, 'type': 0,
             'remoteName': 'iqn.1993-08.org.debian:01:222'}
        ]
        mock_client.getHost.return_value = {
            'name': 'osv-0DM4qZEVSKON-DXN-NwVpw',
            'initiatorChapEnabled': True
        }
        mock_client.getVolumeMetaData.return_value = {
            'value': 'random-pass'
        }

        expected = []
        expected_model = {'provider_auth': None}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            model = self.driver._do_export(common, volume)

            mock_client.assert_has_calls(expected)
            self.assertEqual(expected_model, model)

            mock_client.reset_mock()

        # setup_mock_client drive with CHAP enabled configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.hp3par_iscsi_chap_enabled = True
        mock_client = self.setup_driver(config=config)

        volume = {'host': 'test-host@3pariscsi',
                  'id': 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'}
        mock_utils.return_value = 'random-pass'
        mock_client.getHostVLUNs.return_value = [
            {'active': True,
             'volumeName': self.VOLUME_3PAR_NAME,
             'lun': None, 'type': 0,
             'remoteName': 'iqn.1993-08.org.debian:01:222'}
        ]
        mock_client.getHost.return_value = {
            'name': 'osv-0DM4qZEVSKON-DXN-NwVpw',
            'initiatorChapEnabled': True
        }
        mock_client.getVolumeMetaData.return_value = {
            'value': 'random-pass'
        }

        expected = [
            mock.call.getHostVLUNs('test-host'),
            mock.call.getHost('test-host'),
            mock.call.getVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY),
            mock.call.setVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_USER_KEY, 'test-host'),
            mock.call.setVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY, 'random-pass')
        ]
        expected_model = {'provider_auth': 'CHAP test-host random-pass'}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            model = self.driver._do_export(common, volume)
            mock_client.assert_has_calls(expected)
            self.assertEqual(expected_model, model)

    @mock.patch('cinder.volume.utils.generate_password')
    def test_do_export_host_not_found(self, mock_utils):
        # setup_mock_client drive with CHAP enabled configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.hp3par_iscsi_chap_enabled = True
        mock_client = self.setup_driver(config=config)

        volume = {'host': 'test-host@3pariscsi',
                  'id': 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'}
        mock_utils.return_value = "random-pass"
        mock_client.getHostVLUNs.side_effect = hpexceptions.HTTPNotFound(
            'fake')

        mock_client.getVolumeMetaData.return_value = {
            'value': 'random-pass'
        }

        expected = [
            mock.call.getHostVLUNs('test-host'),
            mock.call.setVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_USER_KEY, 'test-host'),
            mock.call.setVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY, 'random-pass')
        ]
        expected_model = {'provider_auth': 'CHAP test-host random-pass'}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            model = self.driver._do_export(common, volume)
            mock_client.assert_has_calls(expected)
            self.assertEqual(expected_model, model)

    @mock.patch('cinder.volume.utils.generate_password')
    def test_do_export_host_chap_disabled(self, mock_utils):
        # setup_mock_client drive with CHAP enabled configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.hp3par_iscsi_chap_enabled = True
        mock_client = self.setup_driver(config=config)

        volume = {'host': 'test-host@3pariscsi',
                  'id': 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'}
        mock_utils.return_value = 'random-pass'
        mock_client.getHostVLUNs.return_value = [
            {'active': True,
             'volumeName': self.VOLUME_3PAR_NAME,
             'lun': None, 'type': 0,
             'remoteName': 'iqn.1993-08.org.debian:01:222'}
        ]
        mock_client.getHost.return_value = {
            'name': 'fake-host',
            'initiatorChapEnabled': False
        }
        mock_client.getVolumeMetaData.return_value = {
            'value': 'random-pass'
        }

        expected = [
            mock.call.getHostVLUNs('test-host'),
            mock.call.getHost('test-host'),
            mock.call.getVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY),
            mock.call.setVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_USER_KEY, 'test-host'),
            mock.call.setVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY, 'random-pass')
        ]
        expected_model = {'provider_auth': 'CHAP test-host random-pass'}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            model = self.driver._do_export(common, volume)
            mock_client.assert_has_calls(expected)
            self.assertEqual(expected_model, model)

    @mock.patch('cinder.volume.utils.generate_password')
    def test_do_export_no_active_vluns(self, mock_utils):
        # setup_mock_client drive with CHAP enabled configuration
        # and return the mock HTTP 3PAR client
        config = self.setup_configuration()
        config.hp3par_iscsi_chap_enabled = True
        mock_client = self.setup_driver(config=config)

        volume = {'host': 'test-host@3pariscsi',
                  'id': 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'}
        mock_utils.return_value = "random-pass"
        mock_client.getHostVLUNs.return_value = [
            {'active': False,
             'volumeName': self.VOLUME_3PAR_NAME,
             'lun': None, 'type': 0,
             'remoteName': 'iqn.1993-08.org.debian:01:222'}
        ]
        mock_client.getHost.return_value = {
            'name': 'fake-host',
            'initiatorChapEnabled': True
        }
        mock_client.getVolumeMetaData.return_value = {
            'value': 'random-pass'
        }

        expected = [
            mock.call.getHostVLUNs('test-host'),
            mock.call.getHost('test-host'),
            mock.call.setVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_USER_KEY, 'test-host'),
            mock.call.setVolumeMetaData(
                'osv-0DM4qZEVSKON-DXN-NwVpw', CHAP_PASS_KEY, 'random-pass')
        ]
        expected_model = {'provider_auth': 'CHAP test-host random-pass'}

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()
            model = self.driver._do_export(common, volume)
            mock_client.assert_has_calls(expected)
            self.assertEqual(expected_model, model)

    def test_ensure_export(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        volume = {'host': 'test-host@3pariscsi',
                  'id': 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'}

        mock_client.getAllVolumeMetaData.return_value = {
            'total': 0,
            'members': []
        }

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            model = self.driver.ensure_export(None, volume)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getAllVolumeMetaData('osv-0DM4qZEVSKON-DXN-NwVpw')
            ]

            expected_model = {'provider_auth': None}

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(expected_model, model)

            mock_client.getAllVolumeMetaData.return_value = {
                'total': 2,
                'members': [
                    {
                        'creationTimeSec': 1406074222,
                        'value': 'fake-host',
                        'key': CHAP_USER_KEY,
                        'creationTime8601': '2014-07-22T17:10:22-07:00'
                    },
                    {
                        'creationTimeSec': 1406074222,
                        'value': 'random-pass',
                        'key': CHAP_PASS_KEY,
                        'creationTime8601': '2014-07-22T17:10:22-07:00'
                    }
                ]
            }

            model = self.driver.ensure_export(None, volume)

            expected = [
                mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw'),
                mock.call.getAllVolumeMetaData('osv-0DM4qZEVSKON-DXN-NwVpw')
            ]

            expected_model = {'provider_auth': "CHAP fake-host random-pass"}

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(expected_model, model)

    def test_ensure_export_missing_volume(self):
        # setup_mock_client drive with default configuration
        # and return the mock HTTP 3PAR client
        mock_client = self.setup_driver()

        volume = {'host': 'test-host@3pariscsi',
                  'id': 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'}

        mock_client.getVolume.side_effect = hpexceptions.HTTPNotFound(
            'fake')

        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            model = self.driver.ensure_export(None, volume)

            expected = [mock.call.getVolume('osv-0DM4qZEVSKON-DXN-NwVpw')]

            expected_model = None

            mock_client.assert_has_calls(
                self.standard_login +
                expected +
                self.standard_logout)
            self.assertEqual(expected_model, model)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_get_volume_settings_default_pool(self, _mock_volume_types):
        _mock_volume_types.return_value = {
            'name': 'gold',
            'id': 'gold-id',
            'extra_specs': {}}
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            volume = {'host': 'test-host@3pariscsi#pool_foo',
                      'id': 'd03338a9-9115-48a3-8dfc-35cdfcdc15a7'}
            pool = volume_utils.extract_host(volume['host'], 'pool')
            model = common.get_volume_settings_from_type_id('gold-id', pool)
            self.assertEqual('pool_foo', model['cpg'])

    def test_get_model_update(self):
        mock_client = self.setup_driver()
        with mock.patch.object(hpcommon.HP3PARCommon,
                               '_create_client') as mock_create_client:
            mock_create_client.return_value = mock_client
            common = self.driver._login()

            model_update = common._get_model_update('xxx@yyy#zzz', 'CPG')
            self.assertEqual({'host': 'xxx@yyy#CPG'}, model_update)

VLUNS5_RET = ({'members':
               [{'portPos': {'node': 0, 'slot': 8, 'cardPort': 2},
                 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'active': True}]})

PORTS_RET = ({'members':
              [{'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                'protocol': 2,
                'IPAddr': '10.10.220.252',
                'linkState': 4,
                'device': [],
                'iSCSIName': 'iqn.2000-05.com.3pardata:21820002ac00383d',
                'mode': 2,
                'HWAddr': '2C27D75375D2',
                'type': 8},
               {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                'protocol': 2,
                'IPAddr': '10.10.220.253',
                'linkState': 4,
                'device': [],
                'iSCSIName': 'iqn.2000-05.com.3pardata:21810002ac00383d',
                'mode': 2,
                'HWAddr': '2C27D75375D6',
                'type': 8}]})

VLUNS1_RET = ({'members':
               [{'portPos': {'node': 1, 'slot': 8, 'cardPort': 2},
                 'hostname': 'foo', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'hostname': 'bar', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'hostname': 'bar', 'active': True},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'hostname': 'bar', 'active': True}]})

PORTS1_RET = ({'members':
               [{'portPos': {'node': 0, 'slot': 8, 'cardPort': 2},
                 'protocol': 2,
                 'IPAddr': '10.10.120.252',
                 'linkState': 4,
                 'device': [],
                 'iSCSIName': 'iqn.2000-05.com.3pardata:21820002ac00383d',
                 'mode': 2,
                 'HWAddr': '2C27D75375D2',
                 'type': 8},
                {'portPos': {'node': 1, 'slot': 8, 'cardPort': 1},
                 'protocol': 2,
                 'IPAddr': '10.10.220.253',
                 'linkState': 4,
                 'device': [],
                 'iSCSIName': 'iqn.2000-05.com.3pardata:21810002ac00383d',
                 'mode': 2,
                 'HWAddr': '2C27D75375D6',
                 'type': 8},
                {'portWWN': '20210002AC00383D',
                 'protocol': 1,
                 'linkState': 4,
                 'mode': 2,
                 'device': ['cage2'],
                 'nodeWWN': '20210002AC00383D',
                 'type': 2,
                 'portPos': {'node': 0, 'slot': 6, 'cardPort': 3}}]})
