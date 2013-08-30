#    Copyright 2012 OpenStack LLC
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

import mox

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.san.hp_lefthand import HpSanISCSIDriver

LOG = logging.getLogger(__name__)


class HpSanISCSITestCase(test.TestCase):

    def setUp(self):
        super(HpSanISCSITestCase, self).setUp()
        self.stubs.Set(HpSanISCSIDriver, "_cliq_run",
                       self._fake_cliq_run)
        self.stubs.Set(HpSanISCSIDriver, "_get_iscsi_properties",
                       self._fake_get_iscsi_properties)
        configuration = mox.MockObject(conf.Configuration)
        configuration.san_is_local = False
        configuration.san_ip = "10.0.0.1"
        configuration.san_login = "foo"
        configuration.san_password = "bar"
        configuration.san_ssh_port = 16022
        configuration.san_clustername = "CloudCluster1"
        configuration.san_thin_provision = True
        configuration.append_config_values(mox.IgnoreArg())

        self.driver = HpSanISCSIDriver(configuration=configuration)
        self.volume_name = "fakevolume"
        self.snapshot_name = "fakeshapshot"
        self.connector = {'ip': '10.0.0.2',
                          'initiator': 'iqn.1993-08.org.debian:01:222',
                          'host': 'fakehost'}
        self.properties = {
            'target_discoverd': True,
            'target_portal': '10.0.1.6:3260',
            'target_iqn':
            'iqn.2003-10.com.lefthandnetworks:group01:25366:fakev',
            'volume_id': 1}

    def tearDown(self):
        super(HpSanISCSITestCase, self).tearDown()

    def _fake_get_iscsi_properties(self, volume):
        return self.properties

    def _fake_cliq_run(self, verb, cliq_args, check_exit_code=True):
        """Return fake results for the various methods."""

        def create_volume(cliq_args):
            """Create volume CLIQ input for test.

            input = "createVolume description="fake description"
                                  clusterName=Cluster01 volumeName=fakevolume
                                  thinProvision=0 output=XML size=1GB"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="181" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['thinProvision'], '1')
            self.assertEqual(cliq_args['size'], '1GB')
            return output, None

        def delete_volume(cliq_args):
            """Delete volume CLIQ input for test.

            input = "deleteVolume volumeName=fakevolume prompt=false
                                  output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="164" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['prompt'], 'false')
            return output, None

        def extend_volume(cliq_args):
            """Extend volume CLIQ input for test.

            input = "modifyVolume description="fake description"
                                  volumeName=fakevolume
                                  output=XML size=2GB"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="181" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['size'], '2GB')
            return output, None

        def assign_volume(cliq_args):
            """Assign volume CLIQ input for test.

            input = "assignVolumeToServer volumeName=fakevolume
                                          serverName=fakehost
                                          output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="174" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['serverName'], self.connector['host'])
            return output, None

        def unassign_volume(cliq_args):
            """Unassign volume CLIQ input for test.

            input = "unassignVolumeToServer volumeName=fakevolume
                                            serverName=fakehost output=XML
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="205" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['serverName'], self.connector['host'])
            return output, None

        def create_snapshot(cliq_args):
            """Create snapshot CLIQ input for test.

            input = "createSnapshot description="fake description"
                                    snapshotName=fakesnapshot
                                    volumeName=fakevolume
                                    output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="181" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['snapshotName'], self.snapshot_name)
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            return output, None

        def delete_snapshot(cliq_args):
            """Delete shapshot CLIQ input for test.

            input = "deleteSnapshot snapshotName=fakesnapshot prompt=false
                                    output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="164" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['snapshotName'], self.snapshot_name)
            self.assertEqual(cliq_args['prompt'], 'false')
            return output, None

        def create_volume_from_snapshot(cliq_args):
            """Create volume from snapshot CLIQ input for test.

            input = "cloneSnapshot description="fake description"
                                   snapshotName=fakesnapshot
                                   volumeName=fakevolume
                                   output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="181" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['snapshotName'], self.snapshot_name)
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            return output, None

        def get_cluster_info(cliq_args):
            """Get cluster info CLIQ input for test.

            input = "getClusterInfo clusterName=Cluster01 searchDepth=1
                                    verbose=0 output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded." name="CliqSuccess"
                          processingTime="1164" result="0">
                <cluster blockSize="1024" description=""
                         maxVolumeSizeReplication1="622957690"
                         maxVolumeSizeReplication2="311480287"
                         minVolumeSize="262144" name="Cluster01"
                         pageSize="262144" spaceTotal="633697992"
                         storageNodeCount="2" unprovisionedSpace="622960574"
                         useVip="true">
                <nsm ipAddress="10.0.1.7" name="111-vsa"/>
                <nsm ipAddress="10.0.1.8" name="112-vsa"/>
                <vip ipAddress="10.0.1.6" subnetMask="255.255.255.0"/>
                </cluster></response></gauche>"""
            return output, None

        def get_volume_info(cliq_args):
            """Get volume info CLIQ input for test.

            input = "getVolumeInfo volumeName=fakevolume output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded." name="CliqSuccess"
                          processingTime="87" result="0">
                <volume autogrowPages="4" availability="online"
                        blockSize="1024" bytesWritten="0" checkSum="false"
                        clusterName="Cluster01" created="2011-02-08T19:56:53Z"
                        deleting="false" description="" groupName="Group01"
                        initialQuota="536870912" isPrimary="true"
                iscsiIqn="iqn.2003-10.com.lefthandnetworks:group01:25366:fakev"
                maxSize="6865387257856" md5="9fa5c8b2cca54b2948a63d833097e1ca"
                minReplication="1" name="vol-b" parity="0" replication="2"
                reserveQuota="536870912" scratchQuota="4194304"
                serialNumber="9fa5c8b2cca54b2948a63d8"
                size="1073741824" stridePages="32" thinProvision="true">
                <status description="OK" value="2"/>
                <permission access="rw" authGroup="api-1"
                            chapName="chapusername" chapRequired="true"
                            id="25369" initiatorSecret="" iqn=""
                            iscsiEnabled="true" loadBalance="true"
                            targetSecret="supersecret"/>
                </volume></response></gauche>"""
            return output, None

        def get_snapshot_info(cliq_args):
            """Get snapshot info CLIQ input for test.

            input = "getSnapshotInfo snapshotName=fakesnapshot output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded." name="CliqSuccess"
                          processingTime="87" result="0">
                <snapshot applicationManaged="false" autogrowPages="32768"
                    automatic="false" availability="online" bytesWritten="0"
                    clusterName="CloudCluster1" created="2013-08-26T07:03:44Z"
                    deleting="false" description="" groupName="CloudGroup1"
                    id="730" initialQuota="536870912" isPrimary="true"
                    iscsiIqn="iqn.2003-10.com.lefthandnetworks:cloudgroup1:73"
                    md5="a64b4f850539c07fb5ce3cee5db1fcce" minReplication="1"
                    name="snapshot-7849288e-e5e8-42cb-9687-9af5355d674b"
                    replication="2" reserveQuota="536870912" scheduleId="0"
                    scratchQuota="4194304" scratchWritten="0"
                    serialNumber="a64b4f850539c07fb5ce3cee5db1fcce"
                    size="2147483648" stridePages="32"
                    volumeSerial="a64b4f850539c07fb5ce3cee5db1fcce">
               <status description="OK" value="2"/>
               <permission access="rw"
                     authGroup="api-34281B815713B78-(trimmed)51ADD4B7030853AA7"
                     chapName="chapusername" chapRequired="true" id="25369"
                     initiatorSecret="" iqn="" iscsiEnabled="true"
                     loadBalance="true" targetSecret="supersecret"/>
               </snapshot></response></gauche>"""
            return output, None

        def get_server_info(cliq_args):
            """Get server info CLIQ input for test.

            input = "getServerInfo serverName=fakeName"
            """
            output = """<gauche version="1.0"><response result="0"/>
                     </gauche>"""
            return output, None

        def create_server(cliq_args):
            """Create server CLIQ input for test.

            input = "createServer serverName=fakeName initiator=something"
            """
            output = """<gauche version="1.0"><response result="0"/>
                     </gauche>"""
            return output, None

        def test_error(cliq_args):
            output = """<gauche version="1.0">
                <response description="Volume '134234' not found."
                name="CliqVolumeNotFound" processingTime="1083"
                result="8000100c"/>
                </gauche>"""
            return output, None

        self.assertEqual(cliq_args['output'], 'XML')
        try:
            verbs = {'createVolume': create_volume,
                     'deleteVolume': delete_volume,
                     'modifyVolume': extend_volume,
                     'assignVolumeToServer': assign_volume,
                     'unassignVolumeToServer': unassign_volume,
                     'createSnapshot': create_snapshot,
                     'deleteSnapshot': delete_snapshot,
                     'cloneSnapshot': create_volume_from_snapshot,
                     'getClusterInfo': get_cluster_info,
                     'getVolumeInfo': get_volume_info,
                     'getSnapshotInfo': get_snapshot_info,
                     'getServerInfo': get_server_info,
                     'createServer': create_server,
                     'testError': test_error}
        except KeyError:
            raise NotImplementedError()

        return verbs[verb](cliq_args)

    def test_create_volume(self):
        volume = {'name': self.volume_name, 'size': 1}
        model_update = self.driver.create_volume(volume)
        expected_iqn = "iqn.2003-10.com.lefthandnetworks:group01:25366:fakev 0"
        expected_location = "10.0.1.6:3260,1 %s" % expected_iqn
        self.assertEqual(model_update['provider_location'], expected_location)

    def test_delete_volume(self):
        volume = {'name': self.volume_name}
        self.driver.delete_volume(volume)

    def test_extend_volume(self):
        volume = {'name': self.volume_name}
        self.driver.extend_volume(volume, 2)

    def test_initialize_connection(self):
        volume = {'name': self.volume_name}
        result = self.driver.initialize_connection(volume, self.connector)
        self.assertEqual(result['driver_volume_type'], 'iscsi')
        self.assertDictMatch(result['data'], self.properties)

    def test_terminate_connection(self):
        volume = {'name': self.volume_name}
        self.driver.terminate_connection(volume, self.connector)

    def test_create_snapshot(self):
        snapshot = {'name': self.snapshot_name,
                    'volume_name': self.volume_name}
        self.driver.create_snapshot(snapshot)

    def test_delete_snapshot(self):
        snapshot = {'name': self.snapshot_name}
        self.driver.delete_snapshot(snapshot)

    def test_create_volume_from_snapshot(self):
        volume = {'name': self.volume_name}
        snapshot = {'name': self.snapshot_name}
        model_update = self.driver.create_volume_from_snapshot(volume,
                                                               snapshot)
        expected_iqn = "iqn.2003-10.com.lefthandnetworks:group01:25366:fakev 0"
        expected_location = "10.0.1.6:3260,1 %s" % expected_iqn
        self.assertEqual(model_update['provider_location'], expected_location)

    def test_cliq_error(self):
        try:
            self.driver._cliq_run_xml("testError", {})
        except exception.VolumeBackendAPIException:
            pass
