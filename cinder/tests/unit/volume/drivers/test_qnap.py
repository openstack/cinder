# Copyright (c) 2016 QNAP Systems, Inc.
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

import base64
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

import mock
from oslo_config import cfg
from oslo_utils import units
import six
from six.moves import urllib

from cinder import test
from cinder.volume.drivers import qnap

CONF = cfg.CONF

FAKE_LUNNAA = {'LUNNAA': 'fakeLunNaa'}
FAKE_SNAPSHOT = {'snapshot_id': 'fakeSnapshotId'}

FAKE_PASSWORD = 'qnapadmin'
FAKE_PARMS = {}
FAKE_PARMS['pwd'] = base64.b64encode(FAKE_PASSWORD.encode("utf-8"))
FAKE_PARMS['serviceKey'] = 1
FAKE_PARMS['user'] = 'admin'
sanitized_params = {}

for key in FAKE_PARMS:
    value = FAKE_PARMS[key]
    if value is not None:
        sanitized_params[key] = six.text_type(value)
global_sanitized_params = urllib.parse.urlencode(sanitized_params)
header = {
    'charset': 'utf-8', 'Content-Type': 'application/x-www-form-urlencoded'}
login_url = ('/cgi-bin/authLogin.cgi?')

get_basic_info_url = ('/cgi-bin/authLogin.cgi')

