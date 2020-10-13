#    (c) Copyright 2016 Brocade Communications Systems Inc.
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
#

"""Unit tests for brcd fc zone client http(s)."""
import time
from unittest import mock
from unittest.mock import patch

from oslo_utils import encodeutils

from cinder.tests.unit import test
from cinder.zonemanager.drivers.brocade import (brcd_http_fc_zone_client
                                                as client)
from cinder.zonemanager.drivers.brocade import exception as b_exception
import cinder.zonemanager.drivers.brocade.fc_zone_constants as zone_constant


cfgs = {'openstack_cfg': 'zone1;zone2'}
cfgs_to_delete = {
    'openstack_cfg': 'zone1;zone2;openstack50060b0000c26604201900051ee8e329'}
zones = {'zone1': '20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11',
         'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11'}

zones_to_delete = {
    'zone1': '20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11',
    'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11',
    'openstack50060b0000c26604201900051ee8e329':
    '50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29'}

alias = {}
qlps = {}
ifas = {}
parsed_raw_zoneinfo = ""
random_no = ''
auth_version = ''
session = None
active_cfg = 'openstack_cfg'
activate = True
no_activate = False
vf_enable = True
ns_info = ['10:00:00:05:1e:7c:64:96']
nameserver_info = """
<HTML>
<HEAD>
<META HTTP-EQUIV="Pragma" CONTENT="no-cache">
<META HTTP-EQUIV="Expires" CONTENT="-1">
<TITLE>NSInfo Page</TITLE>
</HEAD>
<BODY>
<PRE>
--BEGIN DEVICEPORT 10:00:00:05:1e:7c:64:96
node.wwn=20:00:00:05:1e:7c:64:96
deviceport.portnum=9
deviceport.portid=300900
deviceport.portIndex=9
deviceport.porttype=N
deviceport.portwwn=10:00:00:05:1e:7c:64:96
--END DEVICEPORT 10:00:00:05:1e:7c:64:96
</PRE>
</BODY>
</HTML>
"""
mocked_zone_string = 'zonecfginfo=openstack_cfg zone1;zone2 '\
    'zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 '\
    'zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 '\
    'alia1 10:00:00:05:1e:7c:64:96;10:21:10:05:33:0e:96:12 '\
    'qlp 10:11:f4:ce:46:ae:68:6c;20:11:f4:ce:46:ae:68:6c '\
    'fa1 20:15:f4:ce:96:ae:68:6c;20:11:f4:ce:46:ae:68:6c '\
    'openstack_cfg null &saveonly=false'
mocked_zone_string_no_activate = 'zonecfginfo=openstack_cfg zone1;zone2 '\
    'zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 '\
    'zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 '\
    'alia1 10:00:00:05:1e:7c:64:96;10:21:10:05:33:0e:96:12 '\
    'qlp 10:11:f4:ce:46:ae:68:6c;20:11:f4:ce:46:ae:68:6c '\
    'fa1 20:15:f4:ce:96:ae:68:6c;20:11:f4:ce:46:ae:68:6c &saveonly=true'
zone_string_to_post = "zonecfginfo=openstack_cfg "\
    "openstack50060b0000c26604201900051ee8e329;zone1;zone2 "\
    "openstack50060b0000c26604201900051ee8e329 "\
    "50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29 "\
    "zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 "\
    "zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 "\
    "openstack_cfg null &saveonly=false"
zone_string_to_post_no_activate = "zonecfginfo=openstack_cfg "\
    "openstack50060b0000c26604201900051ee8e329;zone1;zone2 "\
    "openstack50060b0000c26604201900051ee8e329 "\
    "50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29 " \
    "zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 "\
    "zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 "\
    "&saveonly=true"
zone_string_to_post_invalid_request = "zonecfginfo=openstack_cfg "\
    "openstack50060b0000c26604201900051ee8e32900000000000000000000000000;"\
    "zone1;zone2 "\
    "openstack50060b0000c26604201900051ee8e329000000000000000000000"\
    "00000 50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29 "\
    "zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 "\
    "zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 &saveonly=true"
zone_string_del_to_post = "zonecfginfo=openstack_cfg zone1;zone2"\
    " zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 "\
    "zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 "\
    "openstack_cfg null &saveonly=false"
