# Copyright (c) 2012 NetApp, Inc. All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
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
"""Unit tests for the NetApp-specific ssc module."""

import copy
import ddt
from lxml import etree
import mock
from mox3 import mox
import six
from six.moves import BaseHTTPServer
from six.moves import http_client

from cinder import exception
from cinder import test
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap import ssc_cmode


class FakeHTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """HTTP handler that doesn't spam the log."""

    def log_message(self, format, *args):
        pass


class FakeHttplibSocket(object):
    """A fake socket implementation for http_client.HTTPResponse."""
    def __init__(self, value):
        self._rbuffer = six.StringIO(value)
        self._wbuffer = six.StringIO('')
        oldclose = self._wbuffer.close

        def newclose():
            self.result = self._wbuffer.getvalue()
            oldclose()
        self._wbuffer.close = newclose

    def makefile(self, mode, _other):
        """Returns the socket's internal buffer"""
        if mode == 'r' or mode == 'rb':
            return self._rbuffer
        if mode == 'w' or mode == 'wb':
            return self._wbuffer


RESPONSE_PREFIX_DIRECT_CMODE = """<?xml version='1.0' encoding='UTF-8' ?>
<!DOCTYPE netapp SYSTEM 'file:/etc/netapp_gx.dtd'>"""

RESPONSE_PREFIX_DIRECT = """
<netapp version='1.15' xmlns='http://www.netapp.com/filer/admin'>"""

RESPONSE_SUFFIX_DIRECT = """</netapp>"""


