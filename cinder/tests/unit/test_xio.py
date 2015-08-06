# Copyright (c) 2014 X-IO Technologies.
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

import mock
from oslo_log import log as logging

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import utils
from cinder.volume.drivers import xio
from cinder.volume import qos_specs
from cinder.volume import volume_types

LOG = logging.getLogger("cinder.volume.driver")

ISE_IP1 = '10.12.12.1'
ISE_IP2 = '10.11.12.2'
ISE_ISCSI_IP1 = '1.2.3.4'
ISE_ISCSI_IP2 = '1.2.3.5'

ISE_GID = 'isegid'
ISE_IQN = ISE_GID
ISE_WWN1 = ISE_GID + '1'
ISE_WWN2 = ISE_GID + '2'
ISE_WWN3 = ISE_GID + '3'
ISE_WWN4 = ISE_GID + '4'
ISE_TARGETS = [ISE_WWN1, ISE_WWN2, ISE_WWN3, ISE_WWN4]
ISE_INIT_TARGET_MAP = {'init_wwn1': ISE_TARGETS,
                       'init_wwn2': ISE_TARGETS}

VOLUME_SIZE = 10
NEW_VOLUME_SIZE = 20

VOLUME1 = {'id': '1', 'name': 'volume1',
           'size': VOLUME_SIZE, 'volume_type_id': 'type1'}

VOLUME2 = {'id': '2', 'name': 'volume2',
           'size': VOLUME_SIZE, 'volume_type_id': 'type2',
           'provider_auth': 'CHAP abc abc'}

VOLUME3 = {'id': '3', 'name': 'volume3',
           'size': VOLUME_SIZE, 'volume_type_id': None}

SNAPSHOT1 = {'name': 'snapshot1',
             'volume_name': VOLUME1['name'],
             'volume_type_id': 'type3'}

CLONE1 = {'id': '3', 'name': 'clone1',
          'size': VOLUME_SIZE, 'volume_type_id': 'type4'}

HOST1 = 'host1'

HOST2 = 'host2'

ISCSI_CONN1 = {'initiator': 'init_iqn1',
               'host': HOST1}

ISCSI_CONN2 = {'initiator': 'init_iqn2',
               'host': HOST2}

FC_CONN1 = {'wwpns': ['init_wwn1', 'init_wwn2'],
            'host': HOST1}

FC_CONN2 = {'wwpns': ['init_wwn3', 'init_wwn4'],
            'host': HOST2}

ISE_HTTP_IP = 'http://' + ISE_IP1

ISE_HOST_LOCATION = '/storage/hosts/1'
ISE_HOST_LOCATION_URL = ISE_HTTP_IP + ISE_HOST_LOCATION

ISE_VOLUME1_LOCATION = '/storage/volumes/volume1'
ISE_VOLUME1_LOCATION_URL = ISE_HTTP_IP + ISE_VOLUME1_LOCATION
ISE_VOLUME2_LOCATION = '/storage/volumes/volume2'
ISE_VOLUME2_LOCATION_URL = ISE_HTTP_IP + ISE_VOLUME2_LOCATION
ISE_VOLUME3_LOCATION = '/storage/volumes/volume3'
ISE_VOLUME3_LOCATION_URL = ISE_HTTP_IP + ISE_VOLUME3_LOCATION

ISE_SNAPSHOT_LOCATION = '/storage/volumes/snapshot1'
ISE_SNAPSHOT_LOCATION_URL = ISE_HTTP_IP + ISE_SNAPSHOT_LOCATION

ISE_CLONE_LOCATION = '/storage/volumes/clone1'
ISE_CLONE_LOCATION_URL = ISE_HTTP_IP + ISE_CLONE_LOCATION

ISE_ALLOCATION_LOCATION = '/storage/allocations/a1'
ISE_ALLOCATION_LOCATION_URL = ISE_HTTP_IP + ISE_ALLOCATION_LOCATION

ISE_GET_QUERY_XML =\
    """<array>
        <globalid>ABC12345</globalid>
        <capabilities>
            <capability value="3" string="Storage" type="source"/>
            <capability value="49003" string="Volume Affinity"/>
            <capability value="49004" string="Volume Quality of Service IOPS"/>
            <capability value="49005" string="Thin Provisioning"/>
            <capability value="49006" string="Clones" type="source"/>
        </capabilities>
        <controllers>
            <controller>
                <ipaddress>%s</ipaddress>
                <rank value="1"/>
            </controller>
            <controller>
                <ipaddress>%s</ipaddress>
                <rank value="0"/>
            </controller>
        </controllers>
       </array>""" % (ISE_IP1, ISE_IP2)

ISE_GET_QUERY_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_QUERY_XML.split())}

ISE_GET_QUERY_NO_CAP_XML =\
    """<array>
        <globalid>ABC12345</globalid>
        <controllers>
            <controller>
                <ipaddress>%s</ipaddress>
                <rank value="1"/>
            </controller>
            <controller>
                <ipaddress>%s</ipaddress>
                <rank value="0"/>
            </controller>
        </controllers>
       </array>""" % (ISE_IP1, ISE_IP2)

ISE_GET_QUERY_NO_CAP_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_QUERY_NO_CAP_XML.split())}

ISE_GET_QUERY_NO_CTRL_XML =\
    """<array>
        <globalid>ABC12345</globalid>
        <capabilities>
            <capability value="3" string="Storage" type="source"/>
            <capability value="49003" string="Volume Affinity"/>
            <capability value="49004" string="Volume Quality of Service IOPS"/>
            <capability value="49005" string="Thin Provisioning"/>
            <capability value="49006" string="Clones" type="source"/>
            <capability value="49007" string="Thin clones" type="source"/>
            <capability value="49007" string="Thin clones" type="source"/>
        </capabilities>
       </array>"""

ISE_GET_QUERY_NO_CTRL_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_QUERY_NO_CTRL_XML.split())}