FAKE_RES_DETAIL_DATA_LOGIN = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <authSid><![CDATA[fakeSid]]></authSid>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_GETBASIC_INFO_TS = """
    <QDocRoot version="1.0">
        <model>
            <displayModelName><![CDATA[TS-870U-RP]]></displayModelName>
            <internalModelName><![CDATA[TS-879]]></internalModelName>
        </model>
        <firmware>
            <version><![CDATA[4.2.1]]></version>
        </firmware>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_GETBASIC_INFO = """
    <QDocRoot version="1.0">
        <model>
            <displayModelName><![CDATA[ES1640dc]]></displayModelName>
            <internalModelName><![CDATA[ES1640dc]]></internalModelName>
        </model>
        <firmware>
            <version><![CDATA[1.1.3]]></version>
        </firmware>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_GETBASIC_INFO_TES = """
    <QDocRoot version="1.0">
        <model>
            <displayModelName><![CDATA[TES-1885U]]></displayModelName>
            <internalModelName><![CDATA[ES-X85U]]></internalModelName>
        </model>
        <firmware>
            <version><![CDATA[1.1.3]]></version>
        </firmware>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_LUN_INFO = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <iSCSILUNList>
            <LUNInfo>
                <LUNNAA><![CDATA[fakeLunNaa]]></LUNNAA>
                <LUNName><![CDATA[fakeLunName]]></LUNName>
                <LUNIndex><![CDATA[fakeLunIndex]]></LUNIndex>
                <LUNThinAllocate><![CDATA[fakeLunThinAllocate]]></LUNThinAllocate>
                <LUNPath><![CDATA[fakeLunPath]]></LUNPath>
                <LUNTargetList>
                  <row>
                    <targetIndex><![CDATA[9]]></targetIndex>
                    <LUNNumber><![CDATA[1]]></LUNNumber>
                    <LUNEnable><![CDATA[1]]></LUNEnable>
                  </row>
                </LUNTargetList>
                <LUNStatus>1</LUNStatus>
            </LUNInfo>
        </iSCSILUNList>
        <result><![CDATA[0]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_MAPPED_LUN_INFO = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <iSCSILUNList>
            <LUNInfo>
                <LUNNAA><![CDATA[fakeLunNaa]]></LUNNAA>
                <LUNName><![CDATA[fakeLunName]]></LUNName>
                <LUNIndex><![CDATA[fakeLunIndex]]></LUNIndex>
                <LUNThinAllocate><![CDATA[fakeLunThinAllocate]]></LUNThinAllocate>
                <LUNPath><![CDATA[fakeLunPath]]></LUNPath>
                <LUNTargetList>
                  <row>
                    <targetIndex><![CDATA[9]]></targetIndex>
                    <LUNNumber><![CDATA[1]]></LUNNumber>
                    <LUNEnable><![CDATA[1]]></LUNEnable>
                  </row>
                </LUNTargetList>
                <LUNStatus>2</LUNStatus>
            </LUNInfo>
        </iSCSILUNList>
        <result><![CDATA[0]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_SNAPSHOT = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <SnapshotList>
            <row>
                <snapshot_id><![CDATA[fakeSnapshotId]]></snapshot_id>
            </row>
        </SnapshotList>
        <result><![CDATA[0]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_SPECIFIC_POOL_INFO = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <Pool_Index>
            <row>
                <poolIndex><![CDATA[fakePoolIndex]]></poolIndex>
                <poolID><![CDATA[fakePoolId]]></poolID>
                <pool_status><![CDATA[0]]></pool_status>
                <capacity_bytes><![CDATA[930213412209]]></capacity_bytes>
                <allocated_bytes><![CDATA[1480470528]]></allocated_bytes>
                <freesize_bytes><![CDATA[928732941681]]></freesize_bytes>
                <lun_meta_reserve_ratio><![CDATA[0.0315]]></lun_meta_reserve_ratio>
                <pool_capacity><![CDATA[866 GB]]></pool_capacity>
                <pool_allocated><![CDATA[1.38 GB]]></pool_allocated>
                <pool_freesize><![CDATA[865 GB]]></pool_freesize>
                <pool_threshold><![CDATA[80 %]]></pool_threshold>
                <pool_used><![CDATA[0 %]]></pool_used>
                <pool_available><![CDATA[100 %]]></pool_available>
                <pool_owner><![CDATA[SCA]]></pool_owner>
                <pool_type><![CDATA[mirror]]></pool_type>
                <pool_dedup><![CDATA[1.00]]></pool_dedup>
                <pool_bound><![CDATA[0]]></pool_bound>
                <pool_progress><![CDATA[0]]></pool_progress>
                <pool_scrub><![CDATA[0]]></pool_scrub>
            </row>
        </Pool_Index>
        <result><![CDATA[0]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_ISCSI_PORTAL_INFO = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
         <iSCSIPortal>
           <servicePort><![CDATA[fakeServicePort]]></servicePort>
           <targetIQNPrefix><![CDATA[fakeTargetIqnPrefix]]></targetIQNPrefix>
           <targetIQNPostfix><![CDATA[fakeTargetIqnPostfix]]></targetIQNPostfix>
         </iSCSIPortal>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_ETHERNET_IP = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
         <func>
            <ownContent>
                <IPConfig>
                    <ethdev><![CDATA[fakeEthdev]]></ethdev>
                    <ethSlotid><![CDATA[0]]></ethSlotid>
                    <IPType><![CDATA[static]]></IPType>
                    <IP><![CDATA[fakeIp]]></IP>
                </IPConfig>
            </ownContent>
         </func>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_CREATE_LUN = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <result><![CDATA[fakeLunIndex]]></result>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_CREATE_TARGET = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <result><![CDATA[fakeTargetIndex]]></result>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_GETHOSTIDLISTBYINITIQN = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <content>
            <host_list total="4">
                <host>
                    <index><![CDATA[fakeIndex]]></index>
                    <hostid><![CDATA[fakeHostId]]></hostid>
                    <name><![CDATA[fakeHostName]]></name>
                    <iqns>
                        <iqn><![CDATA[fakeIqn]]></iqn>
                    </iqns>
                </host>
            </host_list>
        </content>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_GET_ALL_ISCSI_PORTAL_SETTING = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <targetACL>
            <row>
                <targetIndex><![CDATA[fakeTargeIndex]]></targetIndex>
                <targetIQN><![CDATA[fakeTargetIqn]]></targetIQN>
                <targetInitListCnt><![CDATA[0]]></targetInitListCnt>
                <targetInitInfo>
                    <initiatorIndex><![CDATA[2]]></initiatorIndex>
                    <initiatorAlias><![CDATA[fakeInitiatorAlias]]></initiatorAlias>
                    <initiatorIQN><![CDATA[fakeInitiatorIqn]]></initiatorIQN>
                    <bCHAPEnable><![CDATA[0]]></bCHAPEnable>
                    <bMutualCHAPEnable><![CDATA[0]]></bMutualCHAPEnable>
                </targetInitInfo>
            </row>
        </targetACL>
        <iSCSITargetList>
            <targetInfo>
                <targetIndex><![CDATA[fakeTargeIndex]]></targetIndex>
                <targetName><![CDATA[fakeTargetName]]></targetName>
                <targetIQN active="1">fakeTargetIqn</targetIQN>
                <targetStatus><![CDATA[1]]></targetStatus>
            </targetInfo>
        </iSCSITargetList>
        <result><![CDATA[0]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_TARGET_INFO = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <targetInfo>
            <row>
                <targetIndex><![CDATA[fakeTargeIndex]]></targetIndex>
                <targetName><![CDATA[fakeTargetName]]></targetName>
                <targetIQN active="1">fakeTargetIqn</targetIQN>
                <targetStatus><![CDATA[1]]></targetStatus>
            </row>
        </targetInfo>
        <result><![CDATA[0]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_GET_ALL_ISCSI_PORTAL_SETTING = {
    'data': FAKE_RES_DETAIL_DATA_GET_ALL_ISCSI_PORTAL_SETTING,
    'error': None,
    'http_status': 'fackStatus'
}

FAKE_RES_DETAIL_ISCSI_PORTAL_INFO = {
    'data': FAKE_RES_DETAIL_DATA_ISCSI_PORTAL_INFO,
    'error': None,
    'http_status': 'fackStatus'
}


def create_configuration(
        username,
        password,
        management_url,
        san_iscsi_ip,
        poolname,
        thin_provision=True):
    """Create configuration."""
    configuration = mock.Mock()
    configuration.san_login = username
    configuration.san_password = password
    configuration.qnap_management_url = management_url
    configuration.san_thin_provision = thin_provision
    configuration.san_iscsi_ip = san_iscsi_ip
    configuration.qnap_poolname = poolname
    configuration.safe_get.return_value = 'QNAP'
    configuration.iscsi_ip_address = '1.2.3.4'
    configuration.qnap_storage_protocol = 'iscsi'
    configuration.reserved_percentage = 0
    return configuration


class QnapDriverBaseTestCase(test.TestCase):
    """Base Class for the QnapDriver Tests."""

    def setUp(self):
        """Setup the Qnap Driver Base TestCase."""
        super(QnapDriverBaseTestCase, self).setUp()
        self.driver = None
        self.mock_HTTPConnection = None
        self.mock_object(qnap.QnapISCSIDriver, 'TIME_INTERVAL', 0)

    @staticmethod
    def driver_mock_decorator(configuration):
        """Driver mock decorator."""
        def driver_mock_wrapper(func):
            def inner_driver_mock(
                    self,
                    mock_http_connection,
                    *args,
                    **kwargs):
                """Inner driver mock."""
                self.mock_HTTPConnection = mock_http_connection

                self.driver = qnap.QnapISCSIDriver(configuration=configuration)
                self.driver.do_setup('context')
                func(self, *args, **kwargs)
            return inner_driver_mock
        return driver_mock_wrapper

    def tearDown(self):
        """Tear down."""
        super(QnapDriverBaseTestCase, self).tearDown()


class SnapshotClass(object):
    """Snapshot Class."""

    volume = {}
    name = ''
    volume_name = ''
    volume_size = 0
    metadata = {'snapshot_id': 'fakeSnapshotId'}

    def __init__(self, volume, volume_size):
        """Init."""
        self.volume = volume
        self.volume_size = volume_size

    def __getitem__(self, arg):
        """Getitem."""
        return {
            'display_name': 'fakeSnapshotDisplayName',
            'id': 'fakeSnapshotId',
            'volume_size': self.volume_size,
            'metadata': self.metadata
        }[arg]


class VolumeClass(object):
    """Volume Class."""

    display_name = ''
    id = ''
    size = 0
    name = ''
    volume_metadata = {}

    def __init__(self, display_name, id, size, name):
        """Init."""
        self.display_name = display_name
        self.id = id
        self.size = size
        self.name = name
        self.volume_metadata = {'LUNNAA': 'fakeLunNaa'}

    def __getitem__(self, arg):
        """Getitem."""
        return {
            'display_name': self.display_name,
            'size': self.size,
            'id': self.id,
            'name': self.name,
            'provider_location': None,
            'volume_metadata': self.volume_metadata,
            'metadata': self.volume_metadata
        }[arg]

    def __setitem__(self, key, value):
        """Setitem."""
        if key == 'display_name':
            self.display_name = value


class HostClass(object):
    """Host Class."""

    def __init__(self, host):
        """Init."""
        self.host = host

    def __getitem__(self, arg):
        """Getitem."""
        return {
            'host': 'fakeHost',
        }[arg]


class FakeLoginResponse(object):
    """Fake login response."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_LOGIN


