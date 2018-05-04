# Copyright 2016 Red Hat, Inc
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
Helpers for cgroup related routines.
"""

from oslo_concurrency import processutils

import cinder.privsep


@cinder.privsep.sys_admin_pctxt.entrypoint
def cgroup_create(name):
    processutils.execute('cgcreate', '-g', 'blkio:%s' % name)


@cinder.privsep.sys_admin_pctxt.entrypoint
def cgroup_limit(name, rw, dev, bps):
    processutils.execute('cgset', '-r',
                         'blkio.throttle.%s_bps_device=%s %d' % (rw, dev, bps),
                         name)
