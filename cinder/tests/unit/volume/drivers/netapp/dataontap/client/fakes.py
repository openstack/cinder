# Copyright (c) - 2015, Tom Barron.  All rights reserved.
# Copyright (c) - 2016 Mike Rooney. All rights reserved.
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

from unittest import mock

from lxml import etree
from six.moves import urllib

from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
import cinder.volume.drivers.netapp.dataontap.client.api as netapp_api


FAKE_VOL_XML = b"""<volume-info xmlns='http://www.netapp.com/filer/admin'>
    <name>open123</name>
    <state>online</state>
    <size-total>0</size-total>
    <size-used>0</size-used>
    <size-available>0</size-available>
    <is-inconsistent>false</is-inconsistent>
    <is-invalid>false</is-invalid>
    </volume-info>"""

FAKE_XML1 = b"""<options>\
<test1>abc</test1>\
<test2>abc</test2>\
</options>"""

FAKE_XML2 = b"""<root><options>somecontent</options></root>"""

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

VOLUME_VSERVER_NAME = 'fake_vserver'
VOLUME_NAMES = ('volume1', 'volume2')
VOLUME_NAME = 'volume1'
NAMESPACE_NAME = '/vol/vol1/namespace1'
HOST_NQN = 'nqn.1992-01.example.com:host'
DEST_VOLUME_NAME = 'volume-dest'
LUN_NAME = 'fake-lun-name'
DEST_LUN_NAME = 'new-fake-lun-name'
FILE_NAME = 'fake-file-name'
DEST_FILE_NAME = 'new-fake-file-name'
FAKE_UUID = 'b32bab78-82be-11ec-a8a3-0242ac120002'

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
INITIATOR_IQN = 'iqn.2015-06.com.netapp:fake_iqn'
USER_NAME = 'fake_user'
PASSWORD = 'passw0rd'
ENCRYPTED_PASSWORD = 'B351F145DA527445'

NO_RECORDS_RESPONSE = etree.XML("""
  <results status="passed">
    <num-records>0</num-records>
  </results>
""")

VOLUME_GET_NAME_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <volume-attributes>
        <volume-id-attributes>
          <name>%(volume)s</name>
          <owning-vserver-name>%(vserver)s</owning-vserver-name>
        </volume-id-attributes>
      </volume-attributes>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {'volume': VOLUME_NAMES[0], 'vserver': VOLUME_VSERVER_NAME})

INVALID_GET_ITER_RESPONSE_NO_ATTRIBUTES = etree.XML("""
  <results status="passed">
    <num-records>1</num-records>
    <next-tag>fake_tag</next-tag>
  </results>
""")

INVALID_GET_ITER_RESPONSE_NO_RECORDS = etree.XML("""
  <results status="passed">
    <attributes-list/>
    <next-tag>fake_tag</next-tag>
  </results>
""")

INVALID_RESPONSE = etree.XML("""
  <results status="passed">
    <num-records>1</num-records>
  </results>
""")

GET_OPERATIONAL_LIF_ADDRESSES_RESPONSE = etree.XML("""
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

QOS_POLICY_GROUP_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <qos-policy-group-info>
        <max-throughput>30KB/S</max-throughput>
        <num-workloads>1</num-workloads>
        <pgid>53</pgid>
        <policy-group>fake_qos_policy_group_name</policy-group>
        <policy-group-class>user_defined</policy-group-class>
        <uuid>12496028-b641-11e5-abbd-123478563412</uuid>
        <vserver>cinder-iscsi</vserver>
      </qos-policy-group-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""")

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

SNAPSHOT_INFO_FOR_PRESENT_NOT_BUSY_SNAPSHOT_CMODE = etree.XML("""
    <results status="passed">
    <attributes-list>
      <snapshot-info>
        <name>%(snapshot_name)s</name>
        <busy>False</busy>
        <volume>%(vol_name)s</volume>
        <snapshot-instance-uuid>abcd-ef01-2345-6789</snapshot-instance-uuid>
      </snapshot-info>
    </attributes-list>
    <num-records>1</num-records>
    </results>
""" % {
    'snapshot_name': fake.SNAPSHOT['name'],
    'vol_name': fake.SNAPSHOT['volume_id'],
})

SNAPSHOT_INFO_FOR_PRESENT_BUSY_SNAPSHOT_CMODE = etree.XML("""
    <results status="passed">
    <attributes-list>
      <snapshot-info>
        <name>%(snapshot_name)s</name>
        <busy>True</busy>
        <volume>%(vol_name)s</volume>
      </snapshot-info>
    </attributes-list>
    <num-records>1</num-records>
    </results>
""" % {
    'snapshot_name': fake.SNAPSHOT['name'],
    'vol_name': fake.SNAPSHOT['volume_id'],
})

NODE_NAME = 'fake_node1'
NODE_NAMES = ('fake_node1', 'fake_node2')
VOLUME_AGGREGATE_NAME = 'fake_aggr1'
VOLUME_AGGREGATE_NAMES = ('fake_aggr1', 'fake_aggr2')

AGGR_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <aggr-attributes>
        <aggr-64bit-upgrade-attributes>
          <aggr-status-attributes>
            <is-64-bit-upgrade-in-progress>false</is-64-bit-upgrade-in-progress>
          </aggr-status-attributes>
        </aggr-64bit-upgrade-attributes>
        <aggr-fs-attributes>
          <block-type>64_bit</block-type>
          <fsid>1758646411</fsid>
          <type>aggr</type>
        </aggr-fs-attributes>
        <aggr-inode-attributes>
          <files-private-used>512</files-private-used>
          <files-total>30384</files-total>
          <files-used>96</files-used>
          <inodefile-private-capacity>30384</inodefile-private-capacity>
          <inodefile-public-capacity>30384</inodefile-public-capacity>
          <maxfiles-available>30384</maxfiles-available>
          <maxfiles-possible>243191</maxfiles-possible>
          <maxfiles-used>96</maxfiles-used>
          <percent-inode-used-capacity>0</percent-inode-used-capacity>
        </aggr-inode-attributes>
        <aggr-ownership-attributes>
          <home-id>4082368507</home-id>
          <home-name>cluster3-01</home-name>
          <owner-id>4082368507</owner-id>
          <owner-name>cluster3-01</owner-name>
        </aggr-ownership-attributes>
        <aggr-performance-attributes>
          <free-space-realloc>off</free-space-realloc>
          <max-write-alloc-blocks>0</max-write-alloc-blocks>
        </aggr-performance-attributes>
        <aggr-raid-attributes>
          <checksum-status>active</checksum-status>
          <checksum-style>block</checksum-style>
          <disk-count>3</disk-count>
          <ha-policy>cfo</ha-policy>
          <has-local-root>true</has-local-root>
          <has-partner-root>false</has-partner-root>
          <is-checksum-enabled>true</is-checksum-enabled>
          <is-hybrid>false</is-hybrid>
          <is-hybrid-enabled>false</is-hybrid-enabled>
          <is-inconsistent>false</is-inconsistent>
          <mirror-status>unmirrored</mirror-status>
          <mount-state>online</mount-state>
          <plex-count>1</plex-count>
          <plexes>
            <plex-attributes>
              <is-online>true</is-online>
              <is-resyncing>false</is-resyncing>
              <plex-name>/%(aggr1)s/plex0</plex-name>
              <plex-status>normal,active</plex-status>
              <raidgroups>
                <raidgroup-attributes>
                  <checksum-style>block</checksum-style>
                  <is-cache-tier>false</is-cache-tier>
                  <is-recomputing-parity>false</is-recomputing-parity>
                  <is-reconstructing>false</is-reconstructing>
                  <raidgroup-name>/%(aggr1)s/plex0/rg0</raidgroup-name>
                  <recomputing-parity-percentage>0</recomputing-parity-percentage>
                  <reconstruction-percentage>0</reconstruction-percentage>
                </raidgroup-attributes>
              </raidgroups>
              <resyncing-percentage>0</resyncing-percentage>
            </plex-attributes>
          </plexes>
          <raid-lost-write-state>on</raid-lost-write-state>
          <raid-size>16</raid-size>
          <raid-status>raid_dp, normal</raid-status>
          <raid-type>raid_dp</raid-type>
          <state>online</state>
        </aggr-raid-attributes>
        <aggr-snaplock-attributes>
          <is-snaplock>false</is-snaplock>
        </aggr-snaplock-attributes>
        <aggr-snapshot-attributes>
          <files-total>0</files-total>
          <files-used>0</files-used>
          <is-snapshot-auto-create-enabled>true</is-snapshot-auto-create-enabled>
          <is-snapshot-auto-delete-enabled>true</is-snapshot-auto-delete-enabled>
          <maxfiles-available>0</maxfiles-available>
          <maxfiles-possible>0</maxfiles-possible>
          <maxfiles-used>0</maxfiles-used>
          <percent-inode-used-capacity>0</percent-inode-used-capacity>
          <percent-used-capacity>0</percent-used-capacity>
          <size-available>0</size-available>
          <size-total>0</size-total>
          <size-used>0</size-used>
          <snapshot-reserve-percent>0</snapshot-reserve-percent>
        </aggr-snapshot-attributes>
        <aggr-space-attributes>
          <aggregate-metadata>245760</aggregate-metadata>
          <hybrid-cache-size-total>0</hybrid-cache-size-total>
          <percent-used-capacity>95</percent-used-capacity>
          <size-available>45670400</size-available>
          <size-total>943718400</size-total>
          <size-used>898048000</size-used>
          <total-reserved-space>0</total-reserved-space>
          <used-including-snapshot-reserve>898048000</used-including-snapshot-reserve>
          <volume-footprints>897802240</volume-footprints>
        </aggr-space-attributes>
        <aggr-volume-count-attributes>
          <flexvol-count>1</flexvol-count>
          <flexvol-count-collective>0</flexvol-count-collective>
          <flexvol-count-striped>0</flexvol-count-striped>
        </aggr-volume-count-attributes>
        <aggregate-name>%(aggr1)s</aggregate-name>
        <aggregate-uuid>15863632-ea49-49a8-9c88-2bd2d57c6d7a</aggregate-uuid>
        <nodes>
          <node-name>cluster3-01</node-name>
        </nodes>
        <striping-type>unknown</striping-type>
      </aggr-attributes>
      <aggr-attributes>
        <aggr-64bit-upgrade-attributes>
          <aggr-status-attributes>
            <is-64-bit-upgrade-in-progress>false</is-64-bit-upgrade-in-progress>
          </aggr-status-attributes>
        </aggr-64bit-upgrade-attributes>
        <aggr-fs-attributes>
          <block-type>64_bit</block-type>
          <fsid>706602229</fsid>
          <type>aggr</type>
        </aggr-fs-attributes>
        <aggr-inode-attributes>
          <files-private-used>528</files-private-used>
          <files-total>31142</files-total>
          <files-used>96</files-used>
          <inodefile-private-capacity>31142</inodefile-private-capacity>
          <inodefile-public-capacity>31142</inodefile-public-capacity>
          <maxfiles-available>31142</maxfiles-available>
          <maxfiles-possible>1945584</maxfiles-possible>
          <maxfiles-used>96</maxfiles-used>
          <percent-inode-used-capacity>0</percent-inode-used-capacity>
        </aggr-inode-attributes>
        <aggr-ownership-attributes>
          <home-id>4082368507</home-id>
          <home-name>cluster3-01</home-name>
          <owner-id>4082368507</owner-id>
          <owner-name>cluster3-01</owner-name>
        </aggr-ownership-attributes>
        <aggr-performance-attributes>
          <free-space-realloc>off</free-space-realloc>
          <max-write-alloc-blocks>0</max-write-alloc-blocks>
        </aggr-performance-attributes>
        <aggr-raid-attributes>
          <checksum-status>active</checksum-status>
          <checksum-style>block</checksum-style>
          <disk-count>10</disk-count>
          <ha-policy>sfo</ha-policy>
          <has-local-root>false</has-local-root>
          <has-partner-root>false</has-partner-root>
          <is-checksum-enabled>true</is-checksum-enabled>
          <is-hybrid>false</is-hybrid>
          <is-hybrid-enabled>false</is-hybrid-enabled>
          <is-inconsistent>false</is-inconsistent>
          <mirror-status>unmirrored</mirror-status>
          <mount-state>online</mount-state>
          <plex-count>1</plex-count>
          <plexes>
            <plex-attributes>
              <is-online>true</is-online>
              <is-resyncing>false</is-resyncing>
              <plex-name>/%(aggr2)s/plex0</plex-name>
              <plex-status>normal,active</plex-status>
              <raidgroups>
                <raidgroup-attributes>
                  <checksum-style>block</checksum-style>
                  <is-cache-tier>false</is-cache-tier>
                  <is-recomputing-parity>false</is-recomputing-parity>
                  <is-reconstructing>false</is-reconstructing>
                  <raidgroup-name>/%(aggr2)s/plex0/rg0</raidgroup-name>
                  <recomputing-parity-percentage>0</recomputing-parity-percentage>
                  <reconstruction-percentage>0</reconstruction-percentage>
                </raidgroup-attributes>
                <raidgroup-attributes>
                  <checksum-style>block</checksum-style>
                  <is-cache-tier>false</is-cache-tier>
                  <is-recomputing-parity>false</is-recomputing-parity>
                  <is-reconstructing>false</is-reconstructing>
                  <raidgroup-name>/%(aggr2)s/plex0/rg1</raidgroup-name>
                  <recomputing-parity-percentage>0</recomputing-parity-percentage>
                  <reconstruction-percentage>0</reconstruction-percentage>
                </raidgroup-attributes>
              </raidgroups>
              <resyncing-percentage>0</resyncing-percentage>
            </plex-attributes>
          </plexes>
          <raid-lost-write-state>on</raid-lost-write-state>
          <raid-size>8</raid-size>
          <raid-status>raid4, normal</raid-status>
          <raid-type>raid4</raid-type>
          <state>online</state>
        </aggr-raid-attributes>
        <aggr-snaplock-attributes>
          <is-snaplock>false</is-snaplock>
        </aggr-snaplock-attributes>
        <aggr-snapshot-attributes>
          <files-total>0</files-total>
          <files-used>0</files-used>
          <is-snapshot-auto-create-enabled>true</is-snapshot-auto-create-enabled>
          <is-snapshot-auto-delete-enabled>true</is-snapshot-auto-delete-enabled>
          <maxfiles-available>0</maxfiles-available>
          <maxfiles-possible>0</maxfiles-possible>
          <maxfiles-used>0</maxfiles-used>
          <percent-inode-used-capacity>0</percent-inode-used-capacity>
          <percent-used-capacity>0</percent-used-capacity>
          <size-available>0</size-available>
          <size-total>0</size-total>
          <size-used>0</size-used>
          <snapshot-reserve-percent>0</snapshot-reserve-percent>
        </aggr-snapshot-attributes>
        <aggr-space-attributes>
          <aggregate-metadata>425984</aggregate-metadata>
          <hybrid-cache-size-total>0</hybrid-cache-size-total>
          <percent-used-capacity>15</percent-used-capacity>
          <size-available>6448431104</size-available>
          <size-total>7549747200</size-total>
          <size-used>1101316096</size-used>
          <total-reserved-space>0</total-reserved-space>
          <used-including-snapshot-reserve>1101316096</used-including-snapshot-reserve>
          <volume-footprints>1100890112</volume-footprints>
        </aggr-space-attributes>
        <aggr-volume-count-attributes>
          <flexvol-count>2</flexvol-count>
          <flexvol-count-collective>0</flexvol-count-collective>
          <flexvol-count-striped>0</flexvol-count-striped>
        </aggr-volume-count-attributes>
        <aggregate-name>%(aggr2)s</aggregate-name>
        <aggregate-uuid>2a741934-1aaf-42dd-93ca-aaf231be108a</aggregate-uuid>
        <nodes>
          <node-name>cluster3-01</node-name>
        </nodes>
        <striping-type>not_striped</striping-type>
      </aggr-attributes>
    </attributes-list>
    <num-records>2</num-records>
  </results>
