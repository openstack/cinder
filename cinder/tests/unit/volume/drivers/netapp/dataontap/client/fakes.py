# Copyright (c) - 2015, Tom Barron.  All rights reserved.
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


from lxml import etree
import mock
from six.moves import urllib

import cinder.volume.drivers.netapp.dataontap.client.api as netapp_api


FAKE_VOL_XML = """<volume-info xmlns='http://www.netapp.com/filer/admin'>
    <name>open123</name>
    <state>online</state>
    <size-total>0</size-total>
    <size-used>0</size-used>
    <size-available>0</size-available>
    <is-inconsistent>false</is-inconsistent>
    <is-invalid>false</is-invalid>
    </volume-info>"""

FAKE_XML1 = """<options>\
<test1>abc</test1>\
<test2>abc</test2>\
</options>"""

FAKE_XML2 = """<root><options>somecontent</options></root>"""

FAKE_NA_ELEMENT = netapp_api.NaElement(etree.XML(FAKE_VOL_XML))

FAKE_INVOKE_DATA = 'somecontent'

FAKE_XML_STR = 'abc'

FAKE_API_NAME = 'volume-get-iter'

FAKE_API_NAME_ELEMENT = netapp_api.NaElement(FAKE_API_NAME)

FAKE_NA_SERVER_STR = '127.0.0.1'

FAKE_NA_SERVER = netapp_api.NaServer(FAKE_NA_SERVER_STR)

FAKE_NA_SERVER_API_1_5 = netapp_api.NaServer(FAKE_NA_SERVER_STR)
FAKE_NA_SERVER_API_1_5.set_vfiler('filer')
FAKE_NA_SERVER_API_1_5.set_api_version(1, 5)


FAKE_NA_SERVER_API_1_14 = netapp_api.NaServer(FAKE_NA_SERVER_STR)
FAKE_NA_SERVER_API_1_14.set_vserver('server')
FAKE_NA_SERVER_API_1_14.set_api_version(1, 14)


FAKE_NA_SERVER_API_1_20 = netapp_api.NaServer(FAKE_NA_SERVER_STR)
FAKE_NA_SERVER_API_1_20.set_vfiler('filer')
FAKE_NA_SERVER_API_1_20.set_vserver('server')
FAKE_NA_SERVER_API_1_20.set_api_version(1, 20)


FAKE_QUERY = {'volume-attributes': None}

FAKE_DES_ATTR = {'volume-attributes': ['volume-id-attributes',
                                       'volume-space-attributes',
                                       'volume-state-attributes',
                                       'volume-qos-attributes']}

FAKE_CALL_ARGS_LIST = [mock.call(80), mock.call(8088), mock.call(443),
                       mock.call(8488)]

FAKE_RESULT_API_ERR_REASON = netapp_api.NaElement('result')
FAKE_RESULT_API_ERR_REASON.add_attr('errno', '000')
FAKE_RESULT_API_ERR_REASON.add_attr('reason', 'fake_reason')

FAKE_RESULT_API_ERRNO_INVALID = netapp_api.NaElement('result')
FAKE_RESULT_API_ERRNO_INVALID.add_attr('errno', '000')

FAKE_RESULT_API_ERRNO_VALID = netapp_api.NaElement('result')
FAKE_RESULT_API_ERRNO_VALID.add_attr('errno', '14956')

FAKE_RESULT_SUCCESS = netapp_api.NaElement('result')
FAKE_RESULT_SUCCESS.add_attr('status', 'passed')

FAKE_HTTP_OPENER = urllib.request.build_opener()

GET_OPERATIONAL_NETWORK_INTERFACE_ADDRESSES_RESPONSE = etree.XML("""
    <results status="passed">
        <num-records>2</num-records>
        <attributes-list>
            <net-interface-info>
                <address>%(address1)s</address>
            </net-interface-info>
            <net-interface-info>
                <address>%(address2)s</address>
            </net-interface-info>
        </attributes-list>
    </results>
""" % {"address1": "1.2.3.4", "address2": "99.98.97.96"})

VOLUME_LIST_INFO_RESPONSE = etree.XML("""
  <results status="passed">
    <volumes>
      <volume-info>
        <name>vol0</name>
        <block-type>64_bit</block-type>
        <state>online</state>
        <size-total>1441193750528</size-total>
        <size-used>3161096192</size-used>
        <size-available>1438032654336</size-available>
        <percentage-used>0</percentage-used>
        <owning-vfiler>vfiler0</owning-vfiler>
        <containing-aggregate>aggr0</containing-aggregate>
        <space-reserve>volume</space-reserve>
        <space-reserve-enabled>true</space-reserve-enabled>
        <is-inconsistent>false</is-inconsistent>
        <is-unrecoverable>false</is-unrecoverable>
        <is-invalid>false</is-invalid>
      </volume-info>
      <volume-info>
        <name>vol1</name>
        <block-type>64_bit</block-type>
        <state>online</state>
        <size-total>1441193750528</size-total>
        <size-used>3161096192</size-used>
        <size-available>1438032654336</size-available>
        <percentage-used>0</percentage-used>
        <owning-vfiler>vfiler0</owning-vfiler>
        <containing-aggregate>aggr0</containing-aggregate>
        <space-reserve>volume</space-reserve>
        <space-reserve-enabled>true</space-reserve-enabled>
        <is-inconsistent>false</is-inconsistent>
        <is-unrecoverable>false</is-unrecoverable>
        <is-invalid>false</is-invalid>
      </volume-info>
      <volume-info>
        <name>vol2</name>
        <block-type>64_bit</block-type>
        <state>offline</state>
        <size-total>1441193750528</size-total>
        <size-used>3161096192</size-used>
        <size-available>1438032654336</size-available>
        <percentage-used>0</percentage-used>
        <owning-vfiler>vfiler0</owning-vfiler>
        <containing-aggregate>aggr0</containing-aggregate>
        <space-reserve>volume</space-reserve>
        <space-reserve-enabled>true</space-reserve-enabled>
        <is-inconsistent>false</is-inconsistent>
        <is-unrecoverable>false</is-unrecoverable>
        <is-invalid>false</is-invalid>
      </volume-info>
      <volume-info>
        <name>vol3</name>
        <block-type>64_bit</block-type>
        <state>online</state>
        <size-total>1441193750528</size-total>
        <size-used>3161096192</size-used>
        <size-available>1438032654336</size-available>
        <percentage-used>0</percentage-used>
        <owning-vfiler>vfiler0</owning-vfiler>
        <containing-aggregate>aggr0</containing-aggregate>
        <space-reserve>volume</space-reserve>
        <space-reserve-enabled>true</space-reserve-enabled>
        <is-inconsistent>false</is-inconsistent>
        <is-unrecoverable>false</is-unrecoverable>
        <is-invalid>false</is-invalid>
      </volume-info>
    </volumes>
  </results>
""")