class FakeDirectCMODEServerHandler(FakeHTTPRequestHandler):
    """HTTP handler that fakes enough stuff to allow the driver to run."""

    def do_GET(s):
        """Respond to a GET request."""
        if '/servlets/netapp.servlets.admin.XMLrequest_filer' not in s.path:
            s.send_response(404)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "text/xml; charset=utf-8")
        s.end_headers()
        out = s.wfile
        out.write('<netapp version="1.15">'
                  '<results reason="Not supported method type"'
                  ' status="failed" errno="Not_Allowed"/></netapp>')

    def do_POST(s):
        """Respond to a POST request."""
        if '/servlets/netapp.servlets.admin.XMLrequest_filer' not in s.path:
            s.send_response(404)
            s.end_headers
            return
        request_xml = s.rfile.read(int(s.headers['Content-Length']))
        root = etree.fromstring(request_xml)
        body = [x for x in root.iterchildren()]
        request = body[0]
        tag = request.tag
        localname = etree.QName(tag).localname or tag
        if 'volume-get-iter' == localname:
            body = """<results status="passed"><attributes-list>
                <volume-attributes>
                <volume-id-attributes>
                    <name>iscsi</name>
                    <owning-vserver-name>Openstack</owning-vserver-name>
                    <containing-aggregate-name>aggr0
                    </containing-aggregate-name>
                    <junction-path>/iscsi</junction-path>
                    <type>rw</type>
                </volume-id-attributes>
                <volume-space-attributes>
                    <size-available>214748364</size-available>
                    <size-total>224748364</size-total>
                    <space-guarantee-enabled>enabled</space-guarantee-enabled>
                    <space-guarantee>file</space-guarantee>
                </volume-space-attributes>
                <volume-state-attributes>
                    <is-cluster-volume>true
                    </is-cluster-volume>
                    <is-vserver-root>false</is-vserver-root>
                    <state>online</state>
                    <is-inconsistent>false</is-inconsistent>
                    <is-invalid>false</is-invalid>
                    <is-junction-active>true</is-junction-active>
                </volume-state-attributes>
                </volume-attributes>
                <volume-attributes>
                <volume-id-attributes>
                    <name>nfsvol</name>
                    <owning-vserver-name>Openstack
                    </owning-vserver-name>
                    <containing-aggregate-name>aggr0
                    </containing-aggregate-name>
                    <junction-path>/nfs</junction-path>
                    <type>rw</type>
                </volume-id-attributes>
                <volume-space-attributes>
                    <size-available>14748364</size-available>
                    <size-total>24748364</size-total>
                    <space-guarantee-enabled>enabled
                    </space-guarantee-enabled>
                    <space-guarantee>volume</space-guarantee>
                </volume-space-attributes>
                <volume-state-attributes>
                    <is-cluster-volume>true
                    </is-cluster-volume>
                    <is-vserver-root>false</is-vserver-root>
                    <state>online</state>
                    <is-inconsistent>false</is-inconsistent>
                    <is-invalid>false</is-invalid>
                    <is-junction-active>true</is-junction-active>
                </volume-state-attributes>
                </volume-attributes>
                <volume-attributes>
                <volume-id-attributes>
                    <name>nfsvol2</name>
                    <owning-vserver-name>Openstack
                    </owning-vserver-name>
                    <containing-aggregate-name>aggr0
                    </containing-aggregate-name>
                    <junction-path>/nfs2</junction-path>
                    <type>rw</type>
                </volume-id-attributes>
                <volume-space-attributes>
                    <size-available>14748364</size-available>
                    <size-total>24748364</size-total>
                    <space-guarantee-enabled>enabled
                    </space-guarantee-enabled>
                    <space-guarantee>volume</space-guarantee>
                </volume-space-attributes>
                <volume-state-attributes>
                    <is-cluster-volume>true
                    </is-cluster-volume>
                    <is-vserver-root>false</is-vserver-root>
                    <state>online</state>
                    <is-inconsistent>true</is-inconsistent>
                    <is-invalid>true</is-invalid>
                    <is-junction-active>true</is-junction-active>
                </volume-state-attributes>
                </volume-attributes>
                <volume-attributes>
                <volume-id-attributes>
                    <name>nfsvol3</name>
                    <owning-vserver-name>Openstack
                    </owning-vserver-name>
                    <containing-aggregate-name>aggr0
                    </containing-aggregate-name>
                    <junction-path>/nfs3</junction-path>
                    <type>rw</type>
                </volume-id-attributes>
                <volume-space-attributes>
                    <space-guarantee-enabled>enabled
                    </space-guarantee-enabled>
                    <space-guarantee>volume
                    </space-guarantee>
                </volume-space-attributes>
                <volume-state-attributes>
                    <is-cluster-volume>true
                    </is-cluster-volume>
                    <is-vserver-root>false</is-vserver-root>
                    <state>online</state>
                    <is-inconsistent>false</is-inconsistent>
                    <is-invalid>false</is-invalid>
                    <is-junction-active>true</is-junction-active>
                </volume-state-attributes>
                </volume-attributes>
                </attributes-list>
                <num-records>4</num-records></results>"""
        elif 'aggr-options-list-info' == localname:
            body = """<results status="passed">
                         <options>
                         <aggr-option-info>
                         <name>ha_policy</name>
                         <value>cfo</value>
                         </aggr-option-info>
                         <aggr-option-info>
                         <name>raidtype</name>
                         <value>raid_dp</value>
                         </aggr-option-info>
                         </options>
                         </results>"""
        elif 'sis-get-iter' == localname:
            body = """<results status="passed">
                         <attributes-list>
                         <sis-status-info>
                         <path>/vol/iscsi</path>
                         <is-compression-enabled>
                         true
                         </is-compression-enabled>
                         <state>enabled</state>
                         </sis-status-info>
                         </attributes-list>
                         </results>"""
        elif 'storage-disk-get-iter' == localname:
            body = """<results status="passed">
                             <attributes-list>
                             <storage-disk-info>
                             <disk-raid-info>
            <effective-disk-type>SATA</effective-disk-type>
                             </disk-raid-info>
                             </storage-disk-info>
                             </attributes-list>
                             </results>"""
        else:
            # Unknown API
            s.send_response(500)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "text/xml; charset=utf-8")
        s.end_headers()
        s.wfile.write(RESPONSE_PREFIX_DIRECT_CMODE)
        s.wfile.write(RESPONSE_PREFIX_DIRECT)
        s.wfile.write(body)
        s.wfile.write(RESPONSE_SUFFIX_DIRECT)


