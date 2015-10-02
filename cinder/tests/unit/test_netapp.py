# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2015 Goutham Pacha Ravi.  All rights reserved.
# All rights reserved.
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
"""Tests for NetApp volume driver."""

from lxml import etree
import mock
import six
from six.moves import BaseHTTPServer
from six.moves import http_client

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes
from cinder.volume import configuration as conf
from cinder.volume.drivers.netapp import common
from cinder.volume.drivers.netapp.dataontap import block_7mode
from cinder.volume.drivers.netapp.dataontap import block_cmode
from cinder.volume.drivers.netapp.dataontap.client import client_7mode
from cinder.volume.drivers.netapp.dataontap.client import client_base
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap import ssc_cmode
from cinder.volume.drivers.netapp import options
from cinder.volume.drivers.netapp import utils


FAKE_CONNECTION_HTTP = {
    'transport_type': 'http',
    'username': 'admin',
    'password': 'pass',
    'hostname': '127.0.0.1',
    'port': None,
    'vserver': 'openstack',
}


def create_configuration():
    configuration = conf.Configuration(None)
    configuration.append_config_values(options.netapp_connection_opts)
    configuration.append_config_values(options.netapp_transport_opts)
    configuration.append_config_values(options.netapp_basicauth_opts)
    configuration.append_config_values(options.netapp_cluster_opts)
    configuration.append_config_values(options.netapp_7mode_opts)
    configuration.append_config_values(options.netapp_provisioning_opts)
    return configuration


class FakeHTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """HTTP handler that doesn't spam the log."""

    def log_message(self, format, *args):
        pass


class FakeHttplibSocket(object):
    """A fake socket implementation for http_client.HTTPResponse."""
    def __init__(self, value):
        self._rbuffer = six.BytesIO(value)
        self._wbuffer = six.BytesIO()
        oldclose = self._wbuffer.close

        def newclose():
            self.result = self._wbuffer.getvalue()
            oldclose()
        self._wbuffer.close = newclose

    def makefile(self, mode, *args):
        """Returns the socket's internal buffer"""
        if mode == 'r' or mode == 'rb':
            return self._rbuffer
        if mode == 'w' or mode == 'wb':
            return self._wbuffer

    def close(self):
        pass


RESPONSE_PREFIX_DIRECT_CMODE = b"""<?xml version='1.0' encoding='UTF-8' ?>
<!DOCTYPE netapp SYSTEM 'file:/etc/netapp_gx.dtd'>"""

RESPONSE_PREFIX_DIRECT_7MODE = b"""<?xml version='1.0' encoding='UTF-8' ?>
<!DOCTYPE netapp SYSTEM "/na_admin/netapp_filer.dtd">"""

RESPONSE_PREFIX_DIRECT = b"""
<netapp version='1.15' xmlns='http://www.netapp.com/filer/admin'>"""