ISE_GET_QUERY_NO_IP_XML =\
    """<array>
        <globalid>ABC12345</globalid>
        <capabilities>
            <test value="1"/>
            <capability value="3" string="Storage" type="source"/>
            <capability value="49003" string="Volume Affinity"/>
            <capability value="49004" string="Volume Quality of Service IOPS"/>
            <capability value="49005" string="Thin Provisioning"/>
            <capability value="49006" string="Clones" type="source"/>
            <capability value="49007" string="Thin clones" type="source"/>
            <capability value="49007" string="Thin clones" type="source"/>
        </capabilities>
        <controllers>
            <test value="2"/>
            <controller>
                <rank value="1"/>
            </controller>
            <controller>
                <rank value="0"/>
            </controller>
        </controllers>
       </array>"""

ISE_GET_QUERY_NO_IP_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_QUERY_NO_IP_XML.split())}

ISE_GET_QUERY_NO_GID_XML =\
    """<array>
        <capabilities>
            <capability value="3" string="Storage" type="source"/>
            <capability value="49003" string="Volume Affinity"/>
            <capability value="49004" string="Volume Quality of Service IOPS"/>
            <capability value="49005" string="Thin Provisioning"/>
            <capability value="49006" string="Clones" type="source"/>
        </capabilities>
        <controllers>
            <controller>
                <ipaddress>%s</ipaddress>
                <rank value="1"/>
            </controller>
            <controller>
                <ipaddress>%s</ipaddress>
                <rank value="0"/>
            </controller>
        </controllers>
       </array>""" % (ISE_IP1, ISE_IP2)

ISE_GET_QUERY_NO_GID_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_QUERY_NO_GID_XML.split())}

ISE_GET_QUERY_NO_CLONE_XML =\
    """<array>
        <globalid>ABC12345</globalid>
        <capabilities>
            <capability value="3" string="Storage" type="source"/>
            <capability value="49003" string="Volume Affinity"/>
            <capability value="49004" string="Volume Quality of Service IOPS"/>
            <capability value="49005" string="Thin Provisioning"/>
        </capabilities>
        <controllers>
            <controller>
                <ipaddress>%s</ipaddress>
                <rank value="1"/>
            </controller>
            <controller>
                <ipaddress>%s</ipaddress>
                <rank value="0"/>
            </controller>
        </controllers>
       </array>""" % (ISE_IP1, ISE_IP2)

ISE_GET_QUERY_NO_CLONE_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_QUERY_NO_CLONE_XML.split())}

ISE_GET_STORAGE_POOLS_XML =\
    """
    <pools>
        <pool>
            <name>Pool 1</name>
            <id>1</id>
            <status value="0" string="Operational">
                <details value="0x00000000">
                    <detail>None</detail>
                </details>
            </status>
            <available total="60">
                <byredundancy>
                    <raid-0>60</raid-0>
                    <raid-1>30</raid-1>
                    <raid-5>45</raid-5>
                </byredundancy>
            </available>
            <used total="40">
                <byredundancy>
                    <raid-0>0</raid-0>
                    <raid-1>40</raid-1>
                    <raid-5>0</raid-5>
                </byredundancy>
            </used>
            <media>
                <medium>
                    <health>100</health>
                    <tier value="4" string="Hybrid"/>
                </medium>
            </media>
            <volumes>
                <volume>
                    <globalid>volgid</globalid>
                </volume>
                <volume>
                    <globalid>volgid2</globalid>
                </volume>
            </volumes>
        </pool>
    </pools>
    """

ISE_GET_STORAGE_POOLS_RESP =\
    {'status': 200,
     'location': 'Pool location',
     'content': " ".join(ISE_GET_STORAGE_POOLS_XML.split())}

ISE_GET_VOL_STATUS_NO_VOL_NODE_XML =\
    """<volumes></volumes>"""

ISE_GET_VOL_STATUS_NO_VOL_NODE_RESP =\
    {'status': 200,
     'location': 'u%s' % ISE_VOLUME1_LOCATION_URL,
     'content': " ".join(ISE_GET_VOL_STATUS_NO_VOL_NODE_XML.split())}

ISE_GET_VOL_STATUS_NO_STATUS_XML =\
    """<volumes>
        <volume self="%s">
        </volume>
    </volumes>""" % (ISE_VOLUME1_LOCATION_URL)

ISE_GET_VOL_STATUS_NO_STATUS_RESP =\
    {'status': 200,
     'location': 'u%s' % ISE_VOLUME1_LOCATION_URL,
     'content': " ".join(ISE_GET_VOL_STATUS_NO_STATUS_XML.split())}

ISE_GET_VOL1_STATUS_XML =\
    """<volumes>
        <volume self="%s">
            <status value="0" string="Operational">
                <details>
                    <detail>Prepared</detail>
                </details>
            </status>
            <size>10</size>
        </volume>
    </volumes>""" % (ISE_VOLUME1_LOCATION_URL)

ISE_GET_VOL1_STATUS_RESP =\
    {'status': 200,
     'location': 'u%s' % ISE_VOLUME1_LOCATION_URL,
     'content': " ".join(ISE_GET_VOL1_STATUS_XML.split())}

ISE_GET_VOL2_STATUS_XML =\
    """<volumes>
        <volume self="%s">
            <status value="0" string="Operational">
                <details>
                    <detail>Prepared</detail>
                </details>
            </status>
        </volume>
    </volumes>""" % (ISE_VOLUME2_LOCATION_URL)

ISE_GET_VOL2_STATUS_RESP =\
    {'status': 200,
     'location': 'u%s' % ISE_VOLUME2_LOCATION_URL,
     'content': " ".join(ISE_GET_VOL2_STATUS_XML.split())}

ISE_GET_VOL3_STATUS_XML =\
    """<volumes>
        <volume self="%s">
            <status value="0" string="Operational">
                <details>
                    <detail>Prepared</detail>
                </details>
            </status>
        </volume>
    </volumes>""" % (ISE_VOLUME3_LOCATION_URL)

