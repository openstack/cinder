# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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
"""
Tests for NetApp volume driver

"""

import BaseHTTPServer
import httplib
import shutil
import StringIO
import tempfile

from lxml import etree

from cinder.exception import VolumeBackendAPIException
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.netapp import iscsi
from cinder.volume.drivers.netapp.iscsi import netapp_opts


LOG = logging.getLogger("cinder.volume.driver")

WSDL_HEADER = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<definitions xmlns="http://schemas.xmlsoap.org/wsdl/"
    xmlns:na="http://www.netapp.com/management/v1"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema" name="NetAppDfm"
    targetNamespace="http://www.netapp.com/management/v1">"""

WSDL_TYPES = """<types>
<xsd:schema attributeFormDefault="unqualified" elementFormDefault="qualified"
    targetNamespace="http://www.netapp.com/management/v1">
<xsd:element name="ApiProxy">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Request" type="na:Request"/>
            <xsd:element name="Target" type="xsd:string"/>
            <xsd:element minOccurs="0" name="Timeout" type="xsd:integer"/>
            <xsd:element minOccurs="0" name="Username" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="ApiProxyResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Response" type="na:Response"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditBegin">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="DatasetNameOrId" type="na:ObjNameOrId"/>
            <xsd:element minOccurs="0" name="Force" type="xsd:boolean"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditBeginResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="EditLockId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditCommit">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="AssumeConfirmation"
                type="xsd:boolean"/>
            <xsd:element name="EditLockId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditCommitResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="IsProvisioningFailure"
                type="xsd:boolean"/>
            <xsd:element minOccurs="0" name="JobIds" type="na:ArrayOfJobInfo"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditRollback">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="EditLockId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetEditRollbackResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DatasetListInfoIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetListInfoIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DatasetListInfoIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetListInfoIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Datasets" type="na:ArrayOfDatasetInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetListInfoIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="ObjectNameOrId"
                type="na:ObjNameOrId"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetListInfoIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="DatasetMembers"
                type="na:ArrayOfDatasetMemberInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="DatasetNameOrId" type="na:ObjNameOrId"/>
            <xsd:element minOccurs="0" name="IncludeExportsInfo"
                type="xsd:boolean"/>
            <xsd:element minOccurs="0" name="IncludeIndirect"
                type="xsd:boolean"/>
            <xsd:element minOccurs="0" name="MemberType" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetMemberListInfoIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetProvisionMember">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="EditLockId" type="xsd:integer"/>
            <xsd:element name="ProvisionMemberRequestInfo"
                type="na:ProvisionMemberRequestInfo"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetProvisionMemberResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DatasetRemoveMember">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="DatasetMemberParameters"
                type="na:ArrayOfDatasetMemberParameter"/>
            <xsd:element minOccurs="0" name="Destroy" type="xsd:boolean"/>
            <xsd:element name="EditLockId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DatasetRemoveMemberResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="ProgressEvents"
                type="na:ArrayOfDpJobProgressEventInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="JobId" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DpJobProgressEventListIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DfmAbout">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="IncludeDirectorySizeInfo"
                type="xsd:boolean"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="DfmAboutResult">
    <xsd:complexType>
        <xsd:all/>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="HostListInfoIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Hosts" type="na:ArrayOfHostInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="ObjectNameOrId"
                type="na:ObjNameOrId"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="HostListInfoIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterEnd">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterEndResult">
    <xsd:complexType/>
</xsd:element>
<xsd:element name="LunListInfoIterNext">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Maximum" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterNextResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Luns" type="na:ArrayOfLunInfo"/>
            <xsd:element name="Records" type="xsd:integer"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterStart">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="ObjectNameOrId"
                type="na:ObjNameOrId"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="LunListInfoIterStartResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element name="Records" type="xsd:integer"/>
            <xsd:element name="Tag" type="xsd:string"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="StorageServiceDatasetProvision">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="AssumeConfirmation"
                type="xsd:boolean"/>
            <xsd:element name="DatasetName" type="na:ObjName"/>
            <xsd:element name="StorageServiceNameOrId" type="na:ObjNameOrId"/>
            <xsd:element minOccurs="0" name="StorageSetDetails"
                type="na:ArrayOfStorageSetInfo"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:element name="StorageServiceDatasetProvisionResult">
    <xsd:complexType>
        <xsd:all>
            <xsd:element minOccurs="0" name="ConformanceAlerts"
                type="na:ArrayOfConformanceAlert"/>
            <xsd:element name="DatasetId" type="na:ObjId"/>
            <xsd:element minOccurs="0" name="DryRunResults"
                type="na:ArrayOfDryRunResult"/>
        </xsd:all>
    </xsd:complexType>
</xsd:element>
<xsd:complexType name="ArrayOfDatasetInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DatasetInfo"
            type="na:DatasetInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfDatasetMemberInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DatasetMemberInfo"
            type="na:DatasetMemberInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfDatasetMemberParameter">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DatasetMemberParameter"
            type="na:DatasetMemberParameter"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfDfmMetadataField">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DfmMetadataField"
            type="na:DfmMetadataField"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfDpJobProgressEventInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="DpJobProgressEventInfo"
            type="na:DpJobProgressEventInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfHostInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="HostInfo" type="na:HostInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfJobInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="JobInfo" type="na:JobInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfLunInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="LunInfo" type="na:LunInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="ArrayOfStorageSetInfo">
    <xsd:sequence>
        <xsd:element maxOccurs="unbounded" name="StorageSetInfo"
            type="na:StorageSetInfo"/>
    </xsd:sequence>
</xsd:complexType>
<xsd:complexType name="DatasetExportInfo">
    <xsd:all>
        <xsd:element minOccurs="0" name="DatasetExportProtocol"
            type="na:DatasetExportProtocol"/>
        <xsd:element minOccurs="0" name="DatasetLunMappingInfo"
            type="na:DatasetLunMappingInfo"/>
    </xsd:all>
</xsd:complexType>
<xsd:simpleType name="DatasetExportProtocol">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:complexType name="DatasetInfo">
    <xsd:all>
        <xsd:element name="DatasetId" type="na:ObjId"/>
        <xsd:element name="DatasetName" type="na:ObjName"/>
        <xsd:element name="DatasetMetadata" type="na:ArrayOfDfmMetadataField"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DatasetLunMappingInfo">
    <xsd:all>
        <xsd:element name="IgroupOsType" type="xsd:string"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DatasetMemberInfo">
    <xsd:all>
        <xsd:element name="MemberId" type="na:ObjId"/>
        <xsd:element name="MemberName" type="na:ObjName"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DatasetMemberParameter">
    <xsd:all>
        <xsd:element name="ObjectNameOrId" type="na:ObjNameOrId"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DfmMetadataField">
    <xsd:all>
        <xsd:element name="FieldName" type="xsd:string"/>
        <xsd:element name="FieldValue" type="xsd:string"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="DpJobProgressEventInfo">
    <xsd:all>
        <xsd:element name="EventStatus" type="na:ObjStatus"/>
        <xsd:element name="EventType" type="xsd:string"/>
        <xsd:element minOccurs="0" name="ProgressLunInfo"
            type="na:ProgressLunInfo"/>
    </xsd:all>
