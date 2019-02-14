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
from collections import OrderedDict

from ddt import data
from ddt import ddt
from ddt import unpack
from defusedxml import cElementTree as ET
import eventlet
import mock
from oslo_config import cfg
from oslo_utils import units
import requests
import six
from six.moves import urllib

from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers import qnap

CONF = cfg.CONF

FAKE_LUNNAA = {'LUNNAA': 'fakeLunNaa'}
FAKE_SNAPSHOT = {'snapshot_id': 'fakeSnapshotId'}

FAKE_PASSWORD = 'qnapadmin'
FAKE_PARMS = OrderedDict()
FAKE_PARMS['pwd'] = base64.b64encode(FAKE_PASSWORD.encode("utf-8"))
FAKE_PARMS['serviceKey'] = 1
FAKE_PARMS['user'] = 'admin'
sanitized_params = OrderedDict()

for key in FAKE_PARMS:
    value = FAKE_PARMS[key]
    if value is not None:
        sanitized_params[key] = six.text_type(value)
sanitized_params = utils.create_ordereddict(sanitized_params)
global_sanitized_params = urllib.parse.urlencode(sanitized_params)

header = {
    'charset': 'utf-8',
    'Content-Type': 'application/x-www-form-urlencoded'
}

login_url = '/cgi-bin/authLogin.cgi?'
fake_login_url = 'http://1.2.3.4:8080' + login_url

get_basic_info_url = '/cgi-bin/authLogin.cgi'
fake_get_basic_info_url = 'http://1.2.3.4:8080' + get_basic_info_url

FAKE_RES_DETAIL_DATA_LOGIN = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <authSid><![CDATA[fakeSid]]></authSid>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_NO_AUTHPASSED = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[0]]></authPassed>
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