RESPONSE_SUFFIX_DIRECT = b"""</netapp>"""


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

    def do_POST(s):  # noqa
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
        api = etree.QName(tag).localname or tag
        if 'lun-get-iter' == api:
            tag = \
                FakeDirectCMODEServerHandler._get_child_by_name(request, 'tag')
            if tag is None:
                body = """<results status="passed"><attributes-list>
                <lun-info>
                <alignment>indeterminate</alignment>
                <block-size>512</block-size>
                <comment></comment><creation-timestamp>1354536362
                </creation-timestamp>
                <is-space-alloc-enabled>false</is-space-alloc-enabled>
                <is-space-reservation-enabled>true
                </is-space-reservation-enabled>
                <mapped>false</mapped><multiprotocol-type>linux
                </multiprotocol-type>
                <online>true</online><path>/vol/navneet/lun1</path>
                <prefix-size>0</prefix-size><qtree></qtree><read-only>
                false</read-only><serial-number>2FfGI$APyN68</serial-number>
                <share-state>none</share-state><size>20971520</size>
                <size-used>0</size-used><staging>false</staging>
                <suffix-size>0</suffix-size>
                <uuid>cec1f3d7-3d41-11e2-9cf4-123478563412</uuid>
                <volume>navneet</volume><vserver>ben_vserver</vserver>
                </lun-info></attributes-list>
                <next-tag>&lt;lun-get-iter-key-td&gt;
            &lt;key-0&gt;ben_vserver&lt;/key-0&gt;
            &lt;key-1&gt;/vol/navneet/lun2&lt;/key-1&gt;
            &lt;key-2&gt;navneet&lt;/key-2&gt;
            &lt;key-3&gt;&lt;/key-3&gt;
            &lt;key-4&gt;lun2&lt;/key-4&gt;
            &lt;/lun-get-iter-key-td&gt;
            </next-tag><num-records>1</num-records></results>"""
            else:
                body = """<results status="passed"><attributes-list>
                    <lun-info>
                    <alignment>indeterminate</alignment>
                    <block-size>512</block-size>
                    <comment></comment><creation-timestamp>1354536362
                    </creation-timestamp>
                    <is-space-alloc-enabled>false</is-space-alloc-enabled>
                    <is-space-reservation-enabled>true
                    </is-space-reservation-enabled>
                    <mapped>false</mapped><multiprotocol-type>linux
                    </multiprotocol-type>
                    <online>true</online><path>/vol/navneet/lun3</path>
                    <prefix-size>0</prefix-size><qtree></qtree><read-only>
                    false</read-only><serial-number>2FfGI$APyN68
                    </serial-number>
                    <share-state>none</share-state><size>20971520</size>
                    <size-used>0</size-used><staging>false</staging>
                    <suffix-size>0</suffix-size>
                    <uuid>cec1f3d7-3d41-11e2-9cf4-123478563412</uuid>
                    <volume>navneet</volume><vserver>ben_vserver</vserver>
                    </lun-info></attributes-list>
                    <num-records>1</num-records></results>"""
        elif 'volume-get-iter' == api:
            tag = \
                FakeDirectCMODEServerHandler._get_child_by_name(request, 'tag')
            if tag is None:
                body = """<results status="passed"><attributes-list>
                <volume-attributes>
                <volume-id-attributes><name>iscsi</name>
                <owning-vserver-name>Openstack</owning-vserver-name>
                </volume-id-attributes>
                <volume-space-attributes>
                <size-available>214748364</size-available>
                </volume-space-attributes>
                <volume-state-attributes><is-cluster-volume>true
                </is-cluster-volume>
                <is-vserver-root>false</is-vserver-root><state>online</state>
                </volume-state-attributes></volume-attributes>
                <volume-attributes>
                <volume-id-attributes><name>nfsvol</name>
                <owning-vserver-name>openstack</owning-vserver-name>
                </volume-id-attributes>
                <volume-space-attributes>
                <size-available>247483648</size-available>
                </volume-space-attributes>
                <volume-state-attributes><is-cluster-volume>true
                </is-cluster-volume>
                <is-vserver-root>false</is-vserver-root><state>online</state>
                </volume-state-attributes></volume-attributes>
                </attributes-list>
                <next-tag>&lt;volume-get-iter-key-td&gt;
                &lt;key-0&gt;openstack&lt;/key-0&gt;
                &lt;key-1&gt;nfsvol&lt;/key-1&gt;
                &lt;/volume-get-iter-key-td&gt;
                </next-tag><num-records>2</num-records></results>"""
            else:
                body = """<results status="passed"><attributes-list>
                <volume-attributes>
                <volume-id-attributes><name>iscsi</name>
                <owning-vserver-name>Openstack</owning-vserver-name>
                </volume-id-attributes>
                <volume-space-attributes>
                <size-available>4147483648</size-available>
                </volume-space-attributes>
                <volume-state-attributes><is-cluster-volume>true
                </is-cluster-volume>
                <is-vserver-root>false</is-vserver-root><state>online</state>
                </volume-state-attributes></volume-attributes>
                <volume-attributes>
                <volume-id-attributes><name>nfsvol</name>
                <owning-vserver-name>openstack</owning-vserver-name>
                </volume-id-attributes>
                <volume-space-attributes>
                <size-available>8147483648</size-available>
                </volume-space-attributes>
                <volume-state-attributes><is-cluster-volume>true
                </is-cluster-volume>
                <is-vserver-root>false</is-vserver-root><state>online</state>
                </volume-state-attributes></volume-attributes>
                </attributes-list>
                <num-records>2</num-records></results>"""
        elif 'lun-create-by-size' == api:
            body = """<results status="passed">
            <actual-size>22020096</actual-size></results>"""
        elif 'lun-destroy' == api:
            body = """<results status="passed"/>"""
        elif 'igroup-get-iter' == api:
            init_found = True
            query = FakeDirectCMODEServerHandler._get_child_by_name(request,
                                                                    'query')
            if query is not None:
                igroup_info = FakeDirectCMODEServerHandler._get_child_by_name(
                    query, 'initiator-group-info')
                if igroup_info is not None:
                    inits = FakeDirectCMODEServerHandler._get_child_by_name(
                        igroup_info, 'initiators')
                    if inits is not None:
                        init_info = \
                            FakeDirectCMODEServerHandler._get_child_by_name(
                                inits, 'initiator-info')
                        init_name = \
                            FakeDirectCMODEServerHandler._get_child_content(
                                init_info,
                                'initiator-name')
                        if init_name == 'iqn.1993-08.org.debian:01:10':
                            init_found = True
                        else:
                            init_found = False
            if init_found:
                tag = \
                    FakeDirectCMODEServerHandler._get_child_by_name(
                        request, 'tag')
                if tag is None:
                    body = """<results status="passed"><attributes-list>
                    <initiator-group-info><initiator-group-name>
                    openstack-01f5297b-00f7-4170-bf30-69b1314b2118
                    </initiator-group-name>
                    <initiator-group-os-type>windows</initiator-group-os-type>
                    <initiator-group-type>iscsi</initiator-group-type>
                    <initiators>
                    <initiator-info>
                <initiator-name>iqn.1993-08.org.debian:01:10</initiator-name>
                    </initiator-info></initiators>
                    <vserver>openstack</vserver></initiator-group-info>
                    </attributes-list><next-tag>
                    &lt;igroup-get-iter-key-td&gt;
                    &lt;key-0&gt;openstack&lt;/key-0&gt;
                    &lt;key-1&gt;
                    openstack-01f5297b-00f7-4170-bf30-69b1314b2118&lt;
                    /key-1&gt;
                    &lt;/igroup-get-iter-key-td&gt;
                    </next-tag><num-records>1</num-records></results>"""
                else:
                    body = """<results status="passed"><attributes-list>
                    <initiator-group-info><initiator-group-name>
                    openstack-01f5297b-00f7-4170-bf30-69b1314b2118
                    </initiator-group-name>
                    <initiator-group-os-type>linux</initiator-group-os-type>
                    <initiator-group-type>iscsi</initiator-group-type>
                    <initiators>
                    <initiator-info>
                <initiator-name>iqn.1993-08.org.debian:01:10</initiator-name>
                    </initiator-info></initiators>
                    <vserver>openstack</vserver></initiator-group-info>
                    </attributes-list><num-records>1</num-records></results>"""
            else:
                body = """<results status="passed">
                    <num-records>0</num-records>
                  </results>"""
        elif 'lun-map-get-iter' == api:
            tag = \
                FakeDirectCMODEServerHandler._get_child_by_name(request, 'tag')
            if tag is None:
                body = """<results status="passed"><attributes-list>
                <lun-map-info>
                <initiator-group>openstack-44c5e7e1-3306-4800-9623-259e57d56a83
                </initiator-group>
                <initiator-group-uuid>948ae304-06e9-11e2</initiator-group-uuid>
                <lun-id>0</lun-id>
                <lun-uuid>5587e563-06e9-11e2-9cf4-123478563412</lun-uuid>
                <path>/vol/openvol/lun1</path>
                <vserver>openstack</vserver>
                </lun-map-info></attributes-list>
                <next-tag>
                &lt;lun-map-get-iter-key-td&gt;
                &lt;key-0&gt;openstack&lt;/key-0&gt;
                &lt;key-1&gt;openstack-01f5297b-00f7-4170-bf30-69b1314b2118&lt;
                /key-1&gt;
                &lt;/lun-map-get-iter-key-td&gt;
                </next-tag>
                <num-records>1</num-records>
                </results>"""
            else:
                body = """<results status="passed"><attributes-list>
                <lun-map-info>
                <initiator-group>openstack-44c5e7e1-3306-4800-9623-259e57d56a83
                </initiator-group>
                <initiator-group-uuid>948ae304-06e9-11e2</initiator-group-uuid>
                <lun-id>0</lun-id>
                <lun-uuid>5587e563-06e9-11e2-9cf4-123478563412</lun-uuid>
                <path>/vol/openvol/lun1</path>
                <vserver>openstack</vserver>
                </lun-map-info></attributes-list><num-records>1</num-records>
                </results>"""
        elif 'lun-map' == api:
            body = """<results status="passed"><lun-id-assigned>1
            </lun-id-assigned>
            </results>"""
        elif 'lun-get-geometry' == api:
            body = """<results status="passed"><bytes-per-sector>256
            </bytes-per-sector><cylinders>512</cylinders><max-resize-size>
            3221225472</max-resize-size><sectors-per-track>512
            </sectors-per-track><size>2147483648</size>
            <tracks-per-cylinder>256</tracks-per-cylinder></results>"""
        elif 'iscsi-service-get-iter' == api:
            body = """<results status="passed"><attributes-list>
            <iscsi-service-info>
            <alias-name>openstack</alias-name>
            <is-available>true</is-available>
            <node-name>iqn.1992-08.com.netapp:sn.fa9:vs.105</node-name>
            <vserver>openstack</vserver></iscsi-service-info>
            </attributes-list><num-records>1</num-records></results>"""
        elif 'iscsi-interface-get-iter' == api:
            body = """<results status="passed"><attributes-list>
            <iscsi-interface-list-entry-info><current-node>
            fas3170rre-cmode-01
            </current-node><current-port>e1b-1165</current-port>
            <interface-name>
            iscsi_data_if</interface-name>
            <ip-address>10.63.165.216</ip-address>
            <ip-port>3260</ip-port><is-interface-enabled>true
            </is-interface-enabled>
            <relative-port-id>5</relative-port-id>
            <tpgroup-name>iscsi_data_if</tpgroup-name>
            <tpgroup-tag>1038</tpgroup-tag><vserver>
            openstack</vserver>
            </iscsi-interface-list-entry-info></attributes-list>
            <num-records>1</num-records></results>"""
        elif 'igroup-create' == api:
            body = """<results status="passed"/>"""
        elif 'igroup-add' == api:
            body = """<results status="passed"/>"""
        elif 'clone-create' == api:
            body = """<results status="passed"/>"""
        elif 'lun-unmap' == api:
            body = """<results status="passed"/>"""
        elif 'system-get-ontapi-version' == api:
            body = """<results status="passed">
                        <major-version>1</major-version>
                        <minor-version>19</minor-version>
                      </results>"""
        elif 'vserver-get-iter' == api:
            body = """<results status="passed"><attributes-list>
                      <vserver-info>
                      <vserver-name>vserver</vserver-name>
                      <vserver-type>node</vserver-type>
                      </vserver-info>
                      </attributes-list>
                      <num-records>1</num-records></results>"""
        elif 'ems-autosupport-log' == api:
            body = """<results status="passed"/>"""
        elif 'lun-resize' == api:
            body = """<results status="passed"/>"""
        elif 'lun-get-geometry' == api:
            body = """<results status="passed">
                      <size>1</size>
                      <bytes-per-sector>2</bytes-per-sector>
                      <sectors-per-track>8</sectors-per-track>
                      <tracks-per-cylinder>2</tracks-per-cylinder>
                      <cylinders>4</cylinders>
                      <max-resize-size>5</max-resize-size>
                      </results>"""
        elif 'volume-options-list-info' == api:
            body = """<results status="passed">
                      <options>
                      <option>
                      <name>compression</name>
                      <value>off</value>
                      </option>
                      </options>
                      </results>"""
        elif 'lun-move' == api:
            body = """<results status="passed"/>"""
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
        if isinstance(body, six.text_type):
            body = body.encode('utf-8')
        s.wfile.write(body)
        s.wfile.write(RESPONSE_SUFFIX_DIRECT)

    @staticmethod
    def _get_child_by_name(self, name):
        for child in self.iterchildren():
            if child.tag == name or etree.QName(child.tag).localname == name:
                return child
        return None

    @staticmethod
    def _get_child_content(self, name):
        """Get the content of the child."""
        for child in self.iterchildren():
            if child.tag == name or etree.QName(child.tag).localname == name:
                return child.text
        return None