</xsd:complexType>
<xsd:simpleType name="DpPolicyNodeName">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:simpleType name="HostId">
    <xsd:restriction base="xsd:integer"/>
</xsd:simpleType>
<xsd:complexType name="HostInfo">
    <xsd:all>
        <xsd:element name="HostAddress" type="xsd:string"/>
        <xsd:element name="HostId" type="na:HostId"/>
        <xsd:element name="HostName" type="xsd:string"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="JobInfo">
    <xsd:all>
        <xsd:element name="JobId" type="xsd:integer"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="LunInfo">
    <xsd:all>
        <xsd:element name="HostId" type="na:ObjId"/>
        <xsd:element name="LunPath" type="na:ObjName"/>
        <xsd:element name="QtreeId" type="na:ObjName"/>
    </xsd:all>
</xsd:complexType>
<xsd:simpleType name="ObjId">
    <xsd:restriction base="xsd:integer"/>
</xsd:simpleType>
<xsd:simpleType name="ObjName">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:simpleType name="ObjNameOrId">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:simpleType name="ObjStatus">
    <xsd:restriction base="xsd:string"/>
</xsd:simpleType>
<xsd:complexType name="ProgressLunInfo">
    <xsd:all>
        <xsd:element name="LunPathId" type="na:ObjId"/>
        <xsd:element name="LunName" type="na:ObjName"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="ProvisionMemberRequestInfo">
    <xsd:all>
        <xsd:element minOccurs="0" name="Description" type="xsd:string"/>
        <xsd:element minOccurs="0" name="MaximumSnapshotSpace"
            type="xsd:integer"/>
        <xsd:element name="Name" type="xsd:string"/>
        <xsd:element name="Size" type="xsd:integer"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="Request">
    <xsd:all>
        <xsd:element minOccurs="0" name="Args">
            <xsd:complexType>
                <xsd:sequence>
                    <xsd:any maxOccurs="unbounded" minOccurs="0"/>
                </xsd:sequence>
            </xsd:complexType>
        </xsd:element>
        <xsd:element name="Name" type="xsd:string">
        </xsd:element>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="Response">
    <xsd:all>
        <xsd:element minOccurs="0" name="Errno" type="xsd:integer"/>
        <xsd:element minOccurs="0" name="Reason" type="xsd:string"/>
        <xsd:element minOccurs="0" name="Results">
            <xsd:complexType>
                <xsd:sequence>
                    <xsd:any maxOccurs="unbounded" minOccurs="0"/>
                </xsd:sequence>
            </xsd:complexType>
        </xsd:element>
        <xsd:element name="Status" type="xsd:string"/>
    </xsd:all>
</xsd:complexType>
<xsd:complexType name="StorageSetInfo">
    <xsd:all>
        <xsd:element minOccurs="0" name="DatasetExportInfo"
            type="na:DatasetExportInfo"/>
        <xsd:element minOccurs="0" name="DpNodeName"
            type="na:DpPolicyNodeName"/>
        <xsd:element minOccurs="0" name="ServerNameOrId"
            type="na:ObjNameOrId"/>
    </xsd:all>
