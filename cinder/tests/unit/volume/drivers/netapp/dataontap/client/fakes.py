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


from lxml import etree
import mock
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

SNAPSHOT_INFO_FOR_PRESENT_NOT_BUSY_SNAPSHOT_7MODE = etree.XML("""
    <results status="passed">
    <snapshots>
      <snapshot-info>
        <name>%(snapshot_name)s</name>
        <busy>False</busy>
        <volume>%(vol_name)s</volume>
      </snapshot-info>
    </snapshots>
    </results>
""" % {
    'snapshot_name': fake.SNAPSHOT['name'],
    'vol_name': fake.SNAPSHOT['volume_id'],
})

SNAPSHOT_INFO_FOR_PRESENT_BUSY_SNAPSHOT_7MODE = etree.XML("""
    <results status="passed">
    <snapshots>
      <snapshot-info>
        <name>%(snapshot_name)s</name>
        <busy>True</busy>
        <volume>%(vol_name)s</volume>
      </snapshot-info>
    </snapshots>
    </results>
""" % {
    'snapshot_name': fake.SNAPSHOT['name'],
    'vol_name': fake.SNAPSHOT['volume_id'],
})

SNAPSHOT_NOT_PRESENT_7MODE = etree.XML("""
    <results status="passed">
    <snapshots>
      <snapshot-info>
        <name>NOT_THE_RIGHT_SNAPSHOT</name>
        <busy>false</busy>
        <volume>%(vol_name)s</volume>
      </snapshot-info>
    </snapshots>
    </results>
""" % {'vol_name': fake.SNAPSHOT['volume_id']})

NO_RECORDS_RESPONSE = etree.XML("""
  <results status="passed">
    <num-records>0</num-records>
  </results>
""")

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

PERF_OBJECT_GET_INSTANCES_SYSTEM_RESPONSE_7MODE = etree.XML("""
  <results status="passed">
    <timestamp>1454146292</timestamp>
    <instances>
      <instance-data>
        <name>system</name>
        <counters>
          <counter-data>
            <name>avg_processor_busy</name>
            <value>13215732322</value>
          </counter-data>
        </counters>
      </instance-data>
    </instances>
  </results>""")

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