class FakeGetBasicInfoResponse(object):
    """Fake GetBasicInfo response."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO


class FakeGetBasicInfoTsResponse(object):
    """Fake GetBasicInfoTs response."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_TS


class FakeGetBasicInfoTesResponse(object):
    """Fake GetBasicInfoTs response."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_TES


class FakeLunInfoResponse(object):
    """Fake lun info response."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_LUN_INFO


class FakePoolInfoResponse(object):
    """Fake pool info response."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_SPECIFIC_POOL_INFO


class FakeCreateLunResponse(object):
    """Fake create lun response."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_CREATE_LUN


class FakeCreatTargetResponse(object):
    """Fake create target response."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_CREATE_TARGET


class FakeGetIscsiPortalInfoResponse(object):
    """Fake get iscsi portal inforesponse."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_ISCSI_PORTAL_INFO

    def __repr__(self):
        """Repr."""
        return six.StringIO(FAKE_RES_DETAIL_DATA_ISCSI_PORTAL_INFO)


class FakeCreateSnapshotResponse(object):
    """Fake Create snapshot inforesponse."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_SNAPSHOT


class FakeGetAllIscsiPortalSetting(object):
    """Fake get all iSCSI portal setting."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GET_ALL_ISCSI_PORTAL_SETTING


class FakeGetAllEthernetIp(object):
    """Fake get all ethernet ip setting."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_ETHERNET_IP


class FakeTargetInfo(object):
    """Fake target info setting."""

    status = 'fackStatus'

    def read(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_TARGET_INFO


class QnapDriverLoginTestCase(QnapDriverBaseTestCase):
    """Tests do_setup api."""

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_do_setup_positive(
            self,
            mock_http_connection):
        """Test do_setup with http://1.2.3.4:8080."""
        fake_login_response = FakeLoginResponse()
        fake_get_basic_info_response = FakeGetBasicInfoResponse()
        mock_http_connection.return_value.getresponse.side_effect = ([
            fake_login_response,
            fake_get_basic_info_response,
            fake_login_response])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')

        self.assertEqual('fakeSid', self.driver.api_executor.sid)
        self.assertEqual('admin', self.driver.api_executor.username)
        self.assertEqual('qnapadmin', self.driver.api_executor.password)
        self.assertEqual('1.2.3.4', self.driver.api_executor.ip)
        self.assertEqual('8080', self.driver.api_executor.port)
        self.assertFalse(self.driver.api_executor.ssl)

    @mock.patch('six.moves.http_client.HTTPSConnection')
    def test_do_setup_positive_with_ssl(
            self,
            mock_http_connection):
        """Test do_setup with https://1.2.3.4:443."""
        fake_login_response = FakeLoginResponse()
        fake_get_basic_info_response = FakeGetBasicInfoResponse()
        mock_http_connection.return_value.getresponse.side_effect = ([
            fake_login_response,
            fake_get_basic_info_response,
            fake_login_response])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'https://1.2.3.4:443',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')

        self.assertEqual('fakeSid', self.driver.api_executor.sid)
        self.assertEqual('admin', self.driver.api_executor.username)
        self.assertEqual('qnapadmin', self.driver.api_executor.password)
        self.assertEqual('1.2.3.4', self.driver.api_executor.ip)
        self.assertEqual('443', self.driver.api_executor.port)
        self.assertTrue(self.driver.api_executor.ssl)