</xsd:complexType>
</xsd:schema></types>"""

WSDL_TRAILER = """<service name="DfmService">
<port binding="na:DfmBinding" name="DfmPort">
<soap:address location="https://HOST_NAME:8488/apis/soap/v1"/>
</port></service></definitions>"""

RESPONSE_PREFIX = """<?xml version="1.0" encoding="UTF-8"?>
<env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:na="http://www.netapp.com/management/v1"><env:Header/><env:Body>"""

RESPONSE_SUFFIX = """</env:Body></env:Envelope>"""

APIS = ['ApiProxy', 'DatasetListInfoIterStart', 'DatasetListInfoIterNext',
        'DatasetListInfoIterEnd', 'DatasetEditBegin', 'DatasetEditCommit',
        'DatasetProvisionMember', 'DatasetRemoveMember', 'DfmAbout',
        'DpJobProgressEventListIterStart', 'DpJobProgressEventListIterNext',
        'DpJobProgressEventListIterEnd', 'DatasetMemberListInfoIterStart',
        'DatasetMemberListInfoIterNext', 'DatasetMemberListInfoIterEnd',
        'HostListInfoIterStart', 'HostListInfoIterNext', 'HostListInfoIterEnd',
        'LunListInfoIterStart', 'LunListInfoIterNext', 'LunListInfoIterEnd',
        'StorageServiceDatasetProvision']

iter_count = 0
iter_table = {}


def create_configuration():
    configuration = conf.Configuration(None)
    configuration.append_config_values(netapp_opts)
    return configuration


class FakeDfmServerHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """HTTP handler that fakes enough stuff to allow the driver to run."""

    def do_GET(s):
        """Respond to a GET request."""
        if '/dfm.wsdl' != s.path:
            s.send_response(404)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "application/wsdl+xml")
        s.end_headers()
        out = s.wfile
        out.write(WSDL_HEADER)
        out.write(WSDL_TYPES)
        for api in APIS:
            out.write('<message name="%sRequest">' % api)
            out.write('<part element="na:%s" name="parameters"/>' % api)
            out.write('</message>')
            out.write('<message name="%sResponse">' % api)
            out.write('<part element="na:%sResult" name="results"/>' % api)
            out.write('</message>')
        out.write('<portType name="DfmInterface">')
        for api in APIS:
            out.write('<operation name="%s">' % api)
            out.write('<input message="na:%sRequest"/>' % api)
            out.write('<output message="na:%sResponse"/>' % api)
            out.write('</operation>')
        out.write('</portType>')
        out.write('<binding name="DfmBinding" type="na:DfmInterface">')
        out.write('<soap:binding style="document" ' +
                  'transport="http://schemas.xmlsoap.org/soap/http"/>')
        for api in APIS:
            out.write('<operation name="%s">' % api)
            out.write('<soap:operation soapAction="urn:%s"/>' % api)
            out.write('<input><soap:body use="literal"/></input>')
            out.write('<output><soap:body use="literal"/></output>')
            out.write('</operation>')
        out.write('</binding>')
        out.write(WSDL_TRAILER)

    def do_POST(s):
        """Respond to a POST request."""
        if '/apis/soap/v1' != s.path:
            s.send_response(404)
            s.end_headers
            return
        request_xml = s.rfile.read(int(s.headers['Content-Length']))
        ntap_ns = 'http://www.netapp.com/management/v1'
        nsmap = {'env': 'http://schemas.xmlsoap.org/soap/envelope/',
                 'na': ntap_ns}
        root = etree.fromstring(request_xml)

        body = root.xpath('/env:Envelope/env:Body', namespaces=nsmap)[0]
        request = body.getchildren()[0]
        tag = request.tag
        if not tag.startswith('{' + ntap_ns + '}'):
            s.send_response(500)
            s.end_headers
            return
        api = tag[(2 + len(ntap_ns)):]
        global iter_count
        global iter_table
        if 'DatasetListInfoIterStart' == api:
            iter_name = 'dataset_%s' % iter_count
            iter_count = iter_count + 1
            iter_table[iter_name] = 0
            body = """<na:DatasetListInfoIterStartResult>
                    <na:Records>1</na:Records>
                    <na:Tag>%s</na:Tag>
                </na:DatasetListInfoIterStartResult>""" % iter_name
        elif 'DatasetListInfoIterNext' == api:
            tags = body.xpath('na:DatasetListInfoIterNext/na:Tag',
                              namespaces=nsmap)
            iter_name = tags[0].text
            if iter_table[iter_name]:
                body = """<na:DatasetListInfoIterNextResult>
                        <na:Datasets></na:Datasets>
                        <na:Records>0</na:Records>
                    </na:DatasetListInfoIterNextResult>"""
            else:
                iter_table[iter_name] = 1
                body = """<na:DatasetListInfoIterNextResult>
                        <na:Datasets>
                            <na:DatasetInfo>
                                <na:DatasetId>0</na:DatasetId>
                                <na:DatasetMetadata>
                                    <na:DfmMetadataField>
                                  <na:FieldName>OpenStackProject</na:FieldName>
                                        <na:FieldValue>testproj</na:FieldValue>
                                    </na:DfmMetadataField>
                                    <na:DfmMetadataField>
                                  <na:FieldName>OpenStackVolType</na:FieldName>
                                        <na:FieldValue></na:FieldValue>
                                    </na:DfmMetadataField>
                                </na:DatasetMetadata>
                            <na:DatasetName>OpenStack_testproj</na:DatasetName>
                            </na:DatasetInfo>
                        </na:Datasets>
                        <na:Records>1</na:Records>
                    </na:DatasetListInfoIterNextResult>"""
        elif 'DatasetListInfoIterEnd' == api:
            body = """<na:DatasetListInfoIterEndResult/>"""
        elif 'DatasetEditBegin' == api:
            body = """<na:DatasetEditBeginResult>
                    <na:EditLockId>0</na:EditLockId>
                </na:DatasetEditBeginResult>"""
        elif 'DatasetEditCommit' == api:
            body = """<na:DatasetEditCommitResult>
                    <na:IsProvisioningFailure>false</na:IsProvisioningFailure>
                    <na:JobIds>
                        <na:JobInfo>
                            <na:JobId>0</na:JobId>
                        </na:JobInfo>
                    </na:JobIds>
                </na:DatasetEditCommitResult>"""
        elif 'DatasetProvisionMember' == api:
            body = """<na:DatasetProvisionMemberResult/>"""
        elif 'DatasetRemoveMember' == api:
            body = """<na:DatasetRemoveMemberResult/>"""
        elif 'DfmAbout' == api:
            body = """<na:DfmAboutResult/>"""
        elif 'DpJobProgressEventListIterStart' == api:
            iter_name = 'dpjobprogress_%s' % iter_count
            iter_count = iter_count + 1
            iter_table[iter_name] = 0
            body = """<na:DpJobProgressEventListIterStartResult>
                    <na:Records>2</na:Records>
                    <na:Tag>%s</na:Tag>
                </na:DpJobProgressEventListIterStartResult>""" % iter_name
        elif 'DpJobProgressEventListIterNext' == api:
            tags = body.xpath('na:DpJobProgressEventListIterNext/na:Tag',
                              namespaces=nsmap)
            iter_name = tags[0].text
            if iter_table[iter_name]:
                body = """<na:DpJobProgressEventListIterNextResult/>"""
            else:
                iter_table[iter_name] = 1
                name = ('filer:/OpenStack_testproj/volume-00000001/'
                        'volume-00000001')
                body = """<na:DpJobProgressEventListIterNextResult>
                        <na:ProgressEvents>
                            <na:DpJobProgressEventInfo>
                                <na:EventStatus>normal</na:EventStatus>
                                <na:EventType>lun-create</na:EventType>
                                <na:ProgressLunInfo>
                                    <na:LunPathId>0</na:LunPathId>
                                    <na:LunName>%s</na:LunName>
                                 </na:ProgressLunInfo>
                            </na:DpJobProgressEventInfo>
                            <na:DpJobProgressEventInfo>
                                <na:EventStatus>normal</na:EventStatus>
                                <na:EventType>job-end</na:EventType>
                            </na:DpJobProgressEventInfo>
                        </na:ProgressEvents>
                        <na:Records>2</na:Records>
                    </na:DpJobProgressEventListIterNextResult>""" % name
        elif 'DpJobProgressEventListIterEnd' == api:
            body = """<na:DpJobProgressEventListIterEndResult/>"""
        elif 'DatasetMemberListInfoIterStart' == api:
            iter_name = 'datasetmember_%s' % iter_count
            iter_count = iter_count + 1
            iter_table[iter_name] = 0
            body = """<na:DatasetMemberListInfoIterStartResult>
                    <na:Records>1</na:Records>
                    <na:Tag>%s</na:Tag>
                </na:DatasetMemberListInfoIterStartResult>""" % iter_name
        elif 'DatasetMemberListInfoIterNext' == api:
            tags = body.xpath('na:DatasetMemberListInfoIterNext/na:Tag',
                              namespaces=nsmap)
            iter_name = tags[0].text
            if iter_table[iter_name]:
                body = """<na:DatasetMemberListInfoIterNextResult>
                        <na:DatasetMembers></na:DatasetMembers>
                        <na:Records>0</na:Records>
                    </na:DatasetMemberListInfoIterNextResult>"""
            else:
                iter_table[iter_name] = 1
                name = ('filer:/OpenStack_testproj/volume-00000001/'
                        'volume-00000001')
                body = """<na:DatasetMemberListInfoIterNextResult>
                        <na:DatasetMembers>
                            <na:DatasetMemberInfo>
                                <na:MemberId>0</na:MemberId>
                                <na:MemberName>%s</na:MemberName>
                            </na:DatasetMemberInfo>
                        </na:DatasetMembers>
                        <na:Records>1</na:Records>
                    </na:DatasetMemberListInfoIterNextResult>""" % name
        elif 'DatasetMemberListInfoIterEnd' == api:
            body = """<na:DatasetMemberListInfoIterEndResult/>"""
        elif 'HostListInfoIterStart' == api:
            body = """<na:HostListInfoIterStartResult>
                    <na:Records>1</na:Records>
                    <na:Tag>host</na:Tag>
                </na:HostListInfoIterStartResult>"""
        elif 'HostListInfoIterNext' == api:
            body = """<na:HostListInfoIterNextResult>
                    <na:Hosts>
                        <na:HostInfo>
                            <na:HostAddress>1.2.3.4</na:HostAddress>
                            <na:HostId>0</na:HostId>
                            <na:HostName>filer</na:HostName>
                        </na:HostInfo>
                    </na:Hosts>
                    <na:Records>1</na:Records>
                </na:HostListInfoIterNextResult>"""
        elif 'HostListInfoIterEnd' == api:
            body = """<na:HostListInfoIterEndResult/>"""
        elif 'LunListInfoIterStart' == api:
            body = """<na:LunListInfoIterStartResult>
                    <na:Records>1</na:Records>
                    <na:Tag>lun</na:Tag>
                </na:LunListInfoIterStartResult>"""
        elif 'LunListInfoIterNext' == api:
            path = 'OpenStack_testproj/volume-00000001/volume-00000001'
            body = """<na:LunListInfoIterNextResult>
                    <na:Luns>
                        <na:LunInfo>
                            <na:HostId>0</na:HostId>
                            <na:LunPath>%s</na:LunPath>
                            <na:QtreeId>volume-00000001</na:QtreeId>
                        </na:LunInfo>
                    </na:Luns>
                    <na:Records>1</na:Records>
                </na:LunListInfoIterNextResult>""" % path
        elif 'LunListInfoIterEnd' == api:
            body = """<na:LunListInfoIterEndResult/>"""
        elif 'ApiProxy' == api:
            names = body.xpath('na:ApiProxy/na:Request/na:Name',
                               namespaces=nsmap)
            proxy = names[0].text
            if 'clone-list-status' == proxy:
                op_elem = body.xpath('na:ApiProxy/na:Request/na:Args/'
                                     'clone-id/clone-id-info/clone-op-id',
                                     namespaces=nsmap)
                proxy_body = """<status>
                        <ops-info>
                            <clone-state>completed</clone-state>
                        </ops-info>
                    </status>"""
                if '0' == op_elem[0].text:
                    proxy_body = ''
            elif 'clone-start' == proxy:
                proxy_body = """<clone-id>
                        <clone-id-info>
                            <clone-op-id>1</clone-op-id>
                            <volume-uuid>xxx</volume-uuid>
                        </clone-id-info>
                    </clone-id>"""
            elif 'igroup-list-info' == proxy:
                igroup = 'openstack-iqn.1993-08.org.debian:01:23456789'
                initiator = 'iqn.1993-08.org.debian:01:23456789'
                proxy_body = """<initiator-groups>
                        <initiator-group-info>
                            <initiator-group-name>%s</initiator-group-name>
                            <initiator-group-type>iscsi</initiator-group-type>
                       <initiator-group-os-type>linux</initiator-group-os-type>
                            <initiators>
                                <initiator-info>
                                    <initiator-name>%s</initiator-name>
                                </initiator-info>
                            </initiators>
                        </initiator-group-info>
                    </initiator-groups>""" % (igroup, initiator)
            elif 'igroup-create' == proxy:
                proxy_body = ''
            elif 'igroup-add' == proxy:
                proxy_body = ''
            elif 'lun-map-list-info' == proxy:
                proxy_body = '<initiator-groups/>'
            elif 'lun-map' == proxy:
                proxy_body = '<lun-id-assigned>0</lun-id-assigned>'
            elif 'lun-unmap' == proxy:
                proxy_body = ''
            elif 'iscsi-portal-list-info' == proxy:
                proxy_body = """<iscsi-portal-list-entries>
                        <iscsi-portal-list-entry-info>
                            <ip-address>1.2.3.4</ip-address>
                            <ip-port>3260</ip-port>
                            <tpgroup-tag>1000</tpgroup-tag>
                        </iscsi-portal-list-entry-info>
                    </iscsi-portal-list-entries>"""
            elif 'iscsi-node-get-name' == proxy:
                target = 'iqn.1992-08.com.netapp:sn.111111111'
                proxy_body = '<node-name>%s</node-name>' % target
            else:
                # Unknown proxy API
                s.send_response(500)
                s.end_headers
                return
            api = api + ':' + proxy
            proxy_header = '<na:ApiProxyResult><na:Response><na:Results>'
            proxy_trailer = """</na:Results><na:Status>passed</na:Status>
                </na:Response></na:ApiProxyResult>"""
            body = proxy_header + proxy_body + proxy_trailer
        else:
            # Unknown API
            s.send_response(500)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "text/xml; charset=utf-8")
        s.end_headers()
        s.wfile.write(RESPONSE_PREFIX)
        s.wfile.write(body)
        s.wfile.write(RESPONSE_SUFFIX)


class FakeHttplibSocket(object):
    """A fake socket implementation for httplib.HTTPResponse"""
    def __init__(self, value):
        self._rbuffer = StringIO.StringIO(value)
        self._wbuffer = StringIO.StringIO('')
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


class FakeHTTPConnection(object):
    """A fake httplib.HTTPConnection for netapp tests

    Requests made via this connection actually get translated and routed into
    the fake Dfm handler above, we then turn the response into
    the httplib.HTTPResponse that the caller expects.
    """
    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, data=None, headers=None):
        if not headers:
            headers = {}
        req_str = '%s %s HTTP/1.1\r\n' % (method, path)
        for key, value in headers.iteritems():
            req_str += "%s: %s\r\n" % (key, value)
        if data:
            req_str += '\r\n%s' % data

        # NOTE(vish): normally the http transport normailizes from unicode
        sock = FakeHttplibSocket(req_str.decode("latin-1").encode("utf-8"))
        # NOTE(vish): stop the server from trying to look up address from
        #             the fake socket
        FakeDfmServerHandler.address_string = lambda x: '127.0.0.1'
        self.app = FakeDfmServerHandler(sock, '127.0.0.1:8088', None)

        self.sock = FakeHttplibSocket(sock.result)
        self.http_response = httplib.HTTPResponse(self.sock)

    def set_debuglevel(self, level):
        pass

    def getresponse(self):
        self.http_response.begin()
        return self.http_response

    def getresponsebody(self):
        return self.sock.result


class NetAppDriverTestCase(test.TestCase):
    """Test case for NetAppISCSIDriver"""
    STORAGE_SERVICE = 'Openstack Service'
    STORAGE_SERVICE_PREFIX = 'Openstack Service-'
    PROJECT_ID = 'testproj'
    VOLUME_NAME = 'volume-00000001'
    VOLUME_TYPE = ''
    VOLUME_SIZE = 2147483648L  # 2 GB
    INITIATOR = 'iqn.1993-08.org.debian:01:23456789'

    def setUp(self):
        super(NetAppDriverTestCase, self).setUp()
        self.tempdir = tempfile.mkdtemp()
        self.flags(lock_path=self.tempdir)
        driver = iscsi.NetAppISCSIDriver(configuration=create_configuration())
        self.stubs.Set(httplib, 'HTTPConnection', FakeHTTPConnection)
        driver._create_client(wsdl_url='http://localhost:8088/dfm.wsdl',
                              login='root', password='password',
                              hostname='localhost', port=8088, cache=False)
        driver._set_storage_service(self.STORAGE_SERVICE)
        driver._set_storage_service_prefix(self.STORAGE_SERVICE_PREFIX)
        driver._set_vfiler('')
        self.driver = driver

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        super(NetAppDriverTestCase, self).tearDown()

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_connect(self):
        self.driver.check_for_setup_error()

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_create_destroy(self):
        self.driver._discover_luns()
        self.driver._provision(self.VOLUME_NAME, None, self.PROJECT_ID,
                               self.VOLUME_TYPE, self.VOLUME_SIZE)
        self.driver._remove_destroy(self.VOLUME_NAME, self.PROJECT_ID)

    def test_destroy_uncreated_volume(self):
        self.driver._remove_destroy('fake-nonexistent-volume', self.PROJECT_ID)

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_map_unmap(self):
        self.driver._discover_luns()
        self.driver._provision(self.VOLUME_NAME, None, self.PROJECT_ID,
                               self.VOLUME_TYPE, self.VOLUME_SIZE)
        volume = {'name': self.VOLUME_NAME, 'project_id': self.PROJECT_ID,
                  'id': 0, 'provider_auth': None}
        updates = self.driver._get_export(volume)
        self.assertTrue(updates['provider_location'])
        volume['provider_location'] = updates['provider_location']
        connector = {'initiator': self.INITIATOR}
        connection_info = self.driver.initialize_connection(volume, connector)
        self.assertEqual(connection_info['driver_volume_type'], 'iscsi')
        properties = connection_info['data']
        self.driver.terminate_connection(volume, connector)
        self.driver._remove_destroy(self.VOLUME_NAME, self.PROJECT_ID)

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_clone(self):
        self.driver._discover_luns()
        self.driver._clone_lun(0, '/vol/vol/qtree/src', '/vol/vol/qtree/dst',
                               False)

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_clone_fail(self):
        self.driver._discover_luns()
        self.driver._is_clone_done(0, '0', 'xxx')

    def test_cloned_volume_size_fail(self):
        volume_clone_fail = {'name': 'fail', 'size': '2'}
        volume_src = {'name': 'source_vol', 'size': '1'}
        try:
            self.driver.create_cloned_volume(volume_clone_fail,
                                             volume_src)
            raise AssertionError()
        except VolumeBackendAPIException:
            pass


WSDL_HEADER_CMODE = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
 xmlns:na="http://cloud.netapp.com/"
xmlns:xsd="http://www.w3.org/2001/XMLSchema"
xmlns="http://schemas.xmlsoap.org/wsdl/"
targetNamespace="http://cloud.netapp.com/" name="CloudStorageService">
"""