FAKE_RES_DETAIL_DATA_GETBASIC_INFO_114 = """
    <QDocRoot version="1.0">
        <model>
            <displayModelName><![CDATA[ES1640dc]]></displayModelName>
            <internalModelName><![CDATA[ES1640dc]]></internalModelName>
        </model>
        <firmware>
            <version><![CDATA[1.1.4]]></version>
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

FAKE_RES_DETAIL_DATA_GETBASIC_INFO_TES_433 = """
    <QDocRoot version="1.0">
        <model>
            <displayModelName><![CDATA[TES-1885U]]></displayModelName>
            <internalModelName><![CDATA[TS-X85U]]></internalModelName>
        </model>
        <firmware>
            <version><![CDATA[4.3.3]]></version>
        </firmware>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_GETBASIC_INFO_UNSUPPORT = """
    <QDocRoot version="1.0">
        <model>
            <displayModelName><![CDATA[ES1640dc]]></displayModelName>
            <internalModelName><![CDATA[ES1640dc]]></internalModelName>
        </model>
        <firmware>
            <version><![CDATA[1.1.1]]></version>
        </firmware>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_GETBASIC_INFO_UNSUPPORT_TS = """
    <QDocRoot version="1.0">
        <model>
            <displayModelName><![CDATA[TS-870U-RP]]></displayModelName>
            <internalModelName><![CDATA[TS-879]]></internalModelName>
        </model>
        <firmware>
            <version><![CDATA[4.0.0]]></version>
        </firmware>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_GETBASIC_INFO_UNSUPPORT_TES = """
    <QDocRoot version="1.0">
        <model>
            <displayModelName><![CDATA[TES-1885U]]></displayModelName>
            <internalModelName><![CDATA[ES-X85U]]></internalModelName>
        </model>
        <firmware>
            <version><![CDATA[1.1.1]]></version>
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

FAKE_RES_DETAIL_DATA_LUN_INFO_FAIL = """
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
        <result><![CDATA[-1]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_SNAPSHOT_INFO = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <SnapshotList>
            <row>
                <snapshot_id>fakeSnapshotId</snapshot_id>
                <snapshot_name>fakeSnapshotName</snapshot_name>
            </row>
        </SnapshotList>
        <ErrorList></ErrorList>
        <result>0</result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_SNAPSHOT_INFO_FAIL = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <SnapshotList>
            <row>
                <snapshot_id>fakeSnapshotId</snapshot_id>
                <snapshot_name>fakeSnapshotName</snapshot_name>
            </row>
        </SnapshotList>
        <ErrorList></ErrorList>
        <result>-1</result>
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

FAKE_RES_DETAIL_DATA_ONE_LUN_INFO = """
<QDocRoot version="1.0">
    <authPassed><![CDATA[1]]></authPassed>
    <LUNInfo>
        <row>
            <LUNIndex><![CDATA[fakeLunIndex]]></LUNIndex>
            <LUNName><![CDATA[fakeLunName]]></LUNName>
            <LUNPath><![CDATA[fakeLunPath]]></LUNPath>
            <LUNStatus><![CDATA[1]]></LUNStatus>
            <LUNThinAllocate><![CDATA[fakeLunThinAllocate]]></LUNThinAllocate>
            <LUNNAA><![CDATA[fakeLunNaa]]></LUNNAA>
            <LUNTargetList/>
        </row>
    </LUNInfo>
    <result><![CDATA[0]]></result>
</QDocRoot>"""

FAKE_RES_DETAIL_DATA_MAPPED_ONE_LUN_INFO = """
<QDocRoot version="1.0">
    <authPassed><![CDATA[1]]></authPassed>
    <LUNInfo>
        <row>
            <LUNIndex><![CDATA[fakeLunIndex]]></LUNIndex>
            <LUNName><![CDATA[fakeLunName]]></LUNName>
            <LUNPath><![CDATA[fakeLunPath]]></LUNPath>
            <LUNStatus><![CDATA[2]]></LUNStatus>
            <LUNThinAllocate><![CDATA[fakeLunThinAllocate]]></LUNThinAllocate>
            <LUNNAA><![CDATA[fakeLunNaa]]></LUNNAA>
            <LUNTargetList>
              <row>
                <targetIndex><![CDATA[9]]></targetIndex>
                <LUNNumber><![CDATA[1]]></LUNNumber>
                <LUNEnable><![CDATA[1]]></LUNEnable>
              </row>
            </LUNTargetList>
        </row>
    </LUNInfo>
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

FAKE_RES_DETAIL_DATA_SNAPSHOT_WITHOUT_SNAPSHOT = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <SnapshotList>
            <row>
                <snapshot_id><![CDATA[fakeSnapshotId]]></snapshot_id>
            </row>
        </SnapshotList>
        <result><![CDATA[-206021]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_SNAPSHOT_WITHOUT_LUN = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <SnapshotList>
            <row>
                <snapshot_id><![CDATA[fakeSnapshotId]]></snapshot_id>
            </row>
        </SnapshotList>
        <result><![CDATA[-200005]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_SNAPSHOT_FAIL = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <SnapshotList>
            <row>
                <snapshot_id><![CDATA[fakeSnapshotId]]></snapshot_id>
            </row>
        </SnapshotList>
        <result><![CDATA[-1]]></result>
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

FAKE_RES_DETAIL_DATA_SPECIFIC_POOL_INFO_FAIL = """
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
        <result><![CDATA[-1]]></result>
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
                <IPInfo>
                    <interfaceSlotid><![CDATA[0]]></interfaceSlotid>
                    <isManagePort><![CDATA[1]]></isManagePort>
                    <IP>
                        <IP1><![CDATA[1]]></IP1>
                        <IP2><![CDATA[2]]></IP2>
                        <IP3><![CDATA[3]]></IP3>
                        <IP4><![CDATA[4]]></IP4>
                    </IP>
                    <status><![CDATA[1]]></status>
                </IPInfo>
                <IPInfo>
                    <interfaceSlotid><![CDATA[0]]></interfaceSlotid>
                    <isManagePort><![CDATA[0]]></isManagePort>
                    <IP>
                        <IP1><![CDATA[1]]></IP1>
                        <IP2><![CDATA[2]]></IP2>
                        <IP3><![CDATA[3]]></IP3>
                        <IP4><![CDATA[4]]></IP4>
                    </IP>
                    <status><![CDATA[1]]></status>
                </IPInfo>
                <IPInfo>
                    <interfaceSlotid><![CDATA[0]]></interfaceSlotid>
                    <isManagePort><![CDATA[1]]></isManagePort>
                    <IP>
                        <IP1><![CDATA[1]]></IP1>
                        <IP2><![CDATA[2]]></IP2>
                        <IP3><![CDATA[3]]></IP3>
                        <IP4><![CDATA[4]]></IP4>
                    </IP>
                    <status><![CDATA[0]]></status>
                </IPInfo>
            </ownContent>
         </func>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_CREATE_LUN = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <result><![CDATA[fakeLunIndex]]></result>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_CREATE_LUN_FAIL = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <result><![CDATA[-1]]></result>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_CREATE_LUN_BUSY = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <result><![CDATA[-205041]]></result>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_CREATE_TARGET = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <result><![CDATA[fakeTargetIndex]]></result>
     </QDocRoot>"""

FAKE_RES_DETAIL_DATA_CREATE_TARGET_FAIL = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <result><![CDATA[-1]]></result>
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
                <targetIQN active="1"><![CDATA[fakeTargetIqn]]></targetIQN>
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
                <targetIndex><![CDATA[fakeTargetIndex]]></targetIndex>
                <targetName><![CDATA[fakeTargetName]]></targetName>
                <targetIQN active="1"><![CDATA[fakeTargetIqn]]></targetIQN>
                <targetStatus><![CDATA[1]]></targetStatus>
            </row>
        </targetInfo>
        <result><![CDATA[0]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_TARGET_INFO_FAIL = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <targetInfo>
            <row>
                <targetIndex><![CDATA[fakeTargetIndex]]></targetIndex>
                <targetName><![CDATA[fakeTargetName]]></targetName>
                <targetIQN active="1"><![CDATA[fakeTargetIqn]]></targetIQN>
                <targetStatus><![CDATA[1]]></targetStatus>
            </row>
        </targetInfo>
        <result><![CDATA[-1]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_TARGET_INFO_BY_INITIATOR = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <targetACL>
            <row>
                <targetIndex><![CDATA[fakeTargetIndex]]></targetIndex>
                <targetName><![CDATA[fakeTargetName]]></targetName>
                <targetIQN><![CDATA[fakeTargetIqn]]></targetIQN>
                <targetAlias><![CDATA[fakeTargetAlias]]></targetAlias>
                <targetStatus><![CDATA[1]]></targetStatus>
            </row>
        </targetACL>
        <result><![CDATA[0]]></result>
    </QDocRoot>"""

FAKE_RES_DETAIL_DATA_TARGET_INFO_BY_INITIATOR_FAIL = """
    <QDocRoot version="1.0">
        <authPassed><![CDATA[1]]></authPassed>
        <targetACL>
            <row>
                <targetIndex><![CDATA[fakeTargetIndex]]></targetIndex>
                <targetName><![CDATA[fakeTargetName]]></targetName>
                <targetIQN><![CDATA[fakeTargetIqn]]></targetIQN>
                <targetAlias><![CDATA[fakeTargetAlias]]></targetAlias>
                <targetStatus><![CDATA[1]]></targetStatus>
            </row>
        </targetACL>
        <result><![CDATA[-1]]></result>
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
        thin_provision=True,
        compression=True,
        deduplication=False,
        ssd_cache=False,
        verify_ssl=True):
    """Create configuration."""
    configuration = mock.Mock()
    configuration.san_login = username
    configuration.san_password = password
    configuration.qnap_management_url = management_url
    configuration.san_thin_provision = thin_provision
    configuration.qnap_compression = compression
    configuration.qnap_deduplication = deduplication
    configuration.qnap_ssd_cache = ssd_cache
    configuration.san_iscsi_ip = san_iscsi_ip
    configuration.qnap_poolname = poolname
    configuration.safe_get.return_value = 'QNAP'
    configuration.target_ip_address = '1.2.3.4'
    configuration.qnap_storage_protocol = 'iscsi'
    configuration.reserved_percentage = 0
    configuration.use_chap_auth = False
    configuration.driver_ssl_cert_verify = verify_ssl
    return configuration


class QnapDriverBaseTestCase(test.TestCase):
    """Base Class for the QnapDriver Tests."""

    def setUp(self):
        """Setup the Qnap Driver Base TestCase."""
        super(QnapDriverBaseTestCase, self).setUp()
        self.driver = None
        self.mock_session = None

    @staticmethod
    def sanitize(params):
        sanitized = {_key: six.text_type(_value)
                     for _key, _value in six.iteritems(params)
                     if _value is not None}
        sanitized = utils.create_ordereddict(sanitized)
        return urllib.parse.urlencode(sanitized)


class SnapshotClass(object):
    """Snapshot Class."""

    volume = {}
    name = ''
    volume_name = ''
    volume_size = 0
    metadata = {}

    def __init__(self, volume, volume_size):
        """Init."""
        self.volume = volume
        self.volume_size = volume_size
        self.metadata = {'snapshot_id': 'fakeSnapshotId'}

    def __getitem__(self, arg):
        """Getitem."""
        return {
            'display_name': 'fakeSnapshotDisplayName',
            'id': 'fakeSnapshotId',
            'volume_size': self.volume_size,
            'metadata': self.metadata
        }[arg]

    def __contains__(self, arg):
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
    volume_metadata = []

    def __init__(self, display_name, id, size, name):
        """Init."""
        self.display_name = display_name
        self.id = id
        self.size = size
        self.name = name
        self.volume_metadata = [{'key': 'LUNNAA', 'value': 'fakeLunNaa'},
                                {'key': 'LUNIndex', 'value': 'fakeLunIndex'}]
        self.metadata = {'LUNNAA': 'fakeLunNaa',
                         'LUNIndex': 'fakeLunIndex'}
        self.provider_location = '%(host)s:%(port)s,1 %(name)s %(tgt_lun)s' % {
            'host': '1.2.3.4',
            'port': '3260',
            'name': 'fakeTargetIqn',
            'tgt_lun': '1'
        }
        self.volume_type = {
            'extra_specs': {
                'qnap_thin_provision': 'True',
                'qnap_compression': 'True',
                'qnap_deduplication': 'False',
                'qnap_ssd_cache': 'False'
            }
        }

    def __getitem__(self, arg):
        """Getitem."""
        return {
            'display_name': self.display_name,
            'size': self.size,
            'id': self.id,
            'name': self.name,
            'volume_metadata': self.volume_metadata,
            'metadata': self.metadata,
            'provider_location': self.provider_location,
            'volume_type': self.volume_type
        }[arg]

    def __contains__(self, arg):
        """Getitem."""
        return {
            'display_name': self.display_name,
            'size': self.size,
            'id': self.id,
            'name': self.name,
            'volume_metadata': self.volume_metadata,
            'metadata': self.metadata,
            'provider_location': self.provider_location,
            'volume_type': self.volume_type
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

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_LOGIN


class FakeNoAuthPassedResponse(object):
    """Fake no auth passed response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_NO_AUTHPASSED


class FakeGetBasicInfoResponse(object):
    """Fake GetBasicInfo response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO


class FakeGetBasicInfo114Response(object):
    """Fake GetBasicInfo114 response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_114


class FakeGetBasicInfoTsResponse(object):
    """Fake GetBasicInfoTs response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_TS


class FakeGetBasicInfoTesResponse(object):
    """Fake GetBasicInfoTes response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_TES


class FakeGetBasicInfoTes433Response(object):
    """Fake GetBasicInfoTes response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_TES_433


class FakeGetBasicInfoUnsupportResponse(object):
    """Fake GetBasicInfoUnsupport response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_UNSUPPORT


class FakeGetBasicInfoUnsupportTsResponse(object):
    """Fake GetBasicInfoUnsupportTs response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_UNSUPPORT_TS


class FakeGetBasicInfoUnsupportTesResponse(object):
    """Fake GetBasicInfoUnsupportTes response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_GETBASIC_INFO_UNSUPPORT_TES


class FakeLunInfoResponse(object):
    """Fake lun info response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_LUN_INFO


class FakeLunInfoFailResponse(object):
    """Fake lun info response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_LUN_INFO_FAIL


class FakeSnapshotInfoResponse(object):
    """Fake snapshot info response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_SNAPSHOT_INFO


class FakeSnapshotInfoFailResponse(object):
    """Fake snapshot info response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_SNAPSHOT_INFO_FAIL


class FakeOneLunInfoResponse(object):
    """Fake one lun info response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.read."""
        return FAKE_RES_DETAIL_DATA_ONE_LUN_INFO


class FakeMappedOneLunInfoResponse(object):
    """Fake one lun info response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_MAPPED_ONE_LUN_INFO


class FakePoolInfoResponse(object):
    """Fake pool info response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_SPECIFIC_POOL_INFO


class FakePoolInfoFailResponse(object):
    """Fake pool info response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_SPECIFIC_POOL_INFO_FAIL


class FakeCreateLunResponse(object):
    """Fake create lun response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_CREATE_LUN


class FakeCreateLunFailResponse(object):
    """Fake create lun response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_CREATE_LUN_FAIL


class FakeCreateLunBusyResponse(object):
    """Fake create lun response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_CREATE_LUN_BUSY


class FakeCreateTargetResponse(object):
    """Fake create target response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_CREATE_TARGET


class FakeCreateTargetFailResponse(object):
    """Fake create target response."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_CREATE_TARGET_FAIL


class FakeGetIscsiPortalInfoResponse(object):
    """Fake get iscsi portal inforesponse."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_ISCSI_PORTAL_INFO

    def __repr__(self):
        """Repr."""
        return six.StringIO(FAKE_RES_DETAIL_DATA_ISCSI_PORTAL_INFO)


class FakeCreateSnapshotResponse(object):
    """Fake Create snapshot inforesponse."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_SNAPSHOT


class FakeCreateSnapshotWithoutSnapshotResponse(object):
    """Fake Create snapshot inforesponse."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_SNAPSHOT_WITHOUT_SNAPSHOT


class FakeCreateSnapshotWithoutLunResponse(object):
    """Fake Create snapshot inforesponse."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_SNAPSHOT_WITHOUT_LUN


class FakeCreateSnapshotFailResponse(object):
    """Fake Create snapshot inforesponse."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_SNAPSHOT_FAIL


class FakeGetAllIscsiPortalSetting(object):
    """Fake get all iSCSI portal setting."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_GET_ALL_ISCSI_PORTAL_SETTING


class FakeGetAllEthernetIp(object):
    """Fake get all ethernet ip setting."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_ETHERNET_IP


class FakeTargetInfo(object):
    """Fake target info setting."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_TARGET_INFO


class FakeTargetInfoFail(object):
    """Fake target info setting."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_TARGET_INFO_FAIL


class FakeTargetInfoByInitiator(object):
    """Fake target info setting."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_TARGET_INFO_BY_INITIATOR


class FakeTargetInfoByInitiatorFail(object):
    """Fake target info setting."""

    status_code = 'fackStatus'

    @property
    def text(self):
        """Mock response.text."""
        return FAKE_RES_DETAIL_DATA_TARGET_INFO_BY_INITIATOR_FAIL


@ddt
class QnapDriverLoginTestCase(QnapDriverBaseTestCase):
    """Tests do_setup api."""

    def setUp(self):
        """Setup the Qnap Share Driver login TestCase."""
        super(QnapDriverLoginTestCase, self).setUp()
        self.mock_object(requests, 'request')

    @data({'mng_url': 'http://1.2.3.4:8080', 'port': '8080', 'ssl': False,
          'get_basic_info_response': FakeGetBasicInfoResponse()},
          {'mng_url': 'https://1.2.3.4:443', 'port': '443', 'ssl': True,
           'get_basic_info_response': FakeGetBasicInfoResponse()},
          {'mng_url': 'http://1.2.3.4:8080', 'port': '8080', 'ssl': False,
           'get_basic_info_response': FakeGetBasicInfoTsResponse()},
          {'mng_url': 'https://1.2.3.4:443', 'port': '443', 'ssl': True,
           'get_basic_info_response': FakeGetBasicInfoTsResponse()},
          {'mng_url': 'http://1.2.3.4:8080', 'port': '8080', 'ssl': False,
           'get_basic_info_response': FakeGetBasicInfoTesResponse()},
          {'mng_url': 'https://1.2.3.4:443', 'port': '443', 'ssl': True,
           'get_basic_info_response': FakeGetBasicInfoTesResponse()},
          {'mng_url': 'http://1.2.3.4:8080', 'port': '8080', 'ssl': False,
           'get_basic_info_response': FakeGetBasicInfoTes433Response()},
          {'mng_url': 'https://1.2.3.4:443', 'port': '443', 'ssl': True,
           'get_basic_info_response': FakeGetBasicInfoTes433Response()}
          )
    @unpack
    def test_do_setup_positive(self, mng_url, port,
                               ssl, get_basic_info_response):
        """Test do_setup with http://1.2.3.4:8080."""
        fake_login_response = FakeLoginResponse()
        fake_get_basic_info_response = get_basic_info_response
        mock_request = requests.request
        mock_request.side_effect = ([
            fake_login_response,
            fake_get_basic_info_response,
            fake_login_response])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin', 'qnapadmin', mng_url,
                '1.2.3.4', 'Storage Pool 1', True, verify_ssl=ssl))
        self.driver.do_setup('context')

        self.assertEqual('fakeSid', self.driver.api_executor.sid)
        self.assertEqual('admin', self.driver.api_executor.username)
        self.assertEqual('qnapadmin', self.driver.api_executor.password)
        self.assertEqual('1.2.3.4', self.driver.api_executor.ip)
        self.assertEqual(port, self.driver.api_executor.port)
        self.assertEqual(ssl, self.driver.api_executor.ssl)

    @data({'mng_url': 'http://1.2.3.4:8080', 'port': '8080', 'ssl': False},
          {'mng_url': 'https://1.2.3.4:443', 'port': '443', 'ssl': True})
    @unpack
    def test_do_setup_negative_with_configuration_not_set(self, mng_url,
                                                          port, ssl):
        """Test do_setup with http://1.2.3.4:8080."""
        fake_login_response = FakeLoginResponse()
        fake_get_basic_info_response = FakeGetBasicInfoResponse()
        mock_request = requests.request
        mock_request.side_effect = ([
            fake_login_response,
            fake_get_basic_info_response,
            fake_login_response])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin', 'qnapadmin', mng_url,
                '1.2.3.4', 'Storage Pool 1', True, verify_ssl=ssl))

        del self.driver.configuration.qnap_management_url
        self.assertRaises(exception.InvalidInput,
                          self.driver.do_setup, 'context')

    @data({'mng_url': 'http://1.2.3.4:8080', 'port': '8080', 'ssl': False,
           'get_basic_info_response': FakeGetBasicInfoUnsupportTsResponse()},
          {'mng_url': 'https://1.2.3.4:443', 'port': '443', 'ssl': True,
           'get_basic_info_response': FakeGetBasicInfoUnsupportTsResponse()})
    @unpack
    def test_do_setup_negative_with_unsupport_nas(self, mng_url, port, ssl,
                                                  get_basic_info_response):
        """Test do_setup with http://1.2.3.4:8080."""
        fake_login_response = FakeLoginResponse()
        fake_get_basic_info_response = get_basic_info_response
        mock_request = requests.request
        mock_request.side_effect = ([
            fake_login_response,
            fake_get_basic_info_response,
            fake_login_response])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin', 'qnapadmin', mng_url,
                '1.2.3.4', 'Storage Pool 1', True, verify_ssl=ssl))
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, 'context')

    @data({'mng_url': 'http://1.2.3.4:8080', 'port': '8080', 'ssl': False},
          {'mng_url': 'https://1.2.3.4:443', 'port': '443', 'ssl': True})
    @unpack
    def test_check_for_setup_error(self, mng_url, port, ssl):
        """Test check_for_setup_error."""
        fake_login_response = FakeLoginResponse()
        fake_get_basic_info_response = FakeGetBasicInfoResponse()
        mock_request = requests.request
        mock_request.side_effect = ([
            fake_login_response,
            fake_get_basic_info_response,
            fake_login_response])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin', 'qnapadmin', mng_url,
                '1.2.3.4', 'Storage Pool 1', True, verify_ssl=ssl))
        self.driver.do_setup('context')
        self.driver.check_for_setup_error()

        self.assertEqual('fakeSid', self.driver.api_executor.sid)
        self.assertEqual('admin', self.driver.api_executor.username)
        self.assertEqual('qnapadmin', self.driver.api_executor.password)
        self.assertEqual('1.2.3.4', self.driver.api_executor.ip)
        self.assertEqual(port, self.driver.api_executor.port)
        self.assertEqual(ssl, self.driver.api_executor.ssl)