""" % {
    'aggr1': VOLUME_AGGREGATE_NAMES[0],
    'aggr2': VOLUME_AGGREGATE_NAMES[1],
})

AGGR_GET_SPACE_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <aggr-attributes>
        <aggr-raid-attributes>
          <plexes>
            <plex-attributes>
              <plex-name>/%(aggr1)s/plex0</plex-name>
              <raidgroups>
                <raidgroup-attributes>
                  <raidgroup-name>/%(aggr1)s/plex0/rg0</raidgroup-name>
                </raidgroup-attributes>
              </raidgroups>
            </plex-attributes>
          </plexes>
        </aggr-raid-attributes>
        <aggr-space-attributes>
          <size-available>45670400</size-available>
          <size-total>943718400</size-total>
          <size-used>898048000</size-used>
        </aggr-space-attributes>
        <aggregate-name>%(aggr1)s</aggregate-name>
      </aggr-attributes>
      <aggr-attributes>
        <aggr-raid-attributes>
          <plexes>
            <plex-attributes>
              <plex-name>/%(aggr2)s/plex0</plex-name>
              <raidgroups>
                <raidgroup-attributes>
                  <raidgroup-name>/%(aggr2)s/plex0/rg0</raidgroup-name>
                </raidgroup-attributes>
                <raidgroup-attributes>
                  <raidgroup-name>/%(aggr2)s/plex0/rg1</raidgroup-name>
                </raidgroup-attributes>
              </raidgroups>
            </plex-attributes>
          </plexes>
        </aggr-raid-attributes>
        <aggr-space-attributes>
          <size-available>4267659264</size-available>
          <size-total>7549747200</size-total>
          <size-used>3282087936</size-used>
        </aggr-space-attributes>
        <aggregate-name>%(aggr2)s</aggregate-name>
      </aggr-attributes>
    </attributes-list>
    <num-records>2</num-records>
  </results>
""" % {
    'aggr1': VOLUME_AGGREGATE_NAMES[0],
    'aggr2': VOLUME_AGGREGATE_NAMES[1],
})

AGGR_GET_NODE_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <aggr-attributes>
        <aggr-ownership-attributes>
          <home-name>%(node)s</home-name>
        </aggr-ownership-attributes>
        <aggregate-name>%(aggr)s</aggregate-name>
      </aggr-attributes>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'aggr': VOLUME_AGGREGATE_NAME,
    'node': NODE_NAME,
})

AGGREGATE_RAID_TYPE = 'raid_dp'
AGGR_GET_ITER_SSC_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <aggr-attributes>
        <aggr-raid-attributes>
          <plexes>
            <plex-attributes>
              <plex-name>/%(aggr)s/plex0</plex-name>
              <raidgroups>
                <raidgroup-attributes>
                  <raidgroup-name>/%(aggr)s/plex0/rg0</raidgroup-name>
                </raidgroup-attributes>
              </raidgroups>
            </plex-attributes>
          </plexes>
          <raid-type>%(raid)s</raid-type>
          <is-hybrid>true</is-hybrid>
        </aggr-raid-attributes>
        <aggr-ownership-attributes>
          <home-name>%(node)s</home-name>
        </aggr-ownership-attributes>
        <aggregate-name>%(aggr)s</aggregate-name>
      </aggr-attributes>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'aggr': VOLUME_AGGREGATE_NAME,
    'raid': AGGREGATE_RAID_TYPE,
    'node': NODE_NAME,
})

AGGR_INFO_SSC = {
    'name': VOLUME_AGGREGATE_NAME,
    'raid-type': AGGREGATE_RAID_TYPE,
    'is-hybrid': True,
    'node-name': NODE_NAME,
}

AGGR_SIZE_TOTAL = 107374182400
AGGR_SIZE_AVAILABLE = 59055800320
AGGR_USED_PERCENT = 45
AGGR_SIZE_USED = 58888957952
AGGR_GET_ITER_CAPACITY_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <aggr-attributes>
        <aggr-space-attributes>
          <percent-used-capacity>%(used)s</percent-used-capacity>
          <size-total>%(total_size)s</size-total>
          <size-available>%(available_size)s</size-available>
        </aggr-space-attributes>
        <aggregate-name>%(aggr)s</aggregate-name>
      </aggr-attributes>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'aggr': VOLUME_AGGREGATE_NAME,
    'used': AGGR_USED_PERCENT,
    'available_size': AGGR_SIZE_AVAILABLE,
    'total_size': AGGR_SIZE_TOTAL,
})

VOLUME_STATE_ONLINE = 'online'
VOLUME_GET_ITER_STATE_ATTR_STR = """
    <volume-attributes>
        <volume-id-attributes>
            <style-extended>flexgroup</style-extended>
        </volume-id-attributes>
        <volume-state-attributes>
            <state>%(state)s</state>
        </volume-state-attributes>
    </volume-attributes>
""" % {
    'state': VOLUME_STATE_ONLINE
}

VOLUME_GET_ITER_STATE_ATTR = etree.XML(VOLUME_GET_ITER_STATE_ATTR_STR)

VOLUME_GET_ITER_STATE_RESPONSE = etree.XML("""
    <results status="passed">
        <num-records>1</num-records>
        <attributes-list> %(volume)s </attributes-list>
    </results>
""" % {
    'volume': VOLUME_GET_ITER_STATE_ATTR_STR,
})

VOLUME_SIZE_TOTAL = 19922944
VOLUME_SIZE_AVAILABLE = 19791872
VOLUME_GET_ITER_CAPACITY_ATTR_STR = """
<volume-attributes>
    <volume-id-attributes>
        <style-extended>flexgroup</style-extended>
    </volume-id-attributes>
    <volume-space-attributes>
        <size-available>%(available_size)s</size-available>
        <size-total>%(total_size)s</size-total>
    </volume-space-attributes>
</volume-attributes>
""" % {
    'available_size': VOLUME_SIZE_AVAILABLE,
    'total_size': VOLUME_SIZE_TOTAL,
}

VOLUME_GET_ITER_CAPACITY_ATTR = etree.XML(VOLUME_GET_ITER_CAPACITY_ATTR_STR)

VOLUME_GET_ITER_CAPACITY_RESPONSE = etree.XML("""
    <results status="passed">
        <num-records>1</num-records>
        <attributes-list> %(volume)s </attributes-list>
    </results>
""" % {
    'volume': VOLUME_GET_ITER_CAPACITY_ATTR_STR,
})

VOLUME_GET_ITER_STYLE_RESPONSE = etree.XML("""
    <results status="passed">
        <num-records>3</num-records>
        <attributes-list>
            <volume-attributes>
                <volume-id-attributes>
                    <style-extended>flexgroup</style-extended>
                </volume-id-attributes>
            </volume-attributes>
            <volume-attributes>
                <volume-id-attributes>
                    <style-extended>flexgroup-constituent</style-extended>
                </volume-id-attributes>
            </volume-attributes>
            <volume-attributes>
                <volume-id-attributes>
                    <style-extended>flexgroup-constituent</style-extended>
                </volume-id-attributes>
            </volume-attributes>
        </attributes-list>
    </results>
""")