zone_string_del_to_post_no_active = "zonecfginfo=openstack_cfg zone1;zone2"\
    " zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 " \
    "zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 "\
    "&saveonly=true"
zone_post_page = """
<BODY>
<PRE>
--BEGIN ZONE_TXN_INFO
txnId=34666
adId=0
user=admin
roleUser=admin
openTxnOwner=
openTxnId=0
openTxnAbortable=0
txnStarttime=1421916354
txnEndtime=1421916355
currStateInt=4
prevStateInt=3
actionInt=5
currState=done
prevState=progress
action=error
sessionId=5892021
selfAborted=false
status=done
errorCode=-1
errorMessage=Name too long
--END ZONE_TXN_INFO
</PRE>
</BODY>"""
zone_post_page_no_error = """
<BODY>
<PRE>
--BEGIN ZONE_TXN_INFO
txnId=34666
adId=0
user=admin
roleUser=admin
openTxnOwner=
openTxnId=0
openTxnAbortable=0
txnStarttime=1421916354
txnEndtime=1421916355
currStateInt=4
prevStateInt=3
actionInt=5
currState=done
prevState=progress
action=error
sessionId=5892021
selfAborted=false
status=done
errorCode=0
errorMessage=
--END ZONE_TXN_INFO
</PRE>
</BODY>"""
secinfo_resp = """
<BODY>
<PRE>
--BEGIN SECINFO
SECURITY = OFF
RANDOM = 6281590
DefaultPasswdBitmap = 0
primaryFCS = no
switchType = 66
resource = 10.24.48.210
REALM = FC Switch Administration
AUTHMETHOD = Custom_Basic
hasUpfrontLogin=yes
AUTHVERSION = 1
vfEnabled=false
vfSupported=true
--END SECINFO
</PRE>
</BODY>
"""
authenticate_resp = """<HTML>
<PRE>
--BEGIN AUTHENTICATE
authenticated = yes
username=admin
userrole=admin
adCapable=1
currentAD=AD0
trueADEnvironment=0
adId=0
adList=ALL
contextType=0
--END AUTHENTICATE
</PRE>
</BODY>
"""
un_authenticate_resp = """<HTML>
<HEAD>
<META HTTP-EQUIV="Pragma" CONTENT="no-cache">
<META HTTP-EQUIV="Expires" CONTENT="-1">
<TITLE>Authentication</TITLE>
</HEAD>
<BODY>
<PRE>
--BEGIN AUTHENTICATE
authenticated = no
errCode = -3
authType = Custom_Basic
realm = FC Switch Administration
--END AUTHENTICATE
</PRE>
</BODY>
</HTML>"""
switch_page_resp = """<HTML>
<HEAD>
<META HTTP-EQUIV="Pragma" CONTENT="no-cache">
<META HTTP-EQUIV="Expires" CONTENT="-1">
</HEAD>
<BODY>
<PRE>
--BEGIN SWITCH INFORMATION
didOffset=96
swFWVersion=v7.3.0b_rc1_bld06
swDomain=2
--END SWITCH INFORMATION
</PRE>
</BODY>
</HTML>
"""
switch_page_invalid_firm = """<HTML>
<HEAD>
<META HTTP-EQUIV="Pragma" CONTENT="no-cache">
<META HTTP-EQUIV="Expires" CONTENT="-1">
</HEAD>
<BODY>
<PRE>
--BEGIN SWITCH INFORMATION
didOffset=96
swFWVersion=v6.1.1
swDomain=2
--END SWITCH INFORMATION
</PRE>
</BODY>
</HTML>
"""
parsed_value = """
didOffset=96
swFWVersion=v7.3.0b_rc1_bld06
swDomain=2
"""
parsed_session_info_vf = """
sessionId=524461483
user=admin
userRole=admin
isAdminRole=Yes
authSource=0
sessionIp=172.26.1.146
valid=yes
adName=
adId=128
adCapable=1
currentAD=AD0
currentADId=0
homeAD=AD0
trueADEnvironment=0
adList=
adIdList=
pfAdmin=0
switchIsMember=0
definedADList=AD0,Physical Fabric
definedADIdList=0,255,
effectiveADList=AD0,Physical Fabric
rc=0
err=
contextType=1
vfEnabled=true
vfSupported=true
HomeVF=128
sessionLFId=2
isContextManageable=1
manageableLFList=2,128,
activeLFList=128,2,
"""
session_info_vf = """
<BODY>
<PRE>
--BEGIN SESSION
sessionId=524461483
user=admin
userRole=admin
isAdminRole=Yes
authSource=0
sessionIp=172.26.1.146
valid=yes
adName=
adId=128
adCapable=1
currentAD=AD0
currentADId=0
homeAD=AD0
trueADEnvironment=0
adList=
adIdList=
pfAdmin=0
switchIsMember=0
definedADList=AD0,Physical Fabric
definedADIdList=0,255,
effectiveADList=AD0,Physical Fabric
rc=0
err=
contextType=1
vfEnabled=true
vfSupported=true
HomeVF=128
sessionLFId=2
isContextManageable=1
manageableLFList=2,128,
activeLFList=128,2,
--END SESSION
</PRE>
</BODY>
"""
session_info_vf_not_changed = """
<BODY>
<PRE>
--BEGIN SESSION
sessionId=524461483
user=admin
userRole=admin
isAdminRole=Yes
authSource=0
sessionIp=172.26.1.146
User-Agent=Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML,
valid=yes
adName=
adId=128
adCapable=1
currentAD=AD0
currentADId=0
homeAD=AD0
trueADEnvironment=0
adList=
adIdList=
pfAdmin=0
switchIsMember=0
definedADList=AD0,Physical Fabric
definedADIdList=0,255,
effectiveADList=AD0,Physical Fabric
rc=0
err=
contextType=1
vfEnabled=true
vfSupported=true
HomeVF=128
sessionLFId=128
isContextManageable=1
manageableLFList=2,128,
activeLFList=128,2,
--END SESSION
</PRE>
</BODY>
"""
session_info_AD = """<HTML>
<HEAD>
<META HTTP-EQUIV="Pragma" CONTENT="no-cache">
<META HTTP-EQUIV="Expires" CONTENT="-1">
<TITLE>Webtools Session Info</TITLE>
</HEAD>
<BODY>
<PRE>
--BEGIN SESSION
sessionId=-2096740776
user=
userRole=root
isAdminRole=No
authSource=0
sessionIp=
User-Agent=
valid=no
adName=
adId=0
adCapable=1
currentAD=AD0
currentADId=0
homeAD=AD0
trueADEnvironment=0
adList=
adIdList=
pfAdmin=0
switchIsMember=1
definedADList=AD0,Physical Fabric
definedADIdList=0,255,
effectiveADList=AD0,Physical Fabric
rc=-2
err=Could not obtain session data from store
contextType=0
--END SESSION
</PRE>
</BODY>
</HTML>
"""
zone_info = """<HTML>
<HEAD>
<META HTTP-EQUIV="Pragma" CONTENT="no-cache">
<META HTTP-EQUIV="Expires" CONTENT="-1">
<TITLE>Zone Configuration Information</TITLE>
</HEAD>
<BODY>
<PRE>
--BEGIN ZONE CHANGE
LastZoneChangeTime=1421926251
--END ZONE CHANGE
isZoneTxnSupported=true
ZoneLicense=true
QuickLoopLicense=true
DefZoneStatus=noaccess
McDataDefaultZone=false
McDataSafeZone=false
AvailableZoneSize=1043890
--BEGIN ZONE INFO
openstack_cfg zone1;zone2 """\
"""zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 """\
    """zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 """\
    """alia1 10:00:00:05:1e:7c:64:96;10:21:10:05:33:0e:96:12 """\
    """qlp 10:11:f4:ce:46:ae:68:6c;20:11:f4:ce:46:ae:68:6c """\
    """fa1 20:15:f4:ce:96:ae:68:6c;20:11:f4:ce:46:ae:68:6c """\
    """openstack_cfg null 1045274"""\
    """--END ZONE INFO
</PRE>
</BODY>
</HTML>

"""