ISE_GET_VOL3_STATUS_RESP =\
    {'status': 200,
     'location': 'u%s' % ISE_VOLUME3_LOCATION_URL,
     'content': " ".join(ISE_GET_VOL3_STATUS_XML.split())}

ISE_GET_SNAP1_STATUS_XML =\
    """<volumes>
        <volume self="%s">
            <status value="0" string="Operational">
                <details>
                    <detail>Prepared</detail>
                </details>
            </status>
        </volume>
    </volumes>""" % (ISE_SNAPSHOT_LOCATION_URL)

ISE_GET_SNAP1_STATUS_RESP =\
    {'status': 200,
     'location': 'u%s' % ISE_SNAPSHOT_LOCATION_URL,
     'content': " ".join(ISE_GET_SNAP1_STATUS_XML.split())}

ISE_GET_CLONE1_STATUS_XML =\
    """<volumes>
        <volume self="%s">
            <status value="0" string="Operational">
                <details>
                    <detail>Prepared</detail>
                </details>
            </status>
        </volume>
    </volumes>""" % (ISE_CLONE_LOCATION_URL)

ISE_GET_CLONE1_STATUS_RESP =\
    {'status': 200,
     'location': 'u%s' % ISE_CLONE_LOCATION_URL,
     'content': " ".join(ISE_GET_CLONE1_STATUS_XML.split())}

ISE_CREATE_VOLUME_XML = """<volume/>"""

ISE_CREATE_VOLUME_RESP =\
    {'status': 201,
     'location': ISE_VOLUME1_LOCATION_URL,
     'content': " ".join(ISE_CREATE_VOLUME_XML.split())}

ISE_GET_IONETWORKS_XML =\
    """<chap>
        <chapin value="0" string="disabled">
            <username/>
            <password/>
        </chapin>
        <chapout value="0" string="disabled">
            <username/>
            <password/>
        </chapout>
       </chap>"""

ISE_GET_IONETWORKS_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_IONETWORKS_XML.split())}

ISE_GET_IONETWORKS_CHAP_XML =\
    """<chap>
        <chapin value="1" string="disabled">
            <username>abc</username>
            <password>abc</password>
        </chapin>
        <chapout value="0" string="disabled">
            <username/>
            <password/>
        </chapout>
       </chap>"""

ISE_GET_IONETWORKS_CHAP_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_IONETWORKS_CHAP_XML.split())}

ISE_DELETE_VOLUME_XML = """<volumes/>"""

ISE_DELETE_VOLUME_RESP =\
    {'status': 204,
     'location': '',
     'content': " ".join(ISE_DELETE_VOLUME_XML.split())}

ISE_GET_ALLOC_WITH_EP_XML =\
    """<allocations>
        <allocation self="%s">
            <volume>
                <volumename>%s</volumename>
            </volume>
            <endpoints>
                <hostname>%s</hostname>
            </endpoints>
            <lun>1</lun>
        </allocation>
       </allocations>""" %\
    (ISE_ALLOCATION_LOCATION_URL, VOLUME1['name'], HOST1)

ISE_GET_ALLOC_WITH_EP_RESP =\
    {'status': 200,
     'location': ISE_ALLOCATION_LOCATION_URL,
     'content': " ".join(ISE_GET_ALLOC_WITH_EP_XML.split())}

ISE_GET_ALLOC_WITH_NO_ALLOC_XML =\
    """<allocations self="%s"/>""" % ISE_ALLOCATION_LOCATION_URL

ISE_GET_ALLOC_WITH_NO_ALLOC_RESP =\
    {'status': 200,
     'location': ISE_ALLOCATION_LOCATION_URL,
     'content': " ".join(ISE_GET_ALLOC_WITH_NO_ALLOC_XML.split())}

ISE_DELETE_ALLOC_XML = """<allocations/>"""

ISE_DELETE_ALLOC_RESP =\
    {'status': 204,
     'location': '',
     'content': " ".join(ISE_DELETE_ALLOC_XML.split())}

ISE_GET_HOSTS_NOHOST_XML =\
    """<hosts self="http://ip/storage/hosts"/>"""

ISE_GET_HOSTS_NOHOST_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_HOSTS_NOHOST_XML.split())}

ISE_GET_HOSTS_HOST1_XML =\
    """<hosts self="http://ip/storage/hosts">
        <host self="http://ip/storage/hosts/1">
            <type>"OPENSTACK"</type>
            <name>%s</name>
            <id>1</id>
            <endpoints self="http://ip/storage/endpoints">
                <endpoint self="http://ip/storage/endpoints/ep1">
                    <globalid>init_wwn1</globalid>
                </endpoint>
                <endpoint self="http://ip/storage/endpoints/ep2">
                    <globalid>init_wwn2</globalid>
                </endpoint>
                <endpoint self="http://ip/storage/endpoints/ep1">
                    <globalid>init_iqn1</globalid>
                </endpoint>
            </endpoints>
        </host>
       </hosts>""" % HOST1

ISE_GET_HOSTS_HOST1_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_HOSTS_HOST1_XML.split())}

ISE_GET_HOSTS_HOST1_HOST_TYPE_XML =\
    """<hosts self="http://ip/storage/hosts">
        <host self="http://ip/storage/hosts/1">
            <type>"WINDOWS"</type>
            <name>%s</name>
            <id>1</id>
            <endpoints self="http://ip/storage/endpoints">
                <endpoint self="http://ip/storage/endpoints/ep1">
                    <globalid>init_wwn1</globalid>
                </endpoint>
                <endpoint self="http://ip/storage/endpoints/ep2">
                    <globalid>init_wwn2</globalid>
                </endpoint>
                <endpoint self="http://ip/storage/endpoints/ep1">
                    <globalid>init_iqn1</globalid>
                </endpoint>
            </endpoints>
        </host>
       </hosts>""" % HOST1

ISE_GET_HOSTS_HOST1_HOST_TYPE_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_HOSTS_HOST1_HOST_TYPE_XML.split())}