VOLUME_FLEXGROUP_STYLE = etree.XML("""
<volume-attributes>
    <volume-id-attributes>
        <style-extended>flexgroup</style-extended>
    </volume-id-attributes>
</volume-attributes>
""")

VOLUME_GET_ITER_SAME_STYLE_RESPONSE = etree.XML("""
    <results status="passed">
        <num-records>3</num-records>
        <attributes-list>
            <volume-attributes>
                <volume-id-attributes>
                    <style-extended>flexvol</style-extended>
                </volume-id-attributes>
            </volume-attributes>
            <volume-attributes>
                <volume-id-attributes>
                    <style-extended>flexvol</style-extended>
                </volume-id-attributes>
            </volume-attributes>
            <volume-attributes>
                <volume-id-attributes>
                    <style-extended>flexvol</style-extended>
                </volume-id-attributes>
            </volume-attributes>
        </attributes-list>
    </results>
""")

VOLUME_GET_ITER_LIST_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <volume-attributes>
        <volume-id-attributes>
          <name>%(volume1)s</name>
          <owning-vserver-name>%(vserver)s</owning-vserver-name>
        </volume-id-attributes>
      </volume-attributes>
      <volume-attributes>
        <volume-id-attributes>
          <name>%(volume2)s</name>
          <owning-vserver-name>%(vserver)s</owning-vserver-name>
        </volume-id-attributes>
      </volume-attributes>
    </attributes-list>
    <num-records>2</num-records>
  </results>
""" % {
    'volume1': VOLUME_NAMES[0],
    'volume2': VOLUME_NAMES[1],
    'vserver': VOLUME_VSERVER_NAME,
})

VOLUME_GET_ITER_SSC_RESPONSE_STR = """
<volume-attributes>
    <volume-id-attributes>
      <containing-aggregate-name>%(aggr)s</containing-aggregate-name>
      <junction-path>/%(volume)s</junction-path>
      <name>%(volume)s</name>
      <owning-vserver-name>%(vserver)s</owning-vserver-name>
      <type>rw</type>
      <style-extended>flexvol</style-extended>
    </volume-id-attributes>
    <volume-mirror-attributes>
      <is-data-protection-mirror>false</is-data-protection-mirror>
      <is-replica-volume>false</is-replica-volume>
    </volume-mirror-attributes>
    <volume-qos-attributes>
      <policy-group-name>fake_qos_policy_group_name</policy-group-name>
    </volume-qos-attributes>
    <volume-space-attributes>
      <is-space-guarantee-enabled>true</is-space-guarantee-enabled>
      <space-guarantee>none</space-guarantee>
      <percentage-snapshot-reserve>5</percentage-snapshot-reserve>
      <size>12345</size>
    </volume-space-attributes>
    <volume-snapshot-attributes>
      <snapshot-policy>default</snapshot-policy>
    </volume-snapshot-attributes>
    <volume-language-attributes>
      <language-code>c.utf_8</language-code>
    </volume-language-attributes>
</volume-attributes>
""" % {
    'aggr': VOLUME_AGGREGATE_NAMES[0],
    'volume': VOLUME_NAMES[0],
    'vserver': VOLUME_VSERVER_NAME,
}

VOLUME_GET_ITER_SSC_RESPONSE_ATTR = etree.XML(
    VOLUME_GET_ITER_SSC_RESPONSE_STR)

VOLUME_GET_ITER_SSC_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>%(volume)s</attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'volume': VOLUME_GET_ITER_SSC_RESPONSE_STR,
})

VOLUME_GET_ITER_SSC_RESPONSE_STR_FLEXGROUP = """
<volume-attributes>
    <volume-id-attributes>
      <aggr-list>
        <aggr-name>%(aggr)s</aggr-name>
      </aggr-list>
      <junction-path>/%(volume)s</junction-path>
      <name>%(volume)s</name>
      <owning-vserver-name>%(vserver)s</owning-vserver-name>
      <type>rw</type>
      <style-extended>flexgroup</style-extended>
    </volume-id-attributes>
    <volume-mirror-attributes>
      <is-data-protection-mirror>false</is-data-protection-mirror>
      <is-replica-volume>false</is-replica-volume>
    </volume-mirror-attributes>
    <volume-qos-attributes>
      <policy-group-name>fake_qos_policy_group_name</policy-group-name>
    </volume-qos-attributes>
    <volume-space-attributes>
      <is-space-guarantee-enabled>true</is-space-guarantee-enabled>
      <space-guarantee>none</space-guarantee>
      <percentage-snapshot-reserve>5</percentage-snapshot-reserve>
      <size>12345</size>
    </volume-space-attributes>
    <volume-snapshot-attributes>
      <snapshot-policy>default</snapshot-policy>
    </volume-snapshot-attributes>
    <volume-language-attributes>
      <language-code>c.utf_8</language-code>
    </volume-language-attributes>
</volume-attributes>
""" % {
    'aggr': VOLUME_AGGREGATE_NAMES[0],
    'volume': VOLUME_NAMES[0],
    'vserver': VOLUME_VSERVER_NAME,
}

VOLUME_GET_ITER_SSC_RESPONSE_ATTR_FLEXGROUP = etree.XML(
    VOLUME_GET_ITER_SSC_RESPONSE_STR_FLEXGROUP)

VOLUME_GET_ITER_SSC_RESPONSE_FLEXGROUP = etree.XML("""
  <results status="passed">
    <attributes-list>%(volume)s</attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'volume': VOLUME_GET_ITER_SSC_RESPONSE_STR_FLEXGROUP,
})

VOLUME_INFO_SSC = {
    'name': VOLUME_NAMES[0],
    'vserver': VOLUME_VSERVER_NAME,
    'junction-path': '/%s' % VOLUME_NAMES[0],
    'aggregate': [VOLUME_AGGREGATE_NAMES[0]],
    'space-guarantee-enabled': True,
    'language': 'c.utf_8',
    'percentage-snapshot-reserve': '5',
    'snapshot-policy': 'default',
    'type': 'rw',
    'size': '12345',
    'space-guarantee': 'none',
    'qos-policy-group': 'fake_qos_policy_group_name',
    'style-extended': 'flexvol',
}

VOLUME_INFO_SSC_FLEXGROUP = {
    'name': VOLUME_NAMES[0],
    'vserver': VOLUME_VSERVER_NAME,
    'junction-path': '/%s' % VOLUME_NAMES[0],
    'aggregate': [VOLUME_AGGREGATE_NAMES[0]],
    'space-guarantee-enabled': True,
    'language': 'c.utf_8',
    'percentage-snapshot-reserve': '5',
    'snapshot-policy': 'default',
    'type': 'rw',
    'size': '12345',
    'space-guarantee': 'none',
    'qos-policy-group': 'fake_qos_policy_group_name',
    'style-extended': 'flexgroup',
}

SIS_GET_ITER_SSC_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <sis-status-info>
        <is-compression-enabled>false</is-compression-enabled>
        <state>enabled</state>
        <logical-data-size>211106232532992</logical-data-size>
        <logical-data-limit>703687441776640</logical-data-limit>
      </sis-status-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""")

VOLUME_DEDUPE_INFO_SSC = {
    'compression': False,
    'dedupe': True,
    'logical-data-size': 211106232532992,
    'logical-data-limit': 703687441776640,
}

SIS_GET_ITER_SSC_NO_LOGICAL_DATA_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <sis-status-info>
        <is-compression-enabled>false</is-compression-enabled>
        <state>disabled</state>
      </sis-status-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""")

VOLUME_DEDUPE_INFO_SSC_NO_LOGICAL_DATA = {
    'compression': False,
    'dedupe': False,
    'logical-data-size': 0,
    'logical-data-limit': 1,
}

CLONE_SPLIT_STATUS_RESPONSE = etree.XML("""
  <results status="passed">
    <clone-split-info>
      <unsplit-clone-count>1234</unsplit-clone-count>
      <unsplit-size>316659348799488</unsplit-size>
    </clone-split-info>
  </results>
""")

VOLUME_CLONE_SPLIT_STATUS = {
    'unsplit-size': 316659348799488,
    'unsplit-clone-count': 1234,
}

CLONE_SPLIT_STATUS_NO_DATA_RESPONSE = etree.XML("""
  <results status="passed">
    <clone-split-info>
    </clone-split-info>
  </results>
""")

VOLUME_GET_ITER_ENCRYPTION_SSC_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <volume-attributes>
        <encrypt>true</encrypt>
        <volume-id-attributes>
          <containing-aggregate-name>%(aggr)s</containing-aggregate-name>
          <junction-path>/%(volume)s</junction-path>
          <name>%(volume)s</name>
          <owning-vserver-name>%(vserver)s</owning-vserver-name>
          <type>rw</type>
        </volume-id-attributes>
        <volume-mirror-attributes>
          <is-data-protection-mirror>false</is-data-protection-mirror>
          <is-replica-volume>false</is-replica-volume>
        </volume-mirror-attributes>
        <volume-qos-attributes>
          <policy-group-name>fake_qos_policy_group_name</policy-group-name>
        </volume-qos-attributes>
        <volume-space-attributes>
          <is-space-guarantee-enabled>true</is-space-guarantee-enabled>
          <space-guarantee>none</space-guarantee>
          <percentage-snapshot-reserve>5</percentage-snapshot-reserve>
          <size>12345</size>
        </volume-space-attributes>
        <volume-snapshot-attributes>
          <snapshot-policy>default</snapshot-policy>
        </volume-snapshot-attributes>
        <volume-language-attributes>
          <language-code>c.utf_8</language-code>
        </volume-language-attributes>
      </volume-attributes>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'aggr': VOLUME_AGGREGATE_NAMES[0],
    'volume': VOLUME_NAMES[0],
    'vserver': VOLUME_VSERVER_NAME,
})

STORAGE_DISK_GET_ITER_RESPONSE_PAGE_1 = etree.XML("""
  <results status="passed">
    <attributes-list>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.16</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.17</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.18</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.19</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.20</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.21</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.22</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.24</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.25</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.26</disk-name>
      </storage-disk-info>
    </attributes-list>
    <next-tag>next_tag_1</next-tag>
    <num-records>10</num-records>
  </results>
""")

STORAGE_DISK_GET_ITER_RESPONSE_PAGE_2 = etree.XML("""
  <results status="passed">
    <attributes-list>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.27</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.28</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.29</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v4.32</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.16</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.17</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.18</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.19</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.20</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.21</disk-name>
      </storage-disk-info>
    </attributes-list>
    <next-tag>next_tag_2</next-tag>
    <num-records>10</num-records>
  </results>
""")

STORAGE_DISK_GET_ITER_RESPONSE_PAGE_3 = etree.XML("""
  <results status="passed">
    <attributes-list>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.22</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.24</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.25</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.26</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.27</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.28</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.29</disk-name>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.32</disk-name>
      </storage-disk-info>
    </attributes-list>
    <num-records>8</num-records>
  </results>
""")