@ddt
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

    def get_one_lun_info_return_value(self):
        """Return the lun form get_one_lun_info method."""
        fake_one_lun_info_response = FakeOneLunInfoResponse()
        ret = {'data': fake_one_lun_info_response.text,
               'error': None,
               'http_status': fake_one_lun_info_response.status_code}
        return ret

    def get_mapped_one_lun_info_return_value(self):
        """Return the lun form get_one_lun_info method."""
        fake_mapped_one_lun_info_response = FakeMappedOneLunInfoResponse()
        ret = {'data': fake_mapped_one_lun_info_response.text,
               'error': None,
               'http_status': fake_mapped_one_lun_info_response.status_code}
        return ret

    def get_snapshot_info_return_value(self):
        """Return the lun form get_lun_info method."""
        root = ET.fromstring(FAKE_RES_DETAIL_DATA_SNAPSHOT)

        snapshot_list = root.find('SnapshotList')
        snapshot_info_tree = snapshot_list.findall('row')
        for snapshot in snapshot_info_tree:
            return snapshot

    def get_target_info_return_value(self):
        """Return the target form get_target_info method."""
        root = ET.fromstring(FAKE_RES_DETAIL_DATA_TARGET_INFO)

        target_info = root.find('targetInfo/row')
        return target_info

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
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.side_effect = [
            None,
            self.get_lun_info_return_value()]
        mock_gen_random_name.return_value = 'fakeLun'
        mock_api_return.create_lun.return_value = 'fakeIndex'
        mock_get_volume_metadata.return_value = {}

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.mock_object(eventlet, 'sleep')
        self.driver.do_setup('context')
        self.driver.create_volume(fake_volume)

        mock_api_return.create_lun.assert_called_once_with(
            fake_volume,
            self.driver.configuration.qnap_poolname,
            'fakeLun',
            True, False, True, False)

        expected_call_list = [
            mock.call(LUNName='fakeLun'),
            mock.call(LUNIndex='fakeIndex')]
        self.assertEqual(
            expected_call_list,
            mock_api_return.get_lun_info.call_args_list)

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_delete_volume_positive_without_mapped_lun(
            self,
            mock_api_executor,
            mock_get_lun_naa_from_volume_metadata):
        """Test delete_volume with fake_volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_one_lun_info.return_value = (
            self.get_one_lun_info_return_value())
        mock_api_return.delete_lun.return_value = None

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

        mock_api_return.delete_lun.assert_called_once_with(
            'fakeLunIndex')

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_delete_volume_positive_with_mapped_lun(
            self,
            mock_api_executor,
            mock_get_lun_naa_from_volume_metadata):
        """Test delete_volume with fake_volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_one_lun_info.return_value = (
            self.get_mapped_one_lun_info_return_value())
        mock_api_return.delete_lun.return_value = None

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

        mock_api_return.delete_lun.assert_called_once_with(
            'fakeLunIndex')

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_delete_volume_negative_without_lun_naa(
            self,
            mock_api_executor,
            mock_get_lun_naa_from_volume_metadata):
        """Test delete_volume with fake_volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_get_lun_naa_from_volume_metadata.return_value = ''
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_one_lun_info.return_value = (
            self.get_one_lun_info_return_value())
        mock_api_return.delete_lun.return_value = None

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

    @mock.patch.object(
        qnap.QnapISCSIDriver, '_get_lun_naa_from_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_create_snapshot_name')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch.object(qnap.QnapISCSIDriver, '_get_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_cloned_volume_volume_size_less_src_verf(
            self,
            mock_api_executor,
            mock_get_volume_metadata,
            mock_gen_random_name,
            mock_create_snapshot_name,
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
        mock_gen_random_name.return_value = 'fakeLun'
        mock_create_snapshot_name.return_value = 'fakeSnapshot'
        mock_api_executor.return_value.get_snapshot_info.return_value = (
            self.get_snapshot_info_return_value())
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
        self.mock_object(eventlet, 'sleep')
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
        self.mock_object(eventlet, 'sleep')
        self.driver.do_setup('context')
        self.driver.create_cloned_volume(fake_volume, fake_src_vref)

        mock_extend_lun.assert_called_once_with(fake_volume, 'fakeLunNaa')

    @mock.patch.object(qnap.QnapISCSIDriver, '_create_snapshot_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_snapshot_positive(
            self,
            mock_api_executor,
            mock_create_snapshot_name):
        """Test create snapshot."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        snapshot = SnapshotClass(fake_volume, 100)

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_executor.return_value.get_lun_info.return_value = (
            self.get_lun_info_return_value())
        mock_create_snapshot_name.return_value = 'fakeSnapshot'
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
        self.mock_object(eventlet, 'sleep')
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
            mock_api_return.get_snapshot_info.call_args_list)
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
        mock_api_return = mock_api_executor.return_value
        mock_api_return.delete_snapshot_api.return_value = None

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

        mock_api_return.delete_snapshot_api.assert_called_once_with(
            'fakeSnapshotId')

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_delete_snapshot_negative(
            self,
            mock_api_executor):
        """Test delete snapshot."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_snapshot = SnapshotClass(fake_volume, 100)

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return = mock_api_executor.return_value
        mock_api_return.delete_snapshot_api.return_value = None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        fake_snapshot.metadata.pop('snapshot_id', None)
        self.driver.delete_snapshot(fake_snapshot)

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
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.side_effect = [
            None,
            self.get_lun_info_return_value()]
        mock_api_return.clone_snapshot.return_value = None

        mock_api_return.create_snapshot_api.return_value = (
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
        self.mock_object(eventlet, 'sleep')
        self.driver.do_setup('context')
        self.driver.create_volume_from_snapshot(fake_volume, fake_snapshot)

        expected_call_list = [
            mock.call(LUNName='fakeLun'),
            mock.call(LUNName='fakeLun')]
        self.assertEqual(
            expected_call_list,
            mock_api_return.get_lun_info.call_args_list)

        mock_api_return.clone_snapshot.assert_called_once_with(
            'fakeSnapshotId', 'fakeLun')
        mock_extend_lun.assert_called_once_with(fake_volume, 'fakeLunNaa')

    @mock.patch.object(qnap.QnapISCSIDriver, '_get_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_extend_lun')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_volume_from_snapshot_negative(
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
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.side_effect = [
            None,
            self.get_lun_info_return_value()]
        mock_api_return.clone_snapshot.return_value = None

        mock_api_return.create_snapshot_api.return_value = (
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
        fake_snapshot.metadata.pop('snapshot_id', None)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume_from_snapshot,
                          fake_volume, fake_snapshot)

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
        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return = mock_api_executor.return_value
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
        self.driver.VERSION = 'fakeVersion'

        expected_res = {'volume_backend_name': 'QNAP',
                        'vendor_name': 'QNAP',
                        'driver_version': 'fakeVersion',
                        'storage_protocol': 'iscsi'}
        single_pool = dict(
            pool_name=self.driver.configuration.qnap_poolname,
            total_capacity_gb=930213412209 / units.Gi,
            free_capacity_gb=928732941681 / units.Gi,
            provisioned_capacity_gb=1480470528 / units.Gi,
            reserved_percentage=self.driver.configuration.reserved_percentage,
            QoS_support=False,
            qnap_thin_provision=['True', 'False'],
            qnap_compression=['True', 'False'],
            qnap_deduplication=['True', 'False'],
            qnap_ssd_cache=['True', 'False'])
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
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.return_value = (
            self.get_lun_info_return_value())
        mock_api_return.edit_lun.return_value = None

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
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_export_positive_without_multipath(
            self,
            mock_api_executor,
            mock_gen_random_name,
            mock_get_lun_naa_from_volume_metadata):
        """Test create export."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn'}

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.return_value = (
            self.get_lun_info_return_value())
        mock_api_return.get_iscsi_portal_info.return_value = (
            FAKE_RES_DETAIL_ISCSI_PORTAL_INFO)
        mock_gen_random_name.return_value = 'fakeTargetName'
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_return.create_target.return_value = 'fakeTargetIndex'
        mock_api_return.get_target_info.return_value = (
            self.get_target_info_return_value())
        mock_api_return.map_lun.return_value = None
        mock_api_return.get_ethernet_ip.return_value = ['1.2.3.4'], None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.configuration.use_chap_auth = False
        self.driver.configuration.chap_username = ''
        self.driver.configuration.chap_password = ''
        self.driver.iscsi_port = 'fakeServicePort'
        self.mock_object(eventlet, 'sleep')
        self.driver.do_setup('context')

        expected_properties = '%(host)s:%(port)s,1 %(name)s %(tgt_lun)s' % {
            'host': '1.2.3.4',
            'port': 'fakeServicePort',
            'name': 'fakeTargetIqn',
            'tgt_lun': '1'}
        expected_return = {
            'provider_location': expected_properties, 'provider_auth': None}

        self.assertEqual(expected_return, self.driver.create_export(
            'context', fake_volume, fake_connector))

    @mock.patch.object(qnap.QnapISCSIDriver,
                       '_get_lun_naa_from_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_export_positive_with_multipath(
            self,
            mock_api_executor,
            mock_gen_random_name,
            mock_get_lun_naa_from_volume_metadata):
        """Test create export."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn', 'multipath': True}

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.return_value = (
            self.get_lun_info_return_value())
        mock_api_return.get_iscsi_portal_info.return_value = (
            FAKE_RES_DETAIL_ISCSI_PORTAL_INFO)
        mock_gen_random_name.return_value = 'fakeTargetName'
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_return.create_target.return_value = 'fakeTargetIndex'
        mock_api_return.get_target_info.return_value = (
            self.get_target_info_return_value())
        mock_api_return.map_lun.return_value = None
        mock_api_return.get_ethernet_ip.return_value = ['1.2.3.4'], None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.configuration.use_chap_auth = False
        self.driver.configuration.chap_username = ''
        self.driver.configuration.chap_password = ''
        self.driver.iscsi_port = 'fakeServicePort'
        self.mock_object(eventlet, 'sleep')
        self.driver.do_setup('context')

        expected_properties = '%(host)s:%(port)s,1 %(name)s %(tgt_lun)s' % {
            'host': '1.2.3.4',
            'port': 'fakeServicePort',
            'name': 'fakeTargetIqn',
            'tgt_lun': '1'}
        expected_return = {
            'provider_location': expected_properties, 'provider_auth': None}

        self.assertEqual(expected_return, self.driver.create_export(
            'context', fake_volume, fake_connector))

    @mock.patch.object(qnap.QnapISCSIDriver,
                       '_get_lun_naa_from_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_export_114(
            self,
            mock_api_executor,
            mock_gen_random_name,
            mock_get_lun_naa_from_volume_metadata):
        """Test create export."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn'}

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.4')
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_one_lun_info.return_value = (
            self.get_mapped_one_lun_info_return_value())
        mock_api_return.get_iscsi_portal_info.return_value = (
            FAKE_RES_DETAIL_ISCSI_PORTAL_INFO)
        mock_gen_random_name.return_value = 'fakeTargetName'
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_return.create_target.return_value = 'fakeTargetIndex'
        mock_api_return.get_target_info.return_value = (
            self.get_target_info_return_value())
        mock_api_return.add_target_init.return_value = None
        mock_api_return.map_lun.return_value = None
        mock_api_return.get_ethernet_ip.return_value = ['1.2.3.4'], None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.configuration.use_chap_auth = False
        self.driver.configuration.chap_username = ''
        self.driver.configuration.chap_password = ''
        self.driver.iscsi_port = 'fakeServicePort'
        self.mock_object(eventlet, 'sleep')
        self.driver.do_setup('context')

        expected_properties = '%(host)s:%(port)s,1 %(name)s %(tgt_lun)s' % {
            'host': '1.2.3.4',
            'port': 'fakeServicePort',
            'name': 'fakeTargetIqn',
            'tgt_lun': '1'}
        expected_return = {
            'provider_location': expected_properties, 'provider_auth': None}

        self.assertEqual(expected_return, self.driver.create_export(
            'context', fake_volume, fake_connector))

    @mock.patch.object(qnap.QnapISCSIDriver,
                       '_get_lun_naa_from_volume_metadata')
    @mock.patch.object(qnap.QnapISCSIDriver, '_gen_random_name')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutorTS')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_export_positive_ts(
            self,
            mock_api_executor,
            mock_api_executor_ts,
            mock_gen_random_name,
            mock_get_lun_naa_from_volume_metadata):
        """Test create export."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn'}
        mock_api_executor.return_value.get_basic_info.return_value = (
            'TS-870U-RP ', 'TS-870U-RP ', '4.3.0')
        mock_api_executor_ts.return_value.get_basic_info.return_value = (
            'TS-870U-RP ', 'TS-870U-RP ', '4.3.0')
        mock_api_return = mock_api_executor_ts.return_value
        mock_api_return.get_one_lun_info.return_value = (
            self.get_mapped_one_lun_info_return_value())
        mock_api_return.get_iscsi_portal_info.return_value = (
            FAKE_RES_DETAIL_ISCSI_PORTAL_INFO)
        mock_gen_random_name.return_value = 'fakeTargetName'
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_return.create_target.return_value = 'fakeTargetIndex'
        mock_api_return.get_target_info.return_value = (
            self.get_target_info_return_value())
        mock_api_return.map_lun.return_value = None
        mock_api_return.get_ethernet_ip.return_value = ['1.2.3.4'], None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.configuration.use_chap_auth = False
        self.driver.configuration.chap_username = ''
        self.driver.configuration.chap_password = ''
        self.driver.iscsi_port = 'fakeServicePort'
        self.mock_object(eventlet, 'sleep')
        self.driver.do_setup('context')

        expected_properties = '%(host)s:%(port)s,1 %(name)s %(tgt_lun)s' % {
            'host': '1.2.3.4',
            'port': 'fakeServicePort',
            'name': 'fakeTargetIqn',
            'tgt_lun': '1'}
        expected_return = {
            'provider_location': expected_properties, 'provider_auth': None}

        self.assertEqual(expected_return, self.driver.create_export(
            'context', fake_volume, fake_connector))

    @mock.patch.object(qnap.QnapISCSIDriver,
                       '_get_lun_naa_from_volume_metadata')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_create_export_negative_without_lun_naa(
            self,
            mock_api_executor,
            mock_get_lun_naa_from_volume_metadata):
        """Test create export."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn'}

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        # mock_api_return = mock_api_executor.return_value
        mock_get_lun_naa_from_volume_metadata.return_value = ''

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.iscsi_port = 'fakeServicePort'
        self.driver.do_setup('context')

        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_export,
                          'context', fake_volume, fake_connector)

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

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_iscsi_portal_info.return_value = (
            FAKE_RES_DETAIL_ISCSI_PORTAL_INFO)
        mock_get_lun_naa_from_volume_metadata.return_value = 'fakeLunNaa'
        mock_api_return.get_lun_info.side_effect = [
            self.get_lun_info_return_value(),
            self.get_lun_info_return_value()]
        mock_api_return.get_all_iscsi_portal_setting.return_value = (
            FAKE_RES_DETAIL_GET_ALL_ISCSI_PORTAL_SETTING)
        mock_api_return.map_lun.return_value = None
        mock_api_return.get_ethernet_ip.return_value = ['1.2.3.4'], None

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.configuration.use_chap_auth = False
        self.driver.configuration.chap_username = ''
        self.driver.configuration.chap_password = ''
        self.driver.iscsi_port = 'fakeServicePort'
        self.driver.do_setup('context')

        expected_properties = {
            'target_discovered': False,
            'target_portal': '1.2.3.4:fakeServicePort',
            'target_iqn': 'fakeTargetIqn',
            'target_lun': 1,
            'volume_id': fake_volume['id']}
        expected_return = {
            'driver_volume_type': 'iscsi', 'data': expected_properties}

        self.assertEqual(expected_return, self.driver.initialize_connection(
            fake_volume, fake_connector))

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_initialize_connection_with_target_exist_negative_no_provider(
            self,
            mock_api_executor):
        """Test initialize connection."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn'}

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

        fake_volume.provider_location = None
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.initialize_connection,
                          fake_volume, fake_connector)

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_initialize_connection_with_target_exist_negative_wrong_provider_1(
            self,
            mock_api_executor):
        """Test initialize connection."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn'}

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

        fake_volume.provider_location = (
            '%(host)s:%(port)s,1%(name)s%(tgt_lun)s' % {
                'host': '1.2.3.4',
                'port': '3260',
                'name': 'fakeTargetIqn',
                'tgt_lun': '1'
            })
        self.assertRaises(exception.InvalidInput,
                          self.driver.initialize_connection,
                          fake_volume, fake_connector)

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_initialize_connection_with_target_exist_negative_wrong_provider_2(
            self, mock_api_executor):
        """Test initialize connection."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiatorIqn'}

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

        fake_volume.provider_location = (
            '%(host)s:%(port)s1 %(name)s %(tgt_lun)s' % {
                'host': '1.2.3.4',
                'port': '3260',
                'name': 'fakeTargetIqn',
                'tgt_lun': '1'
            })
        self.assertRaises(exception.InvalidInput,
                          self.driver.initialize_connection,
                          fake_volume, fake_connector)

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_terminate_connection_positive_with_lun_mapped(
            self,
            mock_api_executor):
        """Test terminate connection."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiator'}

        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.return_value = (
            self.get_mapped_lun_info_return_value())
        mock_api_return.unmap_lun.return_value = None

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

        mock_api_return.get_lun_info.assert_called_once_with(
            LUNIndex='fakeLunIndex')
        mock_api_return.unmap_lun.assert_called_once_with(
            'fakeLunIndex', '9')

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_terminate_connection_positive_without_lun_mapped(
            self,
            mock_api_executor):
        """Test terminate connection."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_connector = {'initiator': 'fakeInitiator'}
        mock_api_executor.return_value.get_basic_info.return_value = (
            'ES1640dc ', 'ES1640dc ', '1.1.3')
        mock_api_return = mock_api_executor.return_value
        mock_api_return.get_lun_info.return_value = (
            self.get_lun_info_return_value())
        mock_api_return.unmap_lun.return_value = None

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

        mock_api_return.get_lun_info.assert_called_once_with(
            LUNIndex='fakeLunIndex')

    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_update_migrated_volume(
            self,
            mock_api_executor):
        """Test update migrated volume."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')
        fake_new_volume = VolumeClass(
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
        self.driver.update_migrated_volume('context',
                                           fake_volume, fake_new_volume,
                                           'fakeOriginalVolumeStatus')

    @data({
        'fake_spec': {},
        'expect_spec': {
            'force': False,
            'ignore_errors': False,
            'remote': False
        }
    }, {
        'fake_spec': {
            'force': mock.sentinel.force,
            'ignore_errors': mock.sentinel.ignore_errors,
            'remote': mock.sentinel.remote
        },
        'expect_spec': {
            'force': mock.sentinel.force,
            'ignore_errors': mock.sentinel.ignore_errors,
            'remote': mock.sentinel.remote
        }
    })
    @unpack
    @mock.patch.object(driver.BaseVD, '_detach_volume')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_detach_volume(
            self,
            mock_api_executor,
            mock_detach_volume,
            fake_spec, expect_spec):
        """Test detach volume."""

        mock_detach_volume.return_value = None
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
        self.driver._detach_volume('context',
                                   'attach_info', 'volume',
                                   'property', **fake_spec)
        mock_detach_volume.assert_called_once_with(
            'context', 'attach_info', 'volume', 'property', **expect_spec)

    @mock.patch.object(driver.BaseVD, '_attach_volume')
    @mock.patch('cinder.volume.drivers.qnap.QnapAPIExecutor')
    def test_attach_volume(
            self,
            mock_api_executor,
            mock_attach_volume):
        """Test attach volume."""

        mock_attach_volume.return_value = None
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
        self.driver._attach_volume('context', 'volume', 'properties')
        mock_attach_volume.assert_called_once_with(
            'context', 'volume', 'properties', False)


class QnapAPIExecutorEsTestCase(QnapDriverBaseTestCase):
    """Tests QnapAPIExecutor."""

    @mock.patch('requests.request')
    def test_create_lun_positive_with_thin_allocate(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
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
                fake_volume, 'fakepool', 'fakeLun', True, False, True, False))

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['FileIO'] = 'no'
        fake_params['LUNThinAllocate'] = '1'
        fake_params['LUNName'] = 'fakeLun'
        fake_params['LUNPath'] = 'fakeLun'
        fake_params['poolID'] = 'fakepool'
        fake_params['lv_ifssd'] = 'no'
        fake_params['compression'] = '1'
        fake_params['dedup'] = 'off'
        fake_params['LUNCapacity'] = 100
        fake_params['lv_threshold'] = '80'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)

        create_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_lun_positive_without_thin_allocate(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
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
                fake_volume, 'fakepool', 'fakeLun', False, False, True, False))

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['FileIO'] = 'no'
        fake_params['LUNThinAllocate'] = '0'
        fake_params['LUNName'] = 'fakeLun'
        fake_params['LUNPath'] = 'fakeLun'
        fake_params['poolID'] = 'fakepool'
        fake_params['lv_ifssd'] = 'no'
        fake_params['compression'] = '1'
        fake_params['dedup'] = 'off'
        fake_params['LUNCapacity'] = 100
        fake_params['lv_threshold'] = '80'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)

        create_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_lun_negative(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_lun,
                          fake_volume, 'fakepool', 'fakeLun', 'False',
                          'False', 'True', 'False')

    @mock.patch('requests.request')
    def test_create_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_lun,
                          fake_volume, 'fakepool', 'fakeLun', 'False',
                          'False', 'True', 'False')

    @mock.patch('requests.request')
    def test_delete_lun(
            self,
            mock_request):
        """Test delete lun."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)

        delete_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', delete_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_delete_lun_negative(self, mock_request):
        """Test delete lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.delete_lun,
                          'fakeLunIndex')

    @mock.patch('requests.request')
    def test_delete_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test delete lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.delete_lun,
                          'fakeLunIndex')

    @mock.patch('requests.request')
    def test_delete_lun_positive_with_busy_result(
            self,
            mock_request):
        """Test delete lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunBusyResponse()])

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

        fake_post_params = self.sanitize(fake_params)

        delete_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', delete_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_specific_poolinfo(
            self,
            mock_request):
        """Test get specific pool info."""
        mock_request.side_effect = ([
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
        self.driver.api_executor.get_specific_poolinfo('fakePoolId')

        fake_params = {}
        fake_params['store'] = 'poolInfo'
        fake_params['func'] = 'extra_get'
        fake_params['poolID'] = 'fakePoolId'
        fake_params['Pool_Info'] = '1'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)

        get_specific_poolinfo_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/disk_manage.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_specific_poolinfo_url, data=None,
                      headers=None, verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_specific_poolinfo_negative(
            self,
            mock_request):
        """Test get specific pool info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_specific_poolinfo,
                          'Pool1')

    @mock.patch('requests.request')
    def test_get_specific_poolinfo_negative_with_wrong_result(
            self,
            mock_request):
        """Test get specific pool info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakePoolInfoFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_specific_poolinfo,
                          'Pool1')

    @mock.patch('requests.request')
    def test_create_target(
            self,
            mock_request):
        """Test create target."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateTargetResponse()])

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

        fake_post_params = self.sanitize(fake_params)
        create_target_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_target_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_target_negative(
            self,
            mock_request):
        """Test create target."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_target,
                          'fakeTargetName', 'sca')

    @mock.patch('requests.request')
    def test_create_target_negative_with_wrong_result(
            self,
            mock_request):
        """Test create target."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateTargetFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_target,
                          'fakeTargetName', 'sca')

    @mock.patch('requests.request')
    def test_add_target_init(self, mock_request):
        """Test add target init."""
        mock_request.side_effect = ([
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
            'fakeTargetIqn', 'fakeInitiatorIqn', False, '', '')

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

        fake_post_params = self.sanitize(fake_params)

        add_target_init_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', add_target_init_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_add_target_init_negative(
            self,
            mock_request):
        """Test add target init."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.add_target_init,
                          'fakeTargetIqn', 'fakeInitiatorIqn', False, '', '')

    @mock.patch('requests.request')
    def test_add_target_init_negative_with_wrong_result(
            self,
            mock_request):
        """Test add target init."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.add_target_init,
                          'fakeTargetIqn', 'fakeInitiatorIqn', False, '', '')

    @mock.patch('requests.request')
    def test_remove_target_init(
            self,
            mock_request):
        """Test add target init."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.remove_target_init(
            'fakeTargetIqn', 'fakeInitiatorIqn')

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_map_lun(
            self,
            mock_request):
        """Test map lun."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)
        map_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', map_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_map_lun_negative(
            self,
            mock_request):
        """Test map lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.map_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_map_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test map lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.map_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_disable_lun(
            self,
            mock_request):
        """Test disable lun."""
        mock_request.side_effect = ([
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
        self.driver.api_executor.disable_lun(
            'fakeLunIndex', 'fakeTargetIndex')

        fake_params = {}
        fake_params['func'] = 'edit_lun'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['targetIndex'] = 'fakeTargetIndex'
        fake_params['LUNEnable'] = 0
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        unmap_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', unmap_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_disable_lun_negative(self, mock_request):
        """Test disable lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.disable_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_disable_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test disable lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.disable_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_unmap_lun(
            self,
            mock_request):
        """Test unmap lun."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)
        unmap_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', unmap_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_unmap_lun_negative(
            self,
            mock_request):
        """Test unmap lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.unmap_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_unmap_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test unmap lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.unmap_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_get_iscsi_portal_info(
            self,
            mock_request):
        """Test get iscsi portal info."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)
        get_iscsi_portal_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_iscsi_portal_info_url, data=None,
                      headers=None, verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_iscsi_portal_info_negative(
            self,
            mock_request):
        """Test get iscsi portal info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_iscsi_portal_info)

    @mock.patch('requests.request')
    def test_get_lun_info(self, mock_request):
        """Test get lun info."""
        mock_request.side_effect = ([
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
        fake_post_params = self.sanitize(fake_params)

        get_lun_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_lun_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_lun_info_positive_with_lun_index(
            self,
            mock_request):
        """Test get lun info."""
        mock_request.side_effect = ([
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
        self.driver.api_executor.get_lun_info(LUNIndex='fakeLunIndex')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['lunList'] = '1'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)

        get_lun_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_lun_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_lun_info_positive_with_lun_name(
            self,
            mock_request):
        """Test get lun info."""
        mock_request.side_effect = ([
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
        self.driver.api_executor.get_lun_info(LUNName='fakeLunName')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['lunList'] = '1'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)

        get_lun_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_lun_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_lun_info_positive_with_lun_naa(
            self,
            mock_request):
        """Test get lun info."""
        mock_request.side_effect = ([
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
        self.driver.api_executor.get_lun_info(LUNNAA='fakeLunNaa')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['lunList'] = '1'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)

        get_lun_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_lun_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_lun_info_negative(
            self,
            mock_request):
        """Test get lun info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_lun_info)

    @mock.patch('requests.request')
    def test_get_one_lun_info(
            self,
            mock_request):
        """Test get one lun info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeOneLunInfoResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_one_lun_info('fakeLunId')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['lun_info'] = '1'
        fake_params['lunID'] = 'fakeLunId'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)

        get_lun_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_lun_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_one_lun_info_negative(
            self,
            mock_request):
        """Test get one lun info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_one_lun_info,
                          'fakeLunId')

    @mock.patch('requests.request')
    def test_get_snapshot_info(
            self,
            mock_request):
        """Test get snapshot info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeSnapshotInfoResponse()])

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
        fake_post_params = self.sanitize(fake_params)
        get_snapshot_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/snapshot.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_snapshot_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_snapshot_info_negative(
            self,
            mock_request):
        """Test get snapshot info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_snapshot_info,
                          lun_index='fakeLunIndex',
                          snapshot_name='fakeSnapshotName')

    @mock.patch('requests.request')
    def test_get_snapshot_info_negative_with_wrong_result(
            self,
            mock_request):
        """Test get snapshot info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeSnapshotInfoFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_snapshot_info,
                          lun_index='fakeLunIndex',
                          snapshot_name='fakeSnapshotName')

    @mock.patch('requests.request')
    def test_create_snapshot_api(
            self,
            mock_request):
        """Test create snapshot api."""
        mock_request.side_effect = ([
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
        fake_post_params = self.sanitize(fake_params)
        create_snapshot_api_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/snapshot.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_snapshot_api_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_snapshot_api_negative(
            self,
            mock_request):
        """Test create snapshot api."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_snapshot_api,
                          'fakeLunIndex', 'fakeSnapshotName')

    @mock.patch('requests.request')
    def test_create_snapshot_api_negative_with_wrong_result(
            self,
            mock_request):
        """Test create snapshot api."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateSnapshotFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_snapshot_api,
                          'fakeLunIndex', 'fakeSnapshotName')

    @mock.patch('requests.request')
    def test_delete_snapshot_api(
            self,
            mock_request):
        """Test api delete snapshot."""
        mock_request.side_effect = ([
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
        self.driver.api_executor.delete_snapshot_api(
            'fakeSnapshotId')
        fake_params = {}
        fake_params['func'] = 'del_snapshots'
        fake_params['snapshotID'] = 'fakeSnapshotId'
        fake_params['sid'] = 'fakeSid'
        fake_post_params = self.sanitize(fake_params)
        api_delete_snapshot_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/snapshot.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', api_delete_snapshot_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_delete_snapshot_api_positive_without_snapshot(
            self,
            mock_request):
        """Test api de;ete snapshot."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateSnapshotWithoutSnapshotResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.delete_snapshot_api(
            'fakeSnapshotId')
        fake_params = {}
        fake_params['func'] = 'del_snapshots'
        fake_params['snapshotID'] = 'fakeSnapshotId'
        fake_params['sid'] = 'fakeSid'
        fake_post_params = self.sanitize(fake_params)
        api_delete_snapshot_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/snapshot.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', api_delete_snapshot_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_delete_snapshot_api_positive_without_lun(
            self,
            mock_request):
        """Test api de;ete snapshot."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateSnapshotWithoutLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.delete_snapshot_api(
            'fakeSnapshotId')
        fake_params = {}
        fake_params['func'] = 'del_snapshots'
        fake_params['snapshotID'] = 'fakeSnapshotId'
        fake_params['sid'] = 'fakeSid'
        fake_post_params = self.sanitize(fake_params)
        api_delete_snapshot_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/snapshot.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', api_delete_snapshot_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_delete_snapshot_api_negative(
            self,
            mock_request):
        """Test api de;ete snapshot."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.delete_snapshot_api,
                          'fakeSnapshotId')

    @mock.patch('requests.request')
    def test_delete_snapshot_api_negative_with_wrong_result(
            self,
            mock_request):
        """Test api de;ete snapshot."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateSnapshotFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.delete_snapshot_api,
                          'fakeSnapshotId')

    @mock.patch('requests.request')
    def test_clone_snapshot(
            self,
            mock_request):
        """Test clone snapshot."""
        mock_request.side_effect = ([
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
        fake_post_params = self.sanitize(fake_params)
        clone_snapshot_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/snapshot.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', clone_snapshot_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_clone_snapshot_negative(
            self,
            mock_request):
        """Test clone snapshot."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.clone_snapshot,
                          'fakeSnapshotId', 'fakeLunName')

    @mock.patch('requests.request')
    def test_clone_snapshot_negative_with_wrong_result(
            self,
            mock_request):
        """Test clone snapshot."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeCreateSnapshotFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.clone_snapshot,
                          'fakeSnapshotId', 'fakeLunName')

    @mock.patch('requests.request')
    def test_edit_lun(
            self,
            mock_request):
        """Test edit lun."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)
        edit_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', edit_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_edit_lun_negative(
            self,
            mock_request):
        """Test edit lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

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
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.edit_lun,
                          fake_lun)

    @mock.patch('requests.request')
    def test_edit_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test edit lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeLunInfoFailResponse()])

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
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.edit_lun,
                          fake_lun)

    @mock.patch('requests.request')
    def test_get_all_iscsi_portal_setting(
            self,
            mock_request):
        """Test get all iscsi portal setting."""
        mock_request.side_effect = ([
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
        fake_post_params = self.sanitize(fake_params)
        get_all_iscsi_portal_setting_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_all_iscsi_portal_setting_url, data=None,
                      headers=None, verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_ethernet_ip_with_type_data(
            self,
            mock_request):
        """Test get ethernet ip."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)
        get_ethernet_ip_url = (
            'http://1.2.3.4:8080/cgi-bin/sys/sysRequest.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_ethernet_ip_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_ethernet_ip_with_type_manage(
            self,
            mock_request):
        """Test get ethernet ip."""
        mock_request.side_effect = ([
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
        self.driver.api_executor.get_ethernet_ip(type='manage')

        fake_params = {}
        fake_params['subfunc'] = 'net_setting'
        fake_params['sid'] = 'fakeSid'
        fake_post_params = self.sanitize(fake_params)
        get_ethernet_ip_url = (
            'http://1.2.3.4:8080/cgi-bin/sys/sysRequest.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_ethernet_ip_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_ethernet_ip_with_type_all(self, mock_request):
        """Test get ethernet ip."""
        mock_request.side_effect = ([
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
        self.driver.api_executor.get_ethernet_ip(type='all')

        fake_params = {}
        fake_params['subfunc'] = 'net_setting'
        fake_params['sid'] = 'fakeSid'
        fake_post_params = self.sanitize(fake_params)
        get_ethernet_ip_url = (
            'http://1.2.3.4:8080/cgi-bin/sys/sysRequest.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_ethernet_ip_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_ethernet_ip_negative(
            self,
            mock_request):
        """Test get ethernet ip."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_ethernet_ip,
                          type='data')

    @mock.patch('requests.request')
    def test_get_target_info(
            self,
            mock_request):
        """Test get target info."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)
        get_target_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_target_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_target_info_negative(
            self,
            mock_request):
        """Test get target info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_target_info,
                          'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_get_target_info_negative_with_wrong_result(
            self,
            mock_request):
        """Test get target info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoResponse(),
            FakeLoginResponse(),
            FakeTargetInfoFail()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_target_info,
                          'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_get_target_info_by_initiator(
            self,
            mock_request):
        """Test get target info by initiator."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfo114Response(),
            FakeLoginResponse(),
            FakeTargetInfoByInitiator()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_target_info_by_initiator(
            'fakeInitiatorIQN')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['initiatorIQN'] = 'fakeInitiatorIQN'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        get_target_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_target_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_target_info_by_initiator_negative(
            self,
            mock_request):
        """Test get target info by initiator."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfo114Response(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.
                          get_target_info_by_initiator,
                          'fakeInitiatorIQN')

    @mock.patch('requests.request')
    def test_get_target_info_by_initiator_with_wrong_result(
            self,
            mock_request):
        """Test get target info by initiator."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfo114Response(),
            FakeLoginResponse(),
            FakeTargetInfoByInitiatorFail()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_target_info_by_initiator(
            'fakeInitiatorIQN')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['initiatorIQN'] = 'fakeInitiatorIQN'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        get_target_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_target_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)


