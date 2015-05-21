#    (c) Copyright 2015 Brocade Communications Systems Inc.
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
from mock import patch

from cinder import exception
from cinder import test
from cinder.zonemanager.drivers.brocade import (brcd_http_fc_zone_client
                                                as client)
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
session = None
active_cfg = 'openstack_cfg'
activate = True
no_activate = False
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
--BEGIN NS INFO

2;8;020800;N    ;10:00:00:05:1e:7c:64:96;20:00:00:05:1e:7c:64:96;[89]""" \
"""Brocade-825 | 3.0.4.09 | DCM-X3650-94 | Microsoft Windows Server 2003 R2"""\
    """| Service Pack 2";FCP ;      3;20:08:00:05:1e:89:54:a0;"""\
    """0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0;000000;port8"""\
    """
--END NS INFO

</PRE>
</BODY>
</HTML>
"""
mocked_zone_string = 'zonecfginfo=openstack_cfg zone1;zone2 '\
    'zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 '\
    'zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 '\
    'alia1 10:00:00:05:1e:7c:64:96;10:21:10:05:33:0e:96:12 '\
    'qlp 10:11:f4:ce:46:ae:68:6c;20:11:f4:ce:46:ae:68:6c '\
    'fa1 20:15:f4:ce:96:ae:68:6c;20:11:f4:ce:46:ae:68:6c '\
    'openstack_cfg null &saveonly=false'
mocked_zone_string_no_activate = 'zonecfginfo=openstack_cfg zone1;zone2 '\
    'zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 '\
    'zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 '\
    'alia1 10:00:00:05:1e:7c:64:96;10:21:10:05:33:0e:96:12 '\
    'qlp 10:11:f4:ce:46:ae:68:6c;20:11:f4:ce:46:ae:68:6c '\
    'fa1 20:15:f4:ce:96:ae:68:6c;20:11:f4:ce:46:ae:68:6c &saveonly=true'
zone_string_to_post = "zonecfginfo=openstack_cfg "\
    "openstack50060b0000c26604201900051ee8e329;zone1;zone2 "\
    "zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 "\
    "zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 "\
    "openstack50060b0000c26604201900051ee8e329 "\
    "50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29 "\
    "openstack_cfg null &saveonly=false"
zone_string_to_post_no_activate = "zonecfginfo=openstack_cfg "\
    "openstack50060b0000c26604201900051ee8e329;zone1;zone2 "\
    "zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 "\
    "zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 "\
    "openstack50060b0000c26604201900051ee8e329 "\
    "50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29 &saveonly=true"
zone_string_to_post_invalid_request = "zonecfginfo=openstack_cfg "\
    "openstack50060b0000c26604201900051ee8e32900000000000000000000000000;"\
    "zone1;zone2 openstack50060b0000c26604201900051ee8e329000000000000000000000"\
    "00000 50:06:0b:00:00:c2:66:04;20:19:00:05:1e:e8:e3:29 "\
    "zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 "\
    "zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 &saveonly=true"
zone_string_del_to_post = "zonecfginfo=openstack_cfg zone1;zone2"\
    " zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 "\
    "zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 "\
    "openstack_cfg null &saveonly=false"
zone_string_del_to_post_no_active = "zonecfginfo=openstack_cfg zone1;zone2"\
    " zone2 20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11 "\
    "zone1 20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11 &saveonly=true"
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
            exception.BrocadeZoningHttpException, self.authenticate)

    def test_get_parsed_data(self):
        valid_delimiter1 = zone_constant.SWITCHINFO_BEGIN
        valid_delimiter2 = zone_constant.SWITCHINFO_END
        invalid_delimiter = "--END SWITCH INFORMATION1"
        self.assertEqual(parsed_value, self.get_parsed_data(
            switch_page_resp, valid_delimiter1, valid_delimiter2))
        self.assertRaises(exception.BrocadeZoningHttpException,
                          self.get_parsed_data,
                          switch_page_resp,
                          valid_delimiter1,
                          invalid_delimiter)
        self.assertRaises(exception.BrocadeZoningHttpException,
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
        self.assertRaises(exception.BrocadeZoningHttpException,
                          self.get_nvp_value,
                          parsed_value,
                          invalid_keyname)

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
        self.assertDictMatch(active_zone_set, returned_zone_map)

    def test_form_zone_string(self):
        new_alias = {
            'alia1': '10:00:00:05:1e:7c:64:96;10:21:10:05:33:0e:96:12'}
        new_qlps = {'qlp': '10:11:f4:ce:46:ae:68:6c;20:11:f4:ce:46:ae:68:6c'}
        new_ifas = {'fa1': '20:15:f4:ce:96:ae:68:6c;20:11:f4:ce:46:ae:68:6c'}
        self.assertEqual(mocked_zone_string, self.form_zone_string(
            cfgs, active_cfg, zones, new_alias, new_qlps, new_ifas, True))
        self.assertEqual(mocked_zone_string_no_activate, self.form_zone_string(
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
        post_zone_data_mock.assert_called_once_with(zone_string_to_post)

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
            exception.BrocadeZoningHttpException,
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
            zone_string_to_post_no_activate)

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
        post_zone_data_mock.assert_called_once_with(zone_string_del_to_post)

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
            zone_string_del_to_post_no_active)

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
        self.assertRaises(exception.BrocadeZoningHttpException,
                          self.delete_zones, delete_zones_info, False)

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_post_zone_data(self, connect_mock):
        connect_mock.return_value = zone_post_page
        self.assertEqual(
            ("-1", "Name too long"), self.post_zone_data(zone_string_to_post))
        connect_mock.return_value = zone_post_page_no_error
        self.assertEqual(("0", ""), self.post_zone_data(zone_string_to_post))

    @patch.object(client.BrcdHTTPFCZoneClient, 'connect')
    def test_get_nameserver_info(self, connect_mock):
        connect_mock.return_value = nameserver_info
        self.assertEqual(ns_info, self.get_nameserver_info())

    def test_delete_update_zones_cfgs(self):

        cfgs = {'openstack_cfg': 'zone1;zone2'}
        zones = {'zone1': '20:01:00:05:33:0e:96:15;20:00:00:05:33:0e:93:11',
                 'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11'}
        delete_zones_info = valid_zone_name
        self.assertEqual(
            (zones, cfgs, active_cfg),
            self.delete_update_zones_cfgs(
                cfgs_to_delete.copy(),
                zones_to_delete.copy(),
                delete_zones_info,
                active_cfg))

        cfgs = {'openstack_cfg': 'zone2'}
        zones = {'zone2': '20:01:00:05:33:0e:96:14;20:00:00:05:33:0e:93:11'}
        delete_zones_info = valid_zone_name + ";zone1"
        self.assertEqual(
            (zones, cfgs, active_cfg),
            self.delete_update_zones_cfgs(
                cfgs_to_delete.copy(),
                zones_to_delete.copy(),
                delete_zones_info,
                active_cfg))

    def test_add_update_zones_cfgs(self):
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
                         self.add_update_zones_cfgs(
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
        self.assertEqual(
            (updated_zones, updated_cfgs, active_cfg),
            self.add_update_zones_cfgs(
                cfgs.copy(), zones.copy(), add_zones_info,
                active_cfg, "openstack_cfg"))

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
