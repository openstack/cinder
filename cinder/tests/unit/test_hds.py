# Copyright (c) 2013 Hitachi Data Systems, Inc.
# Copyright (c) 2013 OpenStack Foundation
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
#

"""
Self test for Hitachi Unified Storage (HUS) platform.
"""

import os
import tempfile

import mox

from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.hds import hds


CONF = """<?xml version="1.0" encoding="UTF-8" ?>
<config>
  <mgmt_ip0>172.17.44.16</mgmt_ip0>
  <mgmt_ip1>172.17.44.17</mgmt_ip1>
  <username>system</username>
  <password>manager</password>
  <svc_0>
    <volume_type>default</volume_type>
    <iscsi_ip>172.17.39.132</iscsi_ip>
    <hdp>9</hdp>
  </svc_0>
  <svc_1>
    <volume_type>silver</volume_type>
    <iscsi_ip>172.17.39.133</iscsi_ip>
    <hdp>9</hdp>
  </svc_1>
  <svc_2>
    <volume_type>gold</volume_type>
    <iscsi_ip>172.17.39.134</iscsi_ip>
    <hdp>9</hdp>
  </svc_2>
  <svc_3>
    <volume_type>platinum</volume_type>
    <iscsi_ip>172.17.39.135</iscsi_ip>
    <hdp>9</hdp>
  </svc_3>
  <snapshot>
    <hdp>9</hdp>
  </snapshot>
  <lun_start>
    3300
  </lun_start>
</config>
"""


class SimulatedHusBackend(object):
    """Simulation Back end. Talks to HUS."""

    alloc_lun = []              # allocated LUs
    connections = []            # iSCSI connections
    init_index = 0              # initiator index
    target_index = 0            # target index
    hlun = 0                    # hlun index
    out = ''

    def __init__(self):
        self.start_lun = 0

    def get_version(self, cmd, ver, ip0, ip1, user, pw):
        out = ("Array_ID: 92210013 (HUS130) version: 0920/B-S  LU: 4096"
               "  RG: 75  RG_LU: 1024  Utility_version: 1.0.0")
        return out

    def get_iscsi_info(self, cmd, ver, ip0, ip1, user, pw):
        out = """CTL: 0 Port: 4 IP: 172.17.39.132 Port: 3260 Link: Up
                 CTL: 0 Port: 5 IP: 172.17.39.133 Port: 3260 Link: Up
                 CTL: 1 Port: 4 IP: 172.17.39.134 Port: 3260 Link: Up
                 CTL: 1 Port: 5 IP: 172.17.39.135 Port: 3260 Link: Up"""
        return out

    def get_hdp_info(self, cmd, ver, ip0, ip1, user, pw):
        out = """HDP: 2  272384 MB    33792 MB  12 %  LUs:   70  Normal  Normal
              HDP: 9  546816 MB    73728 MB  13 %  LUs:  194  Normal  Normal"""
        return out

    def create_lu(self, cmd, ver, ip0, ip1, user, pw, id, hdp, start,
                  end, size):
        if self.start_lun < int(start):  # initialize first time
            self.start_lun = int(start)
        out = ("LUN: %d HDP: 9 size: %s MB, is successfully created" %
               (self.start_lun, size))
        self.alloc_lun.append(str(self.start_lun))
        self.start_lun += 1
        return out

    def extend_vol(self, cmd, ver, ip0, ip1, user, pw, id, lu, size):
        out = ("LUN: %s successfully extended to %s MB" % (lu, size))
        SimulatedHusBackend.out = out
        return out

    def delete_lu(self, cmd, ver, ip0, ip1, user, pw, id, lun):
        out = ""
        if lun in self.alloc_lun:
            out = "LUN: %s is successfully deleted" % (lun)
            self.alloc_lun.remove(lun)
        return out

    def create_dup(self, cmd, ver, ip0, ip1, user, pw, id, src_lun,
                   hdp, start, end, size):
        out = ("LUN: %s HDP: 9 size: %s MB, is successfully created" %
               (self.start_lun, size))
        self.alloc_lun.append(str(self.start_lun))
        self.start_lun += 1
        return out

    def add_iscsi_conn(self, cmd, ver, ip0, ip1, user, pw, id, lun, ctl, port,
                       iqn, initiator):
        conn = (self.hlun, lun, initiator, self.init_index, iqn,
                self.target_index, ctl, port)
        out = ("H-LUN: %d mapped. LUN: %s, iSCSI Initiator: %s @ index: %d, \
                and Target: %s @ index %d is successfully paired  @ CTL: %s, \
                Port: %s" % conn)
        self.init_index += 1
        self.target_index += 1
        self.hlun += 1
        SimulatedHusBackend.connections.append(conn)
        return out

    def del_iscsi_conn(self, cmd, ver, ip0, ip1, user, pw, id, lun, ctl, port,
                       iqn, initiator):
        conn = ()
        for connection in SimulatedHusBackend.connections:
            if (connection[1] == lun):
                conn = connection
                SimulatedHusBackend.connections.remove(connection)
        if conn is None:
            return
        (hlun, lun, initiator, init_index, iqn, target_index, ctl, port) = conn
        detail = (hlun, iqn)
        out = ("H-LUN: %d successfully deleted from target %s" % detail)
        return out


# The following information is passed on to tests, when creating a volume

