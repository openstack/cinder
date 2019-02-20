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
Helpers for filesystem related routines.
"""


from oslo_concurrency import processutils
from oslo_log import log as logging

import cinder.privsep

LOG = logging.getLogger(__name__)

mult_table = {'K': 1024}
mult_table['M'] = mult_table['K'] * 1024
mult_table['G'] = mult_table['M'] * 1024
mult_table['T'] = mult_table['G'] * 1024
mult_table['P'] = mult_table['T'] * 1024
mult_table['E'] = mult_table['P'] * 1024


def _convert_sizestr(sizestr):
    try:
        ret = int(sizestr)
        return ret
    except ValueError:
        pass

    error = ValueError(sizestr + " is not a valid sizestr")

    unit = sizestr[-1:].upper()
    if unit in mult_table:
        try:
            ret = int(sizestr[:-1]) * mult_table[unit]
        except ValueError:
            raise error
        return ret

    raise error


@cinder.privsep.sys_admin_pctxt.entrypoint
def umount(mountpoint):
    processutils.execute('umount', mountpoint, attempts=1, delay_on_retry=True)


@cinder.privsep.sys_admin_pctxt.entrypoint
def _truncate(size, path):
    # On Python 3.6, os.truncate() can accept a path arg.
    # For now, do it this way.
    with open(path, 'a+b') as f:
        f.truncate(size)


def truncate(sizestr, path):
    # TODO(eharney): change calling code to use bytes instead size strings
    size = _convert_sizestr(sizestr)

    LOG.debug('truncating file %(path)s to %(size)s bytes', {'path': path,
                                                             'size': size})

    _truncate(size, path)