AGGREGATE_DISK_TYPES = ['SATA', 'SSD']
STORAGE_DISK_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.19</disk-name>
        <disk-raid-info>
          <effective-disk-type>%(type0)s</effective-disk-type>
        </disk-raid-info>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.20</disk-name>
        <disk-raid-info>
          <effective-disk-type>%(type0)s</effective-disk-type>
        </disk-raid-info>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.20</disk-name>
        <disk-raid-info>
          <effective-disk-type>%(type1)s</effective-disk-type>
        </disk-raid-info>
      </storage-disk-info>
      <storage-disk-info>
        <disk-name>cluster3-01:v5.20</disk-name>
        <disk-raid-info>
          <effective-disk-type>%(type1)s</effective-disk-type>
        </disk-raid-info>
      </storage-disk-info>
    </attributes-list>
    <num-records>4</num-records>
  </results>
""" % {
    'type0': AGGREGATE_DISK_TYPES[0],
    'type1': AGGREGATE_DISK_TYPES[1],
})

SYSTEM_USER_CAPABILITY_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <capability-info>
        <object-name>object</object-name>
        <operation-list>
          <operation-info>
            <api-name>api,api2,api3</api-name>
            <name>operation</name>
          </operation-info>
        </operation-list>
      </capability-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""")

PERF_OBJECT_COUNTER_TOTAL_CP_MSECS_LABELS = [
    'SETUP', 'PRE_P0', 'P0_SNAP_DEL', 'P1_CLEAN', 'P1_QUOTA', 'IPU_DISK_ADD',
    'P2V_INOFILE', 'P2V_INO_PUB', 'P2V_INO_PRI', 'P2V_FSINFO', 'P2V_DLOG1',
    'P2V_DLOG2', 'P2V_REFCOUNT', 'P2V_TOPAA', 'P2V_DF_SCORES_SUB', 'P2V_BM',
    'P2V_SNAP', 'P2V_DF_SCORES', 'P2V_VOLINFO', 'P2V_CONT', 'P2A_INOFILE',
    'P2A_INO', 'P2A_DLOG1', 'P2A_HYA', 'P2A_DLOG2', 'P2A_FSINFO',
    'P2A_IPU_BITMAP_GROW', 'P2A_REFCOUNT', 'P2A_TOPAA', 'P2A_HYABC', 'P2A_BM',
    'P2A_SNAP', 'P2A_VOLINFO', 'P2_FLUSH', 'P2_FINISH', 'P3_WAIT',
    'P3V_VOLINFO', 'P3A_VOLINFO', 'P3_FINISH', 'P4_FINISH', 'P5_FINISH',
]

PERF_OBJECT_COUNTER_LIST_INFO_WAFL_RESPONSE = etree.XML("""
  <results status="passed">
    <counters>
      <counter-info>
        <desc>No. of times 8.3 names are accessed per second.</desc>
        <name>access_8_3_names</name>
        <privilege-level>diag</privilege-level>
        <properties>rate</properties>
        <unit>per_sec</unit>
      </counter-info>
      <counter-info>
        <desc>Array of counts of different types of CPs</desc>
        <labels>
          <label-info>wafl_timer generated CP</label-info>
          <label-info>snapshot generated CP</label-info>
          <label-info>wafl_avail_bufs generated CP</label-info>
          <label-info>dirty_blk_cnt generated CP</label-info>
          <label-info>full NV-log generated CP,back-to-back CP</label-info>
          <label-info>flush generated CP,sync generated CP</label-info>
          <label-info>deferred back-to-back CP</label-info>
          <label-info>low mbufs generated CP</label-info>
          <label-info>low datavecs generated CP</label-info>
          <label-info>nvlog replay takeover time limit CP</label-info>
        </labels>
        <name>cp_count</name>
        <privilege-level>diag</privilege-level>
        <properties>delta</properties>
        <type>array</type>
        <unit>none</unit>
      </counter-info>
      <counter-info>
        <base-counter>total_cp_msecs</base-counter>
        <desc>Array of percentage time spent in different phases of CP</desc>
        <labels>
          <label-info>%(labels)s</label-info>
        </labels>
        <name>cp_phase_times</name>
        <privilege-level>diag</privilege-level>
        <properties>percent</properties>
        <type>array</type>
        <unit>percent</unit>
      </counter-info>
    </counters>
  </results>
""" % {'labels': ','.join(PERF_OBJECT_COUNTER_TOTAL_CP_MSECS_LABELS)})

PERF_OBJECT_GET_INSTANCES_SYSTEM_RESPONSE_CMODE = etree.XML("""
  <results status="passed">
    <instances>
      <instance-data>
        <counters>
          <counter-data>
            <name>avg_processor_busy</name>
            <value>5674745133134</value>
          </counter-data>
        </counters>
        <name>system</name>
        <uuid>%(node1)s:kernel:system</uuid>
      </instance-data>
      <instance-data>
        <counters>
          <counter-data>
            <name>avg_processor_busy</name>
            <value>4077649009234</value>
          </counter-data>
        </counters>
        <name>system</name>
        <uuid>%(node2)s:kernel:system</uuid>
      </instance-data>
    </instances>
    <timestamp>1453412013</timestamp>
  </results>
""" % {'node1': NODE_NAMES[0], 'node2': NODE_NAMES[1]})

PERF_OBJECT_INSTANCE_LIST_INFO_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <instance-info>
        <name>system</name>
        <uuid>%(node)s:kernel:system</uuid>
      </instance-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {'node': NODE_NAME})

PERF_OBJECT_INSTANCE_LIST_INFO_RESPONSE = etree.XML("""
  <results status="passed">
    <instances>
      <instance-info>
        <name>processor0</name>
      </instance-info>
      <instance-info>
        <name>processor1</name>
      </instance-info>
    </instances>
  </results>""")

SYSTEM_GET_INFO_RESPONSE = etree.XML("""
  <results status="passed">
    <system-info>
      <system-name>%(node)s</system-name>
      <system-id>4082368508</system-id>
      <system-model>SIMBOX</system-model>
      <system-machine-type>SIMBOX</system-machine-type>
      <vendor-id>NetApp</vendor-id>
      <system-serial-number>4082368508</system-serial-number>
      <board-speed>2593</board-speed>
      <board-type>NetApp VSim</board-type>
      <cpu-serial-number>999999</cpu-serial-number>
      <number-of-processors>2</number-of-processors>
      <memory-size>1599</memory-size>
      <cpu-processor-id>0x40661</cpu-processor-id>
      <cpu-microcode-version>15</cpu-microcode-version>
      <maximum-aggregate-size>2199023255552</maximum-aggregate-size>
      <maximum-flexible-volume-size>17592186044416</maximum-flexible-volume-size>
      <maximum-flexible-volume-count>500</maximum-flexible-volume-count>
      <supports-raid-array>true</supports-raid-array>
    </system-info>
  </results>
""" % {'node': NODE_NAME})

ISCSI_INITIATOR_GET_AUTH_ELEM = etree.XML("""
<iscsi-initiator-get-auth>
  <initiator>%s</initiator>
</iscsi-initiator-get-auth>""" % INITIATOR_IQN)

ISCSI_INITIATOR_AUTH_LIST_INFO_FAILURE = etree.XML("""
<results status="failed" errno="13112" reason="Initiator %s not found,
 please use default authentication." />""" % INITIATOR_IQN)

CLUSTER_NAME = 'fake_cluster'
REMOTE_CLUSTER_NAME = 'fake_cluster_2'
CLUSTER_ADDRESS_1 = 'fake_cluster_address'
CLUSTER_ADDRESS_2 = 'fake_cluster_address_2'
VSERVER_NAME = 'fake_vserver'
DEST_VSERVER_NAME = 'fake_dest_vserver'
VSERVER_NAME_2 = 'fake_vserver_2'
ADMIN_VSERVER_NAME = 'fake_admin_vserver'
NODE_VSERVER_NAME = 'fake_node_vserver'
SM_SOURCE_VSERVER = 'fake_source_vserver'
SM_SOURCE_VOLUME = 'fake_source_volume'
SM_DEST_VSERVER = 'fake_destination_vserver'
SM_DEST_VOLUME = 'fake_destination_volume'
IGROUP_NAME = 'openstack-d9b4194f-5f65-4952-fake-26c911f1e4b2'
LUN_NAME_PATH = '/vol/volume-fake/lun-path-fake-1234'

CLUSTER_PEER_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <cluster-peer-info>
        <active-addresses>
          <remote-inet-address>%(addr1)s</remote-inet-address>
          <remote-inet-address>%(addr2)s</remote-inet-address>
        </active-addresses>
        <availability>available</availability>
        <cluster-name>%(cluster)s</cluster-name>
        <cluster-uuid>fake_uuid</cluster-uuid>
        <peer-addresses>
          <remote-inet-address>%(addr1)s</remote-inet-address>
        </peer-addresses>
        <remote-cluster-name>%(remote_cluster)s</remote-cluster-name>
        <serial-number>fake_serial_number</serial-number>
        <timeout>60</timeout>
      </cluster-peer-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'addr1': CLUSTER_ADDRESS_1,
    'addr2': CLUSTER_ADDRESS_2,
    'cluster': CLUSTER_NAME,
    'remote_cluster': REMOTE_CLUSTER_NAME,
})

CLUSTER_PEER_POLICY_GET_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes>
      <cluster-peer-policy>
        <is-unauthenticated-access-permitted>false</is-unauthenticated-access-permitted>
        <passphrase-minimum-length>8</passphrase-minimum-length>
      </cluster-peer-policy>
    </attributes>
  </results>
""")

FILE_SIZES_BY_DIR_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <file-info>
        <name>%(name)s</name>
        <file-size>1024</file-size>
      </file-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'name': fake.VOLUME_NAME
})

LUN_SIZES_BY_VOLUME_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <lun-info>
        <path>%(path)s</path>
        <size>1024</size>
      </lun-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'path': fake.VOLUME_PATH
})

VSERVER_PEER_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <vserver-peer-info>
        <applications>
          <vserver-peer-application>snapmirror</vserver-peer-application>
        </applications>
        <peer-cluster>%(cluster)s</peer-cluster>
        <peer-state>peered</peer-state>
        <peer-vserver>%(vserver2)s</peer-vserver>
        <vserver>%(vserver1)s</vserver>
      </vserver-peer-info>
    </attributes-list>
    <num-records>2</num-records>
  </results>
""" % {
    'cluster': CLUSTER_NAME,
    'vserver1': VSERVER_NAME,
    'vserver2': VSERVER_NAME_2
})

SNAPMIRROR_GET_ITER_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <snapmirror-info>
        <destination-location>%(vserver)s:%(volume2)s</destination-location>
        <destination-volume>%(volume2)s</destination-volume>
        <destination-volume-node>fake_destination_node</destination-volume-node>
        <destination-vserver>%(vserver)s</destination-vserver>
        <exported-snapshot>fake_snapshot</exported-snapshot>
        <exported-snapshot-timestamp>1442701782</exported-snapshot-timestamp>
        <is-constituent>false</is-constituent>
        <is-healthy>true</is-healthy>
        <lag-time>2187</lag-time>
        <last-transfer-duration>109</last-transfer-duration>
        <last-transfer-end-timestamp>1442701890</last-transfer-end-timestamp>
        <last-transfer-from>test:manila</last-transfer-from>
        <last-transfer-size>1171456</last-transfer-size>
        <last-transfer-type>initialize</last-transfer-type>
        <max-transfer-rate>0</max-transfer-rate>
        <mirror-state>snapmirrored</mirror-state>
        <newest-snapshot>fake_snapshot</newest-snapshot>
        <newest-snapshot-timestamp>1442701782</newest-snapshot-timestamp>
        <policy>DPDefault</policy>
        <relationship-control-plane>v2</relationship-control-plane>
        <relationship-id>ea8bfcc6-5f1d-11e5-8446-123478563412</relationship-id>
        <relationship-status>idle</relationship-status>
        <relationship-type>data_protection</relationship-type>
        <schedule>daily</schedule>
        <source-location>%(vserver)s:%(volume1)s</source-location>
        <source-volume>%(volume1)s</source-volume>
        <source-vserver>%(vserver)s</source-vserver>
        <vserver>fake_destination_vserver</vserver>
      </snapmirror-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {
    'volume1': VOLUME_NAMES[0],
    'volume2': VOLUME_NAMES[1],
    'vserver': VOLUME_VSERVER_NAME,
})

