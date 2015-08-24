# Copyright (c) 2014 Hitachi Data Systems, Inc.
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
Self test for Hitachi Unified Storage (HUS-HNAS) platform.
"""

import os
import tempfile
import time

import mock
from oslo_concurrency import processutils as putils
import six

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.hitachi import hnas_iscsi as iscsi
from cinder.volume import volume_types

HNASCONF = """<?xml version="1.0" encoding="UTF-8" ?>
<config>
  <hnas_cmd>ssc</hnas_cmd>
  <chap_enabled>True</chap_enabled>
  <mgmt_ip0>172.17.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password>supervisor</password>
  <svc_0>
    <volume_type>default</volume_type>
    <iscsi_ip>172.17.39.132</iscsi_ip>
    <hdp>fs2</hdp>
  </svc_0>
  <svc_1>
    <volume_type>silver</volume_type>
    <iscsi_ip>172.17.39.133</iscsi_ip>
    <hdp>fs2</hdp>
  </svc_1>
</config>
"""

HNAS_WRONG_CONF1 = """<?xml version="1.0" encoding="UTF-8" ?>
<config>
  <hnas_cmd>ssc</hnas_cmd>
  <mgmt_ip0>172.17.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password>supervisor</password>
    <volume_type>default</volume_type>
    <hdp>172.17.39.132:/cinder</hdp>
  </svc_0>
</config>
"""

HNAS_WRONG_CONF2 = """<?xml version="1.0" encoding="UTF-8" ?>
<config>
  <hnas_cmd>ssc</hnas_cmd>
  <mgmt_ip0>172.17.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password>supervisor</password>
  <svc_0>
    <volume_type>default</volume_type>
  </svc_0>
  <svc_1>
    <volume_type>silver</volume_type>
  </svc_1>
