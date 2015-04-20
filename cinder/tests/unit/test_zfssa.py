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

import json

import mock
from oslo_log import log as logging
from oslo_utils import units

from cinder.volume.drivers.zfssa import restclient as client
from cinder.volume.drivers.zfssa import zfssarest as rest


LOG = logging.getLogger(__name__)

nfs_logbias = 'latency'
nfs_compression = 'off'


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

        out = {"status": "online",
               "lunguid": "600144F0F8FBD5BD000053CE53AB0001",
               "initiatorgroup": ["fake_initgrp"],
               "volsize": volsize,
               "pool": pool,
               "name": lun,
               "project": project,
               "targetgroup": targetgroup}
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
    """Fake ZFS SA for the NFS Driver
    """
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


class FakeAddIni2InitGrp(object):
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