WSDL_TYPES_CMODE = """<types>
<xs:schema xmlns:na="http://cloud.netapp.com/"
xmlns:xs="http://www.w3.org/2001/XMLSchema" version="1.0"
targetNamespace="http://cloud.netapp.com/">

      <xs:element name="ProvisionLun">
        <xs:complexType>
          <xs:all>
            <xs:element name="Name" type="xs:string"/>
            <xs:element name="Size" type="xsd:long"/>
            <xs:element name="Metadata" type="na:Metadata" minOccurs="0"
              maxOccurs="unbounded"/>
          </xs:all>
        </xs:complexType>
      </xs:element>
      <xs:element name="ProvisionLunResult">
        <xs:complexType>
          <xs:all>
            <xs:element name="Lun" type="na:Lun"/>
          </xs:all>
        </xs:complexType>
      </xs:element>

      <xs:element name="DestroyLun">
        <xs:complexType>
          <xs:all>
            <xs:element name="Handle" type="xsd:string"/>
          </xs:all>
        </xs:complexType>
      </xs:element>
      <xs:element name="DestroyLunResult">
        <xs:complexType>
          <xs:all/>
        </xs:complexType>
      </xs:element>

      <xs:element name="CloneLun">
        <xs:complexType>
          <xs:all>
            <xs:element name="Handle" type="xsd:string"/>
            <xs:element name="NewName" type="xsd:string"/>
            <xs:element name="Metadata" type="na:Metadata" minOccurs="0"
              maxOccurs="unbounded"/>
          </xs:all>
        </xs:complexType>
      </xs:element>
      <xs:element name="CloneLunResult">
        <xs:complexType>
          <xs:all>
            <xs:element name="Lun" type="na:Lun"/>
          </xs:all>
        </xs:complexType>
      </xs:element>

      <xs:element name="MapLun">
        <xs:complexType>
          <xs:all>
            <xs:element name="Handle" type="xsd:string"/>
            <xs:element name="InitiatorType" type="xsd:string"/>
            <xs:element name="InitiatorName" type="xsd:string"/>
          </xs:all>
        </xs:complexType>
      </xs:element>
      <xs:element name="MapLunResult">
        <xs:complexType>
          <xs:all/>
        </xs:complexType>
      </xs:element>

      <xs:element name="UnmapLun">
        <xs:complexType>
          <xs:all>
            <xs:element name="Handle" type="xsd:string"/>
            <xs:element name="InitiatorType" type="xsd:string"/>
            <xs:element name="InitiatorName" type="xsd:string"/>
          </xs:all>
        </xs:complexType>
      </xs:element>
      <xs:element name="UnmapLunResult">
        <xs:complexType>
          <xs:all/>
        </xs:complexType>
      </xs:element>

      <xs:element name="ListLuns">
        <xs:complexType>
          <xs:all>
            <xs:element name="NameFilter" type="xsd:string" minOccurs="0"/>
          </xs:all>
        </xs:complexType>
      </xs:element>
      <xs:element name="ListLunsResult">
        <xs:complexType>
          <xs:all>
            <xs:element name="Lun" type="na:Lun" minOccurs="0"
              maxOccurs="unbounded"/>
          </xs:all>
        </xs:complexType>
      </xs:element>

      <xs:element name="GetLunTargetDetails">
        <xs:complexType>
          <xs:all>
            <xs:element name="Handle" type="xsd:string"/>
            <xs:element name="InitiatorType" type="xsd:string"/>
            <xs:element name="InitiatorName" type="xsd:string"/>
          </xs:all>
        </xs:complexType>
      </xs:element>
      <xs:element name="GetLunTargetDetailsResult">
        <xs:complexType>
          <xs:all>
            <xs:element name="TargetDetails" type="na:TargetDetails"
              minOccurs="0" maxOccurs="unbounded"/>
          </xs:all>
        </xs:complexType>
      </xs:element>

      <xs:complexType name="Metadata">
        <xs:sequence>
          <xs:element name="Key" type="xs:string"/>
          <xs:element name="Value" type="xs:string"/>
        </xs:sequence>
      </xs:complexType>

      <xs:complexType name="Lun">
        <xs:sequence>
          <xs:element name="Name" type="xs:string"/>
          <xs:element name="Size" type="xs:long"/>
          <xs:element name="Handle" type="xs:string"/>
          <xs:element name="Metadata" type="na:Metadata" minOccurs="0"
            maxOccurs="unbounded"/>
        </xs:sequence>
      </xs:complexType>

      <xs:complexType name="TargetDetails">
        <xs:sequence>
          <xs:element name="Address" type="xs:string"/>
          <xs:element name="Port" type="xs:int"/>
          <xs:element name="Portal" type="xs:int"/>
          <xs:element name="Iqn" type="xs:string"/>
          <xs:element name="LunNumber" type="xs:int"/>
        </xs:sequence>
      </xs:complexType>

    </xs:schema></types>"""

