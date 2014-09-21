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
"""
Unit tests for Oracle's ZFSSA Cinder volume driver
"""

import mock

from cinder.openstack.common import log as logging
from cinder.openstack.common import units
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.zfssa import zfssaiscsi as iscsi


LOG = logging.getLogger(__name__)


class FakeZFSSA(object):
    """Fake ZFS SA"""
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
        out = {}
        if not self.host or not self.user:
            return out

        out = {"href": "fake_href",
               "name": "fake_initgrp",
               "initiators": ["fake_iqn.1993-08.org.fake:01:000000000000"]
               }
        return out

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

    def create_lun(self, pool, project, lun, volsize, targetgroup,
                   volblocksize, sparse, compression, logbias):
        out = {}
        if not self.host and not self.user:
            return out

        out = {"logbias": logbias,
               "compression": compression,
               "status": "online",
               "lunguid": "600144F0F8FBD5BD000053CE53AB0001",
               "initiatorgroup": ["fake_initgrp"],
               "volsize": volsize,
               "pool": pool,
               "volblocksize": volblocksize,
               "name": lun,
               "project": project,
               "sparse": sparse,
               "targetgroup": targetgroup}

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


class TestZFSSAISCSIDriver(test.TestCase):

    test_vol = {
        'name': 'cindervol',
        'size': 1
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
            'iqn.1993-08.org.debian:01:daa02db2a827'
        self.configuration.zfssa_initiator_user = ''
        self.configuration.zfssa_initiator_password = ''
        self.configuration.zfssa_target_group = 'test-target-grp1'
        self.configuration.zfssa_target_user = ''
        self.configuration.zfssa_target_password = ''
        self.configuration.zfssa_target_portal = '1.1.1.1:3260'
        self.configuration.zfssa_target_interfaces = 'e1000g0'
        self.configuration.zfssa_rest_timeout = 60

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

    def test_create_export(self):
        self.drv.create_volume(self.test_vol)
        self.drv.create_export({}, self.test_vol)
        self.drv.delete_volume(self.test_vol)

    def test_remove_export(self):
        self.drv.create_volume(self.test_vol)
        self.drv.remove_export({}, self.test_vol)
        self.drv.delete_volume(self.test_vol)

    def test_get_volume_stats(self):
        self.drv.get_volume_stats(refresh=False)

    def test_extend_volume(self):
        self.drv.create_volume(self.test_vol)
        self.drv.extend_volume(self.test_vol, 3)
        self.drv.delete_volume(self.test_vol)

    def tearDown(self):
        super(TestZFSSAISCSIDriver, self).tearDown()