class FakeDirectCmodeHTTPConnection(object):
    """A fake http_client.HTTPConnection for netapp tests

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
        if isinstance(req_str, six.text_type):
            req_str = req_str.encode('latin1')
        if data:
            req_str += b'\r\n' + data

        # NOTE(vish): normally the http transport normalizes from unicode
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

    def close(self):
        pass


class NetAppDirectCmodeISCSIDriverTestCase(test.TestCase):
    """Test case for NetAppISCSIDriver"""

    volume = {'name': 'lun1', 'size': 2, 'volume_name': 'lun1',
              'os_type': 'linux', 'provider_location': 'lun1',
              'id': 'lun1', 'provider_auth': None, 'project_id': 'project',
              'display_name': None, 'display_description': 'lun1',
              'volume_type_id': None, 'host': 'hostname@backend#vol1'}
    snapshot = {'name': 'snapshot1', 'size': 2, 'volume_name': 'lun1',
                'volume_size': 2, 'project_id': 'project',
                'display_name': None, 'display_description': 'lun1',
                'volume_type_id': None}
    snapshot_fail = {'name': 'snapshot2', 'size': 2, 'volume_name': 'lun1',
                     'volume_size': 1, 'project_id': 'project'}
    volume_sec = {'name': 'vol_snapshot', 'size': 2, 'volume_name': 'lun1',
                  'os_type': 'linux', 'provider_location': 'lun1',
                  'id': 'lun1', 'provider_auth': None, 'project_id': 'project',
                  'display_name': None, 'display_description': 'lun1',
                  'volume_type_id': None}
    volume_clone = {'name': 'cl_sm', 'size': 3, 'volume_name': 'lun1',
                    'os_type': 'linux', 'provider_location': 'cl_sm',
                    'id': 'lun1', 'provider_auth': None,
                    'project_id': 'project', 'display_name': None,
                    'display_description': 'lun1',
                    'volume_type_id': None}
    volume_clone_large = {'name': 'cl_lg', 'size': 6, 'volume_name': 'lun1',
                          'os_type': 'linux', 'provider_location': 'cl_lg',
                          'id': 'lun1', 'provider_auth': None,
                          'project_id': 'project', 'display_name': None,
                          'display_description': 'lun1',
                          'volume_type_id': None}
    connector = {'initiator': 'iqn.1993-08.org.debian:01:10'}
    vol_fail = {'name': 'lun_fail', 'size': 10000, 'volume_name': 'lun1',
                'os_type': 'linux', 'provider_location': 'lun1',
                'id': 'lun1', 'provider_auth': None, 'project_id': 'project',
                'display_name': None, 'display_description': 'lun1',
                'volume_type_id': None, 'host': 'hostname@backend#vol1'}
    vol1 = ssc_cmode.NetAppVolume('lun1', 'openstack')
    vol1.state['vserver_root'] = False
    vol1.state['status'] = 'online'
    vol1.state['junction_active'] = True
    vol1.space['size_avl_bytes'] = '4000000000'
    vol1.space['size_total_bytes'] = '5000000000'
    vol1.space['space-guarantee-enabled'] = False
    vol1.space['space-guarantee'] = 'file'
    vol1.space['thin_provisioned'] = True
    vol1.mirror['mirrored'] = True
    vol1.qos['qos_policy_group'] = None
    vol1.aggr['name'] = 'aggr1'
    vol1.aggr['junction'] = '/vola'
    vol1.sis['dedup'] = True
    vol1.sis['compression'] = True
    vol1.aggr['raid_type'] = 'raiddp'
    vol1.aggr['ha_policy'] = 'cfo'
    vol1.aggr['disk_type'] = 'SSD'
    ssc_map = {'mirrored': set([vol1]), 'dedup': set([vol1]),
               'compression': set([vol1]),
               'thin': set([vol1]), 'all': set([vol1])}

    def setUp(self):
        super(NetAppDirectCmodeISCSIDriverTestCase, self).setUp()
        self._custom_setup()

    def _custom_setup(self):
        self.stubs.Set(
            ssc_cmode, 'refresh_cluster_ssc',
            lambda a, b, c, synchronous: None)
        self.mock_object(utils, 'OpenStackInfo')

        configuration = self._set_config(create_configuration())
        driver = common.NetAppDriver(configuration=configuration)
        self.stubs.Set(http_client, 'HTTPConnection',
                       FakeDirectCmodeHTTPConnection)
        driver.do_setup(context='')
        self.driver = driver
        self.driver.ssc_vols = self.ssc_map

    def _set_config(self, configuration):
        configuration.netapp_storage_protocol = 'iscsi'
        configuration.netapp_login = 'admin'
        configuration.netapp_password = 'pass'
        configuration.netapp_server_hostname = '127.0.0.1'
        configuration.netapp_transport_type = 'http'
        configuration.netapp_server_port = None
        configuration.netapp_vserver = 'openstack'
        return configuration

    def test_connect(self):
        self.driver.library.zapi_client = mock.MagicMock()
        self.driver.library.zapi_client.get_ontapi_version.return_value = \
            (1, 20)
        self.mock_object(block_cmode.NetAppBlockStorageCmodeLibrary,
                         '_get_filtered_pools',
                         mock.Mock(return_value=fakes.FAKE_CMODE_POOLS))
        self.driver.check_for_setup_error()

    def test_do_setup_all_default(self):
        self.mock_object(utils, 'OpenStackInfo')
        configuration = self._set_config(create_configuration())
        driver = common.NetAppDriver(configuration=configuration)
        mock_client = self.mock_object(client_cmode, 'Client')
        driver.do_setup(context='')
        mock_client.assert_called_with(**FAKE_CONNECTION_HTTP)

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    def test_do_setup_http_default_port(self):
        self.mock_object(utils, 'OpenStackInfo')
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'http'
        driver = common.NetAppDriver(configuration=configuration)
        mock_client = self.mock_object(client_cmode, 'Client')
        driver.do_setup(context='')
        mock_client.assert_called_with(**FAKE_CONNECTION_HTTP)

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    def test_do_setup_https_default_port(self):
        self.mock_object(utils, 'OpenStackInfo')
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'https'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._get_root_volume_name = mock.Mock()
        mock_client = self.mock_object(client_cmode, 'Client')
        driver.do_setup(context='')
        FAKE_CONNECTION_HTTPS = dict(FAKE_CONNECTION_HTTP,
                                     transport_type='https')
        mock_client.assert_called_with(**FAKE_CONNECTION_HTTPS)

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    def test_do_setup_http_non_default_port(self):
        self.mock_object(utils, 'OpenStackInfo')
        configuration = self._set_config(create_configuration())
        configuration.netapp_server_port = 81
        driver = common.NetAppDriver(configuration=configuration)
        mock_client = self.mock_object(client_cmode, 'Client')
        driver.do_setup(context='')
        FAKE_CONNECTION_HTTP_PORT = dict(FAKE_CONNECTION_HTTP, port=81)
        mock_client.assert_called_with(**FAKE_CONNECTION_HTTP_PORT)

    @mock.patch.object(client_base.Client, 'get_ontapi_version',
                       mock.Mock(return_value=(1, 20)))
    def test_do_setup_https_non_default_port(self):
        self.mock_object(utils, 'OpenStackInfo')
        configuration = self._set_config(create_configuration())
        configuration.netapp_transport_type = 'https'
        configuration.netapp_server_port = 446
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._get_root_volume_name = mock.Mock()
        mock_client = self.mock_object(client_cmode, 'Client')
        driver.do_setup(context='')
        FAKE_CONNECTION_HTTPS_PORT = dict(FAKE_CONNECTION_HTTP, port=446,
                                          transport_type='https')
        mock_client.assert_called_with(**FAKE_CONNECTION_HTTPS_PORT)

    def test_create_destroy(self):
        self.driver.create_volume(self.volume)
        self.driver.delete_volume(self.volume)

    def test_create_vol_snapshot_destroy(self):
        self.driver.create_volume(self.volume)
        self.mock_object(client_7mode.Client, '_check_clone_status')
        self.mock_object(self.driver.library, '_clone_lun')
        self.driver.create_snapshot(self.snapshot)
        self.driver.create_volume_from_snapshot(self.volume_sec, self.snapshot)
        self.driver.delete_snapshot(self.snapshot)
        self.driver.delete_volume(self.volume)

    def test_map_unmap(self):
        self.mock_object(client_cmode.Client, 'get_igroup_by_initiators')
        self.mock_object(client_cmode.Client, 'get_iscsi_target_details')
        self.mock_object(client_cmode.Client, 'get_iscsi_service_details')
        self.mock_object(self.driver.library, '_get_or_create_igroup')
        self.mock_object(self.driver.library, '_map_lun')
        self.mock_object(self.driver.library, '_unmap_lun')
        FAKE_PREFERRED_TARGET = {'address': 'http://host:8080', 'port': 80}
        FAKE_CONN_PROPERTIES = {'driver_volume_type': 'iscsi', 'data': 'test'}
        self.mock_object(self.driver.library,
                         '_get_preferred_target_from_list',
                         mock.Mock(return_value=FAKE_PREFERRED_TARGET))
        self.mock_object(common.na_utils, 'get_iscsi_connection_properties',
                         mock.Mock(return_value=FAKE_CONN_PROPERTIES))
        self.mock_object(client_cmode.Client,
                         'get_operational_network_interface_addresses',
                         mock.Mock(return_value=[]))
        self.driver.create_volume(self.volume)
        updates = self.driver.create_export(None, self.volume, {})
        self.assertTrue(updates['provider_location'])
        self.volume['provider_location'] = updates['provider_location']

        connection_info = self.driver.initialize_connection(self.volume,
                                                            self.connector)
        self.assertEqual('iscsi', connection_info['driver_volume_type'])
        properties = connection_info['data']
        if not properties:
            raise AssertionError('Target portal is none')
        self.driver.terminate_connection(self.volume, self.connector)
        self.driver.delete_volume(self.volume)

    def test_cloned_volume_destroy(self):
        self.driver.create_volume(self.volume)
        self.mock_object(self.driver.library, '_clone_lun')
        self.driver.create_cloned_volume(self.snapshot, self.volume)
        self.driver.delete_volume(self.snapshot)
        self.driver.delete_volume(self.volume)

    def test_map_by_creating_igroup(self):
        FAKE_IGROUP_INFO = {'initiator-group-name': 'debian',
                            'initiator-group-os-type': 'linux',
                            'initiator-group-type': 'igroup'}
        FAKE_PREFERRED_TARGET = {'address': 'http://host:8080', 'port': 80}
        FAKE_CONN_PROPERTIES = {'driver_volume_type': 'iscsi', 'data': 'test'}
        self.mock_object(client_cmode.Client, 'get_igroup_by_initiators',
                         mock.Mock(return_value=[FAKE_IGROUP_INFO]))
        self.mock_object(client_cmode.Client,
                         'get_operational_network_interface_addresses',
                         mock.Mock(return_value=[]))
        self.mock_object(client_cmode.Client, 'get_iscsi_target_details')
        self.mock_object(client_cmode.Client, 'get_iscsi_service_details')
        self.mock_object(self.driver.library,
                         '_get_preferred_target_from_list',
                         mock.Mock(return_value=FAKE_PREFERRED_TARGET))
        self.mock_object(common.na_utils, 'get_iscsi_connection_properties',
                         mock.Mock(return_value=FAKE_CONN_PROPERTIES))
        self.driver.create_volume(self.volume)
        updates = self.driver.create_export(None, self.volume, {})
        self.assertTrue(updates['provider_location'])
        self.volume['provider_location'] = updates['provider_location']
        connector_new = {'initiator': 'iqn.1993-08.org.debian:01:1001'}
        connection_info = self.driver.initialize_connection(self.volume,
                                                            connector_new)
        self.assertEqual('iscsi', connection_info['driver_volume_type'])
        properties = connection_info['data']
        if not properties:
            raise AssertionError('Target portal is none')

    def test_vol_stats(self):
        self.mock_object(client_base.Client, 'provide_ems')
        mock_update_vol_stats = self.mock_object(self.driver.library,
                                                 '_update_volume_stats')
        self.driver.get_volume_stats(refresh=True)
        self.assertEqual(mock_update_vol_stats.call_count, 1)

    def test_create_vol_snapshot_diff_size_resize(self):
        self.driver.create_volume(self.volume)
        self.mock_object(self.driver.library, '_clone_source_to_destination')
        self.mock_object(self.driver.library, '_clone_lun')
        self.driver.create_snapshot(self.snapshot)
        self.driver.create_volume_from_snapshot(
            self.volume_clone, self.snapshot)
        self.driver.delete_snapshot(self.snapshot)
        self.driver.delete_volume(self.volume)

    def test_create_vol_snapshot_diff_size_subclone(self):
        self.driver.create_volume(self.volume)
        self.mock_object(self.driver.library, '_clone_lun')
        self.mock_object(self.driver.library, '_clone_source_to_destination')
        self.driver.create_snapshot(self.snapshot)
        self.driver.create_volume_from_snapshot(
            self.volume_clone_large, self.snapshot)
        self.driver.delete_snapshot(self.snapshot)
        self.driver.delete_volume(self.volume)

    def test_extend_vol_same_size(self):
        self.driver.create_volume(self.volume)
        self.driver.extend_volume(self.volume, self.volume['size'])

    def test_extend_vol_direct_resize(self):
        self.mock_object(self.driver.library.zapi_client,
                         'get_lun_geometry', mock.Mock(return_value=None))
        self.mock_object(self.driver.library, '_do_sub_clone_resize')
        self.driver.create_volume(self.volume)
        self.driver.extend_volume(self.volume, 3)

    def test_extend_vol_sub_lun_clone(self):
        self.mock_object(self.driver.library.zapi_client,
                         'get_lun_geometry', mock.Mock(return_value=None))
        self.mock_object(self.driver.library, '_do_sub_clone_resize')
        self.driver.create_volume(self.volume)
        self.driver.extend_volume(self.volume, 4)


class NetAppDriverNegativeTestCase(test.TestCase):
    """Test case for NetAppDriver"""

    def setUp(self):
        super(NetAppDriverNegativeTestCase, self).setUp()

    def test_incorrect_family(self):
        self.mock_object(utils, 'OpenStackInfo')
        configuration = create_configuration()
        configuration.netapp_storage_family = 'xyz_abc'
        try:
            common.NetAppDriver(configuration=configuration)
            raise AssertionError('Wrong storage family is getting accepted.')
        except exception.InvalidInput:
            pass

    def test_incorrect_protocol(self):
        self.mock_object(utils, 'OpenStackInfo')
        configuration = create_configuration()
        configuration.netapp_storage_family = 'ontap'
        configuration.netapp_storage_protocol = 'ontap'
        try:
            common.NetAppDriver(configuration=configuration)
            raise AssertionError('Wrong storage protocol is getting accepted.')
        except exception.InvalidInput:
            pass


class FakeDirect7MODEServerHandler(FakeHTTPRequestHandler):
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
        api = etree.QName(tag).localname or tag
        if 'lun-list-info' == api:
            body = """<results status="passed">
    <are-vols-onlining>false</are-vols-onlining>
    <are-vols-busy>false</are-vols-busy>
    <luns>
      <lun-info>
        <path>/vol/vol1/lun1</path>
        <size>20971520</size>
        <online>true</online>
        <mapped>false</mapped>
        <read-only>false</read-only>
        <staging>false</staging>
        <share-state>none</share-state>
        <multiprotocol-type>linux</multiprotocol-type>
        <uuid>e867d844-c2c0-11e0-9282-00a09825b3b5</uuid>
        <serial-number>P3lgP4eTyaNl</serial-number>
        <block-size>512</block-size>
        <is-space-reservation-enabled>true</is-space-reservation-enabled>
        <size-used>0</size-used>
        <alignment>indeterminate</alignment>
      </lun-info>
      <lun-info>
        <path>/vol/vol1/lun1</path>
        <size>20971520</size>
        <online>true</online>
        <mapped>false</mapped>
        <read-only>false</read-only>
        <staging>false</staging>
        <share-state>none</share-state>
        <multiprotocol-type>linux</multiprotocol-type>
        <uuid>8e1e9284-c288-11e0-9282-00a09825b3b5</uuid>
        <serial-number>P3lgP4eTc3lp</serial-number>
        <block-size>512</block-size>
        <is-space-reservation-enabled>true</is-space-reservation-enabled>
        <size-used>0</size-used>
        <alignment>indeterminate</alignment>
      </lun-info>
    </luns>
  </results>"""
        elif 'volume-list-info' == api:
            body = """<results status="passed">
    <volumes>
      <volume-info>
        <name>vol0</name>
        <uuid>019c8f7a-9243-11e0-9281-00a09825b3b5</uuid>
        <type>flex</type>
        <block-type>32_bit</block-type>
        <state>online</state>
        <size-total>576914493440</size-total>
        <size-used>13820354560</size-used>
        <size-available>563094110208</size-available>
        <percentage-used>2</percentage-used>
        <snapshot-percent-reserved>20</snapshot-percent-reserved>
        <snapshot-blocks-reserved>140848264</snapshot-blocks-reserved>
        <reserve-required>0</reserve-required>
        <reserve>0</reserve>
        <reserve-used>0</reserve-used>
        <reserve-used-actual>0</reserve-used-actual>
        <files-total>20907162</files-total>
        <files-used>7010</files-used>
        <files-private-used>518</files-private-used>
        <inodefile-public-capacity>31142</inodefile-public-capacity>
        <inodefile-private-capacity>31142</inodefile-private-capacity>
        <quota-init>0</quota-init>
        <is-snaplock>false</is-snaplock>
        <containing-aggregate>aggr0</containing-aggregate>
        <sis>
          <sis-info>
            <state>disabled</state>
            <status>idle</status>
            <progress>idle for 70:36:44</progress>
            <type>regular</type>
            <schedule>sun-sat@0</schedule>
            <last-operation-begin>Mon Aug 8 09:34:15 EST 2011
            </last-operation-begin>
            <last-operation-end>Mon Aug 8 09:34:15 EST 2011
            </last-operation-end>
            <last-operation-size>0</last-operation-size>
            <size-shared>0</size-shared>
            <size-saved>0</size-saved>
            <percentage-saved>0</percentage-saved>
            <compress-saved>0</compress-saved>
            <percent-compress-saved>0</percent-compress-saved>
            <dedup-saved>0</dedup-saved>
            <percent-dedup-saved>0</percent-dedup-saved>
            <total-saved>0</total-saved>
            <percent-total-saved>0</percent-total-saved>
          </sis-info>
        </sis>
        <compression-info>
          <is-compression-enabled>false</is-compression-enabled>
        </compression-info>
        <space-reserve>volume</space-reserve>
        <space-reserve-enabled>true</space-reserve-enabled>
        <raid-size>14</raid-size>
        <raid-status>raid_dp,sis</raid-status>
        <checksum-style>block</checksum-style>
        <is-checksum-enabled>true</is-checksum-enabled>
        <is-inconsistent>false</is-inconsistent>
        <is-unrecoverable>false</is-unrecoverable>
        <is-invalid>false</is-invalid>
        <is-in-snapmirror-jumpahead>false</is-in-snapmirror-jumpahead>
        <mirror-status>unmirrored</mirror-status>
        <disk-count>3</disk-count>
        <plex-count>1</plex-count>
        <plexes>
          <plex-info>
            <name>/aggr0/plex0</name>
            <is-online>true</is-online>
            <is-resyncing>false</is-resyncing>
          </plex-info>
        </plexes>
      </volume-info>
      <volume-info>
        <name>vol1</name>
        <uuid>2d50ecf4-c288-11e0-9282-00a09825b3b5</uuid>
        <type>flex</type>
        <block-type>32_bit</block-type>
        <state>online</state>
        <size-total>42949672960</size-total>
        <size-used>44089344</size-used>
        <size-available>42905583616</size-available>
        <percentage-used>0</percentage-used>
        <snapshot-percent-reserved>20</snapshot-percent-reserved>
        <snapshot-blocks-reserved>10485760</snapshot-blocks-reserved>
        <reserve-required>8192</reserve-required>
        <reserve>8192</reserve>
        <reserve-used>0</reserve-used>
        <reserve-used-actual>0</reserve-used-actual>
        <files-total>1556480</files-total>
        <files-used>110</files-used>
        <files-private-used>504</files-private-used>
        <inodefile-public-capacity>31142</inodefile-public-capacity>
        <inodefile-private-capacity>31142</inodefile-private-capacity>
        <quota-init>0</quota-init>
        <is-snaplock>false</is-snaplock>
        <containing-aggregate>aggr1</containing-aggregate>
        <sis>
          <sis-info>
            <state>disabled</state>
            <status>idle</status>
            <progress>idle for 89:19:59</progress>
            <type>regular</type>
            <schedule>sun-sat@0</schedule>
            <last-operation-begin>Sun Aug 7 14:51:00 EST 2011
            </last-operation-begin>
            <last-operation-end>Sun Aug 7 14:51:00 EST 2011
            </last-operation-end>
            <last-operation-size>0</last-operation-size>
            <size-shared>0</size-shared>
            <size-saved>0</size-saved>
            <percentage-saved>0</percentage-saved>
            <compress-saved>0</compress-saved>
            <percent-compress-saved>0</percent-compress-saved>
            <dedup-saved>0</dedup-saved>
            <percent-dedup-saved>0</percent-dedup-saved>
            <total-saved>0</total-saved>
            <percent-total-saved>0</percent-total-saved>
          </sis-info>
        </sis>
        <compression-info>
          <is-compression-enabled>false</is-compression-enabled>
        </compression-info>
        <space-reserve>volume</space-reserve>
        <space-reserve-enabled>true</space-reserve-enabled>
        <raid-size>7</raid-size>
        <raid-status>raid4,sis</raid-status>
        <checksum-style>block</checksum-style>
        <is-checksum-enabled>true</is-checksum-enabled>
        <is-inconsistent>false</is-inconsistent>
        <is-unrecoverable>false</is-unrecoverable>
        <is-invalid>false</is-invalid>
        <is-in-snapmirror-jumpahead>false</is-in-snapmirror-jumpahead>
        <mirror-status>unmirrored</mirror-status>
        <disk-count>2</disk-count>
        <plex-count>1</plex-count>
        <plexes>
          <plex-info>
            <name>/aggr1/plex0</name>
            <is-online>true</is-online>
            <is-resyncing>false</is-resyncing>
          </plex-info>
        </plexes>
      </volume-info>
    </volumes>
  </results>"""
        elif 'volume-options-list-info' == api:
            body = """<results status="passed">
    <options>
      <volume-option-info>
        <name>snapmirrored</name>
        <value>off</value>
      </volume-option-info>
      <volume-option-info>
        <name>root</name>
        <value>false</value>
      </volume-option-info>
      <volume-option-info>
        <name>ha_policy</name>
        <value>cfo</value>
      </volume-option-info>
      <volume-option-info>
        <name>striping</name>
        <value>not_striped</value>
      </volume-option-info>
      <volume-option-info>
        <name>compression</name>
        <value>off</value>
      </volume-option-info>
    </options>
  </results>"""
        elif 'lun-create-by-size' == api:
            body = """<results status="passed">
            <actual-size>22020096</actual-size></results>"""
        elif 'lun-destroy' == api:
            body = """<results status="passed"/>"""
        elif 'igroup-list-info' == api:
            body = """<results status="passed">
    <initiator-groups>
      <initiator-group-info>
        <initiator-group-name>openstack-8bc96490</initiator-group-name>
        <initiator-group-type>iscsi</initiator-group-type>
        <initiator-group-uuid>b8e1d274-c378-11e0</initiator-group-uuid>
        <initiator-group-os-type>linux</initiator-group-os-type>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-throttle-borrow>false
        </initiator-group-throttle-borrow>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiator-group-alua-enabled>false</initiator-group-alua-enabled>
        <initiator-group-report-scsi-name-enabled>true
        </initiator-group-report-scsi-name-enabled>
        <initiators>
          <initiator-info>
            <initiator-name>iqn.1993-08.org.debian:01:10</initiator-name>
          </initiator-info>
        </initiators>
      </initiator-group-info>
      <initiator-group-info>
        <initiator-group-name>iscsi_group</initiator-group-name>
        <initiator-group-type>iscsi</initiator-group-type>
        <initiator-group-uuid>ccb8cbe4-c36f</initiator-group-uuid>
        <initiator-group-os-type>linux</initiator-group-os-type>
        <initiator-group-throttle-reserve>0</initiator-group-throttle-reserve>
        <initiator-group-throttle-borrow>false
        </initiator-group-throttle-borrow>
        <initiator-group-vsa-enabled>false</initiator-group-vsa-enabled>
        <initiator-group-alua-enabled>false</initiator-group-alua-enabled>
        <initiator-group-report-scsi-name-enabled>true
        </initiator-group-report-scsi-name-enabled>
        <initiators>
          <initiator-info>
            <initiator-name>iqn.1993-08.org.debian:01:10ca</initiator-name>
          </initiator-info>
        </initiators>
      </initiator-group-info>
    </initiator-groups>
  </results>"""
        elif 'lun-map-list-info' == api:
            body = """<results status="passed">
    <initiator-groups/>
  </results>"""
        elif 'lun-map' == api:
            body = """<results status="passed"><lun-id-assigned>1
            </lun-id-assigned>
            </results>"""
        elif 'iscsi-node-get-name' == api:
            body = """<results status="passed">
    <node-name>iqn.1992-08.com.netapp:sn.135093938</node-name>
  </results>"""
        elif 'iscsi-portal-list-info' == api:
            body = """<results status="passed">
    <iscsi-portal-list-entries>
      <iscsi-portal-list-entry-info>
        <ip-address>10.61.176.156</ip-address>
        <ip-port>3260</ip-port>
        <tpgroup-tag>1000</tpgroup-tag>
        <interface-name>e0a</interface-name>
      </iscsi-portal-list-entry-info>
    </iscsi-portal-list-entries>
  </results>"""
        elif 'igroup-create' == api:
            body = """<results status="passed"/>"""
        elif 'igroup-add' == api:
            body = """<results status="passed"/>"""
        elif 'clone-start' == api:
            body = """<results status="passed">
    <clone-id>
      <clone-id-info>
        <volume-uuid>2d50ecf4-c288-11e0-9282-00a09825b3b5</volume-uuid>
        <clone-op-id>11</clone-op-id>
      </clone-id-info>
    </clone-id>
  </results>"""
        elif 'clone-list-status' == api:
            body = """<results status="passed">
    <status>
      <ops-info>
        <clone-state>completed</clone-state>
      </ops-info>
    </status>
  </results>"""
        elif 'lun-unmap' == api:
            body = """<results status="passed"/>"""
        elif 'system-get-ontapi-version' == api:
            body = """<results status="passed">
                        <major-version>1</major-version>
                        <minor-version>8</minor-version>
                      </results>"""
        elif 'lun-set-space-reservation-info' == api:
            body = """<results status="passed"/>"""
        elif 'ems-autosupport-log' == api:
            body = """<results status="passed"/>"""
        elif 'lun-resize' == api:
            body = """<results status="passed"/>"""
        elif 'lun-get-geometry' == api:
            body = """<results status="passed">
                      <size>1</size>
                      <bytes-per-sector>2</bytes-per-sector>
                      <sectors-per-track>8</sectors-per-track>
                      <tracks-per-cylinder>2</tracks-per-cylinder>
                      <cylinders>4</cylinders>
                      <max-resize-size>5</max-resize-size>
                      </results>"""
        elif 'volume-options-list-info' == api:
            body = """<results status="passed">
                      <options>
                      <option>
                      <name>compression</name>
                      <value>off</value>
                      </option>
                      </options>
                      </results>"""
        elif 'lun-move' == api:
            body = """<results status="passed"/>"""
        else:
            # Unknown API
            s.send_response(500)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "text/xml; charset=utf-8")
        s.end_headers()
        s.wfile.write(RESPONSE_PREFIX_DIRECT_7MODE)
        s.wfile.write(RESPONSE_PREFIX_DIRECT)
        if isinstance(body, six.text_type):
            body = body.encode('utf-8')
        s.wfile.write(body)
        s.wfile.write(RESPONSE_SUFFIX_DIRECT)


class FakeDirect7modeHTTPConnection(object):
    """A fake http_client.HTTPConnection for netapp tests

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
        if isinstance(req_str, six.text_type):
            req_str = req_str.encode('latin1')
        if data:
            req_str += b'\r\n' + data

        # NOTE(vish): normally the http transport normailizes from unicode
        sock = FakeHttplibSocket(req_str.decode("latin-1").encode("utf-8"))
        # NOTE(vish): stop the server from trying to look up address from
        #             the fake socket
        FakeDirect7MODEServerHandler.address_string = lambda x: '127.0.0.1'
        self.app = FakeDirect7MODEServerHandler(sock, '127.0.0.1:80', None)

        self.sock = FakeHttplibSocket(sock.result)
        self.http_response = http_client.HTTPResponse(self.sock)

    def set_debuglevel(self, level):
        pass

    def getresponse(self):
        self.http_response.begin()
        return self.http_response

    def getresponsebody(self):
        return self.sock.result

    def close(self):
        pass