class QnapDriverVolumeTestCase(QnapDriverBaseTestCase):
    """Tests volume related api's."""

    def get_lun_info_return_value(self):
        """Return the lun form get_lun_info method."""
        root = ET.fromstring(FAKE_RES_DETAIL_DATA_LUN_INFO)

        lun_list = root.find('iSCSILUNList')
        lun_info_tree = lun_list.findall('LUNInfo')
        for lun in lun_info_tree:
            return lun

    def get_mapped_lun_info_return_value(self):
        """Return the lun form get_lun_info method."""
        root = ET.fromstring(FAKE_RES_DETAIL_DATA_MAPPED_LUN_INFO)

        lun_list = root.find('iSCSILUNList')
        lun_info_tree = lun_list.findall('LUNInfo')
        for lun in lun_info_tree:
            return lun

    def get_snapshot_info_return_value(self):
        """Return the lun form get_lun_info method."""
        root = ET.fromstring(FAKE_RES_DETAIL_DATA_SNAPSHOT)

        snapshot_list = root.find('SnapshotList')
        snapshot_info_tree = snapshot_list.findall('row')
        for snapshot in snapshot_info_tree:
            return snapshot

    @mock.patch.object(qnap.QnapISCSIDriver, '_get_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_volume_positive(
            self,
            mock_api_executor,
            mock_gen_random_name,
            mock_get_volume_metadata):
        """Test create_volume with fake_volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_executor.return_value.get_lun_info.side_effect = [
            None,
            self.get_lun_info_return_value()]
        mock_gen_random_name.return_value = 'fakeLun'
        mock_api_executor.return_value.create_lun.return_value = 'fakeIndex'
        mock_get_volume_metadata.return_value = {}

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.create_volume(fake_volume)

        mock_api_executor.return_value.create_lun.assert_called_once_with(
            fake_volume,
            self.driver.configuration.qnap_poolname,
            'fakeLun',
            True)

        expected_call_list = [
            mock.call(LUNName='fakeLun'),
            mock.call(LUNIndex='fakeIndex')]
        self.assertEqual(
            expected_call_list,
            mock_api_executor.return_value.get_lun_info.call_args_list)

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_delete_volume_positive(
            self,
            mock_api_executor,
            mock_get_lun_naa_from_volume_metadata):
        """Test delete_volume with fake_volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_get_lun_naa_from_volume_metadata.return_value = FAKE_LUNNAA
        mock_api_executor.return_value.get_lun_info.return_value = (
            self.get_lun_info_return_value())
        mock_api_executor.return_value.delete_lun.return_value = None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.delete_volume(fake_volume)

        mock_api_executor.return_value.delete_lun.assert_called_once_with(
            'fakeLunIndex')

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch.object(qnap.QnapISCSIDriver, '_get_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_cloned_volume_volume_size_less_src_verf(
            self,
            mock_api_executor,
            mock_get_volume_metadata,
            mock_gen_random_name,
            mock_get_lun_naa_from_volume_metadata):
        """Test create cloned volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 90, 'fakeLunName')
        fake_src_vref = VolumeClass(
            'fakeSrcVrefName', 'fakeId', 100, 'fakeSrcVref')

        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_get_volume_metadata.return_value = {}
        mock_api_executor.return_value.get_lun_info.side_effect = [
            self.get_lun_info_return_value(),
            None,
            self.get_lun_info_return_value()]
        mock_gen_random_name.side_effect = ['fakeSnapshot', 'fakeLun']
        mock_api_executor.return_value.get_snapshot_info.side_effect = [
            None, self.get_snapshot_info_return_value()]
        mock_api_executor.return_value.create_snapshot_api.return_value = (
            'fakeSnapshotId')
        mock_api_executor.return_value.clone_snapshot.return_value = None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.create_cloned_volume(fake_volume, fake_src_vref)

        expected_call_list = [
            mock.call(LUNNAA='fakeLunNaa'),
            mock.call(LUNName='fakeLun'),
            mock.call(LUNName='fakeLun')]
        self.assertEqual(
            expected_call_list,
            mock_api_executor.return_value.get_lun_info.call_args_list)
        expected_call_list = [
            mock.call(lun_index='fakeLunIndex', snapshot_name='fakeSnapshot'),
            mock.call(lun_index='fakeLunIndex', snapshot_name='fakeSnapshot')]
        self.assertEqual(
            expected_call_list,
            mock_api_executor.return_value.get_snapshot_info.call_args_list)
        mock_api_return = mock_api_executor.return_value
        mock_api_return.create_snapshot_api.assert_called_once_with(
            'fakeLunIndex', 'fakeSnapshot')
        mock_api_return.clone_snapshot.assert_called_once_with(
            'fakeSnapshotId', 'fakeLun')

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_extend_lun')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch.object(qnap.QnapISCSIDriver, '_get_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_cloned_volume_volume_size_morethan_src_verf(
            self,
            mock_api_executor,
            mock_get_volume_metadata,
            mock_gen_random_name,
            mock_extend_lun,
            mock_get_lun_naa_from_volume_metadata):
        """Test create cloned volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_src_vref = VolumeClass(
            'fakeSrcVrefName', 'fakeId', 90, 'fakeSrcVref')

        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_get_volume_metadata.return_value = FAKE_LUNNAA
        mock_api_executor.return_value.get_lun_info.side_effect = [
            self.get_lun_info_return_value(),
            None,
            self.get_lun_info_return_value()]
        mock_gen_random_name.side_effect = ['fakeSnapshot', 'fakeLun']
        mock_api_executor.return_value.get_snapshot_info.side_effect = [
            None, self.get_snapshot_info_return_value()]
        mock_api_executor.return_value.create_snapshot_api.return_value = (
            'fakeSnapshotId')
        mock_api_executor.return_value.clone_snapshot.return_value = None
        mock_extend_lun.return_value = None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.create_cloned_volume(fake_volume, fake_src_vref)

        mock_extend_lun.assert_called_once_with(fake_volume, 'fakeLunNaa')

    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_snapshot_positive(
            self,
            mock_api_executor,
            mock_gen_random_name):
        """Test create snapshot."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        snapshot = SnapshotClass(fake_volume, 100)

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_executor.return_value.get_lun_info.return_value = (
            self.get_lun_info_return_value())
        mock_gen_random_name.return_value = 'fakeSnapshot'
        mock_api_executor.return_value.get_snapshot_info.side_effect = [
            None, self.get_snapshot_info_return_value()]
        mock_api_executor.return_value.create_snapshot_api.return_value = (
            'fakeSnapshotId')

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.create_snapshot(snapshot)

        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.assert_called_once_with(
            LUNNAA='fakeLunNaa')
        expected_call_list = [
            mock.call(lun_index='fakeLunIndex', snapshot_name='fakeSnapshot'),
            mock.call(lun_index='fakeLunIndex', snapshot_name='fakeSnapshot')]
        self.assertEqual(
            expected_call_list,
            mock_api_executor.return_value.get_snapshot_info.call_args_list)
        mock_api_return.create_snapshot_api.assert_called_once_with(
            'fakeLunIndex', 'fakeSnapshot')

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_delete_snapshot_positive(
            self,
            mock_api_executor):
        """Test delete snapshot."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_snapshot = SnapshotClass(fake_volume, 100)

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_executor.return_value.api_delete_snapshot.return_value = None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.delete_snapshot(fake_snapshot)

        mock_api_return = mock_api_executor.return_value
        mock_api_return.api_delete_snapshot.assert_called_once_with(
            'fakeSnapshotId')

    @mock.patch.object(qnap.QnapISCSIDriver, '_get_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_extend_lun')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_volume_from_snapshot_positive_volsize_more_snapshotvolsize(
            self,
            mock_api_executor,
            mock_gen_random_name,
            mock_extend_lun,
            mock_get_volume_metadata):
        """Test create volume from snapshot positive."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_snapshot = SnapshotClass(fake_volume, 90)

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_gen_random_name.return_value = 'fakeLun'
        mock_api_executor.return_value.get_lun_info.side_effect = [
            None,
            self.get_lun_info_return_value()]
        mock_api_executor.return_value.clone_snapshot.return_value = None

        mock_api_executor.return_value.create_snapshot_api.return_value = (
            'fakeSnapshotId')
        mock_extend_lun.return_value = None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.create_volume_from_snapshot(fake_volume, fake_snapshot)

        expected_call_list = [
            mock.call(LUNName='fakeLun'),
            mock.call(LUNName='fakeLun')]
        self.assertEqual(
            expected_call_list,
            mock_api_executor.return_value.get_lun_info.call_args_list)
        mock_api_return = mock_api_executor.return_value
        mock_api_return.clone_snapshot.assert_called_once_with(
            'fakeSnapshotId', 'fakeLun')
        mock_extend_lun.assert_called_once_with(fake_volume, 'fakeLunNaa')

    def get_specific_poolinfo_return_value(self):
        """Get specific pool info."""
        root = ET.fromstring(FAKE_RES_DETAIL_DATA_SPECIFIC_POOL_INFO)
        pool_list = root.find('Pool_Index')
        pool_info_tree = pool_list.findall('row')
        for pool in pool_info_tree:
            return pool

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_get_volume_stats(
            self,
            mock_api_executor):
        """Get volume stats."""
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return.get_specific_poolinfo.return_value = (
            self.get_specific_poolinfo_return_value())

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')

        expected_res = {'volume_backend_name': 'QNAP',
                        'vendor_name': 'QNAP',
                        'driver_version': '1.0.0',
                        'storage_protocol': 'iscsi'}
        single_pool = dict(
            pool_name=self.driver.configuration.qnap_poolname,
            total_capacity_gb=930213412209 / units.Gi,
            free_capacity_gb=928732941681 / units.Gi,
            provisioned_capacity_gb=1480470528 / units.Gi,
            reserved_percentage=self.driver.configuration.reserved_percentage,
            QoS_support=False)
        expected_res['pools'] = [single_pool]

        self.assertEqual(
            expected_res,
            self.driver.get_volume_stats(refresh=True))
        mock_api_return.get_specific_poolinfo.assert_called_once_with(
            self.driver.configuration.qnap_poolname)

    @mock.patch.object(qnap.QnapISCSIDriver, '_extend_lun')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_extend_volume(
            self,
            mock_api_executor,
            mock_extend_lun):
        """Test extend volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.extend_volume(fake_volume, 'fakeSize')

        mock_extend_lun.assert_called_once_with(fake_volume, '')

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_extend_lun(
            self,
            mock_api_executor,
            mock_get_lun_naa_from_volume_metadata):
        """Test _extend_lun method."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_executor.return_value.get_lun_info.return_value = (
            self.get_lun_info_return_value())
        mock_api_executor.return_value.edit_lun.return_value = None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver._extend_lun(fake_volume, '')

        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.assert_called_once_with(
            LUNNAA='fakeLunNaa')
        expect_lun = {
            'LUNName': 'fakeLunName',
            'LUNCapacity': fake_volume['size'],
            'LUNIndex': 'fakeLunIndex',
            'LUNThinAllocate': 'fakeLunThinAllocate',
            'LUNPath': 'fakeLunPath',
            'LUNStatus': '1'}
        mock_api_return.edit_lun.assert_called_once_with(expect_lun)

    @mock.patch.object(qnap.QnapISCSIDriver,
                       '_get_lun_naa_from_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_initialize_connection_with_target_exist(
            self,
            mock_api_executor,
            mock_get_lun_naa_from_volume_metadata):
        """Test initialize connection."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn'}

        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return.get_iscsi_portal_info.return_value = (
            FAKE_RES_DETAIL_ISCSI_PORTAL_INFO)
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_executor.return_value.get_lun_info.side_effect = [
            self.get_lun_info_return_value(),
            self.get_lun_info_return_value()]
        mock_api_return.get_all_iscsi_portal_setting.return_value = (
            FAKE_RES_DETAIL_GET_ALL_ISCSI_PORTAL_SETTING)
        mock_api_executor.return_value.map_lun.return_value = None
        mock_api_return.get_ethernet_ip.return_value = ['1.2.3.4']

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')

        expected_properties = {
            'target_discovered': True,
            'target_portal': '1.2.3.4:fakeServicePort',
            'target_iqn': 'fakeTargetIqn',
            'target_lun': 1,
            'volume_id': fake_volume['id'],
            'target_portals': ['1.2.3.4:fakeServicePort'],
            'target_iqns': ['fakeTargetIqn'],
            'target_luns': [1]}
        expected_return = {
            'driver_volume_type': 'iscsi', 'data': expected_properties}

        self.assertEqual(expected_return, self.driver.initialize_connection(
            fake_volume, fake_connector))

        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_iscsi_portal_info.assert_called_once_with()
        expected_call_list = [
            mock.call(LUNNAA='fakeLunNaa'),
            mock.call(LUNNAA='fakeLunNaa')]
        self.assertEqual(
            expected_call_list,
            mock_api_executor.return_value.get_lun_info.call_args_list)
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_all_iscsi_portal_setting.assert_called_once_with()
        mock_api_return.map_lun.assert_called_once_with(
            'fakeLunIndex', 'fakeTargeIndex')
        mock_api_return.get_ethernet_ip.assert_called_once_with(type='data')

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_terminate_connection(
            self,
            mock_api_executor,
            mock_get_lun_naa_from_volume_metadata):
        """Test terminate connection."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiator'}

        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_executor.return_value.get_lun_info.return_value = (
            self.get_mapped_lun_info_return_value())
        mock_api_executor.return_value.unmap_lun.return_value = None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.terminate_connection(fake_volume, fake_connector)

        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.assert_called_once_with(
            LUNNAA='fakeLunNaa')
        mock_api_return.unmap_lun.assert_called_once_with(
            'fakeLunIndex', '9')


class QnapAPIExecutorTestCase(QnapDriverBaseTestCase):
    """Tests QnapAPIExecutor."""

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_create_lun(
            self,
            mock_http_connection):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')

        self.assertEqual(
            'fakeLunIndex',
            self.driver.api_executor.create_lun(
                fake_volume, 'fakepool', 'fakeLun', 'False'))

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['FileIO'] = 'no'
        fake_params['LUNThinAllocate'] = '1'
        fake_params['LUNName'] = 'fakeLun'
        fake_params['LUNPath'] = 'fakeLun'
        fake_params['poolID'] = 'fakepool'
        fake_params['lv_ifssd'] = 'no'
        fake_params['LUNCapacity'] = 100
        fake_params['lv_threshold'] = '80'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}
        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        create_lun_url = (
            '/cgi-bin/disk/iscsi_lun_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', create_lun_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_delete_lun(
            self,
            mock_http_connection):
        """Test delete lun."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.delete_lun('fakeLunIndex')

        fake_params = {}
        fake_params['func'] = 'remove_lun'
        fake_params['run_background'] = '1'
        fake_params['ha_sync'] = '1'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        delete_lun_url = (
            '/cgi-bin/disk/iscsi_lun_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', delete_lun_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_specific_poolinfo(
            self,
            mock_http_connection):
        """Test get specific pool info."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakePoolInfoResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_specific_poolinfo('Pool1')

        fake_params = {}
        fake_params['store'] = 'poolInfo'
        fake_params['func'] = 'extra_get'
        fake_params['poolID'] = 'Pool1'
        fake_params['Pool_Info'] = '1'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}
        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        get_specific_poolinfo_url = (
            '/cgi-bin/disk/disk_manage.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_specific_poolinfo_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_create_target(
            self,
            mock_http_connection):
        """Test create target."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreatTargetResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.create_target('fakeTargetName', 'sca')
        fake_params = {}
        fake_params['func'] = 'add_target'
        fake_params['targetName'] = 'fakeTargetName'
        fake_params['targetAlias'] = 'fakeTargetName'
        fake_params['bTargetDataDigest'] = '0'
        fake_params['bTargetHeaderDigest'] = '0'
        fake_params['bTargetClusterEnable'] = '1'
        fake_params['controller_name'] = 'sca'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        create_target_url = (
            '/cgi-bin/disk/iscsi_target_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', create_target_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_add_target_init(
            self,
            mock_http_connection):
        """Test add target init."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.add_target_init(
            'fakeTargetIqn', 'fakeInitiatorIqn')

        fake_params = {}
        fake_params['func'] = 'add_init'
        fake_params['targetIQN'] = 'fakeTargetIqn'
        fake_params['initiatorIQN'] = 'fakeInitiatorIqn'
        fake_params['initiatorAlias'] = 'fakeInitiatorIqn'
        fake_params['bCHAPEnable'] = '0'
        fake_params['CHAPUserName'] = ''
        fake_params['CHAPPasswd'] = ''
        fake_params['bMutualCHAPEnable'] = '0'
        fake_params['mutualCHAPUserName'] = ''
        fake_params['mutualCHAPPasswd'] = ''
        fake_params['ha_sync'] = '1'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        add_target_init_url = (
            '/cgi-bin/disk/iscsi_target_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', add_target_init_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_map_lun(
            self,
            mock_http_connection):
        """Test map lun."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.map_lun(
            'fakeLunIndex', 'fakeTargetIndex')

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['targetIndex'] = 'fakeTargetIndex'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        map_lun_url = (
            '/cgi-bin/disk/iscsi_target_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', map_lun_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_unmap_lun(
            self,
            mock_http_connection):
        """Test unmap lun."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.unmap_lun(
            'fakeLunIndex', 'fakeTargetIndex')

        fake_params = {}
        fake_params['func'] = 'remove_lun'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['targetIndex'] = 'fakeTargetIndex'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}
        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        unmap_lun_url = (
            '/cgi-bin/disk/iscsi_target_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', unmap_lun_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_iscsi_portal_info(
            self,
            mock_http_connection):
        """Test get iscsi portal info."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_iscsi_portal_info()

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['iSCSI_portal'] = '1'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}
        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        get_iscsi_portal_info_url = (
            '/cgi-bin/disk/iscsi_portal_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_iscsi_portal_info_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_lun_info(
            self,
            mock_http_connection):
        """Test get lun info."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeLunInfoResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_lun_info()

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['lunList'] = '1'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)
        sanitized_params = urllib.parse.urlencode(sanitized_params)

        get_lun_info_url = (
            '/cgi-bin/disk/iscsi_portal_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_lun_info_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_snapshot_info(
            self,
            mock_http_connection):
        """Test get snapshot info."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeLunInfoResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_snapshot_info(
            lun_index='fakeLunIndex', snapshot_name='fakeSnapshotName')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['snapshot_list'] = '1'
        fake_params['snap_start'] = '0'
        fake_params['snap_count'] = '100'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        get_snapshot_info_url = (
            '/cgi-bin/disk/snapshot.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_snapshot_info_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_create_snapshot_api(
            self,
            mock_http_connection):
        """Test create snapshot api."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateSnapshotResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.create_snapshot_api(
            'fakeLunIndex', 'fakeSnapshotName')

        fake_params = {}
        fake_params['func'] = 'create_snapshot'
        fake_params['lunID'] = 'fakeLunIndex'
        fake_params['snapshot_name'] = 'fakeSnapshotName'
        fake_params['expire_min'] = '0'
        fake_params['vital'] = '1'
        fake_params['snapshot_type'] = '0'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        create_snapshot_api_url = (
            '/cgi-bin/disk/snapshot.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', create_snapshot_api_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_api_delete_snapshot(
            self,
            mock_http_connection):
        """Test api de;ete snapshot."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateSnapshotResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.api_delete_snapshot(
            'fakeSnapshotId')
        fake_params = {}
        fake_params['func'] = 'del_snapshots'
        fake_params['snapshotID'] = 'fakeSnapshotId'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        api_delete_snapshot_url = (
            '/cgi-bin/disk/snapshot.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', api_delete_snapshot_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_clone_snapshot(
            self,
            mock_http_connection):
        """Test clone snapshot."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateSnapshotResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.clone_snapshot(
            'fakeSnapshotId', 'fakeLunName')

        fake_params = {}
        fake_params['func'] = 'clone_qsnapshot'
        fake_params['by_lun'] = '1'
        fake_params['snapshotID'] = 'fakeSnapshotId'
        fake_params['new_name'] = 'fakeLunName'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        clone_snapshot_url = (
            '/cgi-bin/disk/snapshot.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', clone_snapshot_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_edit_lun(
            self,
            mock_http_connection):
        """Test edit lun."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeLunInfoResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        fake_lun = {'LUNName': 'fakeLunName',
                    'LUNCapacity': 100,
                    'LUNIndex': 'fakeLunIndex',
                    'LUNThinAllocate': False,
                    'LUNPath': 'fakeLunPath',
                    'LUNStatus': 'fakeLunStatus'}
        self.driver.api_executor.edit_lun(fake_lun)

        fake_params = {}
        fake_params['func'] = 'edit_lun'
        fake_params['LUNName'] = 'fakeLunName'
        fake_params['LUNCapacity'] = 100
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['LUNThinAllocate'] = False
        fake_params['LUNPath'] = 'fakeLunPath'
        fake_params['LUNStatus'] = 'fakeLunStatus'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        edit_lun_url = (
            '/cgi-bin/disk/iscsi_lun_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', edit_lun_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_all_iscsi_portal_setting(
            self,
            mock_http_connection):
        """Test get all iscsi portal setting."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeLunInfoResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_all_iscsi_portal_setting()

        fake_params = {}
        fake_params['func'] = 'get_all'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        get_all_iscsi_portal_setting_url = (
            '/cgi-bin/disk/iscsi_portal_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_all_iscsi_portal_setting_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_ethernet_ip(
            self,
            mock_http_connection):
        """Test get ethernet ip."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeGetAllEthernetIp()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_ethernet_ip(type='data')

        fake_params = {}
        fake_params['subfunc'] = 'net_setting'
        fake_params['sid'] = 'fakeSid'
        sanitized_params = {}

        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        get_ethernet_ip_url = (
            '/cgi-bin/sys/sysRequest.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_ethernet_ip_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_target_info(
            self,
            mock_http_connection):
        """Test get target info."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeTargetInfo()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_target_info('fakeTargetIndex')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['targetInfo'] = 1
        fake_params['targetIndex'] = 'fakeTargetIndex'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}
        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        get_target_info_url = (
            '/cgi-bin/disk/iscsi_portal_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_target_info_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)


class QnapAPIExecutorTsTestCase(QnapDriverBaseTestCase):
    """Tests QnapAPIExecutorTS."""

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_remove_target_init(
            self,
            mock_http_connection):
        """Test remove target init."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeTargetInfo()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.remove_target_init(
            'fakeTargetIqn', 'fakeDefaultAcl')

        fake_params = {}
        fake_params['func'] = 'remove_init'
        fake_params['targetIQN'] = 'fakeTargetIqn'
        fake_params['initiatorIQN'] = 'fakeDefaultAcl'
        fake_params['ha_sync'] = '1'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}
        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        remove_target_init_url = (
            '/cgi-bin/disk/iscsi_target_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', remove_target_init_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_target_info(
            self,
            mock_http_connection):
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeTargetInfo()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_target_info(
            'fakeTargetIndex')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['targetInfo'] = 1
        fake_params['targetIndex'] = 'fakeTargetIndex'
        fake_params['ha_sync'] = '1'
        fake_params['sid'] = 'fakeSid'

        sanitized_params = {}
        for key in fake_params:
            value = fake_params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        get_target_info_url = (
            '/cgi-bin/disk/iscsi_portal_setting.cgi?%s' % sanitized_params)

        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_target_info_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_ethernet_ip(
            self,
            mock_http_connection):
        """Test get ethernet ip."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeGetAllEthernetIp()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_ethernet_ip(
            type='data')

        get_ethernet_ip_url = (
            '/cgi-bin/sys/sysRequest.cgi?subfunc=net_setting&sid=fakeSid')
        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_ethernet_ip_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)


class QnapAPIExecutorTesTestCase(QnapDriverBaseTestCase):
    """Tests QnapAPIExecutorTES."""

    @mock.patch('six.moves.http_client.HTTPConnection')
    def test_get_ethernet_ip(
            self,
            mock_http_connection):
        """Test get ehternet ip."""
        mock_http_connection.return_value.getresponse.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTesResponse(),
            FakeLoginResponse(),
            FakeGetAllEthernetIp()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_ethernet_ip(
            type='data')

        get_ethernet_ip_url = (
            '/cgi-bin/sys/sysRequest.cgi?subfunc=net_setting&sid=fakeSid')
        expected_call_list = [
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_basic_info_url),
            mock.call('POST', login_url, global_sanitized_params, header),
            mock.call('GET', get_ethernet_ip_url)]
        self.assertEqual(
            expected_call_list,
            mock_http_connection.return_value.request.call_args_list)