SNAPMIRROR_GET_ITER_FILTERED_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <snapmirror-info>
        <destination-vserver>fake_destination_vserver</destination-vserver>
        <destination-volume>fake_destination_volume</destination-volume>
        <is-healthy>true</is-healthy>
        <mirror-state>snapmirrored</mirror-state>
        <schedule>daily</schedule>
        <source-vserver>fake_source_vserver</source-vserver>
        <source-volume>fake_source_volume</source-volume>
      </snapmirror-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""")

SNAPMIRROR_INITIALIZE_RESULT = etree.XML("""
  <results status="passed">
    <result-status>succeeded</result-status>
  </results>
""")

VSERVER_DATA_LIST_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <vserver-info>
        <vserver-name>%(vserver)s</vserver-name>
        <vserver-type>data</vserver-type>
      </vserver-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""" % {'vserver': VSERVER_NAME})

GET_CLUSTER_NAME_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes>
      <cluster-identity-info>
        <cluster-name>%(cluster)s</cluster-name>
      </cluster-identity-info>
    </attributes>
  </results>
""" % {'cluster': CLUSTER_NAME})

START_LUN_MOVE_RESPONSE = etree.XML("""
  <results status="passed">
    <job-uuid>%(job_uuid)s</job-uuid>
  </results>
""" % {'job_uuid': fake.JOB_UUID})

GET_LUN_MOVE_STATUS_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <lun-move-info>
        <job-status>complete</job-status>
      </lun-move-info>
    </attributes-list>
  </results>
""")

START_LUN_COPY_RESPONSE = etree.XML("""
  <results status="passed">
    <job-uuid>%(job_uuid)s</job-uuid>
  </results>
""" % {'job_uuid': fake.JOB_UUID})

GET_LUN_COPY_STATUS_RESPONSE = etree.XML("""
  <results status="passed">
    <attributes-list>
      <lun-move-info>
        <job-status>complete</job-status>
      </lun-move-info>
    </attributes-list>
  </results>
""")

CANCEL_LUN_COPY_RESPONSE = etree.XML("""
    <results status="passed" />
""")

START_FILE_COPY_RESPONSE = etree.XML("""
  <results status="passed">
    <job-uuid>%(job_uuid)s</job-uuid>
  </results>
""" % {'job_uuid': fake.JOB_UUID})

GET_FILE_COPY_STATUS_RESPONSE = etree.XML("""
    <results status="passed">
    <attributes-list>
      <file-copy-info>
        <scanner-status>complete</scanner-status>
      </file-copy-info>
    </attributes-list>
    <num-records>1</num-records>
  </results>
""")

DESTROY_FILE_COPY_RESPONSE = etree.XML("""
    <results status="passed" />
""")

VOLUME_GET_ITER_SSC_RESPONSE_STR_FLEXGROUP_REST = {
    "uuid": "2407b637-119c-11ec-a4fb",
    "language": "c.utf_8",
    "name": VOLUME_NAMES[0],
    "style": "flexgroup",
    "is_svm_root": False,
    "type": "rw",
    "aggregates": [
        {
            "name": VOLUME_AGGREGATE_NAMES[0]
        }
    ],
    "error_state": {
        "is_inconsistent": False
    },
    "nas": {
        "path": '/' + VOLUME_NAMES[0]
    },
    "snapshot_policy": {
        "name": "default",
        "uuid": "e7b0f455-fc15-11ea-b64a"
    },
    "svm": {
        "name": VOLUME_VSERVER_NAME
    },
    "space": {
        "size": 12345,
        "snapshot": {
            "reserve_percent": 5
        }
    },
    "qos": {
        "policy": {
            "name": "fake_qos_policy_group_name"
        }
    },
    "guarantee": {
        "type": "none",
        "honored": True
    },
    "_links": {
        "self": {
            "href": "/api/storage/volumes/2407b637-119c-11ec-a4fb"
        }
    }
}

VOLUME_GET_ITER_SSC_RESPONSE_FLEXGROUP_REST = {
    "records": [
        VOLUME_GET_ITER_SSC_RESPONSE_STR_FLEXGROUP_REST,
    ],
    "num_records": 1,
    "_links": {
        "self": {
            "href": "/api/storage/volumes"
        }
    }
}

VOLUME_GET_ITER_SSC_RESPONSE_STR_REST = {
    "uuid": "2407b637-119c-11ec-a4fb",
    "language": "c.utf_8",
    "name": VOLUME_NAMES[0],
    "style": "flexvol",
    "is_svm_root": False,
    "type": "rw",
    "aggregates": [
        {
            "name": VOLUME_AGGREGATE_NAMES[0]
        }
    ],
    "error_state": {
        "is_inconsistent": False
    },
    "nas": {
        "path": '/' + VOLUME_NAMES[0]
    },
    "snapshot_policy": {
        "name": "default",
        "uuid": "e7b0f455-fc15-11ea-b64a"
    },
    "svm": {
        "name": VOLUME_VSERVER_NAME
    },
    "space": {
        "size": 12345,
        "snapshot": {
            "reserve_percent": 5
        }
    },
    "qos": {
        "policy": {
            "name": "fake_qos_policy_group_name"
        }
    },
    "guarantee": {
        "type": "none",
        "honored": True
    },
    "efficiency": {
        "compression": "none",
        "dedupe": "none",
        "cross_volume_dedupe": "none",
        "compaction": "none",
        "schedule": "-",
        "volume_path": "/vol/" + VOLUME_NAMES[0],
        "state": "disabled",
        "policy": {
            "name": "-"
        }
    },
    "_links": {
        "self": {
            "href": "/api/storage/volumes/2407b637-119c-11ec-a4fb"
        }
    }
}

VOLUME_GET_ITER_SSC_RESPONSE_REST = {
    "records": [
        VOLUME_GET_ITER_SSC_RESPONSE_STR_REST,
    ],
    "num_records": 1,
    "_links": {
        "self": {
            "href": "/api/storage/volumes"
        }
    }
}

VOLUME_GET_ITER_RESPONSE_LIST_REST = [
    {
        "uuid": "2407b637-119c-11ec-a4fb-00a0b89c9a78",
        "name": VOLUME_NAMES[0],
        "state": "online",
        "style": "flexvol",
        "is_svm_root": False,
        "type": "rw",
        "error_state": {
            "is_inconsistent": False
        },
        "_links": {
            "self": {
                "href": "/api/storage/volumes/2407b637-119c-11ec-a4fb"
            }
        }
    },
    {
        "uuid": "2c190609-d51c-11eb-b83a",
        "name": VOLUME_NAMES[1],
        "state": "online",
        "style": "flexvol",
        "is_svm_root": False,
        "type": "rw",
        "error_state": {
            "is_inconsistent": False
        },
        "_links": {
            "self": {
                "href": "/api/storage/volumes/2c190609-d51c-11eb-b83a"
            }
        }
    }
]

VOLUME_GET_ITER_LIST_RESPONSE_REST = {
    "records": [
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[1],
    ],
    "num_records": 2,
    "_links": {
        "self": {
            "href": "/api/storage/volumes"
        }
    }
}

VOLUME_ITEM_SIMPLE_RESPONSE_REST = {
    "uuid": "2407b637-119c-11ec-a4fb-00a0b89c9a78",
    "name": VOLUME_NAMES[0],
    "style": 'flexvol',
    "_links": {
        "self": {
            "href": "/api/storage/volumes/2407b637-119c-11ec-a4fb-00a0b89c9a78"
        }
    }
}

VOLUME_LIST_SIMPLE_RESPONSE_REST = {
    "records": [
        VOLUME_ITEM_SIMPLE_RESPONSE_REST
    ],
    "num_records": 1,
    "_links": {
        "self": {
            "href": "/api/storage/volumes"
        }
    }
}

NO_RECORDS_RESPONSE_REST = {
    "records": [],
    "num_records": 0,
}

VOLUME_GET_ITER_RESPONSE_REST_PAGE = {
    "records": [
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
    ],
    "num_records": 10,
    "_links": {
        "self": {
            "href": "/api/storage/volumes?fields=name&max_records=2"
        },
        "next": {
            "href": "/api/storage/volumes?"
            f"start.uuid={VOLUME_GET_ITER_RESPONSE_LIST_REST[0]['uuid']}"
            "&fields=name&max_records=2"
        }
    }
}

VOLUME_GET_ITER_RESPONSE_REST_LAST_PAGE = {
    "records": [
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
        VOLUME_GET_ITER_RESPONSE_LIST_REST[0],
    ],
    "num_records": 8,
}

INVALID_GET_ITER_RESPONSE_NO_RECORDS_REST = {
    "num_records": 1,
}

INVALID_GET_ITER_RESPONSE_NO_NUM_RECORDS_REST = {
    "records": [],
}

VOLUME_GET_ITER_STYLE_RESPONSE_REST = {
    "records": [
        {
            "style": "flexgroup",
        },
    ],
    "num_records": 1,
}

VOLUME_FLEXGROUP_STYLE_REST = \
    VOLUME_GET_ITER_STYLE_RESPONSE_REST["records"][0]

VOLUME_GET_ITER_SAME_STYLE_RESPONSE_REST = {
    "records": [
        {
            "style": "flexvol",
        },
        {
            "style": "flexvol",
        },
        {
            "style": "flexvol",
        },
    ],
    "num_records": 3,
}

GET_NUM_RECORDS_RESPONSE_REST = {
    "num_records": 1,
}