ISE_GET_HOSTS_HOST2_XML =\
    """<hosts self="http://ip/storage/hosts">
        <host self="http://ip/storage/hosts/2">
            <name>%s</name>
            <id>2</id>
            <endpoints self="http://ip/storage/endpoints">
                <endpoint self="http://ip/storage/endpoints/ep3">
                    <globalid>init_wwn3</globalid>
                </endpoint>
                <endpoint self="http://ip/storage/endpoints/ep4">
                    <globalid>init_wwn4</globalid>
                </endpoint>
                <endpoint self="http://ip/storage/endpoints/ep3">
                    <globalid>init_iqn2</globalid>
                </endpoint>
            </endpoints>
        </host>
       </hosts>""" % HOST2

ISE_GET_HOSTS_HOST2_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_HOSTS_HOST2_XML.split())}

ISE_CREATE_HOST_XML =\
    """<hosts self="http://ip/storage/hosts"/>"""

ISE_CREATE_HOST_RESP =\
    {'status': 201,
     'location': 'http://ip/storage/hosts/host1',
     'content': " ".join(ISE_CREATE_HOST_XML.split())}

ISE_CREATE_ALLOC_XML =\
    """<allocations self="http://ip/storage/allocations"/>"""

ISE_CREATE_ALLOC_RESP =\
    {'status': 201,
     'location': ISE_ALLOCATION_LOCATION_URL,
     'content': " ".join(ISE_CREATE_ALLOC_XML.split())}

ISE_GET_ENDPOINTS_XML =\
    """<endpoints self="http://ip/storage/endpoints">
        <endpoint type="array" self="http://ip/storage/endpoints/isegid">
                <globalid>isegid</globalid>
                <protocol>iSCSI</protocol>
                <array self="http://ip/storage/arrays/ise1">
                    <globalid>ise1</globalid>
                </array>
                <host/>
                <allocations self="http://ip/storage/allocations">
                    <allocation self="%s">
                        <globalid>
                            a1
                        </globalid>
                    </allocation>
                </allocations>
            </endpoint>
        <endpoint type="array" self="http://ip/storage/endpoints/isegid">
                <globalid>isegid</globalid>
                <protocol>Fibre Channel</protocol>
                <array self="http://ip/storage/arrays/ise1">
                    <globalid>ise1</globalid>
                </array>
                <host/>
                <allocations self="http://ip/storage/allocations">
                    <allocation self="%s">
                        <globalid>
                            a1
                        </globalid>
                    </allocation>
                </allocations>
            </endpoint>
        </endpoints>""" % (ISE_ALLOCATION_LOCATION_URL,
                           ISE_ALLOCATION_LOCATION_URL)

ISE_GET_ENDPOINTS_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_ENDPOINTS_XML.split())}

ISE_GET_CONTROLLERS_XML =\
    """<controllers self="http://ip/storage/arrays/controllers">
        <controller>
            <status/>
            <ioports>
                <ioport>
                    <ipaddresses>
                        <ipaddress>%s</ipaddress>
                    </ipaddresses>
                    <endpoint>
                        <globalid>isegid</globalid>
                    </endpoint>
                </ioport>
            </ioports>
            <fcports>
                <fcport>
                    <wwn>%s</wwn>
                </fcport>
                <fcport>
                    <wwn>%s</wwn>
                </fcport>
            </fcports>
        </controller>
        <controller>
            <status/>
            <ioports>
                <ioport>
                    <ipaddresses>
                        <ipaddress>%s</ipaddress>
                    </ipaddresses>
                    <endpoint>
                        <globalid>isegid</globalid>
                    </endpoint>
                </ioport>
            </ioports>
            <fcports>
                <fcport>
                    <wwn>%s</wwn>
                </fcport>
                <fcport>
                    <wwn>%s</wwn>
                </fcport>
            </fcports>
        </controller>
       </controllers>""" % (ISE_ISCSI_IP1, ISE_WWN1, ISE_WWN2,
                            ISE_ISCSI_IP2, ISE_WWN3, ISE_WWN4)

ISE_GET_CONTROLLERS_RESP =\
    {'status': 200,
     'location': '',
     'content': " ".join(ISE_GET_CONTROLLERS_XML.split())}

ISE_CREATE_SNAPSHOT_XML = """<snapshot/>"""

ISE_CREATE_SNAPSHOT_RESP =\
    {'status': 201,
     'location': ISE_SNAPSHOT_LOCATION_URL,
     'content': " ".join(ISE_CREATE_SNAPSHOT_XML.split())}

ISE_PREP_SNAPSHOT_XML = """<snapshot/>"""

ISE_PREP_SNAPSHOT_RESP =\
    {'status': 202,
     'location': ISE_SNAPSHOT_LOCATION_URL,
     'content': " ".join(ISE_PREP_SNAPSHOT_XML.split())}

ISE_MODIFY_VOLUME_XML = """<volume/>"""

ISE_MODIFY_VOLUME_RESP =\
    {'status': 201,
     'location': ISE_VOLUME1_LOCATION_URL,
     'content': " ".join(ISE_MODIFY_VOLUME_XML.split())}

ISE_MODIFY_HOST_XML = """<host/>"""

ISE_MODIFY_HOST_RESP =\
    {'status': 201,
     'location': ISE_HOST_LOCATION_URL,
     'content': " ".join(ISE_MODIFY_HOST_XML.split())}

ISE_BAD_CONNECTION_RESP =\
    {'status': 0,
     'location': '',
     'content': " "}

ISE_400_RESP =\
    {'status': 400,
     'location': '',
     'content': ""}

ISE_GET_VOL_STATUS_404_XML = \
    """<response value="404" index="3">VOLUME not found.</response>"""

ISE_GET_VOL_STATUS_404_RESP =\
    {'status': 404,
     'location': '',
     'content': " ".join(ISE_GET_VOL_STATUS_404_XML.split())}

ISE_400_INVALID_STATE_XML = \
    """<response value="400">Not in a valid state.</response>"""