class FakeDirectCmodeHTTPConnection(object):
    """A fake http_client.HTTPConnection for netapp tests.

    Requests made via this connection actually get translated and routed into
    the fake direct handler above, we then turn the response into
    the http_client.HTTPResponse that the caller expects.
    """
    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, data=None, headers=None):
        if not headers:
            headers = {}
        req_str = '%s %s HTTP/1.1\r\n' % (method, path)
        for key, value in headers.items():
            req_str += "%s: %s\r\n" % (key, value)
        if data:
            req_str += '\r\n%s' % data

        # NOTE(vish): normally the http transport normailizes from unicode
        sock = FakeHttplibSocket(req_str.decode("latin-1").encode("utf-8"))
        # NOTE(vish): stop the server from trying to look up address from
        #             the fake socket
        FakeDirectCMODEServerHandler.address_string = lambda x: '127.0.0.1'
        self.app = FakeDirectCMODEServerHandler(sock, '127.0.0.1:80', None)

        self.sock = FakeHttplibSocket(sock.result)
        self.http_response = http_client.HTTPResponse(self.sock)

    def set_debuglevel(self, level):
        pass

    def getresponse(self):
        self.http_response.begin()
        return self.http_response

    def getresponsebody(self):
        return self.sock.result


def createNetAppVolume(**kwargs):
    vol = ssc_cmode.NetAppVolume(kwargs['name'], kwargs['vs'])
    vol.state['vserver_root'] = kwargs.get('vs_root')
    vol.state['status'] = kwargs.get('status')
    vol.state['junction_active'] = kwargs.get('junc_active')
    vol.space['size_avl_bytes'] = kwargs.get('avl_byt')
    vol.space['size_total_bytes'] = kwargs.get('total_byt')
    vol.space['space-guarantee-enabled'] = kwargs.get('sg_enabled')
    vol.space['space-guarantee'] = kwargs.get('sg')
    vol.space['thin_provisioned'] = kwargs.get('thin')
    vol.mirror['mirrored'] = kwargs.get('mirrored')
    vol.qos['qos_policy_group'] = kwargs.get('qos')
    vol.aggr['name'] = kwargs.get('aggr_name')
    vol.aggr['junction'] = kwargs.get('junction')
    vol.sis['dedup'] = kwargs.get('dedup')
    vol.sis['compression'] = kwargs.get('compression')
    vol.aggr['raid_type'] = kwargs.get('raid')
    vol.aggr['ha_policy'] = kwargs.get('ha')
    vol.aggr['disk_type'] = kwargs.get('disk')
    return vol


