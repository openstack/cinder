# Copyright 2018 Red Hat, Inc
# Copyright 2017 Rackspace Australia
# Copyright 2018 Michael Still and Aptira
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
Helpers for ietadm related routines.
"""

from oslo_concurrency import processutils

import cinder.privsep


@cinder.privsep.sys_admin_pctxt.entrypoint
def new_target(name, tid):
    """Create new scsi target using specified parameters.

    If the target already exists, ietadm returns
    'Invalid argument' and error code '234'.
    This should be ignored for ensure export case.
    """
    processutils.execute('ietadm', '--op', 'new',
                         '--tid=%s' % tid,
                         '--params', 'Name=%s' % name,
                         check_exit_code=[0, 234])


@cinder.privsep.sys_admin_pctxt.entrypoint
def delete_target(tid):
    processutils.execute('ietadm', '--op', 'delete',
                         '--tid=%s' % tid)


@cinder.privsep.sys_admin_pctxt.entrypoint
def force_delete_target(tid, sid, cid):
    processutils.execute('ietadm', '--op', 'delete',
                         '--tid=%s' % tid,
                         '--sid=%s' % sid,
                         '--cid=%s' % cid)


@cinder.privsep.sys_admin_pctxt.entrypoint
def new_logicalunit(tid, lun, path, iotype):
    """Attach a new volume to scsi target as a logical unit.

    If a logical unit exists on the specified target lun,
    ietadm returns 'File exists' and error code '239'.
    This should be ignored for ensure export case.
    """

    processutils.execute('ietadm', '--op', 'new',
                         '--tid=%s' % tid,
                         '--lun=%d' % lun,
                         '--params',
                         'Path=%s,Type=%s' % (path, iotype),
                         check_exit_code=[0, 239])


@cinder.privsep.sys_admin_pctxt.entrypoint
def delete_logicalunit(tid, lun):
    processutils.execute('ietadm', '--op', 'delete',
                         '--tid=%s' % tid,
                         '--lun=%d' % lun)


@cinder.privsep.sys_admin_pctxt.entrypoint
def new_auth(tid, type, username, password):
    processutils.execute('ietadm', '--op', 'new',
                         '--tid=%s' % tid,
                         '--user',
                         '--params=%s=%s,Password=%s' % (type,
                                                         username,
                                                         password))
