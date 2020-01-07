# Copyright 2018 Nexenta Systems, Inc.
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

import re

from oslo_utils import units
import six
import six.moves.urllib.parse as urlparse

from cinder import exception
from cinder.i18n import _


class NexentaException(exception.VolumeDriverException):
    message = "%(reason)s"


def str2size(s, scale=1024):
    """Convert size-string.

    String format: <value>[:space:]<B | K | M | ...> to bytes.

    :param s: size-string
    :param scale: base size
    """
    if not s:
        return 0

    if isinstance(s, six.integer_types):
        return s

    match = re.match(r'^([\.\d]+)\s*([BbKkMmGgTtPpEeZzYy]?)', s)
    if match is None:
        raise ValueError(_('Invalid value: %(value)s')
                         % {'value': s})

    groups = match.groups()
    value = float(groups[0])
    suffix = groups[1].upper() if groups[1] else 'B'

    types = ('B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
    for i, t in enumerate(types):
        if suffix == t:
            return int(value * pow(scale, i))


def str2gib_size(s):
    """Covert size-string to size in gigabytes."""
    size_in_bytes = str2size(s)
    return size_in_bytes // units.Gi


def get_rrmgr_cmd(src, dst, compression=None, tcp_buf_size=None,
                  connections=None):
    """Returns rrmgr command for source and destination."""
    cmd = ['rrmgr', '-s', 'zfs']
    if compression:
        cmd.extend(['-c', six.text_type(compression)])
    cmd.append('-q')
    cmd.append('-e')
    if tcp_buf_size:
        cmd.extend(['-w', six.text_type(tcp_buf_size)])
    if connections:
        cmd.extend(['-n', six.text_type(connections)])
    cmd.extend([src, dst])
    return ' '.join(cmd)


def parse_nms_url(url):
    """Parse NMS url into normalized parts like scheme, user, host and others.

    Example NMS URL:
        auto://admin:nexenta@192.168.1.1:2000/

    NMS URL parts:

    .. code-block:: none

        auto                True if url starts with auto://, protocol
                            will be automatically switched to https
                            if http not supported;
        scheme (auto)       connection protocol (http or https);
        user (admin)        NMS user;
        password (nexenta)  NMS password;
        host (192.168.1.1)  NMS host;
        port (2000)         NMS port.

    :param url: url string
    :return: tuple (auto, scheme, user, password, host, port, path)
    """
    pr = urlparse.urlparse(url)
    scheme = pr.scheme
    auto = scheme == 'auto'
    if auto:
        scheme = 'http'
    user = 'admin'
    password = 'nexenta'
    if '@' not in pr.netloc:
        host_and_port = pr.netloc
    else:
        user_and_password, host_and_port = pr.netloc.split('@', 1)
        if ':' in user_and_password:
            user, password = user_and_password.split(':')
        else:
            user = user_and_password
    if ':' in host_and_port:
        host, port = host_and_port.split(':', 1)
    else:
        host, port = host_and_port, '2000'
    return auto, scheme, user, password, host, port, '/rest/nms/'


def get_migrate_snapshot_name(volume):
    """Return name for snapshot that will be used to migrate the volume."""
    return 'cinder-migrate-snapshot-%(id)s' % volume


def ex2err(ex):
    """Convert a Cinder Exception to a Nexenta Error."""
    return ex.msg