WSDL_TRAILER_CMODE = """<service name="CloudStorageService">
    <port name="CloudStoragePort" binding="na:CloudStorageBinding">
      <soap:address location="http://hostname:8080/ws/ntapcloud"/>
    </port>
  </service>
</definitions>"""

RESPONSE_PREFIX_CMODE = """<?xml version='1.0' encoding='UTF-8'?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
<soapenv:Body>"""

RESPONSE_SUFFIX_CMODE = """</soapenv:Body></soapenv:Envelope>"""

CMODE_APIS = ['ProvisionLun', 'DestroyLun', 'CloneLun', 'MapLun', 'UnmapLun',
              'ListLuns', 'GetLunTargetDetails']


class FakeCMODEServerHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """HTTP handler that fakes enough stuff to allow the driver to run"""

    def do_GET(s):
        """Respond to a GET request."""
        if '/ntap_cloud.wsdl' != s.path:
            s.send_response(404)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "application/wsdl+xml")
        s.end_headers()
        out = s.wfile
        out.write(WSDL_HEADER_CMODE)
        out.write(WSDL_TYPES_CMODE)
        for api in CMODE_APIS:
            out.write('<message name="%sRequest">' % api)
            out.write('<part element="na:%s" name="req"/>' % api)
            out.write('</message>')
            out.write('<message name="%sResponse">' % api)
            out.write('<part element="na:%sResult" name="res"/>' % api)
            out.write('</message>')
        out.write('<portType name="CloudStorage">')
        for api in CMODE_APIS:
            out.write('<operation name="%s">' % api)
            out.write('<input message="na:%sRequest"/>' % api)
            out.write('<output message="na:%sResponse"/>' % api)
            out.write('</operation>')
        out.write('</portType>')
        out.write('<binding name="CloudStorageBinding" '
                  'type="na:CloudStorage">')
        out.write('<soap:binding style="document" ' +
                  'transport="http://schemas.xmlsoap.org/soap/http"/>')
        for api in CMODE_APIS:
            out.write('<operation name="%s">' % api)
            out.write('<soap:operation soapAction=""/>')
            out.write('<input><soap:body use="literal"/></input>')
            out.write('<output><soap:body use="literal"/></output>')
            out.write('</operation>')
        out.write('</binding>')
        out.write(WSDL_TRAILER_CMODE)

    def do_POST(s):
        """Respond to a POST request."""
        if '/ws/ntapcloud' != s.path:
            s.send_response(404)
            s.end_headers
            return
        request_xml = s.rfile.read(int(s.headers['Content-Length']))
        ntap_ns = 'http://cloud.netapp.com/'
        nsmap = {'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/',
                 'na': ntap_ns}
        root = etree.fromstring(request_xml)

        body = root.xpath('/soapenv:Envelope/soapenv:Body',
                          namespaces=nsmap)[0]
        request = body.getchildren()[0]
        tag = request.tag
        if not tag.startswith('{' + ntap_ns + '}'):
            s.send_response(500)
            s.end_headers
            return
        api = tag[(2 + len(ntap_ns)):]
        if 'ProvisionLun' == api:
            body = """<ns:ProvisionLunResult xmlns:ns=
            "http://cloud.netapp.com/">
            <Lun><Name>lun1</Name><Size>20</Size>
             <Handle>1d9c006c-a406-42f6-a23f-5ed7a6dc33e3</Handle>
            <Metadata><Key>OsType</Key>
            <Value>linux</Value></Metadata></Lun>
            </ns:ProvisionLunResult>"""
        elif 'DestroyLun' == api:
            body = """<ns:DestroyLunResult xmlns:ns="http://cloud.netapp.com/"
             />"""
        elif 'CloneLun' == api:
            body = """<ns:CloneLunResult xmlns:ns="http://cloud.netapp.com/">
                     <Lun><Name>snapshot1</Name><Size>2</Size>
                     <Handle>98ea1791d228453899d422b4611642c3</Handle>
                     <Metadata><Key>OsType</Key>
                     <Value>linux</Value></Metadata>
                     </Lun></ns:CloneLunResult>"""
        elif 'MapLun' == api:
            body = """<ns1:MapLunResult xmlns:ns="http://cloud.netapp.com/"
             />"""
        elif 'Unmap' == api:
            body = """<ns1:UnmapLunResult xmlns:ns="http://cloud.netapp.com/"
             />"""
        elif 'ListLuns' == api:
            body = """<ns:ListLunsResult xmlns:ns="http://cloud.netapp.com/">
                 <Lun>
                 <Name>lun1</Name>
                 <Size>20</Size>
                 <Handle>asdjdnsd</Handle>
                 </Lun>
                 </ns:ListLunsResult>"""
        elif 'GetLunTargetDetails' == api:
            body = """<ns:GetLunTargetDetailsResult
            xmlns:ns="http://cloud.netapp.com/">
                    <TargetDetail>
                     <Address>1.2.3.4</Address>
                     <Port>3260</Port>
                     <Portal>1000</Portal>
                     <Iqn>iqn.199208.com.netapp:sn.123456789</Iqn>
                     <LunNumber>0</LunNumber>
                    </TargetDetail>
                    </ns:GetLunTargetDetailsResult>"""
        else:
            # Unknown API
            s.send_response(500)
            s.end_headers
            return
        s.send_response(200)
        s.send_header("Content-Type", "text/xml; charset=utf-8")
        s.end_headers()
        s.wfile.write(RESPONSE_PREFIX_CMODE)
        s.wfile.write(body)
        s.wfile.write(RESPONSE_SUFFIX_CMODE)


