#    Copyright (c) 2020 Open-E, Inc.
#    All Rights Reserved.
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

from datetime import datetime

from cinder import exception
from cinder.i18n import _


def is_volume(name):
    """Return True if volume"""

    return name.startswith("v_")


def is_snapshot(name):
    """Return True if volume"""

    return name.startswith("s_")


def idname(name):
    """Extract UUID from physical volume name"""

    if name.startswith(('v_', 't_')):
        return name[2:]

    if name.startswith(('s_')):
        return sid_from_sname(name)

    msg = _('Object name %s is incorrect') % name
    raise exception.VolumeDriverException(message=msg)


def vname(name):
    """Convert id into volume name"""

    if name.startswith("v_"):
        return name

    if name.startswith('s_'):
        msg = _('Attempt to use snapshot %s as a volume') % name
        raise exception.VolumeDriverException(message=msg)

    if name.startswith('t_'):
        msg = _('Attempt to use deleted object %s as a volume') % name
        raise exception.VolumeDriverException(message=msg)

    return f'v_{name}'


def sname_to_id(sname):

    spl = sname.split('_')

    if len(spl) == 2:
        return (spl[1], None)

    return (spl[1], spl[2])


def sid_from_sname(name):
    return sname_to_id(name)[0]


def vid_from_sname(name):
    return sname_to_id(name)[1]


def sname(sid, vid):
    """Convert id into snapshot name

    :param: vid: volume id
    :param: sid: snapshot id
    """
    if vid is None:
        return 's_%(sid)s' % {'sid': sid}
    return 's_%(sid)s_%(vid)s' % {'sid': sid, 'vid': vid}


def sname_from_snap(snapshot_struct):
    return snapshot_struct['name']


def is_hidden(name):
    """Check if object is active or no"""

    if len(name) < 2:
        return False
    if name.startswith('t_'):
        return True
    return False


def origin_snapshot(vol):
    """Extracts original physical snapshot name from volume dict"""
    if 'origin' in vol and vol['origin'] is not None:
        return vol['origin'].split("@")[1]
    return None


def origin_volume(vol):
    """Extracts original physical volume name from volume dict"""

    if 'origin' in vol and vol['origin'] is not None:
        return vol['origin'].split("@")[0].split("/")[1]
    return None


def snapshot_clones(snap):
    """Return list of clones associated with snapshot or return empty list"""
    out = []
    clones = []
    if 'clones' not in snap:
        return out
    else:
        clones = snap['clones'].split(',')

    for clone in clones:
        out.append(clone.split('/')[1])
    return out


def hidden(name):
    """Get hidden version of a name"""

    if len(name) < 2:
        raise exception.VolumeDriverException("Incorrect volume name")

    if name[:2] == 'v_' or name[:2] == 's_':
        return 't_' + name[2:]
    return 't_' + name


def get_newest_snapshot_name(snapshots):
    newest_date = None
    sname = None
    for snap in snapshots:
        current_date = datetime.strptime(snap['creation'], "%Y-%m-%d %H:%M:%S")
        if newest_date is None or current_date > newest_date:
            newest_date = current_date
            sname = snap['name']
    return sname