@ddt.ddt
class SscUtilsTestCase(test.TestCase):
    """Test ssc utis."""
    vol1 = createNetAppVolume(name='vola', vs='openstack',
                              vs_root=False, status='online', junc_active=True,
                              avl_byt='1000', total_byt='1500',
                              sg_enabled=False,
                              sg='file', thin=False, mirrored=False,
                              qos=None, aggr_name='aggr1', junction='/vola',
                              dedup=False, compression=False,
                              raid='raiddp', ha='cfo', disk='SSD')

    vol2 = createNetAppVolume(name='volb', vs='openstack',
                              vs_root=False, status='online', junc_active=True,
                              avl_byt='2000', total_byt='2500',
                              sg_enabled=True,
                              sg='file', thin=True, mirrored=False,
                              qos=None, aggr_name='aggr2', junction='/volb',
                              dedup=True, compression=False,
                              raid='raid4', ha='cfo', disk='SSD')

    vol3 = createNetAppVolume(name='volc', vs='openstack',
                              vs_root=False, status='online', junc_active=True,
                              avl_byt='3000', total_byt='3500',
                              sg_enabled=True,
                              sg='volume', thin=True, mirrored=False,
                              qos=None, aggr_name='aggr1', junction='/volc',
                              dedup=True, compression=True,
                              raid='raiddp', ha='cfo', disk='SAS')

    vol4 = createNetAppVolume(name='vold', vs='openstack',
                              vs_root=False, status='online', junc_active=True,
                              avl_byt='4000', total_byt='4500',
                              sg_enabled=False,
                              sg='none', thin=False, mirrored=False,
                              qos=None, aggr_name='aggr1', junction='/vold',
                              dedup=False, compression=False,
                              raid='raiddp', ha='cfo', disk='SSD')

    vol5 = createNetAppVolume(name='vole', vs='openstack',
                              vs_root=False, status='online', junc_active=True,
                              avl_byt='5000', total_byt='5500',
                              sg_enabled=True,
                              sg='none', thin=False, mirrored=True,
                              qos=None, aggr_name='aggr2', junction='/vole',
                              dedup=True, compression=False,
                              raid='raid4', ha='cfo', disk='SAS')

    test_vols = {vol1, vol2, vol3, vol4, vol5}

    ssc_map = {
        'mirrored': {vol1},
        'dedup': {vol1, vol2, vol3},
        'compression': {vol3, vol4},
        'thin': {vol5, vol2},
        'all': test_vols
    }

    def setUp(self):
        super(SscUtilsTestCase, self).setUp()
        self.stubs.Set(http_client, 'HTTPConnection',
                       FakeDirectCmodeHTTPConnection)

    @ddt.data({'na_server_exists': False, 'volume': None},
              {'na_server_exists': True, 'volume': 'vol'},
              {'na_server_exists': True, 'volume': None})
    @ddt.unpack
    def test_query_cluster_vols_for_ssc(self, na_server_exists, volume):
        if na_server_exists:
            na_server = netapp_api.NaServer('127.0.0.1')
            fake_api_return = mock.Mock(return_value=[])
            self.mock_object(ssc_cmode.netapp_api, 'invoke_api',
                             new_attr=fake_api_return)
            ssc_cmode.query_cluster_vols_for_ssc(na_server, 'vserver',
                                                 volume)
        else:
            na_server = None
            fake_api_error = mock.Mock(side_effect=exception.InvalidInput)
            self.mock_object(ssc_cmode.netapp_api, 'invoke_api',
                             new_attr=fake_api_error)
            self.assertRaises(KeyError, ssc_cmode.query_cluster_vols_for_ssc,
                              na_server, 'vserver', volume)

    def test_cl_vols_ssc_all(self):
        """Test cluster ssc for all vols."""
        na_server = netapp_api.NaServer('127.0.0.1')
        vserver = 'openstack'
        test_vols = set([copy.deepcopy(self.vol1),
                         copy.deepcopy(self.vol2), copy.deepcopy(self.vol3)])
        sis = {'vola': {'dedup': False, 'compression': False},
               'volb': {'dedup': True, 'compression': False}}
        mirrored = {'vola': [{'dest_loc': 'openstack1:vol1',
                              'rel_type': 'data_protection',
                              'mirr_state': 'broken'},
                             {'dest_loc': 'openstack2:vol2',
                              'rel_type': 'data_protection',
                              'mirr_state': 'snapmirrored'}],
                    'volb': [{'dest_loc': 'openstack1:vol2',
                              'rel_type': 'data_protection',
                              'mirr_state': 'broken'}]}

        self.mox.StubOutWithMock(ssc_cmode, 'query_cluster_vols_for_ssc')
        self.mox.StubOutWithMock(ssc_cmode, 'get_sis_vol_dict')
        self.mox.StubOutWithMock(ssc_cmode, 'get_snapmirror_vol_dict')
        self.mox.StubOutWithMock(ssc_cmode, 'query_aggr_options')
        self.mox.StubOutWithMock(ssc_cmode, 'query_aggr_storage_disk')
        ssc_cmode.query_cluster_vols_for_ssc(
            na_server, vserver, None).AndReturn(test_vols)
        ssc_cmode.get_sis_vol_dict(na_server, vserver, None).AndReturn(sis)
        ssc_cmode.get_snapmirror_vol_dict(na_server, vserver, None).AndReturn(
            mirrored)
        raiddp = {'ha_policy': 'cfo', 'raid_type': 'raiddp'}
        ssc_cmode.query_aggr_options(
            na_server, mox.IgnoreArg()).AndReturn(raiddp)
        ssc_cmode.query_aggr_storage_disk(
            na_server, mox.IgnoreArg()).AndReturn('SSD')
        raid4 = {'ha_policy': 'cfo', 'raid_type': 'raid4'}
        ssc_cmode.query_aggr_options(
            na_server, mox.IgnoreArg()).AndReturn(raid4)
        ssc_cmode.query_aggr_storage_disk(
            na_server, mox.IgnoreArg()).AndReturn('SAS')
        self.mox.ReplayAll()

        res_vols = ssc_cmode.get_cluster_vols_with_ssc(
            na_server, vserver, volume=None)

        self.mox.VerifyAll()
        for vol in res_vols:
            if vol.id['name'] == 'volc':
                self.assertEqual(False, vol.sis['compression'])
                self.assertEqual(False, vol.sis['dedup'])
            else:
                pass

    def test_cl_vols_ssc_single(self):
        """Test cluster ssc for single vol."""
        na_server = netapp_api.NaServer('127.0.0.1')
        vserver = 'openstack'
        test_vols = set([copy.deepcopy(self.vol1)])
        sis = {'vola': {'dedup': False, 'compression': False}}
        mirrored = {'vola': [{'dest_loc': 'openstack1:vol1',
                              'rel_type': 'data_protection',
                              'mirr_state': 'broken'},
                             {'dest_loc': 'openstack2:vol2',
                              'rel_type': 'data_protection',
                              'mirr_state': 'snapmirrored'}]}

        self.mox.StubOutWithMock(ssc_cmode, 'query_cluster_vols_for_ssc')
        self.mox.StubOutWithMock(ssc_cmode, 'get_sis_vol_dict')
        self.mox.StubOutWithMock(ssc_cmode, 'get_snapmirror_vol_dict')
        self.mox.StubOutWithMock(ssc_cmode, 'query_aggr_options')
        self.mox.StubOutWithMock(ssc_cmode, 'query_aggr_storage_disk')
        ssc_cmode.query_cluster_vols_for_ssc(
            na_server, vserver, 'vola').AndReturn(test_vols)
        ssc_cmode.get_sis_vol_dict(
            na_server, vserver, 'vola').AndReturn(sis)
        ssc_cmode.get_snapmirror_vol_dict(
            na_server, vserver, 'vola').AndReturn(mirrored)
        raiddp = {'ha_policy': 'cfo', 'raid_type': 'raiddp'}
        ssc_cmode.query_aggr_options(
            na_server, 'aggr1').AndReturn(raiddp)
        ssc_cmode.query_aggr_storage_disk(na_server, 'aggr1').AndReturn('SSD')
        self.mox.ReplayAll()

        res_vols = ssc_cmode.get_cluster_vols_with_ssc(
            na_server, vserver, volume='vola')

        self.mox.VerifyAll()
        self.assertEqual(1, len(res_vols))

    def test_get_cluster_ssc(self):
        """Test get cluster ssc map."""
        na_server = netapp_api.NaServer('127.0.0.1')
        vserver = 'openstack'
        test_vols = set(
            [self.vol1, self.vol2, self.vol3, self.vol4, self.vol5])

        self.mox.StubOutWithMock(ssc_cmode, 'get_cluster_vols_with_ssc')
        ssc_cmode.get_cluster_vols_with_ssc(
            na_server, vserver).AndReturn(test_vols)
        self.mox.ReplayAll()

        res_map = ssc_cmode.get_cluster_ssc(na_server, vserver)

        self.mox.VerifyAll()
        self.assertEqual(1, len(res_map['mirrored']))
        self.assertEqual(3, len(res_map['dedup']))
        self.assertEqual(1, len(res_map['compression']))
        self.assertEqual(2, len(res_map['thin']))
        self.assertEqual(5, len(res_map['all']))

    def test_vols_for_boolean_specs(self):
        """Test ssc for boolean specs."""
        test_vols = set(
            [self.vol1, self.vol2, self.vol3, self.vol4, self.vol5])
        ssc_map = {'mirrored': set([self.vol1]),
                   'dedup': set([self.vol1, self.vol2, self.vol3]),
                   'compression': set([self.vol3, self.vol4]),
                   'thin': set([self.vol5, self.vol2]), 'all': test_vols}
        test_map = {'mirrored': ('netapp_mirrored', 'netapp_unmirrored'),
                    'dedup': ('netapp_dedup', 'netapp_nodedup'),
                    'compression': ('netapp_compression',
                                    'netapp_nocompression'),
                    'thin': ('netapp_thin_provisioned',
                             'netapp_thick_provisioned')}
        for type in test_map.keys():
            # type
            extra_specs = {test_map[type][0]: 'true'}
            res = ssc_cmode.get_volumes_for_specs(ssc_map, extra_specs)
            self.assertEqual(len(ssc_map[type]), len(res))
            # opposite type
            extra_specs = {test_map[type][1]: 'true'}
            res = ssc_cmode.get_volumes_for_specs(ssc_map, extra_specs)
            self.assertEqual(len(ssc_map['all'] - ssc_map[type]), len(res))
            # both types
            extra_specs =\
                {test_map[type][0]: 'true', test_map[type][1]: 'true'}
            res = ssc_cmode.get_volumes_for_specs(ssc_map, extra_specs)
            self.assertEqual(len(ssc_map['all']), len(res))

    def test_vols_for_optional_specs(self):
        """Test ssc for optional specs."""
        extra_specs =\
            {'netapp_dedup': 'true',
             'netapp:raid_type': 'raid4', 'netapp:disk_type': 'SSD'}
        res = ssc_cmode.get_volumes_for_specs(self.ssc_map, extra_specs)
        self.assertEqual(1, len(res))

    def test_get_volumes_for_specs_none_specs(self):
        none_specs = None
        expected = self.ssc_map['all']

        result = ssc_cmode.get_volumes_for_specs(self.ssc_map, none_specs)

        self.assertEqual(expected, result)

    def test_get_volumes_for_specs_empty_dict(self):
        empty_dict = {}
        expected = self.ssc_map['all']

        result = ssc_cmode.get_volumes_for_specs(
            self.ssc_map, empty_dict)

        self.assertEqual(expected, result)

    def test_get_volumes_for_specs_not_a_dict(self):
        not_a_dict = False
        expected = self.ssc_map['all']

        result = ssc_cmode.get_volumes_for_specs(
            self.ssc_map, not_a_dict)

        self.assertEqual(expected, result)

    def test_query_cl_vols_for_ssc(self):
        na_server = netapp_api.NaServer('127.0.0.1')
        body = etree.XML("""<results status="passed"><attributes-list>
                <volume-attributes>
                <volume-id-attributes>
                    <name>iscsi</name>
                    <owning-vserver-name>Openstack</owning-vserver-name>
                    <containing-aggregate-name>aggr0
                    </containing-aggregate-name>
                    <junction-path>/iscsi</junction-path>
                    <type>rw</type>
                </volume-id-attributes>
                <volume-space-attributes>
                    <size-available>214748364</size-available>
                    <size-total>224748364</size-total>
                    <space-guarantee-enabled>enabled</space-guarantee-enabled>
                    <space-guarantee>file</space-guarantee>
                </volume-space-attributes>
                <volume-state-attributes>
                    <is-cluster-volume>true
                    </is-cluster-volume>
                    <is-vserver-root>false</is-vserver-root>
                    <state>online</state>
                    <is-inconsistent>false</is-inconsistent>
                    <is-invalid>false</is-invalid>
                    <is-junction-active>true</is-junction-active>
                </volume-state-attributes>
                </volume-attributes>
                <volume-attributes>
                <volume-id-attributes>
                    <name>nfsvol</name>
                    <owning-vserver-name>Openstack
                    </owning-vserver-name>
                    <containing-aggregate-name>aggr0
                    </containing-aggregate-name>
                    <junction-path>/nfs</junction-path>
                    <type>rw</type>
                </volume-id-attributes>
                <volume-space-attributes>
                    <size-available>14748364</size-available>
                    <size-total>24748364</size-total>
                    <space-guarantee-enabled>enabled
                    </space-guarantee-enabled>
                    <space-guarantee>volume</space-guarantee>
                </volume-space-attributes>
                <volume-state-attributes>
                    <is-cluster-volume>true
                    </is-cluster-volume>
                    <is-vserver-root>false</is-vserver-root>
                    <state>online</state>
                    <is-inconsistent>false</is-inconsistent>
                    <is-invalid>false</is-invalid>
                    <is-junction-active>true</is-junction-active>
                </volume-state-attributes>
                </volume-attributes>
                <volume-attributes>
                <volume-id-attributes>
                    <name>nfsvol2</name>
                    <owning-vserver-name>Openstack
                    </owning-vserver-name>
                    <containing-aggregate-name>aggr0
                    </containing-aggregate-name>
                    <junction-path>/nfs2</junction-path>
                    <type>rw</type>
                </volume-id-attributes>
                <volume-space-attributes>
                    <size-available>14748364</size-available>
                    <size-total>24748364</size-total>
                    <space-guarantee-enabled>enabled
                    </space-guarantee-enabled>
                    <space-guarantee>volume</space-guarantee>
                </volume-space-attributes>
                <volume-state-attributes>
                    <is-cluster-volume>true
                    </is-cluster-volume>
                    <is-vserver-root>false</is-vserver-root>
                    <state>online</state>
                    <is-inconsistent>true</is-inconsistent>
                    <is-invalid>true</is-invalid>
                    <is-junction-active>true</is-junction-active>
                </volume-state-attributes>
                </volume-attributes>
                <volume-attributes>
                <volume-id-attributes>
                    <name>nfsvol3</name>
                    <owning-vserver-name>Openstack
                    </owning-vserver-name>
                    <containing-aggregate-name>aggr0
                    </containing-aggregate-name>
                    <junction-path>/nfs3</junction-path>
                    <type>rw</type>
                </volume-id-attributes>
                <volume-space-attributes>
                    <space-guarantee-enabled>enabled
                    </space-guarantee-enabled>
                    <space-guarantee>volume
                    </space-guarantee>
                </volume-space-attributes>
                <volume-state-attributes>
                    <is-cluster-volume>true
                    </is-cluster-volume>
                    <is-vserver-root>false</is-vserver-root>
                    <state>online</state>
                    <is-inconsistent>false</is-inconsistent>
                    <is-invalid>false</is-invalid>
                    <is-junction-active>true</is-junction-active>
                </volume-state-attributes>
                </volume-attributes>
                </attributes-list>
                <num-records>4</num-records></results>""")

        self.mock_object(ssc_cmode.netapp_api, 'invoke_api', mock.Mock(
            return_value=[netapp_api.NaElement(body)]))

        vols = ssc_cmode.query_cluster_vols_for_ssc(na_server, 'Openstack')
        self.assertEqual(2, len(vols))
        for vol in vols:
            if vol.id['name'] != 'iscsi' or vol.id['name'] != 'nfsvol':
                pass
            else:
                raise exception.InvalidVolume('Invalid volume returned.')

    def test_query_aggr_options(self):
        na_server = netapp_api.NaServer('127.0.0.1')
        body = etree.XML("""<results status="passed">
        <options>
        <aggr-option-info>
        <name>ha_policy</name>
        <value>cfo</value>
        </aggr-option-info>
        <aggr-option-info>
        <name>raidtype</name>
        <value>raid_dp</value>
        </aggr-option-info>
        </options>
        </results>""")

        self.mock_object(ssc_cmode.netapp_api, 'invoke_api', mock.Mock(
            return_value=[netapp_api.NaElement(body)]))

        aggr_attribs = ssc_cmode.query_aggr_options(na_server, 'aggr0')
        if aggr_attribs:
            self.assertEqual('cfo', aggr_attribs['ha_policy'])
            self.assertEqual('raid_dp', aggr_attribs['raid_type'])
        else:
            raise exception.InvalidParameterValue("Incorrect aggr options")

    def test_query_aggr_storage_disk(self):
        na_server = netapp_api.NaServer('127.0.0.1')
        body = etree.XML("""<results status="passed">
        <attributes-list>
        <storage-disk-info>
        <disk-raid-info>
        <effective-disk-type>SATA</effective-disk-type>
        </disk-raid-info>
        </storage-disk-info>
        </attributes-list>
        </results>""")

        self.mock_object(ssc_cmode.netapp_api, 'invoke_api',
                         mock.Mock(return_value=[netapp_api.NaElement(body)]))

        eff_disk_type = ssc_cmode.query_aggr_storage_disk(na_server, 'aggr0')
        self.assertEqual('SATA', eff_disk_type)