AGGR_GET_ITER_RESPONSE_REST = {
    "records": [
        {
            "uuid": "6aad2b76-a069-47e9-93ee-e501ebf2cdd2",
            "name": VOLUME_AGGREGATE_NAMES[1],
            "node": {
                "uuid": "2ac8f13a-fc16-11ea-8799-52540006bba9",
                "name": NODE_NAME
            },
            "home_node": {
                "uuid": "2ac8f13a-fc16-11ea-8799-52540006bba9",
                "name": NODE_NAME
            },
            "snapshot": {
                "files_total": 0,
                "files_used": 0,
                "max_files_available": 0,
                "max_files_used": 0
            },
            "space": {
                "footprint": 58491584512,
                "footprint_percent": 4,
                "block_storage": {
                    "size": AGGR_SIZE_TOTAL,
                    "available": AGGR_SIZE_AVAILABLE,
                    "used": AGGR_SIZE_USED,
                    "inactive_user_data": 0,
                    "inactive_user_data_percent": 0,
                    "full_threshold_percent": 98,
                    "physical_used": 7706808320,
                    "physical_used_percent": 1,
                    "aggregate_metadata": 397373440,
                    "aggregate_metadata_percent": 0,
                    "used_including_snapshot_reserve": 58888957952,
                    "used_including_snapshot_reserve_percent": 4,
                    "data_compacted_count": 0,
                    "data_compaction_space_saved": 0,
                    "data_compaction_space_saved_percent": 0,
                    "volume_deduplication_shared_count": 0,
                    "volume_deduplication_space_saved": 0,
                    "volume_deduplication_space_saved_percent": 0
                },
                "snapshot": {
                    "used_percent": 0,
                    "available": 0,
                    "total": 0,
                    "used": 0,
                    "reserve_percent": 0
                },
                "cloud_storage": {
                    "used": 0
                },
                "efficiency": {
                    "savings": 0,
                    "ratio": 1,
                    "logical_used": 117510144
                },
                "efficiency_without_snapshots": {
                    "savings": 0,
                    "ratio": 1,
                    "logical_used": 9617408
                },
                "efficiency_without_snapshots_flexclones": {
                    "savings": 0,
                    "ratio": 1,
                    "logical_used": 9617408
                }
            },
            "state": "online",
            "snaplock_type": "non_snaplock",
            "create_time": "2020-09-21T14:45:11+00:00",
            "data_encryption": {
                "software_encryption_enabled": False,
                "drive_protection_enabled": False
            },
            "block_storage": {
                "primary": {
                    "disk_count": 1,
                    "disk_class": "virtual",
                    "raid_type": "raid0",
                    "raid_size": 8,
                    "checksum_style": "advanced_zoned",
                    "disk_type": "vm_disk"
                },
                "hybrid_cache": {
                    "enabled": False
                },
                "mirror": {
                    "enabled": False,
                    "state": "unmirrored"
                },
                "plexes": [
                    {
                        "name": "plex0"
                    }
                ],
                "storage_type": "hdd"
            },
            "cloud_storage": {
                "attach_eligible": True
            },
            "inactive_data_reporting": {
                "enabled": False
            },
            "metric": {
                "timestamp": "2021-12-21T13:25:15Z",
                "duration": "PT15S",
                "status": "ok",
                "throughput": {
                    "read": 0,
                    "write": 13107,
                    "other": 0,
                    "total": 13107
                },
                "latency": {
                    "read": 0,
                    "write": 2659,
                    "other": 0,
                    "total": 2659
                },
                "iops": {
                    "read": 0,
                    "write": 0,
                    "other": 0,
                    "total": 0
                }
            },
            "statistics": {
                "timestamp": "2021-12-21T13:25:21Z",
                "status": "ok",
                "throughput_raw": {
                    "read": 3699994624,
                    "write": 111813349376,
                    "other": 0,
                    "total": 115513344000
                },
                "latency_raw": {
                    "read": 1884163936,
                    "write": 9308463160,
                    "other": 0,
                    "total": 11192627096
                },
                "iops_raw": {
                    "read": 242498,
                    "write": 4871034,
                    "other": 0,
                    "total": 5113532
                }
            }
        },
        {
            "uuid": "ad20dafb-1dcb-483a-b457-012ae9225062",
            "name": VOLUME_AGGREGATE_NAMES[0],
            "node": {
                "uuid": "2ac8f13a-fc16-11ea-8799-52540006bba9",
                "name": NODE_NAME
            },
            "home_node": {
                "uuid": "2ac8f13a-fc16-11ea-8799-52540006bba9",
                "name": NODE_NAME
            },
            "snapshot": {
                "files_total": 0,
                "files_used": 0,
                "max_files_available": 0,
                "max_files_used": 0
            },
            "space": {
                "footprint": 172316893184,
                "footprint_percent": 14,
                "block_storage": {
                    "size": 1271819509760,
                    "available": 1099709939712,
                    "used": 172109570048,
                    "inactive_user_data": 0,
                    "inactive_user_data_percent": 0,
                    "full_threshold_percent": 98,
                    "physical_used": 27038863360,
                    "physical_used_percent": 2,
                    "aggregate_metadata": 0,
                    "aggregate_metadata_percent": 0,
                    "used_including_snapshot_reserve": 172109570048,
                    "used_including_snapshot_reserve_percent": 14,
                    "data_compacted_count": 0,
                    "data_compaction_space_saved": 0,
                    "data_compaction_space_saved_percent": 0,
                    "volume_deduplication_shared_count": 0,
                    "volume_deduplication_space_saved": 0,
                    "volume_deduplication_space_saved_percent": 0
                },
                "snapshot": {
                    "used_percent": 0,
                    "available": 0,
                    "total": 0,
                    "used": 0,
                    "reserve_percent": 0
                },
                "cloud_storage": {
                    "used": 0
                },
                "efficiency": {
                    "savings": 74937720832,
                    "ratio": 9.238858947247071,
                    "logical_used": 84033363968
                },
                "efficiency_without_snapshots": {
                    "savings": 0,
                    "ratio": 1,
                    "logical_used": 7005036544
                },
                "efficiency_without_snapshots_flexclones": {
                    "savings": 0,
                    "ratio": 1,
                    "logical_used": 7005036544
                }
            },
            "state": "online",
            "snaplock_type": "non_snaplock",
            "create_time": "2020-09-21T14:44:51+00:00",
            "data_encryption": {
                "software_encryption_enabled": False,
                "drive_protection_enabled": False
            },
            "block_storage": {
                "primary": {
                    "disk_count": 1,
                    "disk_class": "virtual",
                    "raid_type": "raid0",
                    "raid_size": 8,
                    "checksum_style": "advanced_zoned",
                    "disk_type": "vm_disk"
                },
                "hybrid_cache": {
                    "enabled": False
                },
                "mirror": {
                    "enabled": False,
                    "state": "unmirrored"
                },
                "plexes": [
                    {
                        "name": "plex0"
                    }
                ],
                "storage_type": "hdd"
            },
            "cloud_storage": {
                "attach_eligible": True
            },
            "inactive_data_reporting": {
                "enabled": False
            },
            "metric": {
                "timestamp": "2021-12-21T13:25:15Z",
                "duration": "PT15S",
                "status": "ok",
                "throughput": {
                    "read": 0,
                    "write": 27033,
                    "other": 0,
                    "total": 27033
                },
                "latency": {
                    "read": 0,
                    "write": 1173,
                    "other": 0,
                    "total": 1173
                },
                "iops": {
                    "read": 0,
                    "write": 0,
                    "other": 0,
                    "total": 0
                }
            },
            "statistics": {
                "timestamp": "2021-12-21T13:25:21Z",
                "status": "ok",
                "throughput_raw": {
                    "read": 5740912640,
                    "write": 132358234112,
                    "other": 0,
                    "total": 138099146752
                },
                "latency_raw": {
                    "read": 15095876198,
                    "write": 12140289450,
                    "other": 0,
                    "total": 27236165648
                },
                "iops_raw": {
                    "read": 535930,
                    "write": 6011240,
                    "other": 0,
                    "total": 6547170
                }
            }
        }
    ],
    "num_records": 2
}

LUN_GET_ITER_REST = {
    "records": [
        {
            "uuid": "bd6baab3-4842-45b6-b627-45b305ed2e84",
            "svm": {
                "uuid": "fake-uuid",
                "name": "vserver-name",
            },
            "name": "/vol/nahim_dev_vol01/volume-fake-uuid",
            "location": {
                "logical_unit": "volume-fake-uuid",
                "node": {
                    "name": "node-name",
                    "uuid": "fake-uuid",
                },
                "volume": {
                    "uuid": "fake-uuid",
                    "name": "nahim_dev_vol01",
                }
            },
            "auto_delete": False,
            "class": "regular",
            "create_time": "2021-12-09T14:07:31+00:00",
            "enabled": True,
            "lun_maps": [
                {
                    "logical_unit_number": 0,
                    "igroup": {
                        "uuid": "fake-uuid",
                        "name": "openstack-fake-uuid",
                    },
                }
            ],
            "os_type": "linux",
            "serial_number": "ZlAFA?QMnBdX",
            "space": {
                "scsi_thin_provisioning_support_enabled": False,
                "size": 10737418240,
                "used": 3474366464,
                "guarantee": {
                    "requested": False,
                    "reserved": False
                }
            },
            "status": {
                "container_state": "online",
                "mapped": True,
                "read_only": False,
                "state": "online"
            },
            "vvol": {
                "is_bound": False
            },
            "metric": {
                "timestamp": "2021-12-23T20:36:00Z",
                "duration": "PT15S",
                "status": "ok",
                "throughput": {
                    "read": 0,
                    "write": 0,
                    "other": 0,
                    "total": 0
                },
                "iops": {
                    "read": 0,
                    "write": 0,
                    "other": 0,
                    "total": 0
                },
                "latency": {
                    "read": 0,
                    "write": 0,
                    "other": 0,
                    "total": 0
                }
            },
            "statistics": {
                "timestamp": "2021-12-23T20:36:02Z",
                "status": "ok",
                "throughput_raw": {
                    "read": 1078230528,
                    "write": 3294724096,
                    "other": 0,
                    "total": 4372954624
                },
                "iops_raw": {
                    "read": 16641,
                    "write": 51257,
                    "other": 59,
                    "total": 67957
                },
                "latency_raw": {
                    "read": 2011655,
                    "write": 1235068755,
                    "other": 1402,
                    "total": 1237081812
                }
            },
        },
        {
            "uuid": "dff549b8-fabe-466b-8608-871a6493b492",
            "svm": {
                "uuid": "fake-uuid",
                "name": "vserver-name",
                "_links": {
                    "self": {
                        "href": "/api/svm/svms/fake-uuid"
                    }
                }
            },
            "name": "/vol/nahim_dev_vol01/volume-fake-uuid",
            "location": {
                "logical_unit": "volume-fake-uuid",
                "node": {
                    "name": "node-name",
                    "uuid": "fake-uuid",
                    "_links": {
                        "self": {
                            "href": "/api/cluster/nodes/fake-uuid"
                        }
                    }
                },
                "volume": {
                    "uuid": "fake-uuid",
                    "name": "nahim_dev_vol01",
                    "_links": {
                        "self": {
                            "href": "/api/storage/volumes/fake-uuid"
                        }
                    }
                }
            },
            "auto_delete": False,
            "class": "regular",
            "create_time": "2021-12-14T18:12:38+00:00",
            "enabled": True,
            "os_type": "linux",
            "serial_number": "ZlAFA?QMnBdf",
            "space": {
                "scsi_thin_provisioning_support_enabled": False,
                "size": 5368709120,
                "used": 0,
                "guarantee": {
                    "requested": False,
                    "reserved": False
                }
            },
            "status": {
                "container_state": "online",
                "mapped": False,
                "read_only": False,
                "state": "online"
            },
            "vvol": {
                "is_bound": False
            },
        }
    ],
    "num_records": 2,
}

LUN_GET_ITER_RESULT = [
    {
        'Vserver': LUN_GET_ITER_REST['records'][0]['svm']['name'],
        'Volume':
            LUN_GET_ITER_REST['records'][0]['location']['volume']['name'],
        'Size': LUN_GET_ITER_REST['records'][0]['space']['size'],
        'Qtree': (LUN_GET_ITER_REST['records'][0]['location']
                  .get('qtree', {}).get('name', '')),
        'Path': LUN_GET_ITER_REST['records'][0]['name'],
        'OsType': LUN_GET_ITER_REST['records'][0]['os_type'],
        'SpaceReserved':
            LUN_GET_ITER_REST['records'][0]['space']['guarantee']['requested'],
        'UUID': LUN_GET_ITER_REST['records'][0]['uuid'],
    },
    {
        'Vserver': LUN_GET_ITER_REST['records'][1]['svm']['name'],
        'Volume':
            LUN_GET_ITER_REST['records'][1]['location']['volume']['name'],
        'Size': LUN_GET_ITER_REST['records'][1]['space']['size'],
        'Qtree': (LUN_GET_ITER_REST['records'][1]['location']
                  .get('qtree', {}).get('name', '')),
        'Path': LUN_GET_ITER_REST['records'][1]['name'],
        'OsType': LUN_GET_ITER_REST['records'][1]['os_type'],
        'SpaceReserved':
            LUN_GET_ITER_REST['records'][1]['space']['guarantee']['requested'],
        'UUID': LUN_GET_ITER_REST['records'][1]['uuid'],
    },
]

