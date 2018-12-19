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
Helpers for iscsi related routines.
"""

from oslo_concurrency import processutils

import cinder.privsep


@cinder.privsep.sys_admin_pctxt.entrypoint
def tgtadmin_show():
    return processutils.execute('tgt-admin', '--show')


@cinder.privsep.sys_admin_pctxt.entrypoint
def tgtadmin_update(name, force=False):
    cmd = ['tgt-admin']
    cmd.extend(['--update', name])
    if force:
        cmd.extend(['-f'])
    return processutils.execute(*cmd)


@cinder.privsep.sys_admin_pctxt.entrypoint
def tgtadmin_delete(iqn, force=False):
    cmd = ['tgt-admin']
    cmd.extend(['--delete', iqn])
    if force:
        cmd.extend(['-f'])
    processutils.execute(*cmd)


@cinder.privsep.sys_admin_pctxt.entrypoint
def tgtadm_show():
    cmd = ('tgtadm', '--lld', 'iscsi', '--op', 'show', '--mode', 'target')
    return processutils.execute(*cmd)


@cinder.privsep.sys_admin_pctxt.entrypoint
def tgtadm_create(tid, path):
    cmd = ('tgtadm', '--lld', 'iscsi', '--op', 'new', '--mode',
           'logicalunit', '--tid', tid, '--lun', '1', '-b',
           path)
    return processutils.execute(*cmd)
