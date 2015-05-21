# Copyright (c) 2014, Oracle and/or its affiliates. All rights reserved.
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
"""Unit tests for Oracle's ZFSSA Cinder volume driver."""

import json

import mock
from oslo_utils import units

from cinder import test
from cinder.tests.unit import fake_utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.zfssa import restclient as client
from cinder.volume.drivers.zfssa import zfssaiscsi as iscsi
from cinder.volume.drivers.zfssa import zfssanfs
from cinder.volume.drivers.zfssa import zfssarest as rest


nfs_logbias = 'latency'
nfs_compression = 'off'


class FakeZFSSA(object):
    """Fake ZFS SA."""
    def __init__(self):
        self.user = None
        self.host = None

    def login(self, user):
        self.user = user

    def set_host(self, host, timeout=None):
        self.host = host

    def create_project(self, pool, project, compression, logbias):
        out = {}
        if not self.host or not self.user:
            return out

        out = {"status": "online",
               "name": "pool",
               "usage": {"available": 10,
                         "total": 10,
                         "dedupratio": 100,
                         "used": 1},
               "peer": "00000000-0000-0000-0000-000000000000",
               "owner": "host",
               "asn": "11111111-2222-3333-4444-555555555555"}
        return out

    def create_initiator(self, init, initgrp, chapuser, chapsecret):
        out = {}
        if not self.host or not self.user:
            return out
        out = {"href": "fake_href",
               "alias": "fake_alias",
               "initiator": "fake_iqn.1993-08.org.fake:01:000000000000",
               "chapuser": "",
               "chapsecret": ""
               }

        return out

    def add_to_initiatorgroup(self, init, initgrp):
        r = rest.ZFSSAApi()
        type(r).rclient = mock.PropertyMock(return_value=FakeAddIni2InitGrp())
        r.add_to_initiatorgroup(init, initgrp)

    def create_target(self, tgtalias, inter, tchapuser, tchapsecret):
        out = {}
        if not self.host or not self.user:
            return out
        out = {"href": "fake_href",
               "alias": "fake_tgtgrp",
               "iqn": "iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd",
               "auth": "none",
               "targetchapuser": "",
               "targetchapsecret": "",
               "interfaces": ["eth0"]
               }

        return out

    def add_to_targetgroup(self, iqn, tgtgrp):
        out = {}
        if not self.host or not self.user:
            return {}
        out = {"href": "fake_href",
               "name": "fake_tgtgrp",
               "targets": ["iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd"]
               }
        return out

    def get_lun(self, pool, project, lun):
        ret = {
            'guid': '600144F0F8FBD5BD000053CE53AB0001',
            'number': 0,
            'initiatorgroup': 'fake_initgrp',
            'size': 1 * units.Gi
        }
        return ret

    def get_target(self, target):
        return 'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'

    def create_lun(self, pool, project, lun, volsize, targetgroup, specs):
        out = {}
        if not self.host and not self.user:
            return out

        out = {
            "status": "online",
            "lunguid": "600144F0F8FBD5BD000053CE53AB0001",
            "initiatorgroup": ["fake_initgrp"],
            "volsize": volsize,
            "pool": pool,
            "name": lun,
            "project": project,
            "targetgroup": targetgroup,
            "lun": {"assignednumber": 0},
        }
        if specs:
            out.update(specs)

        return out

    def delete_lun(self, pool, project, lun):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"pool": pool,
               "project": project,
               "name": lun}

        return out

    def create_snapshot(self, pool, project, vol, snap):
        out = {}
        if not self.host and not self.user:
            return {}
        out = {"name": snap,
               "numclones": 0,
               "share": vol,
               "project": project,
               "pool": pool}

        return out

    def delete_snapshot(self, pool, project, vol, snap):
        out = {}
        if not self.host and not self.user:
            return {}
        out = {"name": snap,
               "share": vol,
               "project": project,
               "pool": pool}

        return out

    def clone_snapshot(self, pool, project, pvol, snap, vol):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"origin": {"project": project,
                          "snapshot": snap,
                          "share": pvol,
                          "pool": pool},
               "logbias": "latency",
               "assignednumber": 1,
               "status": "online",
               "lunguid": "600144F0F8FBD5BD000053CE67A50002",
               "volsize": 1,
               "pool": pool,
               "name": vol,
               "project": project}

        return out

    def set_lun_initiatorgroup(self, pool, project, vol, initgrp):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"lunguid": "600144F0F8FBD5BD000053CE67A50002",
               "pool": pool,
               "name": vol,
               "project": project,
               "initiatorgroup": ["fake_initgrp"]}

        return out

    def has_clones(self, pool, project, vol, snapshot):
        return False

    def set_lun_props(self, pool, project, vol, **kargs):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"pool": pool,
               "name": vol,
               "project": project,
               "volsize": kargs['volsize']}

        return out

    def get_initiator_initiatorgroup(self, initiator):
        ret = ['test-init-grp1']
        return ret


