# Copyright (c) 2014 Hitachi Data Systems, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
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

import os
import StringIO
import tempfile

import mock
from oslo_log import log as logging

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.hds import nfs
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

SHARESCONF = """172.17.39.132:/cinder
172.17.39.133:/cinder"""

HNASCONF = """<?xml version="1.0" encoding="UTF-8" ?>
<config>
  <hnas_cmd>ssc</hnas_cmd>
  <mgmt_ip0>172.17.44.15</mgmt_ip0>
  <username>supervisor</username>
  <password>supervisor</password>
  <svc_0>
    <volume_type>default</volume_type>
    <hdp>172.17.39.132:/cinder</hdp>
  </svc_0>
  <svc_1>
    <volume_type>silver</volume_type>
    <hdp>172.17.39.133:/cinder</hdp>
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
_SERVICE = ('Test_hdp', 'Test_path', 'Test_label')
_SHARE = '172.17.39.132:/cinder'
_SHARE2 = '172.17.39.133:/cinder'
_EXPORT = '/cinder'
_VOLUME = {'name': 'volume-bcc48c61-9691-4e5f-897c-793686093190',
           'volume_id': 'bcc48c61-9691-4e5f-897c-793686093190',
           'size': 128,
           'volume_type': 'silver',
           'volume_type_id': 'test',
           'metadata': [{'key': 'type',
                         'service_label': 'silver'}],
           'provider_location': None,
           'id': 'bcc48c61-9691-4e5f-897c-793686093190',
           'status': 'available',
           'host': 'host1@hnas-iscsi-backend#silver'}
_SNAPVOLUME = {'name': 'snapshot-51dd4-8d8a-4aa9-9176-086c9d89e7fc',
               'id': '51dd4-8d8a-4aa9-9176-086c9d89e7fc',
               'size': 128,
               'volume_type': None,
               'provider_location': None,
               'volume_size': 128,
               'volume_name': 'volume-bcc48c61-9691-4e5f-897c-793686093190',
               'volume_id': 'bcc48c61-9691-4e5f-897c-793686093191',
               'host': 'host1@hnas-iscsi-backend#silver'}

GET_ID_VOL = {
    ("bcc48c61-9691-4e5f-897c-793686093190"): [_VOLUME],
    ("bcc48c61-9691-4e5f-897c-793686093191"): [_SNAPVOLUME]
}


def id_to_vol(arg):
    return GET_ID_VOL.get(arg)


class SimulatedHnasBackend(object):
    """Simulation Back end. Talks to HNAS."""

    # these attributes are shared across object instances
    start_lun = 0

    def __init__(self):
        self.type = 'HNAS'
        self.out = ''

    def file_clone(self, cmd, ip0, user, pw, fslabel, source_path,
                   target_path):
        _out = ""
        LOG.info("Clone: %s -> %s" % (source_path, target_path))
        return _out

    def get_version(self, ver, cmd, ip0, user, pw):
        self.out = "Array_ID: 18-48-A5-A1-80-13 (3080-G2) " \
                   "version: 11.2.3319.09 LU: 256 " \
                   "RG: 0 RG_LU: 0 Utility_version: 11.1.3225.01"
        return self.out

    def get_hdp_info(self, ip0, user, pw):
        self.out = "HDP: 1024  272384 MB    33792 MB  12 %  LUs:   70 " \
                   "Normal  fs1\n" \
                   "HDP: 1025  546816 MB    73728 MB  13 %  LUs:  194 " \
                   "Normal  fs2"
        return self.out

    def get_nfs_info(self, cmd, ip0, user, pw):
        self.out = "Export: /cinder Path: /volumes HDP: fs1 FSID: 1024 " \
                   "EVS: 1 IPS: 172.17.39.132\n" \
                   "Export: /cinder Path: /volumes HDP: fs2 FSID: 1025 " \
                   "EVS: 1 IPS: 172.17.39.133"
        return self.out


class HDSNFSDriverTest(test.TestCase):
    """Test HNAS NFS volume driver."""

    def __init__(self, *args, **kwargs):
        super(HDSNFSDriverTest, self).__init__(*args, **kwargs)

    @mock.patch.object(nfs, 'factory_bend')
    def setUp(self, m_factory_bend):
        super(HDSNFSDriverTest, self).setUp()

        self.backend = SimulatedHnasBackend()
        m_factory_bend.return_value = self.backend

        (handle, self.config_file) = tempfile.mkstemp('.xml')
        os.write(handle, HNASCONF)
        os.close(handle)
        (handle, self.shares_file) = tempfile.mkstemp('')
        os.write(handle, SHARESCONF)
        os.close(handle)

        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.hds_hnas_nfs_config_file = self.config_file
        self.configuration.nfs_shares_config = self.shares_file
        self.configuration.nfs_mount_point_base = '/opt/stack/cinder/mnt'
        self.configuration.nfs_mount_options = None
        self.configuration.nas_ip = None
        self.configuration.nas_share_path = None
        self.configuration.nas_mount_options = None

        self.driver = nfs.HDSNFSDriver(configuration=self.configuration)
        self.driver.do_setup("")
        self.addCleanup(self._clean)

    def _clean(self):
        os.remove(self.config_file)
        os.remove(self.shares_file)

    @mock.patch('__builtin__.open')
    @mock.patch.object(os, 'access')
    def test_read_config(self, m_access, m_open):
        # Test exception when file is not found
        m_access.return_value = False
        m_open.return_value = StringIO.StringIO(HNASCONF)
        self.assertRaises(exception.NotFound, nfs._read_config, '')

        # Test exception when config file has parsing errors
        # due to missing <svc> tag
        m_access.return_value = True
        m_open.return_value = StringIO.StringIO(HNAS_WRONG_CONF1)
        self.assertRaises(exception.ConfigNotFound, nfs._read_config, '')

        # Test exception when config file has parsing errors
        # due to missing <hdp> tag
        m_open.return_value = StringIO.StringIO(HNAS_WRONG_CONF2)
        self.configuration.hds_hnas_iscsi_config_file = ''
        self.assertRaises(exception.ParameterNotFound, nfs._read_config, '')

    @mock.patch.object(nfs.HDSNFSDriver, '_id_to_vol')
    @mock.patch.object(nfs.HDSNFSDriver, '_get_provider_location')
    @mock.patch.object(nfs.HDSNFSDriver, '_get_export_path')
    @mock.patch.object(nfs.HDSNFSDriver, '_get_volume_location')
    def test_create_snapshot(self, m_get_volume_location, m_get_export_path,
                             m_get_provider_location, m_id_to_vol):
        svol = _SNAPVOLUME.copy()
        m_id_to_vol.return_value = svol

        m_get_provider_location.return_value = _SHARE
        m_get_volume_location.return_value = _SHARE
        m_get_export_path.return_value = _EXPORT

        loc = self.driver.create_snapshot(svol)
        out = "{'provider_location': \'" + _SHARE + "'}"
        self.assertEqual(str(loc), out)

    @mock.patch.object(nfs.HDSNFSDriver, '_get_service')
    @mock.patch.object(nfs.HDSNFSDriver, '_id_to_vol', side_effect=id_to_vol)
    @mock.patch.object(nfs.HDSNFSDriver, '_get_provider_location')
    @mock.patch.object(nfs.HDSNFSDriver, '_get_volume_location')
    def test_create_cloned_volume(self, m_get_volume_location,
                                  m_get_provider_location, m_id_to_vol,
                                  m_get_service):
        vol = _VOLUME.copy()
        svol = _SNAPVOLUME.copy()

        m_get_service.return_value = _SERVICE
        m_get_provider_location.return_value = _SHARE
        m_get_volume_location.return_value = _SHARE

        loc = self.driver.create_cloned_volume(vol, svol)

        out = "{'provider_location': \'" + _SHARE + "'}"
        self.assertEqual(str(loc), out)

    @mock.patch.object(nfs.HDSNFSDriver, '_ensure_shares_mounted')
    @mock.patch.object(nfs.HDSNFSDriver, '_do_create_volume')
    @mock.patch.object(nfs.HDSNFSDriver, '_id_to_vol', side_effect=id_to_vol)
    @mock.patch.object(nfs.HDSNFSDriver, '_get_provider_location')
    @mock.patch.object(nfs.HDSNFSDriver, '_get_volume_location')
    def test_create_volume(self, m_get_volume_location,
                           m_get_provider_location, m_id_to_vol,
                           m_do_create_volume, m_ensure_shares_mounted):

        vol = _VOLUME.copy()

        m_get_provider_location.return_value = _SHARE2
        m_get_volume_location.return_value = _SHARE2

        loc = self.driver.create_volume(vol)

        out = "{'provider_location': \'" + _SHARE2 + "'}"
        self.assertEqual(str(loc), out)

    @mock.patch.object(nfs.HDSNFSDriver, '_id_to_vol')
    @mock.patch.object(nfs.HDSNFSDriver, '_get_provider_location')
    @mock.patch.object(nfs.HDSNFSDriver, '_volume_not_present')
    def test_delete_snapshot(self, m_volume_not_present,
                             m_get_provider_location, m_id_to_vol):
        svol = _SNAPVOLUME.copy()

        m_id_to_vol.return_value = svol
        m_get_provider_location.return_value = _SHARE

        m_volume_not_present.return_value = True

        self.driver.delete_snapshot(svol)
        self.assertEqual(svol['provider_location'], None)

    @mock.patch.object(nfs.HDSNFSDriver, '_get_service')
    @mock.patch.object(nfs.HDSNFSDriver, '_id_to_vol', side_effect=id_to_vol)
    @mock.patch.object(nfs.HDSNFSDriver, '_get_provider_location')
    @mock.patch.object(nfs.HDSNFSDriver, '_get_export_path')
    @mock.patch.object(nfs.HDSNFSDriver, '_get_volume_location')
    def test_create_volume_from_snapshot(self, m_get_volume_location,
                                         m_get_export_path,
                                         m_get_provider_location, m_id_to_vol,
                                         m_get_service):
        vol = _VOLUME.copy()
        svol = _SNAPVOLUME.copy()

        m_get_service.return_value = _SERVICE
        m_get_provider_location.return_value = _SHARE
        m_get_export_path.return_value = _EXPORT
        m_get_volume_location.return_value = _SHARE

        loc = self.driver.create_volume_from_snapshot(vol, svol)
        out = "{'provider_location': \'" + _SHARE + "'}"
        self.assertEqual(str(loc), out)

    @mock.patch.object(volume_types, 'get_volume_type_extra_specs',
                       return_value={'key': 'type', 'service_label': 'silver'})
    def test_get_pool(self, m_ext_spec):
        vol = _VOLUME.copy()

        self.assertEqual(self.driver.get_pool(vol), 'silver')
