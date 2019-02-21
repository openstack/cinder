# Copyright 2018 Red Hat, Inc
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
Helpers for lvm related routines
"""

from oslo_concurrency import processutils

import cinder.privsep


@cinder.privsep.sys_admin_pctxt.entrypoint
def udevadm_settle():
    processutils.execute('udevadm', 'settle')


@cinder.privsep.sys_admin_pctxt.entrypoint
def lvrename(vg_name, lv_name, new_name):
    processutils.execute(
        'lvrename', vg_name, lv_name, new_name)


@cinder.privsep.sys_admin_pctxt.entrypoint
def create_vg(vg_name, pv_list):
    cmd = ['vgcreate', vg_name, ','.join(pv_list)]
    processutils.execute(*cmd)


@cinder.privsep.sys_admin_pctxt.entrypoint
def lvconvert(vg_name, snapshot_name):
    processutils.execute(
        'lvconvert', '--merge', '%s/%s' % (vg_name, snapshot_name))