class FakeNFSZFSSA(FakeZFSSA):
    """Fake ZFS SA for the NFS Driver."""
    def set_webdav(self, https_path, auth_str):
        self.webdavclient = https_path

    def create_share(self, pool, project, share, args):
        out = {}
        if not self.host and not self.user:
            return out

        out = {"logbias": nfs_logbias,
               "compression": nfs_compression,
               "status": "online",
               "pool": pool,
               "name": share,
               "project": project,
               "mountpoint": '/export/nfs_share'}

        return out

    def get_share(self, pool, project, share):
        out = {}
        if not self.host and not self.user:
            return out

        out = {"logbias": nfs_logbias,
               "compression": nfs_compression,
               "encryption": "off",
               "status": "online",
               "pool": pool,
               "name": share,
               "project": project,
               "mountpoint": '/export/nfs_share'}

        return out

    def create_snapshot_of_volume_file(self, src_file="", dst_file=""):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"status": 201}

        return out

    def delete_snapshot_of_volume_file(self, src_file=""):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"status": 204}

        return out

    def create_volume_from_snapshot_file(self, src_file="", dst_file="",
                                         method='COPY'):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"status": 202}

        return out

    def modify_service(self, service, args):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"service": {"<status>": "online"}}
        return out

    def enable_service(self, service):
        out = {}
        if not self.host and not self.user:
            return out
        out = {"service": {"<status>": "online"}}
        return out


class TestZFSSAISCSIDriver(test.TestCase):

    test_vol = {
        'name': 'cindervol',
        'size': 1,
        'id': 1,
        'provider_location': 'fake_location 1 2',
        'provider_auth': 'fake_auth user pass',
    }

    test_snap = {
        'name': 'cindersnap',
        'volume_name': test_vol['name']
    }

    test_vol_snap = {
        'name': 'cindersnapvol',
        'size': test_vol['size']
    }

    def __init__(self, method):
        super(TestZFSSAISCSIDriver, self).__init__(method)

    @mock.patch.object(iscsi, 'factory_zfssa')
    def setUp(self, _factory_zfssa):
        super(TestZFSSAISCSIDriver, self).setUp()
        self._create_fake_config()
        _factory_zfssa.return_value = FakeZFSSA()
        iscsi.ZFSSAISCSIDriver._execute = fake_utils.fake_execute
        self.drv = iscsi.ZFSSAISCSIDriver(configuration=self.configuration)
        self.drv.do_setup({})

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.san_ip = '1.1.1.1'
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'passwd'
        self.configuration.zfssa_pool = 'pool'
        self.configuration.zfssa_project = 'project'
        self.configuration.zfssa_lun_volblocksize = '8k'
        self.configuration.zfssa_lun_sparse = 'false'
        self.configuration.zfssa_lun_logbias = 'latency'
        self.configuration.zfssa_lun_compression = 'off'
        self.configuration.zfssa_initiator_group = 'test-init-grp1'
        self.configuration.zfssa_initiator = \
            'iqn.1-0.org.deb:01:d7, iqn.1-0.org.deb:01:d9'
        self.configuration.zfssa_initiator_user = ''
        self.configuration.zfssa_initiator_password = ''
        self.configuration.zfssa_initiator_config = "{'test-init-grp1':[{'iqn':\
            'iqn.1-0.org.deb:01:d7','user':'','password':''}],'test-init-grp\
            2':[{'iqn':'iqn.1-0.org.deb:01:d9','user':'','password':''}]}"
        self.configuration.zfssa_target_group = 'test-target-grp1'
        self.configuration.zfssa_target_user = ''
        self.configuration.zfssa_target_password = ''
        self.configuration.zfssa_target_portal = '1.1.1.1:3260'
        self.configuration.zfssa_target_interfaces = 'e1000g0'
        self.configuration.zfssa_rest_timeout = 60
        self.configuration.volume_backend_name = 'fake_zfssa'
        self.configuration.safe_get = self.fake_safe_get

    def test_create_delete_volume(self):
        self.drv.create_volume(self.test_vol)
        self.drv.delete_volume(self.test_vol)

    def test_create_delete_snapshot(self):
        self.drv.create_volume(self.test_vol)
        self.drv.create_snapshot(self.test_snap)
        self.drv.delete_snapshot(self.test_snap)
        self.drv.delete_volume(self.test_vol)

    def test_create_volume_from_snapshot(self):
        self.drv.create_volume(self.test_vol)
        self.drv.create_snapshot(self.test_snap)
        self.drv.create_volume_from_snapshot(self.test_vol_snap,
                                             self.test_snap)
        self.drv.delete_volume(self.test_vol)

    def test_remove_export(self):
        self.drv.create_volume(self.test_vol)
        self.drv.terminate_connection(self.test_vol, '')
        self.drv.delete_volume(self.test_vol)

    def test_volume_attach_detach(self):
        self.drv.create_volume(self.test_vol)

        connector = dict(initiator='iqn.1-0.org.deb:01:d7')
        props = self.drv.initialize_connection(self.test_vol, connector)
        self.assertEqual('iscsi', props['driver_volume_type'])
        self.assertEqual(self.test_vol['id'], props['data']['volume_id'])

        self.drv.terminate_connection(self.test_vol, '')
        self.drv.delete_volume(self.test_vol)

    def test_get_volume_stats(self):
        self.drv.get_volume_stats(refresh=False)

    def test_extend_volume(self):
        self.drv.create_volume(self.test_vol)
        self.drv.extend_volume(self.test_vol, 3)
        self.drv.delete_volume(self.test_vol)

    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs')
    def test_get_voltype_specs(self, get_volume_type_extra_specs):
        volume_type_id = mock.sentinel.volume_type_id
        volume = {'volume_type_id': volume_type_id}
        get_volume_type_extra_specs.return_value = {
            'zfssa:volblocksize': '128k',
            'zfssa:compression': 'gzip'
        }
        ret = self.drv._get_voltype_specs(volume)
        self.assertEqual(ret.get('volblocksize'), '128k')
        self.assertEqual(ret.get('sparse'),
                         self.configuration.zfssa_lun_sparse)
        self.assertEqual(ret.get('compression'), 'gzip')
        self.assertEqual(ret.get('logbias'),
                         self.configuration.zfssa_lun_logbias)

    def tearDown(self):
        super(TestZFSSAISCSIDriver, self).tearDown()

    def fake_safe_get(self, value):
        try:
            val = getattr(self.configuration, value)
        except AttributeError:
            val = None
        return val