FILE_DIRECTORY_GET_ITER_REST = {
    "_links": {
        "next": {
            "href": "/api/resourcelink"
        },
        "self": {
            "href": "/api/resourcelink"
        }
    },
    "num_records": 2,
    "records": [
        {
            "_links": {
                "metadata": {
                    "href": "/api/resourcelink"
                },
                "self": {
                    "href": "/api/resourcelink"
                }
            },
            "name": "test_file",
            "path": "d1/d2/d3",
            "size": 200,
            "type": "file"
        },
        {
            "_links": {
                "metadata": {
                    "href": "/api/resourcelink"
                },
                "self": {
                    "href": "/api/resourcelink"
                }
            },
            "name": "test_file_2",
            "path": "d1/d2/d3",
            "size": 250,
            "type": "file"
        }
    ]
}

FILE_DIRECTORY_GET_ITER_RESULT_REST = [
    {
        'name': FILE_DIRECTORY_GET_ITER_REST['records'][0]['name'],
        'file-size': float(FILE_DIRECTORY_GET_ITER_REST['records'][0]['size'])
    },
    {
        'name': FILE_DIRECTORY_GET_ITER_REST['records'][1]['name'],
        'file-size': float(FILE_DIRECTORY_GET_ITER_REST['records'][1]['size'])
    }
]

LUN_GET_MOVEMENT_REST = {
    "_links": {
        "self": {
            "href": "/api/resourcelink"
        }
    },
    "name": "/vol/volume1/qtree1/lun1",
    "uuid": "1cd8a442-86d1-11e0-ae1c-123478563412",
    "movement": {
        "progress": {
            "elapsed": 0,
            "failure": {
                "arguments": [
                    {
                        "code": "string",
                        "message": "string"
                    }
                ],
                "code": "4",
                "message": "entry doesn't exist",
                "target": "uuid"
            },
            "percent_complete": 0,
            "state": "preparing",
            "volume_snapshot_blocked": True
        }
    }
}

LUN_GET_COPY_REST = {
    "_links": {
        "self": {
            "href": "/api/resourcelink"
        }
    },
    "name": "/vol/volume1/qtree1/lun1",
    "uuid": "1cd8a442-86d1-11e0-ae1c-123478563412",
    "copy": {
        "source": {
            "_links": {
                "self": {
                    "href": "/api/resourcelink"
                }
            },
            "progress": {
                "elapsed": 0,
                "failure": {
                    "arguments": [
                        {
                            "code": "string",
                            "message": "string"
                        }
                    ],
                    "code": "4",
                    "message": "entry doesn't exist",
                    "target": "uuid"
                },
                "percent_complete": 0,
                "state": "preparing",
                "volume_snapshot_blocked": True
            },
        }
    },
}

VOLUME_GET_ITER_STATE_RESPONSE_REST = {
    "records": [
        {
            "uuid": "c19aef05-ac60-4211-9fe4-3ef8c8816c83",
            "name": "fake_volume",
            "state": VOLUME_STATE_ONLINE,
            "style": "flexvol",
            "nas": {
                "path": "/fake/vol"
            },
        }
    ],
    "num_records": 1,
}

GET_OPERATIONAL_LIF_ADDRESSES_RESPONSE_REST = {
    'records': [
        {
            'uuid': 'fake_uuid_1',
            'name': 'vserver_name',
            'ip': {'address': '1.2.3.4'},
            'state': 'up'
        },
        {
            'uuid': 'fake_uuid_2',
            'name': 'vserver_name',
            'ip': {'address': '99.98.97.96'},
            'state': 'up'
        }
    ],
    'num_records': 2
}

ERROR_RESPONSE_REST = {
    "error": {
        "code": 1100,
        "message": "fake error",
    }
}

FAKE_ACTION_ENDPOINT = '/fake_endpoint'
FAKE_BASE_ENDPOINT = '/fake_api'
FAKE_HEADERS = {'header': 'fake_header'}
FAKE_BODY = {'body': 'fake_body'}
FAKE_HTTP_QUERY = {'type': 'fake_type'}
FAKE_FORMATTED_HTTP_QUERY = '?type=fake_type'

JOB_RESPONSE_REST = {
    "job": {
        "uuid": FAKE_UUID,
        "_links": {
            "self": {
                "href": f"/api/cluster/jobs/{FAKE_UUID}"
            }
        }
    }
}

VSERVER_DATA_LIST_RESPONSE_REST = {
    'records': [
        {
            'name': VSERVER_NAME
        },
        {
            'name': VSERVER_NAME_2
        }
    ],
    'num_records': 2,
}

PERF_COUNTER_LIST_INFO_WAFL_RESPONSE_REST = {
    'name': 'wafl',
    'counter_schemas': [
        {
            'name': 'cp_phase_times',
            'description': 'Array of percentage time spent in different phases'
                           + ' of Consistency Point (CP).',
            'type': 'percent',
            'unit': 'percent',
            'denominator': {
                'name': 'total_cp_msecs'
            }
        }
    ],
}

PERF_COUNTER_TOTAL_CP_MSECS_LABELS_REST = [
    'cp_setup', 'cp_pre_p0', 'cp_p0_snap_del', 'cp_p1_clean', 'cp_p1_quota',
    'cp_ipu_disk_add', 'cp_p2v_inofile', 'cp_p2v_ino_pub', 'cp_p2v_ino_pri',
    'cp_p2v_fsinfo', 'cp_p2v_dlog1', 'cp_p2v_dlog2', 'cp_p2v_refcount',
    'cp_p2v_topaa', 'cp_p2v_df_scores_sub', 'cp_p2v_bm', 'cp_p2v_snap',
    'cp_p2v_df_scores', 'cp_p2v_volinfo', 'cp_p2v_cont', 'cp_p2a_inofile',
    'cp_p2a_ino', 'cp_p2a_dlog1', 'cp_p2a_hya', 'cp_p2a_dlog2',
    'cp_p2a_fsinfo', 'cp_p2a_ipu_bitmap_grow', 'cp_p2a_refcount',
    'cp_p2a_topaa', 'cp_p2a_hyabc', 'cp_p2a_bm', 'cp_p2a_snap',
    'cp_p2a_volinfo', 'cp_p2_flush', 'cp_p2_finish', 'cp_p3_wait',
    'cp_p3v_volinfo', 'cp_p3a_volinfo', 'cp_p3_finish', 'cp_p4_finish',
    'cp_p5_finish',
]

PERF_COUNTER_TOTAL_CP_MSECS_LABELS_RESULT = [
    label[3:] for label in PERF_COUNTER_TOTAL_CP_MSECS_LABELS_REST
]

PERF_COUNTER_TOTAL_CP_MSECS_VALUES_REST = [
    0, 3112, 3, 0, 0, 3, 757, 0, 99, 0, 26, 0, 22, 1, 0, 194, 4, 224, 359, 222,
    0, 0, 0, 0, 0, 0, 82, 0, 0, 0, 0, 0, 0, 62, 0, 133, 16, 35, 334219, 43,
    2218, 20, 0,
]

PERF_COUNTER_TABLE_ROWS_WAFL = {
    'records': [
        {
            'id': NODE_NAME + ':wafl',
            'counters': [
                {
                    'name': 'cp_phase_times',
                    'values': PERF_COUNTER_TOTAL_CP_MSECS_VALUES_REST,
                    'labels': PERF_COUNTER_TOTAL_CP_MSECS_LABELS_REST
                }
            ],
        }
    ],
    'num_records': 1,
}

PERF_COUNTER_DOMAIN_BUSY_LABELS = [
    'exempt', 'ha', 'host_os', 'idle', 'kahuna', 'kahuna_legacy', 'none',
    'nwk_exempt', 'network', 'protocol', 'raid', 'raid_exempt', 'sm_exempt',
    'ssan_exempt', 'storage', 'target', 'unclassified', 'wafl_exempt',
    'wafl_mpcleaner', 'xor_exempt', 'ssan_exempt2', 'exempt_ise', 'zombie',
]

PERF_COUNTER_DOMAIN_BUSY_VALUES_1 = [
    83071627197, 1334877, 19459898, 588539096, 11516887, 14878622, 18,
    647698, 20, 229232646, 4310322, 441035, 12946782, 57837913, 38765442,
    1111004351701, 1497335, 949657, 109890, 768027, 21, 14, 13
]

PERF_COUNTER_DOMAIN_BUSY_VALUES_2 = [
    1191129018056, 135991, 22842513, 591213798, 9449562, 15345460, 0,
    751656, 0, 162605694, 3927323, 511160, 7644403, 29696759, 21787992,
    3585552592, 1058902, 957296, 87811, 499766, 0, 0, 0
]

PERF_COUNTER_ELAPSED_TIME_1 = 1199265469753
PERF_COUNTER_ELAPSED_TIME_2 = 1199265469755

PERF_GET_INSTANCES_PROCESSOR_RESPONSE_REST = {
    'records': [
        {
            'counter_table': {
                'name': 'processor'
            },
            'id': NODE_NAME + ':processor0',
            'counters': [
                {
                    'name': 'domain_busy_percent',
                    'values': PERF_COUNTER_DOMAIN_BUSY_VALUES_1,
                    'labels': PERF_COUNTER_DOMAIN_BUSY_LABELS
                },
                {
                    'name': 'elapsed_time',
                    'value': PERF_COUNTER_ELAPSED_TIME_1,
                }
            ],
        },
        {
            'counter_table': {
                'name': 'processor'
            },
            'id': NODE_NAME + ':processor1',
            'counters': [
                {
                    'name': 'domain_busy_percent',
                    'values': PERF_COUNTER_DOMAIN_BUSY_VALUES_2,
                    'labels': PERF_COUNTER_DOMAIN_BUSY_LABELS
                },
                {
                    'name': 'elapsed_time',
                    'value': PERF_COUNTER_ELAPSED_TIME_2,
                }
            ],
        }
    ],
    'num_records': 2,
}

PERF_COUNTERS_PROCESSOR_EXPECTED = [
    {
        'instance-name': 'processor',
        'instance-uuid': NODE_NAME + ':processor0',
        'node-name': NODE_NAME,
        'timestamp': mock.ANY,
        'domain_busy':
            ','.join([str(v) for v in PERF_COUNTER_DOMAIN_BUSY_VALUES_1])
    },
    {
        'instance-name': 'processor',
        'instance-uuid': NODE_NAME + ':processor0',
        'node-name': NODE_NAME,
        'timestamp': mock.ANY,
        'processor_elapsed_time': PERF_COUNTER_ELAPSED_TIME_1
    },
    {
        'instance-name': 'processor',
        'instance-uuid': NODE_NAME + ':processor1',
        'node-name': NODE_NAME,
        'timestamp': mock.ANY,
        'domain_busy':
            ','.join([str(v) for v in PERF_COUNTER_DOMAIN_BUSY_VALUES_2])
    },
    {
        'instance-name': 'processor',
        'instance-uuid': NODE_NAME + ':processor1',
        'node-name': NODE_NAME,
        'timestamp': mock.ANY,
        'processor_elapsed_time': PERF_COUNTER_ELAPSED_TIME_2
    },
]