ISE_400_INVALID_STATE_RESP =\
    {'status': 400,
     'location': '',
     'content': " ".join(ISE_400_INVALID_STATE_XML.split())}

ISE_409_CONFLICT_XML = \
    """<response value="409">Conflict</response>"""

ISE_409_CONFLICT_RESP =\
    {'status': 409,
     'location': '',
     'content': " ".join(ISE_409_CONFLICT_XML.split())}


DRIVER = "cinder.volume.drivers.xio.XIOISEDriver"


@mock.patch(DRIVER + "._opener", autospec=True)
class XIOISEDriverTestCase(object):

    # Test cases for X-IO volume driver

    def setUp(self):
        super(XIOISEDriverTestCase, self).setUp()

        # set good default values
        self.configuration = mock.Mock()
        self.configuration.san_ip = ISE_IP1
        self.configuration.san_user = 'fakeuser'
        self.configuration.san_password = 'fakepass'
        self.configuration.iscsi_ip_address = ISE_ISCSI_IP1
        self.configuration.driver_use_ssl = False
        self.configuration.ise_completion_retries = 30
        self.configuration.ise_connection_retries = 5
        self.configuration.ise_retry_interval = 1
        self.configuration.volume_backend_name = 'ise1'
        self.driver = None
        self.protocol = ''
        self.connector = None
        self.connection_failures = 0
        self.hostgid = ''
        self.use_response_table = 1

    def setup_test(self, protocol):
        self.protocol = protocol

        # set good default values
        if self.protocol == 'iscsi':
            self.configuration.ise_protocol = protocol
            self.connector = ISCSI_CONN1
            self.hostgid = self.connector['initiator']
        elif self.protocol == 'fibre_channel':
            self.configuration.ise_protocol = protocol
            self.connector = FC_CONN1
            self.hostgid = self.connector['wwpns'][0]

    def setup_driver(self):
        # this setups up driver object with previously set configuration values
        if self.configuration.ise_protocol == 'iscsi':
            self.driver =\
                xio.XIOISEISCSIDriver(configuration=self.configuration)
        elif self.configuration.ise_protocol == 'fibre_channel':
            self.driver =\
                xio.XIOISEFCDriver(configuration=self.configuration)
        elif self.configuration.ise_protocol == 'test_prot':
            # if test_prot specified override with correct protocol
            # used to bypass protocol specific driver
            self.configuration.ise_protocol = self.protocol
            self.driver = xio.XIOISEDriver(configuration=self.configuration)
        else:
            # Invalid protocol type
            raise exception.Invalid()