class FakeCmodeHTTPConnection(object):
    """A fake httplib.HTTPConnection for netapp tests

    Requests made via this connection actually get translated and routed into
    the fake Dfm handler above, we then turn the response into
    the httplib.HTTPResponse that the caller expects.
    """
    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, data=None, headers=None):
        if not headers:
            headers = {}
        req_str = '%s %s HTTP/1.1\r\n' % (method, path)
        for key, value in headers.iteritems():
            req_str += "%s: %s\r\n" % (key, value)
        if data:
            req_str += '\r\n%s' % data

        # NOTE(vish): normally the http transport normailizes from unicode
        sock = FakeHttplibSocket(req_str.decode("latin-1").encode("utf-8"))
        # NOTE(vish): stop the server from trying to look up address from
        #             the fake socket
        FakeCMODEServerHandler.address_string = lambda x: '127.0.0.1'
        self.app = FakeCMODEServerHandler(sock, '127.0.0.1:8080', None)

        self.sock = FakeHttplibSocket(sock.result)
        self.http_response = httplib.HTTPResponse(self.sock)

    def set_debuglevel(self, level):
        pass

    def getresponse(self):
        self.http_response.begin()
        return self.http_response

    def getresponsebody(self):
        return self.sock.result


class NetAppCmodeISCSIDriverTestCase(test.TestCase):
    """Test case for NetAppISCSIDriver"""
    volume = {'name': 'lun1', 'size': 2, 'volume_name': 'lun1',
              'os_type': 'linux', 'provider_location': 'lun1',
              'id': 'lun1', 'provider_auth': None, 'project_id': 'project',
              'display_name': None, 'display_description': 'lun1',
              'volume_type_id': None}
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
    volume_clone_fail = {'name': 'cl_fail', 'size': 1, 'volume_name': 'fail',
                         'os_type': 'linux', 'provider_location': 'cl_fail',
                         'id': 'lun1', 'provider_auth': None,
                         'project_id': 'project', 'display_name': None,
                         'display_description': 'lun1',
                         'volume_type_id': None}
    connector = {'initiator': 'iqn.1993-08.org.debian:01:10'}

    def setUp(self):
        super(NetAppCmodeISCSIDriverTestCase, self).setUp()
        self._custom_setup()

    def _custom_setup(self):
        driver = iscsi.NetAppCmodeISCSIDriver(
            configuration=create_configuration())
        self.stubs.Set(httplib, 'HTTPConnection', FakeCmodeHTTPConnection)
        driver._create_client(wsdl_url='http://localhost:8080/ntap_cloud.wsdl',
                              login='root', password='password',
                              hostname='localhost', port=8080, cache=False)
        self.driver = driver

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_connect(self):
        self.driver.check_for_setup_error()

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_create_destroy(self):
        self.driver.create_volume(self.volume)
        self.driver.delete_volume(self.volume)

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_create_vol_snapshot_destroy(self):
        self.driver.create_volume(self.volume)
        self.driver.create_snapshot(self.snapshot)
        self.driver.create_volume_from_snapshot(self.volume_sec, self.snapshot)
        self.driver.delete_snapshot(self.snapshot)
        self.driver.delete_volume(self.volume)

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_map_unmap(self):
        self.driver.create_volume(self.volume)
        updates = self.driver.create_export(None, self.volume)
        self.assertTrue(updates['provider_location'])
        self.volume['provider_location'] = updates['provider_location']

        connection_info = self.driver.initialize_connection(self.volume,
                                                            self.connector)
        self.assertEqual(connection_info['driver_volume_type'], 'iscsi')
        properties = connection_info['data']
        if not properties:
            raise AssertionError('Target portal is none')
        self.driver.terminate_connection(self.volume, self.connector)
        self.driver.delete_volume(self.volume)

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_fail_vol_from_snapshot_creation(self):
        self.driver.create_volume(self.volume)
        try:
            self.driver.create_volume_from_snapshot(self.volume,
                                                    self.snapshot_fail)
            raise AssertionError()
        except VolumeBackendAPIException:
            pass
        finally:
            self.driver.delete_volume(self.volume)

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_cloned_volume_destroy(self):
        self.driver.create_volume(self.volume)
        self.driver.create_cloned_volume(self.snapshot, self.volume)
        self.driver.delete_volume(self.snapshot)
        self.driver.delete_volume(self.volume)

    @test.skip_test("Failing due to suds error - skip until fixed")
    def test_fail_cloned_volume_creation(self):
        self.driver.create_volume(self.volume)
        try:
            self.driver.create_cloned_volume(self.volume_clone_fail,
                                             self.volume)
            raise AssertionError()
        except VolumeBackendAPIException:
            pass
        finally:
            self.driver.delete_volume(self.volume)