_VOLUME = {'volume_id': '1234567890', 'size': 128,
           'volume_type': None, 'provider_location': None, 'id': 'abcdefg'}


class HUSiSCSIDriverTest(test.TestCase):
    """Test HUS iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(HUSiSCSIDriverTest, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HUSiSCSIDriverTest, self).setUp()
        (handle, self.config_file) = tempfile.mkstemp('.xml')
        self.addCleanup(os.remove, self.config_file)
        os.write(handle, CONF)
        os.close(handle)
        SimulatedHusBackend.alloc_lun = []
        SimulatedHusBackend.connections = []
        SimulatedHusBackend.out = ''
        self.mox = mox.Mox()
        self.mox.StubOutWithMock(hds, 'factory_bend')
        hds.factory_bend().AndReturn(SimulatedHusBackend())
        self.mox.ReplayAll()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.hds_cinder_config_file = self.config_file
        self.driver = hds.HUSDriver(configuration=self.configuration)
        self.addCleanup(self.mox.UnsetStubs)

    def test_get_volume_stats(self):
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(stats["vendor_name"], "HDS")
        self.assertEqual(stats["storage_protocol"], "iSCSI")
        self.assertGreater(stats["total_capacity_gb"], 0)

    def test_create_volume(self):
        loc = self.driver.create_volume(_VOLUME)
        self.assertIsNotNone(loc)
        vol = _VOLUME.copy()
        vol['provider_location'] = loc['provider_location']
        self.assertIsNotNone(loc['provider_location'])
        return vol

    def test_delete_volume(self):
        """Delete a volume (test).

        Note: this API call should not expect any exception:
        This driver will silently accept a delete request, because
        the DB can be out of sync, and Cinder manager will keep trying
        to delete, even though the volume has been wiped out of the
        Array. We don't want to have a dangling volume entry in the
        customer dashboard.
        """
        vol = self.test_create_volume()
        self.assertTrue(SimulatedHusBackend.alloc_lun)
        num_luns_before = len(SimulatedHusBackend.alloc_lun)
        self.driver.delete_volume(vol)
        num_luns_after = len(SimulatedHusBackend.alloc_lun)
        self.assertGreater(num_luns_before, num_luns_after)

    def test_extend_volume(self):
        vol = self.test_create_volume()
        new_size = _VOLUME['size'] * 2
        self.driver.extend_volume(vol, new_size)
        self.assertTrue(str(new_size * 1024) in
                        SimulatedHusBackend.out)

    def test_create_snapshot(self):
        vol = self.test_create_volume()
        self.mox.StubOutWithMock(self.driver, '_id_to_vol')
        self.driver._id_to_vol(vol['volume_id']).AndReturn(vol)
        self.mox.ReplayAll()
        svol = vol.copy()
        svol['volume_size'] = svol['size']
        loc = self.driver.create_snapshot(svol)
        self.assertIsNotNone(loc)
        svol['provider_location'] = loc['provider_location']
        return svol

    def test_create_clone(self):
        vol = self.test_create_volume()
        self.mox.StubOutWithMock(self.driver, '_id_to_vol')
        self.driver._id_to_vol(vol['volume_id']).AndReturn(vol)
        self.mox.ReplayAll()
        svol = vol.copy()
        svol['volume_size'] = svol['size']
        loc = self.driver.create_snapshot(svol)
        self.assertIsNotNone(loc)
        svol['provider_location'] = loc['provider_location']
        return svol

    def test_delete_snapshot(self):
        """Delete a snapshot (test).

        Note: this API call should not expect any exception:
        This driver will silently accept a delete request, because
        the DB can be out of sync, and Cinder manager will keep trying
        to delete, even though the snapshot has been wiped out of the
        Array. We don't want to have a dangling snapshot entry in the
        customer dashboard.
        """
        svol = self.test_create_snapshot()
        num_luns_before = len(SimulatedHusBackend.alloc_lun)
        self.driver.delete_snapshot(svol)
        num_luns_after = len(SimulatedHusBackend.alloc_lun)
        self.assertGreater(num_luns_before, num_luns_after)

    def test_create_volume_from_snapshot(self):
        svol = self.test_create_snapshot()
        vol = self.driver.create_volume_from_snapshot(_VOLUME, svol)
        self.assertIsNotNone(vol)
        return vol

    def test_initialize_connection(self):
        connector = {}
        connector['initiator'] = 'iqn.1993-08.org.debian:01:11f90746eb2'
        connector['host'] = 'dut_1.lab.hds.com'
        vol = self.test_create_volume()
        self.mox.StubOutWithMock(self.driver, '_update_vol_location')
        conn = self.driver.initialize_connection(vol, connector)
        self.assertIn('hitachi', conn['data']['target_iqn'])
        self.assertIn('3260', conn['data']['target_portal'])
        vol['provider_location'] = conn['data']['provider_location']
        return (vol, connector)

    def test_terminate_connection(self):
        """Terminate a connection (test).

        Note: this API call should not expect any exception:
        This driver will silently accept a terminate_connection request
        because an error/exception return will only jeopardize the
        connection tear down at a host.
        """
        (vol, conn) = self.test_initialize_connection()
        num_conn_before = len(SimulatedHusBackend.connections)
        self.driver.terminate_connection(vol, conn)
        num_conn_after = len(SimulatedHusBackend.connections)
        self.assertGreater(num_conn_before, num_conn_after)