#################################
#         UNIT TESTS            #
#################################
    def test_do_setup(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP])
        self.driver.do_setup(None)

    def test_negative_do_setup_no_clone_support(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_NO_CLONE_RESP])
        self.assertRaises(exception.XIODriverException,
                          self.driver.do_setup, None)

    def test_negative_do_setup_no_capabilities(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_NO_CAP_RESP])
        self.assertRaises(exception.XIODriverException,
                          self.driver.do_setup, None)

    def test_negative_do_setup_no_ctrl(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_NO_CTRL_RESP])
        self.assertRaises(exception.XIODriverException,
                          self.driver.do_setup, None)

    def test_negative_do_setup_no_ipaddress(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_NO_IP_RESP])
        self.driver.do_setup(None)

    def test_negative_do_setup_bad_globalid_none(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_NO_GID_RESP])
        self.assertRaises(exception.XIODriverException,
                          self.driver.do_setup, None)

    def test_check_for_setup_error(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP])
        self.setup_driver()
        self.driver.check_for_setup_error()

    def test_negative_do_setup_bad_ip(self, mock_req):
        # set san_ip to bad value
        self.configuration.san_ip = ''
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP])
        self.setup_driver()
        self.assertRaises(exception.XIODriverException,
                          self.driver.check_for_setup_error)

    def test_negative_do_setup_bad_user_blank(self, mock_req):
        # set san_user to bad value
        self.configuration.san_login = ''
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP])
        self.setup_driver()
        self.assertRaises(exception.XIODriverException,
                          self.driver.check_for_setup_error)

    def test_negative_do_setup_bad_password_blank(self, mock_req):
        # set san_password to bad value
        self.configuration.san_password = ''
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP])
        self.setup_driver()
        self.assertRaises(exception.XIODriverException,
                          self.driver.check_for_setup_error)

    def test_get_volume_stats(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_STORAGE_POOLS_RESP])

        backend_name = self.configuration.volume_backend_name
        if self.configuration.ise_protocol == 'iscsi':
            protocol = 'iSCSI'
        else:
            protocol = 'fibre_channel'
        exp_result = {}
        exp_result = {'vendor_name': "X-IO",
                      'driver_version': "1.1.3",
                      'volume_backend_name': backend_name,
                      'reserved_percentage': 0,
                      'total_capacity_gb': 100,
                      'free_capacity_gb': 60,
                      'QoS_support': True,
                      'affinity': True,
                      'thin': False,
                      'pools': [{'pool_ise_name': "Pool 1",
                                 'pool_name': "1",
                                 'status': "Operational",
                                 'status_details': "None",
                                 'free_capacity_gb': 60,
                                 'free_capacity_gb_raid_0': 60,
                                 'free_capacity_gb_raid_1': 30,
                                 'free_capacity_gb_raid_5': 45,
                                 'allocated_capacity_gb': 40,
                                 'allocated_capacity_gb_raid_0': 0,
                                 'allocated_capacity_gb_raid_1': 40,
                                 'allocated_capacity_gb_raid_5': 0,
                                 'health': 100,
                                 'media': "Hybrid",
                                 'total_capacity_gb': 100,
                                 'QoS_support': True,
                                 'reserved_percentage': 0}],
                      'active_volumes': 2,
                      'storage_protocol': protocol}

        act_result = self.driver.get_volume_stats(True)
        self.assertDictMatch(exp_result, act_result)

    def test_get_volume_stats_ssl(self, mock_req):
        self.configuration.driver_use_ssl = True
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_STORAGE_POOLS_RESP])
        self.driver.get_volume_stats(True)

    def test_negative_get_volume_stats_bad_primary(self, mock_req):
        self.configuration.ise_connection_retries = 1
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_BAD_CONNECTION_RESP,
                                     ISE_GET_STORAGE_POOLS_RESP])
        self.driver.get_volume_stats(True)

    def test_create_volume(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        VOLUME1['volume_type_id'] = type_ref['id']
        self.setup_driver()
        if self.configuration.ise_protocol == 'iscsi':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_CREATE_VOLUME_RESP,
                                         ISE_GET_VOL1_STATUS_RESP,
                                         ISE_GET_IONETWORKS_RESP])
            exp_result = {}
            exp_result = {"provider_auth": ""}
            act_result = self.driver.create_volume(VOLUME1)
            self.assertDictMatch(exp_result, act_result)
        elif self.configuration.ise_protocol == 'fibre_channel':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_CREATE_VOLUME_RESP,
                                         ISE_GET_VOL1_STATUS_RESP])
            self.driver.create_volume(VOLUME1)

    def test_create_volume_chap(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        VOLUME1['volume_type_id'] = type_ref['id']
        self.setup_driver()
        if self.configuration.ise_protocol == 'iscsi':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_CREATE_VOLUME_RESP,
                                         ISE_GET_VOL1_STATUS_RESP,
                                         ISE_GET_IONETWORKS_CHAP_RESP])
            exp_result = {}
            exp_result = {"provider_auth": "CHAP abc abc"}
            act_result = self.driver.create_volume(VOLUME1)
            self.assertDictMatch(exp_result, act_result)
        elif self.configuration.ise_protocol == 'fibre_channel':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_CREATE_VOLUME_RESP,
                                         ISE_GET_VOL1_STATUS_RESP])
            self.driver.create_volume(VOLUME1)

    def test_create_volume_type_none(self, mock_req):
        self.setup_driver()
        if self.configuration.ise_protocol == 'iscsi':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_CREATE_VOLUME_RESP,
                                         ISE_GET_VOL1_STATUS_RESP,
                                         ISE_GET_IONETWORKS_RESP])
        elif self.configuration.ise_protocol == 'fibre_channel':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_CREATE_VOLUME_RESP,
                                         ISE_GET_VOL1_STATUS_RESP])
        self.driver.create_volume(VOLUME3)

    def test_delete_volume(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_ALLOC_WITH_EP_RESP,
                                     ISE_DELETE_ALLOC_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_DELETE_VOLUME_RESP,
                                     ISE_GET_VOL_STATUS_404_RESP])
        self.setup_driver()
        self.driver.delete_volume(VOLUME1)

    def test_delete_volume_delayed(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_ALLOC_WITH_EP_RESP,
                                     ISE_DELETE_ALLOC_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_DELETE_VOLUME_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_GET_VOL_STATUS_404_RESP])
        self.setup_driver()
        self.driver.delete_volume(VOLUME1)

    def test_delete_volume_timeout(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_ALLOC_WITH_EP_RESP,
                                     ISE_DELETE_ALLOC_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_DELETE_VOLUME_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_GET_VOL1_STATUS_RESP])

        self.configuration.ise_completion_retries = 3
        self.setup_driver()
        self.driver.delete_volume(VOLUME1)

    def test_delete_volume_none_existing(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_ALLOC_WITH_EP_RESP,
                                     ISE_DELETE_ALLOC_RESP,
                                     ISE_GET_VOL1_STATUS_RESP])
        self.setup_driver()
        self.driver.delete_volume(VOLUME2)

    def test_initialize_connection_positive(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_HOSTS_HOST2_RESP,
                                     ISE_CREATE_HOST_RESP,
                                     ISE_GET_HOSTS_HOST1_RESP,
                                     ISE_CREATE_ALLOC_RESP,
                                     ISE_GET_ALLOC_WITH_EP_RESP,
                                     ISE_GET_CONTROLLERS_RESP])
        self.setup_driver()

        exp_result = {}
        if self.configuration.ise_protocol == 'iscsi':
            exp_result = {"driver_volume_type": "iscsi",
                          "data": {"target_lun": '1',
                                   "volume_id": '1',
                                   "access_mode": 'rw',
                                   "target_discovered": False,
                                   "target_iqn": ISE_IQN,
                                   "target_portal": ISE_ISCSI_IP1 + ":3260"}}
        elif self.configuration.ise_protocol == 'fibre_channel':
            exp_result = {"driver_volume_type": "fibre_channel",
                          "data": {"target_lun": '1',
                                   "volume_id": '1',
                                   "access_mode": 'rw',
                                   "target_discovered": True,
                                   "initiator_target_map": ISE_INIT_TARGET_MAP,
                                   "target_wwn": ISE_TARGETS}}

        act_result =\
            self.driver.initialize_connection(VOLUME1, self.connector)
        self.assertDictMatch(exp_result, act_result)

    def test_initialize_connection_positive_host_type(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_HOSTS_HOST1_HOST_TYPE_RESP,
                                     ISE_MODIFY_HOST_RESP,
                                     ISE_CREATE_ALLOC_RESP,
                                     ISE_GET_ALLOC_WITH_EP_RESP,
                                     ISE_GET_CONTROLLERS_RESP])
        self.setup_driver()

        exp_result = {}
        if self.configuration.ise_protocol == 'iscsi':
            exp_result = {"driver_volume_type": "iscsi",
                          "data": {"target_lun": '1',
                                   "volume_id": '1',
                                   "access_mode": 'rw',
                                   "target_discovered": False,
                                   "target_iqn": ISE_IQN,
                                   "target_portal": ISE_ISCSI_IP1 + ":3260"}}
        elif self.configuration.ise_protocol == 'fibre_channel':
            exp_result = {"driver_volume_type": "fibre_channel",
                          "data": {"target_lun": '1',
                                   "volume_id": '1',
                                   "access_mode": 'rw',
                                   "target_discovered": True,
                                   "initiator_target_map": ISE_INIT_TARGET_MAP,
                                   "target_wwn": ISE_TARGETS}}

        act_result =\
            self.driver.initialize_connection(VOLUME1, self.connector)
        self.assertDictMatch(exp_result, act_result)

    def test_initialize_connection_positive_chap(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_HOSTS_HOST2_RESP,
                                     ISE_CREATE_HOST_RESP,
                                     ISE_GET_HOSTS_HOST1_RESP,
                                     ISE_CREATE_ALLOC_RESP,
                                     ISE_GET_ALLOC_WITH_EP_RESP,
                                     ISE_GET_CONTROLLERS_RESP])
        self.setup_driver()
        exp_result = {}
        if self.configuration.ise_protocol == 'iscsi':
            exp_result = {"driver_volume_type": "iscsi",
                          "data": {"target_lun": '1',
                                   "volume_id": '2',
                                   "access_mode": 'rw',
                                   "target_discovered": False,
                                   "target_iqn": ISE_IQN,
                                   "target_portal": ISE_ISCSI_IP1 + ":3260",
                                   'auth_method': 'CHAP',
                                   'auth_username': 'abc',
                                   'auth_password': 'abc'}}
        elif self.configuration.ise_protocol == 'fibre_channel':
            exp_result = {"driver_volume_type": "fibre_channel",
                          "data": {"target_lun": '1',
                                   "volume_id": '2',
                                   "access_mode": 'rw',
                                   "target_discovered": True,
                                   "initiator_target_map": ISE_INIT_TARGET_MAP,
                                   "target_wwn": ISE_TARGETS}}

        act_result =\
            self.driver.initialize_connection(VOLUME2, self.connector)
        self.assertDictMatch(exp_result, act_result)

    def test_initialize_connection_negative_no_host(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_HOSTS_HOST2_RESP,
                                     ISE_CREATE_HOST_RESP,
                                     ISE_GET_HOSTS_HOST2_RESP])
        self.setup_driver()
        self.assertRaises(exception.XIODriverException,
                          self.driver.initialize_connection,
                          VOLUME2, self.connector)

    def test_initialize_connection_negative_host_type(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_HOSTS_HOST1_HOST_TYPE_RESP,
                                     ISE_400_RESP])
        self.setup_driver()
        self.assertRaises(exception.XIODriverException,
                          self.driver.initialize_connection,
                          VOLUME2, self.connector)

    def test_terminate_connection_positive(self, mock_req):
        self.setup_driver()
        if self.configuration.ise_protocol == 'iscsi':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_GET_ALLOC_WITH_EP_RESP,
                                         ISE_DELETE_ALLOC_RESP,
                                         ISE_GET_ALLOC_WITH_EP_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_DELETE_ALLOC_RESP])
        elif self.configuration.ise_protocol == 'fibre_channel':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_GET_ALLOC_WITH_EP_RESP,
                                         ISE_DELETE_ALLOC_RESP,
                                         ISE_GET_ALLOC_WITH_EP_RESP,
                                         ISE_GET_CONTROLLERS_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_DELETE_ALLOC_RESP])
        self.driver.terminate_connection(VOLUME1, self.connector)

    def test_terminate_connection_positive_noalloc(self, mock_req):
        self.setup_driver()
        if self.configuration.ise_protocol == 'iscsi':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_GET_ALLOC_WITH_NO_ALLOC_RESP,
                                         ISE_GET_ALLOC_WITH_NO_ALLOC_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_DELETE_ALLOC_RESP])
        elif self.configuration.ise_protocol == 'fibre_channel':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_GET_ALLOC_WITH_NO_ALLOC_RESP,
                                         ISE_GET_ALLOC_WITH_NO_ALLOC_RESP,
                                         ISE_GET_CONTROLLERS_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_DELETE_ALLOC_RESP])
        self.driver.terminate_connection(VOLUME1, self.connector)

    def test_negative_terminate_connection_bad_host(self, mock_req):
        self.setup_driver()
        test_connector = {}
        if self.configuration.ise_protocol == 'iscsi':
            test_connector['initiator'] = 'bad_iqn'
            test_connector['host'] = ''
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP])
        elif self.configuration.ise_protocol == 'fibre_channel':
            test_connector['wwpns'] = 'bad_wwn'
            test_connector['host'] = ''
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_HOSTS_HOST1_RESP,
                                         ISE_GET_CONTROLLERS_RESP])

        self.driver.terminate_connection(VOLUME1, test_connector)

    def test_create_snapshot(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        SNAPSHOT1['volume_type_id'] = type_ref['id']

        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_PREP_SNAPSHOT_RESP,
                                     ISE_GET_SNAP1_STATUS_RESP,
                                     ISE_CREATE_SNAPSHOT_RESP,
                                     ISE_GET_SNAP1_STATUS_RESP])
        self.setup_driver()
        self.driver.create_snapshot(SNAPSHOT1)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_negative_create_snapshot_invalid_state_recover(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        SNAPSHOT1['volume_type_id'] = type_ref['id']

        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_400_INVALID_STATE_RESP,
                                     ISE_PREP_SNAPSHOT_RESP,
                                     ISE_GET_SNAP1_STATUS_RESP,
                                     ISE_CREATE_SNAPSHOT_RESP,
                                     ISE_GET_SNAP1_STATUS_RESP])
        self.setup_driver()
        self.driver.create_snapshot(SNAPSHOT1)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_negative_create_snapshot_invalid_state_norecover(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        SNAPSHOT1['volume_type_id'] = type_ref['id']

        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_400_INVALID_STATE_RESP,
                                     ISE_400_INVALID_STATE_RESP,
                                     ISE_400_INVALID_STATE_RESP,
                                     ISE_400_INVALID_STATE_RESP,
                                     ISE_400_INVALID_STATE_RESP])
        self.configuration.ise_completion_retries = 5
        self.setup_driver()
        self.assertRaises(exception.XIODriverException,
                          self.driver.create_snapshot, SNAPSHOT1)

    def test_negative_create_snapshot_conflict(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        SNAPSHOT1['volume_type_id'] = type_ref['id']

        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_409_CONFLICT_RESP])
        self.configuration.ise_completion_retries = 1
        self.setup_driver()
        self.assertRaises(exception.XIODriverException,
                          self.driver.create_snapshot, SNAPSHOT1)

    def test_delete_snapshot(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_ALLOC_WITH_EP_RESP,
                                     ISE_DELETE_ALLOC_RESP,
                                     ISE_GET_SNAP1_STATUS_RESP,
                                     ISE_DELETE_VOLUME_RESP])
        self.setup_driver()
        self.driver.delete_snapshot(SNAPSHOT1)

    def test_clone_volume(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        VOLUME1['volume_type_id'] = type_ref['id']
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_PREP_SNAPSHOT_RESP,
                                     ISE_GET_SNAP1_STATUS_RESP,
                                     ISE_CREATE_SNAPSHOT_RESP,
                                     ISE_GET_SNAP1_STATUS_RESP])
        self.setup_driver()
        self.driver.create_cloned_volume(CLONE1, VOLUME1)

    def test_extend_volume(self, mock_req):
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_MODIFY_VOLUME_RESP])
        self.setup_driver()
        self.driver.extend_volume(VOLUME1, NEW_VOLUME_SIZE)

    def test_retype_volume(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        VOLUME1['volume_type_id'] = type_ref['id']
        # New volume type
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "5",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT2', extra_specs)
        specs = {'qos:minIOPS': '30',
                 'qos:maxIOPS': '3000',
                 'qos:burstIOPS': '10000'}
        qos = qos_specs.create(ctxt, 'fake-qos2', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])

        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_MODIFY_VOLUME_RESP])
        self.setup_driver()
        self.driver.retype(ctxt, VOLUME1, type_ref, 0, 0)

    def test_create_volume_from_snapshot(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        SNAPSHOT1['volume_type_id'] = type_ref['id']
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_SNAP1_STATUS_RESP,
                                     ISE_PREP_SNAPSHOT_RESP,
                                     ISE_GET_VOL1_STATUS_RESP,
                                     ISE_CREATE_SNAPSHOT_RESP,
                                     ISE_GET_VOL1_STATUS_RESP])
        self.setup_driver()
        self.driver.create_volume_from_snapshot(VOLUME1, SNAPSHOT1)

    def test_manage_existing(self, mock_req):
        ctxt = context.get_admin_context()
        extra_specs = {"Feature:Pool": "1",
                       "Feature:Raid": "1",
                       "Affinity:Type": "flash",
                       "Alloc:Type": "thick"}
        type_ref = volume_types.create(ctxt, 'VT1', extra_specs)
        specs = {'qos:minIOPS': '20',
                 'qos:maxIOPS': '2000',
                 'qos:burstIOPS': '5000'}
        qos = qos_specs.create(ctxt, 'fake-qos', specs)
        qos_specs.associate_qos_with_type(ctxt, qos['id'], type_ref['id'])
        VOLUME1['volume_type_id'] = type_ref['id']
        self.setup_driver()
        if self.configuration.ise_protocol == 'iscsi':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_VOL1_STATUS_RESP,
                                         ISE_MODIFY_VOLUME_RESP,
                                         ISE_GET_IONETWORKS_RESP])
        elif self.configuration.ise_protocol == 'fibre_channel':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_VOL1_STATUS_RESP,
                                         ISE_MODIFY_VOLUME_RESP])
        self.driver.manage_existing(VOLUME1, {'source-name': 'testvol'})

    def test_manage_existing_no_source_name(self, mock_req):
        self.setup_driver()
        if self.configuration.ise_protocol == 'iscsi':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_VOL1_STATUS_RESP,
                                         ISE_MODIFY_VOLUME_RESP,
                                         ISE_GET_IONETWORKS_RESP])
        elif self.configuration.ise_protocol == 'fibre_channel':
            mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                         ISE_GET_VOL1_STATUS_RESP,
                                         ISE_MODIFY_VOLUME_RESP])
        self.assertRaises(exception.XIODriverException,
                          self.driver.manage_existing, VOLUME1, {})

    def test_manage_existing_get_size(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP])
        exp_result = 10
        act_result = \
            self.driver.manage_existing_get_size(VOLUME1,
                                                 {'source-name': 'a'})
        self.assertEqual(exp_result, act_result)

    def test_manage_existing_get_size_no_source_name(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL1_STATUS_RESP])
        self.assertRaises(exception.XIODriverException,
                          self.driver.manage_existing_get_size, VOLUME1, {})

    def test_unmanage(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                    ISE_GET_VOL1_STATUS_RESP])
        self.driver.unmanage(VOLUME1)

    def test_negative_unmanage_no_volume_status_xml(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                    ISE_GET_VOL_STATUS_NO_STATUS_RESP])
        self.driver.unmanage(VOLUME1)

    def test_negative_unmanage_no_volume_xml(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                    ISE_GET_VOL_STATUS_NO_VOL_NODE_RESP])
        self.assertRaises(exception.XIODriverException,
                          self.driver.unmanage, VOLUME1)

    def test_negative_unmanage_non_existing_volume(self, mock_req):
        self.setup_driver()
        mock_req.side_effect = iter([ISE_GET_QUERY_RESP,
                                     ISE_GET_VOL_STATUS_404_RESP])
        self.assertRaises(exception.XIODriverException,
                          self.driver.unmanage, VOLUME1)


class XIOISEISCSIDriverTestCase(XIOISEDriverTestCase, test.TestCase):

    def setUp(self):
        super(XIOISEISCSIDriverTestCase, self).setUp()
        self.setup_test('iscsi')


class XIOISEFCDriverTestCase(XIOISEDriverTestCase, test.TestCase):

    def setUp(self):
        super(XIOISEFCDriverTestCase, self).setUp()
        self.setup_test('fibre_channel')