RESPONSE_PREFIX_DIRECT_CMODE = """<?xml version='1.0' encoding='UTF-8' ?>
<!DOCTYPE netapp SYSTEM 'file:/etc/netapp_gx.dtd'>"""

RESPONSE_PREFIX_DIRECT_7MODE = """<?xml version='1.0' encoding='UTF-8' ?>
<!DOCTYPE netapp SYSTEM "/na_admin/netapp_filer.dtd">"""

RESPONSE_PREFIX_DIRECT = """
<netapp version='1.15' xmlns='http://www.netapp.com/filer/admin'>"""

RESPONSE_SUFFIX_DIRECT = """</netapp>"""


class FakeDirectCMODEServerHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """HTTP handler that fakes enough stuff to allow the driver to run"""

    def do_GET(s):
        """Respond to a GET request."""
        if '/servlets/netapp.servlets.admin.XMLrequest_filer' != s.path:
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
        if '/servlets/netapp.servlets.admin.XMLrequest_filer' != s.path:
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
                <online>true</online><path>/vol/navneet/lun2</path>
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
            if query:
                igroup_info = FakeDirectCMODEServerHandler._get_child_by_name(
                    query, 'initiator-group-info')
                if igroup_info:
                    inits = FakeDirectCMODEServerHandler._get_child_by_name(
                        igroup_info, 'initiators')
                    if inits:
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

    @staticmethod
    def _get_child_by_name(self, name):
        for child in self.iterchildren():
            if child.tag == name or etree.QName(child.tag).localname == name:
                return child
        return None

    @staticmethod
    def _get_child_content(self, name):
        """Get the content of the child"""
        for child in self.iterchildren():
            if child.tag == name or etree.QName(child.tag).localname == name:
                return child.text
        return None