class FakeAddIni2InitGrp(object):

    def logout(self):
        result = client.RestResult()
        result.status = client.Status.ACCEPTED
        return result

    def get(self, path, **kwargs):
        result = client.RestResult()
        result.status = client.Status.OK
        result.data = json.JSONEncoder().encode({'group':
                                                {'initiators':
                                                 ['iqn.1-0.org.deb:01:d7']}})
        return result

    def put(self, path, body="", **kwargs):
        result = client.RestResult()
        result.status = client.Status.ACCEPTED
        return result

    def post(self, path, body="", **kwargs):
        result = client.RestResult()
        result.status = client.Status.CREATED
        return result

    def islogin(self):
        return True


class TestZFSSANFSDriver(test.TestCase):

    test_vol = {
        'name': 'test-vol',
        'size': 1
    }

    test_snap = {
        'name': 'cindersnap',
        'volume_name': test_vol['name'],
        'volume_size': test_vol['size']
    }

    test_vol_snap = {
        'name': 'cindersnapvol',
        'size': test_vol['size']
    }

    def __init__(self, method):
        super(TestZFSSANFSDriver, self).__init__(method)

    @mock.patch.object(zfssanfs, 'factory_zfssa')
    def setUp(self, _factory_zfssa):
        super(TestZFSSANFSDriver, self).setUp()
        self._create_fake_config()
        _factory_zfssa.return_value = FakeNFSZFSSA()
        self.drv = zfssanfs.ZFSSANFSDriver(configuration=self.configuration)
        self.drv._execute = fake_utils.fake_execute
        self.drv.do_setup({})

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.san_ip = '1.1.1.1'
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'passwd'
        self.configuration.zfssa_data_ip = '2.2.2.2'
        self.configuration.zfssa_https_port = '443'
        self.configuration.zfssa_nfs_pool = 'pool'
        self.configuration.zfssa_nfs_project = 'nfs_project'
        self.configuration.zfssa_nfs_share = 'nfs_share'
        self.configuration.zfssa_nfs_share_logbias = nfs_logbias
        self.configuration.zfssa_nfs_share_compression = nfs_compression
        self.configuration.zfssa_nfs_mount_options = ''
        self.configuration.zfssa_rest_timeout = '30'
        self.configuration.nfs_oversub_ratio = 1
        self.configuration.nfs_used_ratio = 1

    def test_create_delete_snapshot(self):
        self.drv.create_snapshot(self.test_snap)
        self.drv.delete_snapshot(self.test_snap)

    def test_create_volume_from_snapshot(self):
        self.drv.create_snapshot(self.test_snap)
        with mock.patch.object(self.drv, '_ensure_shares_mounted'):
            prov_loc = self.drv.create_volume_from_snapshot(self.test_vol_snap,
                                                            self.test_snap,
                                                            method='COPY')
        self.assertEqual('2.2.2.2:/export/nfs_share',
                         prov_loc['provider_location'])

    def test_get_volume_stats(self):
        self.drv._mounted_shares = ['nfs_share']
        with mock.patch.object(self.drv, '_ensure_shares_mounted'):
            with mock.patch.object(self.drv, '_get_share_capacity_info') as \
                    mock_get_share_capacity_info:
                mock_get_share_capacity_info.return_value = (1073741824,
                                                             9663676416)
                self.drv.get_volume_stats(refresh=True)

    def tearDown(self):
        super(TestZFSSANFSDriver, self).tearDown()