class NetAppDirect7modeISCSIDriverTestCase_NV(test.TestCase):
    """Test case for NetAppISCSIDriver without vfiler"""
    volume = {
        'name': 'lun1',
        'size': 2,
        'volume_name': 'lun1',
        'os_type': 'linux',
        'provider_location': 'lun1',
        'id': 'lun1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': None,
        'display_description': 'lun1',
        'volume_type_id': None,
        'host': 'hostname@backend#vol1',
    }

    def setUp(self):
        super(NetAppDirect7modeISCSIDriverTestCase_NV, self).setUp()
        self._custom_setup()

    def _custom_setup(self):
        self.mock_object(utils, 'OpenStackInfo')

        configuration = self._set_config(create_configuration())
        driver = common.NetAppDriver(configuration=configuration)
        self.stubs.Set(http_client, 'HTTPConnection',
                       FakeDirect7modeHTTPConnection)
        self.mock_object(driver.library, '_get_root_volume_name', mock.Mock(
            return_value='root'))
        driver.do_setup(context='')
        driver.root_volume_name = 'root'
        self.driver = driver

    def _set_config(self, configuration):
        configuration.netapp_storage_family = 'ontap_7mode'
        configuration.netapp_storage_protocol = 'iscsi'
        configuration.netapp_login = 'admin'
        configuration.netapp_password = 'pass'
        configuration.netapp_server_hostname = '127.0.0.1'
        configuration.netapp_transport_type = 'http'
        configuration.netapp_server_port = None
        return configuration

    def test_create_on_select_vol(self):
        self.driver.volume_list = ['vol0', 'vol1']
        self.driver.create_volume(self.volume)
        self.driver.delete_volume(self.volume)
        self.driver.volume_list = []

    def test_connect(self):
        self.driver.library.zapi_client = mock.MagicMock()
        self.driver.library.zapi_client.get_ontapi_version.\
            return_value = (1, 20)
        self.mock_object(block_7mode.NetAppBlockStorage7modeLibrary,
                         '_get_filtered_pools',
                         mock.Mock(return_value=fakes.FAKE_7MODE_POOLS))
        self.driver.check_for_setup_error()

    def test_check_for_setup_error_version(self):
        drv = self.driver
        self.mock_object(client_base.Client, 'get_ontapi_version',
                         mock.Mock(return_value=None))
        # check exception raises when version not found
        self.assertRaises(exception.VolumeBackendAPIException,
                          drv.check_for_setup_error)

        self.mock_object(client_base.Client, 'get_ontapi_version',
                         mock.Mock(return_value=(1, 8)))

        # check exception raises when not supported version
        self.assertRaises(exception.VolumeBackendAPIException,
                          drv.check_for_setup_error)


class NetAppDirect7modeISCSIDriverTestCase_WV(
        NetAppDirect7modeISCSIDriverTestCase_NV):
    """Test case for NetAppISCSIDriver with vfiler"""
    def setUp(self):
        super(NetAppDirect7modeISCSIDriverTestCase_WV, self).setUp()

    def _custom_setup(self):
        self.mock_object(utils, 'OpenStackInfo')

        configuration = self._set_config(create_configuration())
        driver = common.NetAppDriver(configuration=configuration)
        self.stubs.Set(http_client, 'HTTPConnection',
                       FakeDirect7modeHTTPConnection)
        self.mock_object(driver.library, '_get_root_volume_name',
                         mock.Mock(return_value='root'))
        driver.do_setup(context='')
        self.driver = driver
        self.driver.root_volume_name = 'root'

    def _set_config(self, configuration):
        configuration.netapp_storage_family = 'ontap_7mode'
        configuration.netapp_storage_protocol = 'iscsi'
        configuration.netapp_login = 'admin'
        configuration.netapp_password = 'pass'
        configuration.netapp_server_hostname = '127.0.0.1'
        configuration.netapp_transport_type = 'http'
        configuration.netapp_server_port = None
        configuration.netapp_vfiler = 'openstack'
        return configuration
