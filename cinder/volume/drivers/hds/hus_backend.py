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
Hitachi Unified Storage (HUS) platform. Backend operations.
"""

from cinder.openstack.common import log as logging
from cinder import utils

LOG = logging.getLogger("cinder.volume.driver")


class HusBackend:
    """Back end. Talks to HUS."""
    def get_version(self, cmd, ver, ip0, ip1, user, pw):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--version', '1',
                                 run_as_root=True,
                                 check_exit_code=True)
        LOG.debug('get_version: ' + out + ' -- ' + err)
        return out

    def get_iscsi_info(self, cmd, ver, ip0, ip1, user, pw):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--iscsi', '1',
                                 check_exit_code=True)
        LOG.debug('get_iscsi_info: ' + out + ' -- ' + err)
        return out

    def get_hdp_info(self, cmd, ver, ip0, ip1, user, pw):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--hdp', '1',
                                 check_exit_code=True)
        LOG.debug('get_hdp_info: ' + out + ' -- ' + err)
        return out

    def create_lu(self, cmd, ver, ip0, ip1, user, pw, id, hdp, start,
                  end, size):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--create-lun', '1',
                                 '--array-id', id,
                                 '--hdp', hdp,
                                 '--start', start,
                                 '--end', end,
                                 '--size', size,
                                 check_exit_code=True)
        LOG.debug('create_lu: ' + out + ' -- ' + err)
        return out

    def delete_lu(self, cmd, ver, ip0, ip1, user, pw, id, lun):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--delete-lun', '1',
                                 '--array-id', id,
                                 '--lun', lun,
                                 '--force', 1,
                                 check_exit_code=True)
        LOG.debug('delete_lu: ' + out + ' -- ' + err)
        return out

    def create_dup(self, cmd, ver, ip0, ip1, user, pw, id, src_lun,
                   hdp, start, end, size):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--create-dup', '1',
                                 '--array-id', id,
                                 '--pvol', src_lun,
                                 '--hdp', hdp,
                                 '--start', start,
                                 '--end', end,
                                 '--size', size,
                                 check_exit_code=True)
        LOG.debug('create_dup: ' + out + ' -- ' + err)
        return out

    def extend_vol(self, cmd, ver, ip0, ip1, user, pw, id, lun, new_size):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--extend-lun', '1',
                                 '--array-id', id,
                                 '--lun', lun,
                                 '--size', new_size,
                                 check_exit_code=True)
        LOG.debug('extend_vol: ' + out + ' -- ' + err)
        return out

    def add_iscsi_conn(self, cmd, ver, ip0, ip1, user, pw, id, lun, ctl, port,
                       iqn, initiator):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--add-iscsi-connection', '1',
                                 '--array-id', id,
                                 '--lun', lun,
                                 '--ctl', ctl,
                                 '--port', port,
                                 '--target', iqn,
                                 '--initiator', initiator,
                                 check_exit_code=True)
        LOG.debug('add_iscsi_conn: ' + out + ' -- ' + err)
        return out

    def del_iscsi_conn(self, cmd, ver, ip0, ip1, user, pw, id, lun, ctl, port,
                       iqn, initiator):
        out, err = utils.execute(cmd,
                                 '--driver-version', ver,
                                 '--ip0', ip0,
                                 '--ip1', ip1,
                                 '--user', user,
                                 '--password', pw,
                                 '--delete-iscsi-connection', '1',
                                 '--array-id', id,
                                 '--lun', lun,
                                 '--ctl', ctl,
                                 '--port', port,
                                 '--target', iqn,
                                 '--initiator', initiator,
                                 '--force', 1,
                                 check_exit_code=True)
        LOG.debug('del_iscsi_conn: ' + out + ' -- ' + err)
        return out