class QnapAPIExecutorTsTestCase(QnapDriverBaseTestCase):
    """Tests QnapAPIExecutorTS."""

    @mock.patch('requests.request')
    def test_create_lun_positive_with_thin_allocate(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')

        self.assertEqual(
            'fakeLunIndex',
            self.driver.api_executor.create_lun(
                fake_volume, 'fakepool', 'fakeLun', True, False, True, False))

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['FileIO'] = 'no'
        fake_params['LUNThinAllocate'] = '1'
        fake_params['LUNName'] = 'fakeLun'
        fake_params['LUNPath'] = 'fakeLun'
        fake_params['poolID'] = 'fakepool'
        fake_params['lv_ifssd'] = 'no'
        fake_params['LUNCapacity'] = 100
        fake_params['LUNSectorSize'] = '512'
        fake_params['lv_threshold'] = '80'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        create_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_lun_positive_without_thin_allocate(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')

        self.assertEqual(
            'fakeLunIndex',
            self.driver.api_executor.create_lun(
                fake_volume, 'fakepool', 'fakeLun', False, False, True, False))

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['FileIO'] = 'no'
        fake_params['LUNThinAllocate'] = '0'
        fake_params['LUNName'] = 'fakeLun'
        fake_params['LUNPath'] = 'fakeLun'
        fake_params['poolID'] = 'fakepool'
        fake_params['lv_ifssd'] = 'no'
        fake_params['LUNCapacity'] = 100
        fake_params['LUNSectorSize'] = '512'
        fake_params['lv_threshold'] = '80'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        create_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_lun_negative(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_lun,
                          fake_volume, 'fakepool', 'fakeLun', 'False',
                          'False', 'True', 'False')

    @mock.patch('requests.request')
    def test_create_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_lun,
                          fake_volume, 'fakepool', 'fakeLun', 'False',
                          'False', 'True', 'False')

    @mock.patch('requests.request')
    def test_delete_lun(
            self,
            mock_request):
        """Test delete lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.delete_lun('fakeLunIndex')

        fake_params = {}
        fake_params['func'] = 'remove_lun'
        fake_params['run_background'] = '1'
        fake_params['ha_sync'] = '1'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        delete_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', delete_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_delete_lun_negative(
            self,
            mock_request):
        """Test delete lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.delete_lun,
                          'fakeLunIndex')

    @mock.patch('requests.request')
    def test_delete_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test delete lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.delete_lun,
                          'fakeLunIndex')

    @mock.patch('requests.request')
    def test_delete_lun_positive_with_busy_result(
            self,
            mock_request):
        """Test delete lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunBusyResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.delete_lun('fakeLunIndex')

        fake_params = {}
        fake_params['func'] = 'remove_lun'
        fake_params['run_background'] = '1'
        fake_params['ha_sync'] = '1'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        delete_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', delete_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_map_lun(
            self,
            mock_request):
        """Test map lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.map_lun(
            'fakeLunIndex', 'fakeTargetIndex')

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['targetIndex'] = 'fakeTargetIndex'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        map_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', map_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_map_lun_negative(
            self,
            mock_request):
        """Test map lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.map_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_map_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test map lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.map_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_disable_lun(
            self,
            mock_request):
        """Test disable lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.disable_lun(
            'fakeLunIndex', 'fakeTargetIndex')

        fake_params = {}
        fake_params['func'] = 'edit_lun'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['targetIndex'] = 'fakeTargetIndex'
        fake_params['LUNEnable'] = 0
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        unmap_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', unmap_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_disable_lun_negative(
            self,
            mock_request):
        """Test disable lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.disable_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_disable_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test disable lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.disable_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_unmap_lun(
            self,
            mock_request):
        """Test unmap lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.unmap_lun(
            'fakeLunIndex', 'fakeTargetIndex')

        fake_params = {}
        fake_params['func'] = 'remove_lun'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['targetIndex'] = 'fakeTargetIndex'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        unmap_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', unmap_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_unmap_lun_negative(
            self,
            mock_request):
        """Test unmap lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.unmap_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_unmap_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test unmap lun."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.unmap_lun,
                          'fakeLunIndex', 'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_remove_target_init(
            self,
            mock_request):
        """Test remove target init."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)
        remove_target_init_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', remove_target_init_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_remove_target_init_negative(
            self,
            mock_request):
        """Test remove target init."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.remove_target_init,
                          'fakeTargetIqn', 'fakeDefaultAcl')

    @mock.patch('requests.request')
    def test_remove_target_init_negative_with_wrong_result(
            self, mock_request):
        """Test remove target init."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeTargetInfoFail()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.remove_target_init,
                          'fakeTargetIqn', 'fakeDefaultAcl')

    @mock.patch('requests.request')
    def test_get_target_info(
            self, mock_request):
        """Test get get target info."""
        mock_request.side_effect = ([
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

        fake_post_params = self.sanitize(fake_params)
        get_target_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_portal_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_target_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_target_info_negative(
            self,
            mock_request):
        """Test get get target info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_target_info,
                          'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_get_target_info_negative_with_wrong_result(
            self,
            mock_request):
        """Test get get target info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeTargetInfoFail()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_target_info,
                          'fakeTargetIndex')

    @mock.patch('requests.request')
    def test_get_ethernet_ip_with_type(
            self,
            mock_request):
        """Test get ethernet ip."""
        mock_request.side_effect = ([
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

        fake_post_parm = 'sid=fakeSid&subfunc=net_setting'
        get_ethernet_ip_url = (
            'http://1.2.3.4:8080/cgi-bin/sys/sysRequest.cgi?' + fake_post_parm)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_ethernet_ip_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_ethernet_ip_negative(self, mock_request):
        """Test get ethernet ip."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_ethernet_ip,
                          type='data')

    @mock.patch('requests.request')
    def test_get_snapshot_info(
            self,
            mock_request):
        """Test get snapshot info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeSnapshotInfoResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.driver.api_executor.get_snapshot_info(
            lun_index='fakeLunIndex', snapshot_name='fakeSnapshotName')

        fake_params = {}
        fake_params['func'] = 'extra_get'
        fake_params['LUNIndex'] = 'fakeLunIndex'
        fake_params['smb_snapshot_list'] = '1'
        fake_params['smb_snapshot'] = '1'
        fake_params['snapshot_list'] = '1'
        fake_params['sid'] = 'fakeSid'
        fake_post_params = self.sanitize(fake_params)
        get_snapshot_info_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/snapshot.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_snapshot_info_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_snapshot_info_negative(
            self,
            mock_request):
        """Test get snapshot info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_snapshot_info,
                          lun_index='fakeLunIndex',
                          snapshot_name='fakeSnapshotName')

    @mock.patch('requests.request')
    def test_get_snapshot_info_negative_with_wrong_result(
            self,
            mock_request):
        """Test get snapshot info."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeSnapshotInfoFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_snapshot_info,
                          lun_index='fakeLunIndex',
                          snapshot_name='fakeSnapshotName')

    @mock.patch('requests.request')
    def test_create_target(
            self,
            mock_request):
        """Test create target."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateTargetResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
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
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        create_target_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_target_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_target_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_target_negative(
            self,
            mock_request):
        """Test create target."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_target,
                          'fakeTargetName', 'sca')

    @mock.patch('requests.request')
    def test_create_target_negative_with_wrong_result(
            self,
            mock_request):
        """Test create target."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTsResponse(),
            FakeLoginResponse(),
            FakeCreateTargetFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Storage Pool 1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_target,
                          'fakeTargetName', 'sca')


class QnapAPIExecutorTesTestCase(QnapDriverBaseTestCase):
    """Tests QnapAPIExecutorTES."""

    @mock.patch('requests.request')
    def test_create_lun_positive_with_thin_allocate(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTesResponse(),
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
                fake_volume, 'fakepool', 'fakeLun', True, False, True, False))

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['FileIO'] = 'no'
        fake_params['LUNThinAllocate'] = '1'
        fake_params['LUNName'] = 'fakeLun'
        fake_params['LUNPath'] = 'fakeLun'
        fake_params['poolID'] = 'fakepool'
        fake_params['lv_ifssd'] = 'no'
        fake_params['compression'] = '1'
        fake_params['dedup'] = 'off'
        fake_params['sync'] = 'disabled'
        fake_params['LUNCapacity'] = 100
        fake_params['lv_threshold'] = '80'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        create_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_lun_positive_without_thin_allocate(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTesResponse(),
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
                fake_volume, 'fakepool', 'fakeLun', False, False, True, False))

        fake_params = {}
        fake_params['func'] = 'add_lun'
        fake_params['FileIO'] = 'no'
        fake_params['LUNThinAllocate'] = '0'
        fake_params['LUNName'] = 'fakeLun'
        fake_params['LUNPath'] = 'fakeLun'
        fake_params['poolID'] = 'fakepool'
        fake_params['lv_ifssd'] = 'no'
        fake_params['compression'] = '1'
        fake_params['dedup'] = 'off'
        fake_params['sync'] = 'disabled'
        fake_params['LUNCapacity'] = 100
        fake_params['lv_threshold'] = '80'
        fake_params['sid'] = 'fakeSid'

        fake_post_params = self.sanitize(fake_params)
        create_lun_url = (
            'http://1.2.3.4:8080/cgi-bin/disk/iscsi_lun_setting.cgi?' +
            fake_post_params)

        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', create_lun_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_create_lun_negative(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTesResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_lun,
                          fake_volume, 'fakepool', 'fakeLun', 'False',
                          'False', 'True', 'False')

    @mock.patch('requests.request')
    def test_create_lun_negative_with_wrong_result(
            self,
            mock_request):
        """Test create lun."""
        fake_volume = VolumeClass(
            'fakeDisplayName', 'fakeId', 100, 'fakeLunName')

        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTesResponse(),
            FakeLoginResponse(),
            FakeCreateLunFailResponse()])

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.create_lun,
                          fake_volume, 'fakepool', 'fakeLun', 'False',
                          'False', 'True', 'False')

    @mock.patch('requests.request')
    def test_get_ethernet_ip_with_type(
            self,
            mock_request):
        """Test get ehternet ip."""
        mock_request.side_effect = ([
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

        fake_post_parm = 'sid=fakeSid&subfunc=net_setting'
        get_ethernet_ip_url = (
            'http://1.2.3.4:8080/cgi-bin/sys/sysRequest.cgi?' + fake_post_parm)
        expected_call_list = [
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', fake_get_basic_info_url, data=None, headers=None,
                      verify=False),
            mock.call('POST', fake_login_url, data=global_sanitized_params,
                      headers=header, verify=False),
            mock.call('GET', get_ethernet_ip_url, data=None, headers=None,
                      verify=False)]
        self.assertEqual(expected_call_list, mock_request.call_args_list)

    @mock.patch('requests.request')
    def test_get_ethernet_ip_negative(
            self,
            mock_request):
        """Test get ethernet ip."""
        mock_request.side_effect = ([
            FakeLoginResponse(),
            FakeGetBasicInfoTesResponse(),
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] + [
            FakeLoginResponse(),
            FakeNoAuthPassedResponse()] * 4)

        self.driver = qnap.QnapISCSIDriver(
            configuration=create_configuration(
                'admin',
                'qnapadmin',
                'http://1.2.3.4:8080',
                '1.2.3.4',
                'Pool1',
                True))
        self.driver.do_setup('context')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.api_executor.get_ethernet_ip,
                          type='data')
