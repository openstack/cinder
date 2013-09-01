# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
Helper methods to deal with images.

This is essentially a copy from nova.virt.images.py
Some slight modifications, but at some point
we should look at maybe pushign this up to OSLO
"""


import contextlib
import os
import re
import tempfile

from oslo.config import cfg

from cinder import exception
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import strutils
from cinder import utils


LOG = logging.getLogger(__name__)

image_helper_opt = [cfg.StrOpt('image_conversion_dir',
                    default='/tmp',
                    help='parent dir for tempdir used for image conversion'), ]

CONF = cfg.CONF
CONF.register_opts(image_helper_opt)


class QemuImgInfo(object):
    BACKING_FILE_RE = re.compile((r"^(.*?)\s*\(actual\s+path\s*:"
                                  r"\s+(.*?)\)\s*$"), re.I)
    TOP_LEVEL_RE = re.compile(r"^([\w\d\s\_\-]+):(.*)$")
    SIZE_RE = re.compile(r"\(\s*(\d+)\s+bytes\s*\)", re.I)

    def __init__(self, cmd_output):
        details = self._parse(cmd_output)
        self.image = details.get('image')
        self.backing_file = details.get('backing_file')
        self.file_format = details.get('file_format')
        self.virtual_size = details.get('virtual_size')
        self.cluster_size = details.get('cluster_size')
        self.disk_size = details.get('disk_size')
        self.snapshots = details.get('snapshot_list', [])
        self.encryption = details.get('encryption')

    def __str__(self):
        lines = [
            'image: %s' % self.image,
            'file_format: %s' % self.file_format,
            'virtual_size: %s' % self.virtual_size,
            'disk_size: %s' % self.disk_size,
            'cluster_size: %s' % self.cluster_size,
            'backing_file: %s' % self.backing_file,
        ]
        if self.snapshots:
            lines.append("snapshots: %s" % self.snapshots)
        return "\n".join(lines)

    def _canonicalize(self, field):
        # Standardize on underscores/lc/no dash and no spaces
        # since qemu seems to have mixed outputs here... and
        # this format allows for better integration with python
        # - ie for usage in kwargs and such...
        field = field.lower().strip()
        for c in (" ", "-"):
            field = field.replace(c, '_')
        return field

    def _extract_bytes(self, details):
        # Replace it with the byte amount
        real_size = self.SIZE_RE.search(details)
        if real_size:
            details = real_size.group(1)
        try:
            details = strutils.to_bytes(details)
        except TypeError:
            pass
        return details

    def _extract_details(self, root_cmd, root_details, lines_after):
        consumed_lines = 0
        real_details = root_details
        if root_cmd == 'backing_file':
            # Replace it with the real backing file
            backing_match = self.BACKING_FILE_RE.match(root_details)
            if backing_match:
                real_details = backing_match.group(2).strip()
        elif root_cmd in ['virtual_size', 'cluster_size', 'disk_size']:
            # Replace it with the byte amount (if we can convert it)
            real_details = self._extract_bytes(root_details)
        elif root_cmd == 'file_format':
            real_details = real_details.strip().lower()
        elif root_cmd == 'snapshot_list':
            # Next line should be a header, starting with 'ID'
            if not lines_after or not lines_after[0].startswith("ID"):
                msg = _("Snapshot list encountered but no header found!")
                raise ValueError(msg)
            consumed_lines += 1
            possible_contents = lines_after[1:]
            real_details = []
            # This is the sprintf pattern we will try to match
            # "%-10s%-20s%7s%20s%15s"
            # ID TAG VM SIZE DATE VM CLOCK (current header)
            for line in possible_contents:
                line_pieces = line.split(None)
                if len(line_pieces) != 6:
                    break
                else:
                    # Check against this pattern occuring in the final position
                    # "%02d:%02d:%02d.%03d"
                    date_pieces = line_pieces[5].split(":")
                    if len(date_pieces) != 3:
                        break
                    real_details.append({
                        'id': line_pieces[0],
                        'tag': line_pieces[1],
                        'vm_size': line_pieces[2],
                        'date': line_pieces[3],
                        'vm_clock': line_pieces[4] + " " + line_pieces[5],
                    })
                    consumed_lines += 1
        return (real_details, consumed_lines)

    def _parse(self, cmd_output):
        # Analysis done of qemu-img.c to figure out what is going on here
        # Find all points start with some chars and then a ':' then a newline
        # and then handle the results of those 'top level' items in a separate
        # function.
        #
        # TODO(harlowja): newer versions might have a json output format
        #                 we should switch to that whenever possible.
        #                 see: http://bit.ly/XLJXDX
        if not cmd_output:
            cmd_output = ''
        contents = {}
        lines = cmd_output.splitlines()
        i = 0
        line_am = len(lines)
        while i < line_am:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            consumed_lines = 0
            top_level = self.TOP_LEVEL_RE.match(line)
            if top_level:
                root = self._canonicalize(top_level.group(1))
                if not root:
                    i += 1
                    continue
                root_details = top_level.group(2).strip()
                details, consumed_lines = self._extract_details(root,
                                                                root_details,
                                                                lines[i + 1:])
                contents[root] = details
            i += consumed_lines + 1
        return contents


def qemu_img_info(path):
    """Return a object containing the parsed output from qemu-img info."""
    cmd = ('env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info', path)
    if os.name == 'nt':
        cmd = cmd[3:]
    out, err = utils.execute(*cmd, run_as_root=True)
    return QemuImgInfo(out)


def convert_image(source, dest, out_format):
    """Convert image to other format"""
    cmd = ('qemu-img', 'convert', '-O', out_format, source, dest)
    utils.execute(*cmd, run_as_root=True)


def resize_image(source, size):
    """Changes the virtual size of the image."""
    cmd = ('qemu-img', 'resize', source, '%sG' % size)
    utils.execute(*cmd, run_as_root=False)


def fetch(context, image_service, image_id, path, _user_id, _project_id):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    with fileutils.remove_path_on_error(path):
        with open(path, "wb") as image_file:
            image_service.download(context, image_id, image_file)


def fetch_verify_image(context, image_service, image_id, dest,
                       user_id=None, project_id=None):
    fetch(context, image_service, image_id, dest,
          None, None)

    with fileutils.remove_path_on_error(dest):
        data = qemu_img_info(dest)
        fmt = data.file_format
        if fmt is None:
            raise exception.ImageUnacceptable(
                reason=_("'qemu-img info' parsing failed."),
                image_id=image_id)

        backing_file = data.backing_file
        if backing_file is not None:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=(_("fmt=%(fmt)s backed by: %(backing_file)s") %
                        {'fmt': fmt, 'backing_file': backing_file}))


def fetch_to_vhd(context, image_service,
                 image_id, dest,
                 user_id=None, project_id=None):
    fetch_to_volume_format(context, image_service, image_id, dest, 'vpc',
                           user_id, project_id)


def fetch_to_raw(context, image_service,
                 image_id, dest,
                 user_id=None, project_id=None):
    fetch_to_volume_format(context, image_service, image_id, dest, 'raw',
                           user_id, project_id)


def fetch_to_volume_format(context, image_service,
                           image_id, dest, volume_format,
                           user_id=None, project_id=None):
    if (CONF.image_conversion_dir and not
            os.path.exists(CONF.image_conversion_dir)):
        os.makedirs(CONF.image_conversion_dir)

    # NOTE(avishay): I'm not crazy about creating temp files which may be
    # large and cause disk full errors which would confuse users.
    # Unfortunately it seems that you can't pipe to 'qemu-img convert' because
    # it seeks. Maybe we can think of something for a future version.
    with temporary_file() as tmp:
        fetch(context, image_service, image_id, tmp, user_id, project_id)

        if is_xenserver_image(context, image_service, image_id):
            replace_xenserver_image_with_coalesced_vhd(tmp)

        data = qemu_img_info(tmp)
        fmt = data.file_format
        if fmt is None:
            raise exception.ImageUnacceptable(
                reason=_("'qemu-img info' parsing failed."),
                image_id=image_id)

        backing_file = data.backing_file
        if backing_file is not None:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("fmt=%(fmt)s backed by:"
                         "%(backing_file)s") % {
                             'fmt': fmt,
                             'backing_file': backing_file,
                         })

        # NOTE(jdg): I'm using qemu-img convert to write
        # to the volume regardless if it *needs* conversion or not
        # TODO(avishay): We can speed this up by checking if the image is raw
        # and if so, writing directly to the device. However, we need to keep
        # check via 'qemu-img info' that what we copied was in fact a raw
        # image and not a different format with a backing file, which may be
        # malicious.
        LOG.debug("%s was %s, converting to %s " % (image_id, fmt,
                                                    volume_format))
        convert_image(tmp, dest, volume_format)

        data = qemu_img_info(dest)
        if data.file_format != volume_format:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("Converted to %(vol_format)s, but format is "
                         "now %(file_format)s") % {'vol_format': volume_format,
                                                   'file_format': data.
                                                   file_format})


def upload_volume(context, image_service, image_meta, volume_path,
                  volume_format='raw'):
    image_id = image_meta['id']
    if (image_meta['disk_format'] == volume_format):
        LOG.debug("%s was %s, no need to convert to %s" %
                  (image_id, volume_format, image_meta['disk_format']))
        if os.name == 'nt':
            with fileutils.file_open(volume_path) as image_file:
                image_service.update(context, image_id, {}, image_file)
        with utils.temporary_chown(volume_path):
            with fileutils.file_open(volume_path) as image_file:
                image_service.update(context, image_id, {}, image_file)
        return

    if (CONF.image_conversion_dir and not
            os.path.exists(CONF.image_conversion_dir)):
        os.makedirs(CONF.image_conversion_dir)

    fd, tmp = tempfile.mkstemp(dir=CONF.image_conversion_dir)
    os.close(fd)
    with fileutils.remove_path_on_error(tmp):
        LOG.debug("%s was %s, converting to %s" %
                  (image_id, volume_format, image_meta['disk_format']))
        convert_image(volume_path, tmp, image_meta['disk_format'])

        data = qemu_img_info(tmp)
        if data.file_format != image_meta['disk_format']:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("Converted to %(f1)s, but format is now %(f2)s") %
                {'f1': image_meta['disk_format'], 'f2': data.file_format})

        with fileutils.file_open(tmp) as image_file:
            image_service.update(context, image_id, {}, image_file)
        fileutils.delete_if_exists(tmp)


def is_xenserver_image(context, image_service, image_id):
    image_meta = image_service.show(context, image_id)
    return is_xenserver_format(image_meta)


def is_xenserver_format(image_meta):
    return (
        image_meta['disk_format'] == 'vhd'
        and image_meta['container_format'] == 'ovf'
    )


def file_exist(fpath):
    return os.path.exists(fpath)


def set_vhd_parent(vhd_path, parentpath):
    utils.execute('vhd-util', 'modify', '-n', vhd_path, '-p', parentpath)


def extract_targz(archive_name, target):
    utils.execute('tar', '-xzf', archive_name, '-C', target)


def fix_vhd_chain(vhd_chain):
    for child, parent in zip(vhd_chain[:-1], vhd_chain[1:]):
        set_vhd_parent(child, parent)


def get_vhd_size(vhd_path):
    out, err = utils.execute('vhd-util', 'query', '-n', vhd_path, '-v')
    return int(out)


def resize_vhd(vhd_path, size, journal):
    utils.execute(
        'vhd-util', 'resize', '-n', vhd_path, '-s', '%d' % size, '-j', journal)


def coalesce_vhd(vhd_path):
    utils.execute(
        'vhd-util', 'coalesce', '-n', vhd_path)


def create_temporary_file():
    fd, tmp = tempfile.mkstemp(dir=CONF.image_conversion_dir)
    os.close(fd)
    return tmp


def rename_file(src, dst):
    os.rename(src, dst)


@contextlib.contextmanager
def temporary_file():
    try:
        tmp = create_temporary_file()
        yield tmp
    finally:
        fileutils.delete_if_exists(tmp)


def temporary_dir():
    return utils.tempdir(dir=CONF.image_conversion_dir)


def coalesce_chain(vhd_chain):
    for child, parent in zip(vhd_chain[:-1], vhd_chain[1:]):
        with temporary_dir() as directory_for_journal:
            size = get_vhd_size(child)
            journal_file = os.path.join(
                directory_for_journal, 'vhd-util-resize-journal')
            resize_vhd(parent, size, journal_file)
            coalesce_vhd(child)

    return vhd_chain[-1]


def discover_vhd_chain(directory):
    counter = 0
    chain = []

    while True:
        fpath = os.path.join(directory, '%d.vhd' % counter)
        if file_exist(fpath):
            chain.append(fpath)
        else:
            break
        counter += 1

    return chain


def replace_xenserver_image_with_coalesced_vhd(image_file):
    with temporary_dir() as tempdir:
        extract_targz(image_file, tempdir)
        chain = discover_vhd_chain(tempdir)
        fix_vhd_chain(chain)
        coalesced = coalesce_chain(chain)
        fileutils.delete_if_exists(image_file)
        rename_file(coalesced, image_file)