SINGLE_IGROUP_REST = {
    "svm": {
        "uuid": FAKE_UUID,
        "name": VOLUME_VSERVER_NAME,
    },
    "uuid": FAKE_UUID,
    "name": "openstack-e6bf1584-bfb3-4cdb-950d-525bf6f26b53",
            "protocol": "iscsi",
            "os_type": "linux",
            "initiators": [
                {
                    "name": "iqn.1993-08.org.fake:01:5b67769f5c5e",
                }
    ],
}

IGROUP_GET_ITER_REST = {
    "records": [
        SINGLE_IGROUP_REST
    ],
    "num_records": 1,
}

IGROUP_GET_ITER_MULT_REST = {
    "records": [
        SINGLE_IGROUP_REST,
        SINGLE_IGROUP_REST
    ],
    "num_records": 2,
}

IGROUP_GET_ITER_INITS_REST = {
    "records": [
        {
            "svm": {
                "uuid": FAKE_UUID,
                "name": VOLUME_VSERVER_NAME,
            },
            "uuid": FAKE_UUID,
            "name": "openstack-e6bf1584-bfb3-4cdb-950d-525bf6f26b53",
            "protocol": "iscsi",
            "os_type": "linux",
            "initiators": [
                {
                    "name": "iqn.1993-08.org.fake:01:5b67769f5c5e",
                },
                {
                    "name": "iqn.1993-08.org.fake:02:5b67769f5c5e",
                }
            ],
        }
    ],
    "num_records": 1,
}

GET_LUN_MAP_REST = {
    "records": [
        {
            "svm": {
                "uuid": FAKE_UUID,
                "name": VSERVER_NAME,
            },
            "lun": {
                "uuid": "6c2969dc-b022-434c-b7cd-9240bs975187",
                "name": LUN_NAME_PATH,
            },
            "igroup": {
                "uuid": "08088517-a6f5-11ec-82cc-00a0b89c9a78",
                "name": IGROUP_NAME,
            },
            "logical_unit_number": 0,
        }
    ],
    "num_records": 1,
}

FC_INTERFACE_REST = {
    "records": [
        {
            "data_protocol": "fcp",
            "location": {
                "port": {
                    "name": "0a",
                    "uuid": FAKE_UUID,
                    "node": {
                        "name": "node1"
                    }
                },
                "node": {
                    "name": "node1",
                    "uuid": FAKE_UUID,
                }
            },
            "wwpn": "20:00:00:50:56:b4:13:a8",
            "name": "lif1",
            "uuid": FAKE_UUID,
            "state": "up",
            "port_address": "5060F",
            "wwnn": "20:00:00:50:56:b4:13:01",
            "comment": "string",
            "svm": {
                "name": VOLUME_VSERVER_NAME,
                "uuid": FAKE_UUID,
            },
            "enabled": True
        }
    ],
    "num_records": 1
}

GET_LUN_MAPS = {
    "records": [
        {
            "svm": {
                "uuid": "77deec3a-38ea-11ec-aca8-00a0b89c9a78",
                "name": VOLUME_NAME,
            },
            "uuid": "99809170-a92c-11ec-82cc-0aa0b89c9a78",
            "name": "openstack-626d20dc-c420-4a5a-929c-59178d64f2c5",
            "initiators": [
                {
                    "name": "iqn.2005-03.org.open-iscsi:49ebe8a87d1",
                }
            ],
            "lun_maps": [
                {
                    "logical_unit_number": 0,
                    "lun": {
                        "name": LUN_NAME_PATH,
                        "uuid": "91e83a0a-72c3-4278-9a24-f2f8135aa5db",
                        "node": {
                            "name": CLUSTER_NAME,
                            "uuid": "9eff6c76-fc13-11ea-8799-525a0006bba9",
                        },
                    },
                }
            ],
        }
    ],
    "num_records": 1,
}

SNAPMIRROR_GET_ITER_RESPONSE_REST = {
    "records": [
        {
            "uuid": FAKE_UUID,
            "source": {
                "path": SM_SOURCE_VSERVER + ':' + SM_SOURCE_VOLUME,
                "svm": {
                    "name": SM_SOURCE_VSERVER
                }
            },
            "destination": {
                "path": SM_DEST_VSERVER + ':' + SM_DEST_VOLUME,
                "svm": {
                    "name": SM_DEST_VSERVER
                }
            },
            "policy": {
                "type": "async"
            },
            "state": "snapmirrored",
            "transfer": {"state": "success"},
            "healthy": True
        }
    ],
    "num_records": 1,
}

GET_LUN_MAPS_NO_MAPS = {
    "records": [
        {
            "svm": {
                "uuid": "77deec3a-38ea-11ec-aca8-00a0b89c9a78",
                "name": VOLUME_NAME,
            },
            "uuid": "99809170-a92c-11ec-82cc-0aa0b89c9a78",
            "name": "openstack-626d20dc-c420-4a5a-929c-59178d64f2c5",
            "initiators": [
                {
                    "name": "iqn.2005-03.org.open-iscsi:49ebe8a87d1",
                }
            ],
        }
    ],
    "num_records": 1,
}

GET_ISCSI_SERVICE_DETAILS_REST = {
    "records": [
        {
            "svm": {
                "uuid": FAKE_UUID,
                "name": VOLUME_VSERVER_NAME,
            },
            "target": {
                "name": INITIATOR_IQN
            },
        }
    ],
    "num_records": 1,
}

CHECK_ISCSI_INITIATOR_REST = {
    "records": [
        {
            "svm": {
                "uuid": FAKE_UUID,
                "name": VOLUME_VSERVER_NAME,
            },
            "initiator": INITIATOR_IQN,
        }
    ],
    "num_records": 1,
}

GET_ISCSI_TARGET_DETAILS_REST = {
    "records": [
        {
            "uuid": FAKE_UUID,
            "name": VOLUME_VSERVER_NAME,
            "ip": {
                "address": "192.168.1.254"
            },
            "enabled": True,
            "services": [
                "data_core",
                "data_iscsi"
            ],
        }
    ],
    "num_records": 1,
}

VOLUME_GET_ITER_CAPACITY_RESPONSE_REST = {
    "records": [
        {
            "uuid": FAKE_UUID,
            "name": VOLUME_NAME,
            "space": {
                "available": VOLUME_SIZE_AVAILABLE,
                "afs_total": VOLUME_SIZE_TOTAL
            },
        }
    ],
    "num_records": 1,
}

REST_GET_SNAPMIRRORS_RESPONSE = [{
    'destination-volume': SM_DEST_VOLUME,
    'destination-vserver': SM_DEST_VSERVER,
    'is-healthy': True,
    'lag-time': None,
    'last-transfer-end-timestamp': None,
    'mirror-state': 'snapmirrored',
    'relationship-status': 'idle',
    'source-volume': SM_SOURCE_VOLUME,
    'source-vserver': SM_SOURCE_VSERVER,
    'uuid': FAKE_UUID,
    'transferring-state': 'success',
}]

TRANSFERS_GET_ITER_REST = {
    "records": [
        {
            "uuid": FAKE_UUID,
            "state": "transferring"
        },
        {
            "uuid": FAKE_UUID,
            "state": "failed"
        }
    ],
    "num_records": 2,
}

JOB_SUCCESSFUL_REST = {
    "uuid": FAKE_UUID,
    "description": "Fake description",
    "state": "success",
    "message": "success",
    "code": 0,
    "start_time": "2022-02-18T20:08:03+00:00",
    "end_time": "2022-02-18T20:08:04+00:00",
}

JOB_ERROR_REST = {
    "uuid": FAKE_UUID,
    "description": "Fake description",
    "state": "failure",
    "message": "failure",
    "code": -1,
    "start_time": "2022-02-18T20:08:03+00:00",
    "end_time": "2022-02-18T20:08:04+00:00",
}

GET_CLUSTER_NAME_RESPONSE_REST = {
    "name": CLUSTER_NAME,
    "uuid": "fake-cluster-uuid"
}

GET_VSERVER_PEERS_RECORDS_REST = [
    {
        "_links": {
            "self": {
                "href": "/api/resourcelink"
            }
        },
        "applications": [
            "snapmirror",
            "lun_copy"
        ],
        "name": CLUSTER_NAME,
        "peer": {
            "cluster": {
                "_links": {
                    "self": {
                        "href": "/api/resourcelink"
                    }
                },
                "name": REMOTE_CLUSTER_NAME,
                "uuid": "fake-cluster-uuid-2"
            },
            "svm": {
                "_links": {
                    "self": {
                        "href": "/api/resourcelink"
                    }
                },
                "name": VSERVER_NAME_2,
                "uuid": "fake-svm-uuid-2"
            }
        },
        "state": "peered",
        "svm": {
            "_links": {
                "self": {
                    "href": "/api/resourcelink"
                }
            },
            "name": VSERVER_NAME,
            "uuid": "fake-svm-uuid"
        },
        "uuid": "fake-cluster-uuid"
    }
]

GET_VSERVER_PEERS_RESPONSE_REST = {
    "_links": {
        "next": {
            "href": "/api/resourcelink"
        },
        "self": {
            "href": "/api/resourcelink"
        }
    },
    "num_records": 1,
    "records": GET_VSERVER_PEERS_RECORDS_REST
}

GET_NAMESPACE_RESPONSE_REST = {
    "records": [
        {
            "uuid": "fake_uuid1",
            "svm": {
                "name": "fake_vserver1"
            },
            "name": "/vol/fake_vol_001/test",
            "location": {
                "volume": {
                    "name": "fake_vol_001"
                }
            },
            "os_type": "linux",
            "space": {
                "block_size": 9999,
                "size": 999999,
                "guarantee": {
                    "requested": True
                }
            },
        },
        {
            "uuid": "fake_uuid2",
            "svm": {
                "name": "fake_vserver2"
            },
            "name": "/vol/fake_vol_002/test",
            "location": {
                "volume": {
                    "name": "fake_vol_002"
                }
            },
            "os_type": "linux",
            "space": {
                "block_size": 8888,
                "size": 8888888,
                "guarantee": {
                    "requested": True
                }
            },
        }
    ],
    "num_records": 2,
}

SUBSYSTEM = 'openstack-fake_subsystem'
TARGET_NQN = 'nqn.1992-01.example.com:target'
GET_SUBSYSTEM_RESPONSE_REST = {
    "records": [
        {
            "uuid": "fake_uuid1",
            "name": SUBSYSTEM,
            "os_type": "linux",
            "target_nqn": TARGET_NQN,
        }
    ],
    "num_records": 1,
}

GET_SUBSYSTEM_MAP_RESPONSE_REST = {
    "records": [
        {
            "namespace": {
                "uuid": FAKE_UUID,
            },
            "subsystem": {
                "name": SUBSYSTEM
            },
            "svm": {
                "name": VSERVER_NAME
            },
        },
    ],
    "num_records": 1,
}

GET_INTERFACES_NVME_REST = {
    'records': [
        {
            "ip": {
                "address": "10.10.10.10",
            }
        }
    ],
    'num_records': 1
}