class FakeDirectCmodeHTTPConnection(object):
    """A fake httplib.HTTPConnection for netapp tests

    Requests made via this connection actually get translated and routed into
    the fake direct handler above, we then turn the response into
    the httplib.HTTPResponse that the caller expects.
    """
    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, data=None, headers=None):
        if not headers:
            headers = {}
        req_str = '%s %s HTTP/1.1\r\n' % (method, path)
        for key, value in headers.iteritems():
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
        self.http_response = httplib.HTTPResponse(self.sock)

    def set_debuglevel(self, level):
        pass

    def getresponse(self):
        self.http_response.begin()
        return self.http_response

    def getresponsebody(self):
        return self.sock.result


class NetAppDirectCmodeISCSIDriverTestCase(NetAppCmodeISCSIDriverTestCase):
    """Test case for NetAppISCSIDriver"""

    vol_fail = {'name': 'lun_fail', 'size': 10000, 'volume_name': 'lun1',
                'os_type': 'linux', 'provider_location': 'lun1',
                'id': 'lun1', 'provider_auth': None, 'project_id': 'project',
                'display_name': None, 'display_description': 'lun1',
                'volume_type_id': None}

    def setUp(self):
        super(NetAppDirectCmodeISCSIDriverTestCase, self).setUp()

    def _custom_setup(self):
        driver = iscsi.NetAppDirectCmodeISCSIDriver(
            configuration=create_configuration())
        self.stubs.Set(httplib, 'HTTPConnection',
                       FakeDirectCmodeHTTPConnection)
        driver._create_client(transport_type='http',
                              login='admin', password='pass',
                              hostname='127.0.0.1',
                              port='80')
        driver.vserver = 'openstack'
        driver.client.set_api_version(1, 15)
        self.driver = driver

    def test_map_by_creating_igroup(self):
        self.driver.create_volume(self.volume)
        updates = self.driver.create_export(None, self.volume)
        self.assertTrue(updates['provider_location'])
        self.volume['provider_location'] = updates['provider_location']
        connector_new = {'initiator': 'iqn.1993-08.org.debian:01:1001'}
        connection_info = self.driver.initialize_connection(self.volume,
                                                            connector_new)
        self.assertEqual(connection_info['driver_volume_type'], 'iscsi')
        properties = connection_info['data']
        if not properties:
            raise AssertionError('Target portal is none')

    def test_fail_create_vol(self):
        self.assertRaises(VolumeBackendAPIException,
                          self.driver.create_volume, self.vol_fail)


class FakeDirect7MODEServerHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """HTTP handler that fakes enough stuff to allow the driver to run"""

    def do_GET(s):
        """Respond to a GET request."""
        if '/servlets/netapp.servlets.admin.XMLrequest_filer' != s.path:
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
        if '/servlets/netapp.servlets.admin.XMLrequest_filer' != s.path:
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
        <path>/vol/vol1/clone1</path>
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
        s.wfile.write(body)
        s.wfile.write(RESPONSE_SUFFIX_DIRECT)


class FakeDirect7modeHTTPConnection(object):
    """A fake httplib.HTTPConnection for netapp tests

    Requests made via this connection actually get translated and routed into
    the fake direct handler above, we then turn the response into
    the httplib.HTTPResponse that the caller expects.
    """
    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, data=None, headers=None):
        if not headers:
            headers = {}
        req_str = '%s %s HTTP/1.1\r\n' % (method, path)
        for key, value in headers.iteritems():
            req_str += "%s: %s\r\n" % (key, value)
        if data:
            req_str += '\r\n%s' % data

        # NOTE(vish): normally the http transport normailizes from unicode
        sock = FakeHttplibSocket(req_str.decode("latin-1").encode("utf-8"))
        # NOTE(vish): stop the server from trying to look up address from
        #             the fake socket
        FakeDirect7MODEServerHandler.address_string = lambda x: '127.0.0.1'
        self.app = FakeDirect7MODEServerHandler(sock, '127.0.0.1:80', None)

        self.sock = FakeHttplibSocket(sock.result)
        self.http_response = httplib.HTTPResponse(self.sock)

    def set_debuglevel(self, level):
        pass

    def getresponse(self):
        self.http_response.begin()
        return self.http_response

    def getresponsebody(self):
        return self.sock.result


class NetAppDirect7modeISCSIDriverTestCase_NV(
        NetAppDirectCmodeISCSIDriverTestCase):
    """Test case for NetAppISCSIDriver
       No vfiler
    """
    def setUp(self):
        super(NetAppDirect7modeISCSIDriverTestCase_NV, self).setUp()

    def _custom_setup(self):
        driver = iscsi.NetAppDirect7modeISCSIDriver(
            configuration=create_configuration())
        self.stubs.Set(httplib,
                       'HTTPConnection', FakeDirect7modeHTTPConnection)
        driver._create_client(transport_type='http',
                              login='admin', password='pass',
                              hostname='127.0.0.1',
                              port='80')
        driver.vfiler = None
        driver.volume_list = None
        self.driver = driver

    def test_create_on_select_vol(self):
        self.driver.volume_list = ['vol0', 'vol1']
        self.driver.create_volume(self.volume)
        self.driver.delete_volume(self.volume)
        self.driver.volume_list = []

    def test_create_fail_on_select_vol(self):
        self.driver.volume_list = ['vol2', 'vol3']
        success = False
        try:
            self.driver.create_volume(self.volume)
        except VolumeBackendAPIException:
            success = True
            pass
        finally:
            self.driver.volume_list = []
        if not success:
            raise AssertionError('Failed creating on selected volumes')


class NetAppDirect7modeISCSIDriverTestCase_WV(
        NetAppDirect7modeISCSIDriverTestCase_NV):
    """Test case for NetAppISCSIDriver
       With vfiler
    """
    def setUp(self):
        super(NetAppDirect7modeISCSIDriverTestCase_WV, self).setUp()

    def _custom_setup(self):
        driver = iscsi.NetAppDirect7modeISCSIDriver(
            configuration=create_configuration())
        self.stubs.Set(httplib, 'HTTPConnection',
                       FakeDirect7modeHTTPConnection)
        driver._create_client(transport_type='http',
                              login='admin', password='pass',
                              hostname='127.0.0.1',
                              port='80')
        driver.vfiler = 'vfiler'
        driver.client.set_api_version(1, 7)
        driver.volume_list = None
        self.driver = driver