active_zone_set = {
    'zones':
    {'zone1':
     ['20:01:00:05:33:0e:96:15', '20:00:00:05:33:0e:93:11'],
     'zone2':
     ['20:01:00:05:33:0e:96:14', '20:00:00:05:33:0e:93:11']},
    'active_zone_config': 'openstack_cfg'}
updated_zones = {'zone1': '20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11',
                 'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11',
                 'test_updated_zone':
                 '20:01:00:05:33:0e:96:10;20:00:00:05:33:0e:93:11'}
updated_cfgs = {'openstack_cfg': 'test_updated_zone;zone1;zone2'}
valid_zone_name = "openstack50060b0000c26604201900051ee8e329"


class TestBrcdHttpFCZoneClient(client.BrcdHTTPFCZoneClient, test.TestCase):

    def setUp(self):
        self.auth_header = "YWRtaW46cGFzc3dvcmQ6NDM4ODEyNTIw"
        self.switch_user = "admin"
        self.switch_pwd = "password"
        self.protocol = "HTTPS"
        self.conn = None
        self.alias = {}
        self.qlps = {}
        self.ifas = {}
        self.parsed_raw_zoneinfo = ""
        self.random_no = ''
        self.auth_version = ''
        self.session = None
        super(TestBrcdHttpFCZoneClient, self).setUp()

    # override some of the functions
    def __init__(self, *args, **kwargs):
        test.TestCase.__init__(self, *args, **kwargs)

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_create_auth_token(self, connect_mock):
        connect_mock.return_value = secinfo_resp
        self.assertEqual("Custom_Basic YWRtaW46cGFzc3dvcmQ6NjI4MTU5MA==",
                         self.create_auth_token())

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_authenticate(self, connect_mock):
        connect_mock.return_value = authenticate_resp
        self.assertEqual(
            (True, "Custom_Basic YWRtaW46eHh4Og=="), self.authenticate())

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_authenticate_failed(self, connect_mock):
        connect_mock.return_value = un_authenticate_resp
        self.assertRaises(
            b_exception.BrocadeZoningHttpException, self.authenticate)

    def test_get_parsed_data(self):
        valid_delimiter1 = zone_constant.SWITCHINFO_BEGIN
        valid_delimiter2 = zone_constant.SWITCHINFO_END
        invalid_delimiter = "--END SWITCH INFORMATION1"
        self.assertEqual(parsed_value, self.get_parsed_data(
            switch_page_resp, valid_delimiter1, valid_delimiter2))
        self.assertRaises(b_exception.BrocadeZoningHttpException,
                          self.get_parsed_data,
                          switch_page_resp,
                          valid_delimiter1,
                          invalid_delimiter)
        self.assertRaises(b_exception.BrocadeZoningHttpException,
                          self.get_parsed_data,
                          switch_page_resp,
                          invalid_delimiter,
                          valid_delimiter2)

    def test_get_nvp_value(self):
        valid_keyname = zone_constant.FIRMWARE_VERSION
        invalid_keyname = "swFWVersion1"
        self.assertEqual(
            "v7.3.0b_rc1_bld06", self.get_nvp_value(parsed_value,
                                                    valid_keyname))
        self.assertRaises(b_exception.BrocadeZoningHttpException,
                          self.get_nvp_value,
                          parsed_value,
                          invalid_keyname)

    def test_get_managable_vf_list(self):
        manageable_list = ['2', '128']
        self.assertEqual(
            manageable_list, self.get_managable_vf_list(session_info_vf))
        self.assertRaises(b_exception.BrocadeZoningHttpException,
                          self.get_managable_vf_list, session_info_AD)

    @mock.patch.object(client.BrcdHTTPFCZoneClient, 'is_vf_enabled')
    def test_check_change_vf_context_vf_enabled(self, is_vf_enabled_mock):
        is_vf_enabled_mock.return_value = (True, session_info_vf)
        self.vfid = None
        self.assertRaises(
            b_exception.BrocadeZoningHttpException,
            self.check_change_vf_context)
        self.vfid = "2"
        with mock.patch.object(self, 'change_vf_context') \
                as change_vf_context_mock:
            self.check_change_vf_context()
            change_vf_context_mock.assert_called_once_with(
                self.vfid, session_info_vf)

    @mock.patch.object(client.BrcdHTTPFCZoneClient, 'is_vf_enabled')
    def test_check_change_vf_context_vf_disabled(self, is_vf_enabled_mock):
        is_vf_enabled_mock.return_value = (False, session_info_AD)
        self.vfid = "128"
        self.assertRaises(
            b_exception.BrocadeZoningHttpException,
            self.check_change_vf_context)

    @mock.patch.object(client.BrcdHTTPFCZoneClient, 'get_managable_vf_list')
    @mock.patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_change_vf_context_valid(self, connect_mock,
                                     get_managable_vf_list_mock):
        get_managable_vf_list_mock.return_value = ['2', '128']
        connect_mock.return_value = session_info_vf
        self.assertIsNone(self.change_vf_context("2", session_info_vf))
        data = zone_constant.CHANGE_VF.format(vfid="2")
        headers = {zone_constant.AUTH_HEADER: self.auth_header}
        connect_mock.assert_called_once_with(
            zone_constant.POST_METHOD, zone_constant.SESSION_PAGE,
            data, headers)

    @mock.patch.object(client.BrcdHTTPFCZoneClient, 'get_managable_vf_list')
    @mock.patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_change_vf_context_vf_not_changed(self,
                                              connect_mock,
                                              get_managable_vf_list_mock):
        get_managable_vf_list_mock.return_value = ['2', '128']
        connect_mock.return_value = session_info_vf_not_changed
        self.assertRaises(b_exception.BrocadeZoningHttpException,
                          self.change_vf_context, "2", session_info_vf)
        data = zone_constant.CHANGE_VF.format(vfid="2")
        headers = {zone_constant.AUTH_HEADER: self.auth_header}
        connect_mock.assert_called_once_with(
            zone_constant.POST_METHOD, zone_constant.SESSION_PAGE,
            data, headers)

    @mock.patch.object(client.BrcdHTTPFCZoneClient, 'get_managable_vf_list')
    def test_change_vf_context_vfid_not_managaed(self,
                                                 get_managable_vf_list_mock):
        get_managable_vf_list_mock.return_value = ['2', '128']
        self.assertRaises(b_exception.BrocadeZoningHttpException,
                          self.change_vf_context, "12", session_info_vf)

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_is_supported_firmware(self, connect_mock):
        connect_mock.return_value = switch_page_resp
        self.assertTrue(self.is_supported_firmware())

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_is_supported_firmware_invalid(self, connect_mock):
        connect_mock.return_value = switch_page_invalid_firm
        self.assertFalse(self.is_supported_firmware())

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_get_active_zone_set(self, connect_mock):
        connect_mock.return_value = zone_info
        returned_zone_map = self.get_active_zone_set()
        self.assertDictEqual(active_zone_set, returned_zone_map)

    def test_form_zone_string(self):
        new_alias = {
            'alia1': u'10:00:00:05:1e:7c:64:96;10:21:10:05:33:0e:96:12'}
        new_qlps = {'qlp': u'10:11:f4:ce:46:ae:68:6c;20:11:f4:ce:46:ae:68:6c'}
        new_ifas = {'fa1': u'20:15:f4:ce:96:ae:68:6c;20:11:f4:ce:46:ae:68:6c'}
        self.assertEqual(type(self.form_zone_string(
            cfgs, active_cfg, zones, new_alias, new_qlps, new_ifas, True)),
            bytes)
        self.assertEqual(
            encodeutils.safe_encode(mocked_zone_string),
            self.form_zone_string(
                cfgs, active_cfg, zones, new_alias, new_qlps, new_ifas, True))
        self.assertEqual(
            encodeutils.safe_encode(mocked_zone_string_no_activate),
            self.form_zone_string(
                cfgs, active_cfg, zones, new_alias, new_qlps, new_ifas, False))

    @patch.object(client.BrcdHTTPFCZoneClient, 'post_zone_data')
    def test_add_zones_activate(self, post_zone_data_mock):
        post_zone_data_mock.return_value = ("0", "")
        self.cfgs = cfgs.copy()
        self.zones = zones.copy()
        self.alias = alias.copy()
        self.qlps = qlps.copy()
        self.ifas = ifas.copy()
        self.active_cfg = active_cfg
        add_zones_info = {valid_zone_name:
                          ['50:06:0b:00:00:c2:66:04',
                              '20:19:00:05:1e:e8:e3:29']
                          }
        self.add_zones(add_zones_info, True)
        post_zone_data_mock.assert_called_once_with(
            encodeutils.safe_encode(zone_string_to_post))

    @patch.object(client.BrcdHTTPFCZoneClient, 'post_zone_data')
    def test_add_zones_invalid_zone_name(self, post_zone_data_mock):
        post_zone_data_mock.return_value = ("-1", "Name Too Long")
        self.cfgs = cfgs.copy()
        self.zones = zones.copy()
        self.alias = alias.copy()
        self.qlps = qlps.copy()
        self.ifas = ifas.copy()
        self.active_cfg = active_cfg
        invalid_zone_name = valid_zone_name + "00000000000000000000000000"
        add_zones_info = {invalid_zone_name:
                          ['50:06:0b:00:00:c2:66:04',
                              '20:19:00:05:1e:e8:e3:29']
                          }
        self.assertRaises(
            b_exception.BrocadeZoningHttpException,
            self.add_zones, add_zones_info, False)

    @patch.object(client.BrcdHTTPFCZoneClient, 'post_zone_data')
    def test_add_zones_no_activate(self, post_zone_data_mock):
        post_zone_data_mock.return_value = ("0", "")
        self.cfgs = cfgs.copy()
        self.zones = zones.copy()
        self.alias = alias.copy()
        self.qlps = qlps.copy()
        self.ifas = ifas.copy()
        self.active_cfg = active_cfg
        add_zones_info = {valid_zone_name:
                          ['50:06:0b:00:00:c2:66:04',
                              '20:19:00:05:1e:e8:e3:29']
                          }
        self.add_zones(add_zones_info, False)
        post_zone_data_mock.assert_called_once_with(
            encodeutils.safe_encode(zone_string_to_post_no_activate))

    @patch.object(client.BrcdHTTPFCZoneClient, 'post_zone_data')
    def test_delete_zones_activate(self, post_zone_data_mock):
        post_zone_data_mock.return_value = ("0", "")
        self.cfgs = cfgs_to_delete.copy()
        self.zones = zones_to_delete.copy()
        self.alias = alias.copy()
        self.qlps = qlps.copy()
        self.ifas = ifas.copy()
        self.active_cfg = active_cfg
        delete_zones_info = valid_zone_name

        self.delete_zones(delete_zones_info, True)
        post_zone_data_mock.assert_called_once_with(
            encodeutils.safe_encode(zone_string_del_to_post))

    @patch.object(client.BrcdHTTPFCZoneClient, 'post_zone_data')
    def test_delete_zones_no_activate(self, post_zone_data_mock):
        post_zone_data_mock.return_value = ("0", "")
        self.cfgs = cfgs_to_delete.copy()
        self.zones = zones_to_delete.copy()
        self.alias = alias.copy()
        self.qlps = qlps.copy()
        self.ifas = ifas.copy()
        self.active_cfg = active_cfg
        delete_zones_info = valid_zone_name
        self.delete_zones(delete_zones_info, False)
        post_zone_data_mock.assert_called_once_with(
            encodeutils.safe_encode(zone_string_del_to_post_no_active))

    @patch.object(client.BrcdHTTPFCZoneClient, 'post_zone_data')
    def test_delete_zones_invalid_zone_name(self, post_zone_data_mock):
        post_zone_data_mock.return_value = ("0", "")
        self.cfgs = cfgs_to_delete.copy()
        self.zones = zones_to_delete.copy()
        self.alias = alias.copy()
        self.qlps = qlps.copy()
        self.ifas = ifas.copy()
        self.active_cfg = active_cfg
        delete_zones_info = 'openstack50060b0000c26604201900051ee8e32'
        self.assertRaises(b_exception.BrocadeZoningHttpException,
                          self.delete_zones, delete_zones_info, False)

    @patch.object(time, 'sleep')
    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_post_zone_data(self, connect_mock, sleep_mock):
        connect_mock.return_value = zone_post_page
        self.assertEqual(
            ("-1", "Name too long"), self.post_zone_data(zone_string_to_post))
        connect_mock.return_value = zone_post_page_no_error
        self.assertEqual(("0", ""), self.post_zone_data(zone_string_to_post))

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_get_nameserver_info(self, connect_mock):
        connect_mock.return_value = nameserver_info
        self.assertEqual(ns_info, self.get_nameserver_info())

    @patch.object(client.BrcdHTTPFCZoneClient, 'get_session_info')
    def test_is_vf_enabled(self, get_session_info_mock):
        get_session_info_mock.return_value = session_info_vf
        self.assertEqual((True, parsed_session_info_vf), self.is_vf_enabled())

    def test_delete_zones_cfgs(self):

        cfgs = {'openstack_cfg': 'zone1;zone2'}
        zones = {'zone1': '20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11',
                 'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11'}
        delete_zones_info = valid_zone_name
        self.assertEqual(
            (zones, cfgs, active_cfg),
            self.delete_zones_cfgs(
                cfgs_to_delete.copy(),
                zones_to_delete.copy(),
                delete_zones_info,
                active_cfg))

        cfgs = {'openstack_cfg': 'openstack50060b0000c26604201900051ee8e329'}
        res = self.delete_zones_cfgs(cfgs,
                                     zones_to_delete.copy(),
                                     delete_zones_info,
                                     active_cfg)
        self.assertEqual((zones, {}, ''), res)

        cfgs = {'openstack_cfg': 'zone2'}
        zones = {'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11'}
        delete_zones_info = valid_zone_name + ";zone1"
        self.assertEqual(
            (zones, cfgs, active_cfg),
            self.delete_zones_cfgs(
                cfgs_to_delete.copy(),
                zones_to_delete.copy(),
                delete_zones_info,
                active_cfg))

    def test_add_zones_cfgs(self):
        add_zones_info = {valid_zone_name:
                          ['50:06:0b:00:00:c2:66:04',
                              '20:19:00:05:1e:e8:e3:29']
                          }
        updated_cfgs = {
            'openstack_cfg':
                valid_zone_name + ';zone1;zone2'}
        updated_zones = {
            'zone1': '20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11',
            'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11',
            valid_zone_name:
            '50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29'}
        self.assertEqual((updated_zones, updated_cfgs, active_cfg),
                         self.add_zones_cfgs(
                         cfgs.copy(),
                         zones.copy(),
                         add_zones_info,
                         active_cfg,
                         "openstack_cfg"))

        add_zones_info = {valid_zone_name:
                          ['50:06:0b:00:00:c2:66:04',
                              '20:19:00:05:1e:e8:e3:29'],
                          'test4':
                          ['20:06:0b:00:00:b2:66:07',
                              '20:10:00:05:1e:b8:c3:19']
                          }
        updated_cfgs = {
            'openstack_cfg':
                'test4;openstack50060b0000c26604201900051ee8e329;zone1;zone2'}
        updated_zones = {
            'zone1': '20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11',
            'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11',
            valid_zone_name:
            '50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29',
            'test4': '20:06:0b:00:00:b2:66:07;20:10:00:05:1e:b8:c3:19'}

        result = self.add_zones_cfgs(cfgs.copy(), zones.copy(), add_zones_info,
                                     active_cfg, "openstack_cfg")
        self.assertEqual(updated_zones, result[0])
        self.assertEqual(active_cfg, result[2])

        result_cfg = result[1]['openstack_cfg']
        self.assertIn('test4', result_cfg)
        self.assertIn('openstack50060b0000c26604201900051ee8e329', result_cfg)
        self.assertIn('zone1', result_cfg)
        self.assertIn('zone2', result_cfg)

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_get_zone_info(self, connect_mock):
        connect_mock.return_value = zone_info
        self.get_zone_info()
        self.assertEqual({'openstack_cfg': 'zone1;zone2'}, self.cfgs)
        self.assertEqual(
            {'zone1': '20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11',
             'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11'},
            self.zones)
        self.assertEqual('openstack_cfg', self.active_cfg)
        self.assertEqual(
            {'alia1': '10:00:00:05:1e:7c:64:96;10:21:10:05:33:0e:96:12'},
            self.alias)
        self.assertEqual(
            {'fa1': '20:15:f4:ce:96:ae:68:6c;20:11:f4:ce:46:ae:68:6c'},
            self.ifas)
        self.assertEqual(
            {'qlp': '10:11:f4:ce:46:ae:68:6c;20:11:f4:ce:46:ae:68:6c'},
            self.qlps)