</config>
"""

# The following information is passed on to tests, when creating a volume
_VOLUME = {'name': 'testvol', 'volume_id': '1234567890', 'size': 128,
           'volume_type': 'silver', 'volume_type_id': '1',
           'provider_location': '83-68-96-AA-DA-5D.volume-2dfe280e-470a-4182'
                                '-afb8-1755025c35b8', 'id': 'abcdefg',
           'host': 'host1@hnas-iscsi-backend#silver'}


class SimulatedHnasBackend(object):
    """Simulation Back end. Talks to HNAS."""

    # these attributes are shared across object instances
    start_lun = 0
    init_index = 0
    target_index = 0
    hlun = 0

    def __init__(self):
        self.type = 'HNAS'
        self.out = ''
        self.volumes = []
        # iSCSI connections
        self.connections = []

    def rename_existing_lu(self, cmd, ip0, user, pw, fslabel,
                           vol_name, vol_ref_name):
        return 'Logical unit modified successfully.'

    def get_existing_lu_info(self, cmd, ip0, user, pw, fslabel, lun):
        out = "Name   : volume-test                \n\
               Comment:                            \n\
               Path   : /.cinder/volume-test.iscsi \n\
               Size   : 20 GB                      \n\
               File System : manage_iscsi_test     \n\
               File System Mounted : Yes           \n\
               Logical Unit Mounted: Yes"
        return out

    def deleteVolume(self, name):
        volume = self.getVolume(name)
        if volume:
            self.volumes.remove(volume)
            return True
        else:
            return False

    def deleteVolumebyProvider(self, provider):
        volume = self.getVolumebyProvider(provider)
        if volume:
            self.volumes.remove(volume)
            return True
        else:
            return False

    def getVolumes(self):
        return self.volumes

    def getVolume(self, name):
        if self.volumes:
            for volume in self.volumes:
                if str(volume['name']) == name:
                    return volume
        return None

    def getVolumebyProvider(self, provider):
        if self.volumes:
            for volume in self.volumes:
                if str(volume['provider_location']) == provider:
                    return volume
        return None

    def createVolume(self, name, provider, sizeMiB, comment):
        new_vol = {'additionalStates': [],
                   'adminSpace': {'freeMiB': 0,
                                  'rawReservedMiB': 384,
                                  'reservedMiB': 128,
                                  'usedMiB': 128},
                   'baseId': 115,
                   'copyType': 1,
                   'creationTime8601': '2012-10-22T16:37:57-07:00',
                   'creationTimeSec': 1350949077,
                   'failedStates': [],
                   'id': 115,
                   'provider_location': provider,
                   'name': name,
                   'comment': comment,
                   'provisioningType': 1,
                   'readOnly': False,
                   'sizeMiB': sizeMiB,
                   'state': 1,
                   'userSpace': {'freeMiB': 0,
                                 'rawReservedMiB': 41984,
                                 'reservedMiB': 31488,
                                 'usedMiB': 31488},
                   'usrSpcAllocLimitPct': 0,
                   'usrSpcAllocWarningPct': 0,
                   'uuid': '1e7daee4-49f4-4d07-9ab8-2b6a4319e243',
                   'wwn': '50002AC00073383D'}
        self.volumes.append(new_vol)

    def create_lu(self, cmd, ip0, user, pw, hdp, size, name):
        vol_id = name
        _out = ("LUN: %d HDP: fs2 size: %s MB, is successfully created" %
                (self.start_lun, size))
        self.createVolume(name, vol_id, size, "create-lu")
        self.start_lun += 1
        return _out

    def delete_lu(self, cmd, ip0, user, pw, hdp, lun):
        _out = ""
        id = "myID"

        self.deleteVolumebyProvider(id + '.' + str(lun))
        return _out

    def create_dup(self, cmd, ip0, user, pw, src_lun, hdp, size, name):
        _out = ("LUN: %s HDP: 9 size: %s MB, is successfully created" %
                (self.start_lun, size))

        id = name
        self.createVolume(name, id + '.' + str(self.start_lun), size,
                          "create-dup")
        self.start_lun += 1
        return _out

    def add_iscsi_conn(self, cmd, ip0, user, pw, lun, hdp,
                       port, iqn, initiator):
        ctl = ""
        conn = (self.hlun, lun, initiator, self.init_index, iqn,
                self.target_index, ctl, port)
        _out = ("H-LUN: %d mapped. LUN: %s, iSCSI Initiator: %s @ index: %d, \
                and Target: %s @ index %d is successfully paired  @ CTL: %s, \
                Port: %s" % conn)
        self.init_index += 1
        self.target_index += 1
        self.hlun += 1
        self.connections.append(conn)
        return _out

    def del_iscsi_conn(self, cmd, ip0, user, pw, port, iqn, initiator):

        self.connections.pop()

        _out = ("H-LUN: successfully deleted from target")
        return _out

    def extend_vol(self, cmd, ip0, user, pw, hdp, lu, size, name):
        _out = ("LUN: %s successfully extended to %s MB" % (lu, size))
        id = name
        self.out = _out
        v = self.getVolumebyProvider(id + '.' + str(lu))
        if v:
            v['sizeMiB'] = size
        return _out

    def get_luns(self):
        return len(self.alloc_lun)

    def get_conns(self):
        return len(self.connections)

    def get_out(self):
        return str(self.out)

    def get_version(self, cmd, ver, ip0, user, pw):
        self.out = "Array_ID: 18-48-A5-A1-80-13 (3080-G2) " \
            "version: 11.2.3319.09 LU: 256" \
            " RG: 0 RG_LU: 0 Utility_version: 11.1.3225.01"
        return self.out

    def get_iscsi_info(self, cmd, ip0, user, pw):
        self.out = "CTL: 0 Port: 4 IP: 172.17.39.132 Port: 3260 Link: Up\n" \
            "CTL: 1 Port: 5 IP: 172.17.39.133 Port: 3260 Link: Up"
        return self.out

    def get_hdp_info(self, cmd, ip0, user, pw, fslabel=None):
        self.out = "HDP: 1024  272384 MB    33792 MB  12 %  LUs:  " \
            "70  Normal  fs1\n" \
            "HDP: 1025  546816 MB    73728 MB  13 %  LUs:  194  Normal  fs2"
        return self.out

    def get_targetiqn(self, cmd, ip0, user, pw, id, hdp, secret):
        self.out = """iqn.2013-08.cinderdomain:vs61.cindertarget"""
        return self.out

    def set_targetsecret(self, cmd, ip0, user, pw, target, hdp, secret):
        self.out = """iqn.2013-08.cinderdomain:vs61.cindertarget"""
        return self.out

    def get_targetsecret(self, cmd, ip0, user, pw, target, hdp):
        self.out = """wGkJhTpXaaYJ5Rv"""
        return self.out

    def get_evs(self, cmd, ip0, user, pw, fsid):
        return '1'

    def check_lu(self, cmd, ip0, user, pw, volume_name, hdp):
        return True, 1, {'alias': 'cinder-default', 'secret': 'mysecret',
                         'iqn': 'iqn.1993-08.org.debian:01:11f90746eb2'}

    def check_target(self, cmd, ip0, user, pw, hdp, target_alias):
        return False, None


class HNASiSCSIDriverTest(test.TestCase):
    """Test HNAS iSCSI volume driver."""
    def __init__(self, *args, **kwargs):
        super(HNASiSCSIDriverTest, self).__init__(*args, **kwargs)

    @mock.patch.object(iscsi, 'factory_bend')
    def setUp(self, _factory_bend):
        super(HNASiSCSIDriverTest, self).setUp()

        self.backend = SimulatedHnasBackend()
        _factory_bend.return_value = self.backend

        self.config_file = tempfile.NamedTemporaryFile("w+", suffix='.xml')
        self.addCleanup(self.config_file.close)
        self.config_file.write(HNASCONF)
        self.config_file.flush()

        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.hds_hnas_iscsi_config_file = self.config_file.name
        self.configuration.hds_svc_iscsi_chap_enabled = True
        self.driver = iscsi.HDSISCSIDriver(configuration=self.configuration)
        self.driver.do_setup("")

    def _create_volume(self):
        loc = self.driver.create_volume(_VOLUME)
        vol = _VOLUME.copy()
        vol['provider_location'] = loc['provider_location']
        return vol

    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(os, 'access')
    def test_read_config(self, m_access, m_open):
        # Test exception when file is not found
        m_access.return_value = False
        m_open.return_value = six.StringIO(HNASCONF)
        self.assertRaises(exception.NotFound, iscsi._read_config, '')

        # Test exception when config file has parsing errors
        # due to missing <svc> tag
        m_access.return_value = True
        m_open.return_value = six.StringIO(HNAS_WRONG_CONF1)
        self.assertRaises(exception.ConfigNotFound, iscsi._read_config, '')

        # Test exception when config file has parsing errors
        # due to missing <hdp> tag
        m_open.return_value = six.StringIO(HNAS_WRONG_CONF2)
        self.configuration.hds_hnas_iscsi_config_file = ''
        self.assertRaises(exception.ParameterNotFound, iscsi._read_config, '')

    def test_create_volume(self):
        loc = self.driver.create_volume(_VOLUME)
        self.assertNotEqual(loc, None)
        self.assertNotEqual(loc['provider_location'], None)
        # cleanup
        self.backend.deleteVolumebyProvider(loc['provider_location'])

    def test_get_volume_stats(self):
        stats = self.driver.get_volume_stats(True)
        self.assertEqual("HDS", stats["vendor_name"])
        self.assertEqual("iSCSI", stats["storage_protocol"])
        self.assertEqual(2, len(stats['pools']))

    def test_delete_volume(self):
        vol = self._create_volume()
        self.driver.delete_volume(vol)
        # should not be deletable twice
        prov_loc = self.backend.getVolumebyProvider(vol['provider_location'])
        self.assertTrue(prov_loc is None)

    def test_extend_volume(self):
        vol = self._create_volume()
        new_size = _VOLUME['size'] * 2
        self.driver.extend_volume(vol, new_size)
        # cleanup
        self.backend.deleteVolumebyProvider(vol['provider_location'])

    @mock.patch.object(iscsi.HDSISCSIDriver, '_id_to_vol')
    def test_create_snapshot(self, m_id_to_vol):
        vol = self._create_volume()
        m_id_to_vol.return_value = vol
        svol = vol.copy()
        svol['volume_size'] = svol['size']
        loc = self.driver.create_snapshot(svol)
        self.assertNotEqual(loc, None)
        svol['provider_location'] = loc['provider_location']
        # cleanup
        self.backend.deleteVolumebyProvider(svol['provider_location'])
        self.backend.deleteVolumebyProvider(vol['provider_location'])

    @mock.patch.object(iscsi.HDSISCSIDriver, '_id_to_vol')
    def test_create_clone(self, m_id_to_vol):

        src_vol = self._create_volume()
        m_id_to_vol.return_value = src_vol
        src_vol['volume_size'] = src_vol['size']

        dst_vol = self._create_volume()
        dst_vol['volume_size'] = dst_vol['size']

        loc = self.driver.create_cloned_volume(dst_vol, src_vol)
        self.assertNotEqual(loc, None)
        # cleanup
        self.backend.deleteVolumebyProvider(src_vol['provider_location'])
        self.backend.deleteVolumebyProvider(loc['provider_location'])

    @mock.patch.object(iscsi.HDSISCSIDriver, '_id_to_vol')
    def test_delete_snapshot(self, m_id_to_vol):
        svol = self._create_volume()

        lun = svol['provider_location']
        m_id_to_vol.return_value = svol
        self.driver.delete_snapshot(svol)
        self.assertTrue(self.backend.getVolumebyProvider(lun) is None)

    def test_create_volume_from_snapshot(self):
        svol = self._create_volume()
        svol['volume_size'] = svol['size']
        vol = self.driver.create_volume_from_snapshot(_VOLUME, svol)
        self.assertNotEqual(vol, None)
        # cleanup
        self.backend.deleteVolumebyProvider(svol['provider_location'])
        self.backend.deleteVolumebyProvider(vol['provider_location'])

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(iscsi.HDSISCSIDriver, '_update_vol_location')
    def test_initialize_connection(self, m_update_vol_location, m_sleep):
        connector = {}
        connector['initiator'] = 'iqn.1993-08.org.debian:01:11f90746eb2'
        connector['host'] = 'dut_1.lab.hds.com'
        vol = self._create_volume()
        conn = self.driver.initialize_connection(vol, connector)
        self.assertTrue('3260' in conn['data']['target_portal'])

        self.backend.add_iscsi_conn = mock.MagicMock()
        self.backend.add_iscsi_conn.side_effect = putils.ProcessExecutionError
        self.assertRaises(exception.ISCSITargetAttachFailed,
                          self.driver.initialize_connection, vol, connector)

        # cleanup
        self.backend.deleteVolumebyProvider(vol['provider_location'])

    @mock.patch.object(iscsi.HDSISCSIDriver, '_update_vol_location')
    def test_terminate_connection(self, m_update_vol_location):
        connector = {}
        connector['initiator'] = 'iqn.1993-08.org.debian:01:11f90746eb2'
        connector['host'] = 'dut_1.lab.hds.com'

        vol = self._create_volume()
        vol['provider_location'] = "portal," +\
                                   connector['initiator'] +\
                                   ",18-48-A5-A1-80-13.0,ctl,port,hlun"

        conn = self.driver.initialize_connection(vol, connector)
        num_conn_before = self.backend.get_conns()
        self.driver.terminate_connection(vol, conn)
        num_conn_after = self.backend.get_conns()
        self.assertNotEqual(num_conn_before, num_conn_after)
        # cleanup
        self.backend.deleteVolumebyProvider(vol['provider_location'])

    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       return_value={'key': 'type', 'service_label': 'silver'})
    def test_get_pool(self, m_ext_spec):
        label = self.driver.get_pool(_VOLUME)
        self.assertEqual('silver', label)

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(iscsi.HDSISCSIDriver, '_update_vol_location')
    def test_get_service_target(self, m_update_vol_location, m_sleep):

        vol = _VOLUME.copy()
        self.backend.check_lu = mock.MagicMock()
        self.backend.check_target = mock.MagicMock()

        # Test the case where volume is not already mapped - CHAP enabled
        self.backend.check_lu.return_value = (False, 0, None)
        self.backend.check_target.return_value = (False, None)
        ret = self.driver._get_service_target(vol)
        iscsi_ip, iscsi_port, ctl, svc_port, hdp, alias, secret = ret
        self.assertEqual('evs1-tgt0', alias)

        # Test the case where volume is not already mapped - CHAP disabled
        self.driver.config['chap_enabled'] = 'False'
        ret = self.driver._get_service_target(vol)
        iscsi_ip, iscsi_port, ctl, svc_port, hdp, alias, secret = ret
        self.assertEqual('evs1-tgt0', alias)

        # Test the case where all targets are full
        fake_tgt = {'alias': 'fake', 'luns': range(0, 32)}
        self.backend.check_lu.return_value = (False, 0, None)
        self.backend.check_target.return_value = (True, fake_tgt)
        self.assertRaises(exception.NoMoreTargets,
                          self.driver._get_service_target, vol)

    @mock.patch.object(iscsi.HDSISCSIDriver, '_get_service')
    def test_unmanage(self, get_service):
        get_service.return_value = ('fs2')

        self.driver.unmanage(_VOLUME)
        get_service.assert_called_once_with(_VOLUME)

    def test_manage_existing_get_size(self):
        vol = _VOLUME.copy()
        existing_vol_ref = {'source-name': 'manage_iscsi_test/volume-test'}

        out = self.driver.manage_existing_get_size(vol, existing_vol_ref)
        self.assertEqual(20, out)

    def test_manage_existing_get_size_error(self):
        vol = _VOLUME.copy()
        existing_vol_ref = {'source-name': 'invalid_FS/vol-not-found'}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, vol,
                          existing_vol_ref)

    def test_manage_existing_get_size_without_source_name(self):
        vol = _VOLUME.copy()
        existing_vol_ref = {
            'source-id': 'bcc48c61-9691-4e5f-897c-793686093190'}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, vol,
                          existing_vol_ref)

    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    def test_manage_existing(self, m_get_extra_specs):
        vol = _VOLUME.copy()
        existing_vol_ref = {'source-name': 'fs2/volume-test'}
        version = {'provider_location': '18-48-A5-A1-80-13.testvol'}

        m_get_extra_specs.return_value = {'key': 'type',
                                          'service_label': 'silver'}

        out = self.driver.manage_existing(vol, existing_vol_ref)

        m_get_extra_specs.assert_called_once_with('1')
        self.assertEqual(version, out)

    @mock.patch.object(volume_types, 'get_volume_type_extra_specs')
    def test_manage_existing_invalid_pool(self, m_get_extra_specs):
        vol = _VOLUME.copy()
        existing_vol_ref = {'source-name': 'fs2/volume-test'}

        m_get_extra_specs.return_value = {'key': 'type',
                                          'service_label': 'gold'}

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, vol, existing_vol_ref)
        m_get_extra_specs.assert_called_once_with('1')

    def test_manage_existing_invalid_volume_name(self):
        vol = _VOLUME.copy()
        existing_vol_ref = {'source-name': 'fs2/t/est_volume'}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, vol, existing_vol_ref)

    def test_manage_existing_without_volume_name(self):
        vol = _VOLUME.copy()
        existing_vol_ref = {'source-name': 'fs2/'}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, vol, existing_vol_ref)

    def test_manage_existing_with_FS_and_spaces(self):
        vol = _VOLUME.copy()
        existing_vol_ref = {'source-name': 'fs2/  '}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, vol, existing_vol_ref)
