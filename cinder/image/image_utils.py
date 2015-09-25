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
we should look at maybe pushing this up to Oslo
"""


import contextlib
import math
import os
import re
import tempfile

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder.openstack.common import imageutils
from cinder import utils
from cinder.volume import throttling
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

image_helper_opts = [cfg.StrOpt('image_conversion_dir',
                                default='$state_path/conversion',
                                help='Directory used for temporary storage '
                                'during image conversion'), ]

CONF = cfg.CONF
CONF.register_opts(image_helper_opts)


def qemu_img_info(path, run_as_root=True):
    """Return a object containing the parsed output from qemu-img info."""
    cmd = ('env', 'LC_ALL=C', 'qemu-img', 'info', path)
    if os.name == 'nt':
        cmd = cmd[2:]
    out, _err = utils.execute(*cmd, run_as_root=run_as_root)
    return imageutils.QemuImgInfo(out)


def get_qemu_img_version():
    info = utils.execute('qemu-img', '--help', check_exit_code=False)[0]
    pattern = r"qemu-img version ([0-9\.]*)"
    version = re.match(pattern, info)
    if not version:
        LOG.warning(_LW("qemu-img is not installed."))
        return None
    return _get_version_from_string(version.groups()[0])


def _get_version_from_string(version_string):
    return [int(x) for x in version_string.split('.')]


def check_qemu_img_version(minimum_version):
    qemu_version = get_qemu_img_version()
    if (qemu_version is None
       or qemu_version < _get_version_from_string(minimum_version)):
        if qemu_version:
            current_version = '.'.join((str(element)
                                       for element in qemu_version))
        else:
            current_version = None

        _msg = _('qemu-img %(minimum_version)s or later is required by '
                 'this volume driver. Current qemu-img version: '
                 '%(current_version)s') % {'minimum_version': minimum_version,
                                           'current_version': current_version}
        raise exception.VolumeBackendAPIException(data=_msg)


def _convert_image(prefix, source, dest, out_format, run_as_root=True):
    """Convert image to other format."""

    cmd = prefix + ('qemu-img', 'convert',
                    '-O', out_format, source, dest)

    # Check whether O_DIRECT is supported and set '-t none' if it is
    # This is needed to ensure that all data hit the device before
    # it gets unmapped remotely from the host for some backends
    # Reference Bug: #1363016

    # NOTE(jdg): In the case of file devices qemu does the
    # flush properly and more efficiently than would be done
    # setting O_DIRECT, so check for that and skip the
    # setting for non BLK devs
    if (utils.is_blk_device(dest) and
            volume_utils.check_for_odirect_support(source,
                                                   dest,
                                                   'oflag=direct')):
        cmd = prefix + ('qemu-img', 'convert',
                        '-t', 'none',
                        '-O', out_format, source, dest)

    start_time = timeutils.utcnow()
    utils.execute(*cmd, run_as_root=run_as_root)
    duration = timeutils.delta_seconds(start_time, timeutils.utcnow())

    # NOTE(jdg): use a default of 1, mostly for unit test, but in
    # some incredible event this is 0 (cirros image?) don't barf
    if duration < 1:
        duration = 1
    fsz_mb = os.stat(source).st_size / units.Mi
    mbps = (fsz_mb / duration)
    msg = ("Image conversion details: src %(src)s, size %(sz).2f MB, "
           "duration %(duration).2f sec, destination %(dest)s")
    LOG.debug(msg, {"src": source,
                    "sz": fsz_mb,
                    "duration": duration,
                    "dest": dest})

    msg = _LI("Converted %(sz).2f MB image at %(mbps).2f MB/s")
    LOG.info(msg, {"sz": fsz_mb, "mbps": mbps})


def convert_image(source, dest, out_format, run_as_root=True, throttle=None):
    if not throttle:
        throttle = throttling.Throttle.get_default()
    with throttle.subcommand(source, dest) as throttle_cmd:
        _convert_image(tuple(throttle_cmd['prefix']),
                       source, dest,
                       out_format, run_as_root=run_as_root)


def resize_image(source, size, run_as_root=False):
    """Changes the virtual size of the image."""
    cmd = ('qemu-img', 'resize', source, '%sG' % size)
    utils.execute(*cmd, run_as_root=run_as_root)


def fetch(context, image_service, image_id, path, _user_id, _project_id):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    start_time = timeutils.utcnow()
    with fileutils.remove_path_on_error(path):
        with open(path, "wb") as image_file:
            image_service.download(context, image_id, image_file)
    duration = timeutils.delta_seconds(start_time, timeutils.utcnow())

    # NOTE(jdg): use a default of 1, mostly for unit test, but in
    # some incredible event this is 0 (cirros image?) don't barf
    if duration < 1:
        duration = 1
    fsz_mb = os.stat(image_file.name).st_size / units.Mi
    mbps = (fsz_mb / duration)
    msg = ("Image fetch details: dest %(dest)s, size %(sz).2f MB, "
           "duration %(duration).2f sec")
    LOG.debug(msg, {"dest": image_file.name,
                    "sz": fsz_mb,
                    "duration": duration})
    msg = _LI("Image download %(sz).2f MB at %(mbps).2f MB/s")
    LOG.info(msg, {"sz": fsz_mb, "mbps": mbps})


def fetch_verify_image(context, image_service, image_id, dest,
                       user_id=None, project_id=None, size=None,
                       run_as_root=True):
    fetch(context, image_service, image_id, dest,
          None, None)

    with fileutils.remove_path_on_error(dest):
        data = qemu_img_info(dest, run_as_root=run_as_root)
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

        # NOTE(xqueralt): If the image virtual size doesn't fit in the
        # requested volume there is no point on resizing it because it will
        # generate an unusable image.
        if size is not None and data.virtual_size > size:
            params = {'image_size': data.virtual_size, 'volume_size': size}
            reason = _("Size is %(image_size)dGB and doesn't fit in a "
                       "volume of size %(volume_size)dGB.") % params
            raise exception.ImageUnacceptable(image_id=image_id, reason=reason)


def fetch_to_vhd(context, image_service,
                 image_id, dest, blocksize,
                 user_id=None, project_id=None, run_as_root=True):
    fetch_to_volume_format(context, image_service, image_id, dest, 'vpc',
                           blocksize, user_id, project_id,
                           run_as_root=run_as_root)


def fetch_to_raw(context, image_service,
                 image_id, dest, blocksize,
                 user_id=None, project_id=None, size=None, run_as_root=True):
    fetch_to_volume_format(context, image_service, image_id, dest, 'raw',
                           blocksize, user_id, project_id, size,
                           run_as_root=run_as_root)


def fetch_to_volume_format(context, image_service,
                           image_id, dest, volume_format, blocksize,
                           user_id=None, project_id=None, size=None,
                           run_as_root=True):
    qemu_img = True
    image_meta = image_service.show(context, image_id)

    # NOTE(avishay): I'm not crazy about creating temp files which may be
    # large and cause disk full errors which would confuse users.
    # Unfortunately it seems that you can't pipe to 'qemu-img convert' because
    # it seeks. Maybe we can think of something for a future version.
    with temporary_file() as tmp:
        # We may be on a system that doesn't have qemu-img installed.  That
        # is ok if we are working with a RAW image.  This logic checks to see
        # if qemu-img is installed.  If not we make sure the image is RAW and
        # throw an exception if not.  Otherwise we stop before needing
        # qemu-img.  Systems with qemu-img will always progress through the
        # whole function.
        try:
            # Use the empty tmp file to make sure qemu_img_info works.
            qemu_img_info(tmp, run_as_root=run_as_root)
        except processutils.ProcessExecutionError:
            qemu_img = False
            if image_meta:
                if image_meta['disk_format'] != 'raw':
                    raise exception.ImageUnacceptable(
                        reason=_("qemu-img is not installed and image is of "
                                 "type %s.  Only RAW images can be used if "
                                 "qemu-img is not installed.") %
                        image_meta['disk_format'],
                        image_id=image_id)
            else:
                raise exception.ImageUnacceptable(
                    reason=_("qemu-img is not installed and the disk "
                             "format is not specified.  Only RAW images "
                             "can be used if qemu-img is not installed."),
                    image_id=image_id)

        tmp_images = TemporaryImages.for_image_service(image_service)
        tmp_image = tmp_images.get(context, image_id)
        if tmp_image:
            tmp = tmp_image
        else:
            fetch(context, image_service, image_id, tmp, user_id, project_id)

        if is_xenserver_image(context, image_service, image_id):
            replace_xenserver_image_with_coalesced_vhd(tmp)

        if not qemu_img:
            # qemu-img is not installed but we do have a RAW image.  As a
            # result we only need to copy the image to the destination and then
            # return.
            LOG.debug('Copying image from %(tmp)s to volume %(dest)s - '
                      'size: %(size)s', {'tmp': tmp, 'dest': dest,
                                         'size': image_meta['size']})
            image_size_m = math.ceil(image_meta['size'] / units.Mi)
            volume_utils.copy_volume(tmp, dest, image_size_m, blocksize)
            return

        data = qemu_img_info(tmp, run_as_root=run_as_root)
        virt_size = data.virtual_size / units.Gi

        # NOTE(xqueralt): If the image virtual size doesn't fit in the
        # requested volume there is no point on resizing it because it will
        # generate an unusable image.
        if size is not None and virt_size > size:
            params = {'image_size': virt_size, 'volume_size': size}
            reason = _("Size is %(image_size)dGB and doesn't fit in a "
                       "volume of size %(volume_size)dGB.") % params
            raise exception.ImageUnacceptable(image_id=image_id, reason=reason)

        fmt = data.file_format
        if fmt is None:
            raise exception.ImageUnacceptable(
                reason=_("'qemu-img info' parsing failed."),
                image_id=image_id)

        backing_file = data.backing_file
        if backing_file is not None:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("fmt=%(fmt)s backed by:%(backing_file)s")
                % {'fmt': fmt, 'backing_file': backing_file, })

        # NOTE(jdg): I'm using qemu-img convert to write
        # to the volume regardless if it *needs* conversion or not
        # TODO(avishay): We can speed this up by checking if the image is raw
        # and if so, writing directly to the device. However, we need to keep
        # check via 'qemu-img info' that what we copied was in fact a raw
        # image and not a different format with a backing file, which may be
        # malicious.
        LOG.debug("%s was %s, converting to %s ", image_id, fmt, volume_format)
        convert_image(tmp, dest, volume_format,
                      run_as_root=run_as_root)

        data = qemu_img_info(dest, run_as_root=run_as_root)

        if not _validate_file_format(data, volume_format):
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("Converted to %(vol_format)s, but format is "
                         "now %(file_format)s") % {'vol_format': volume_format,
                                                   'file_format': data.
                                                   file_format})


def _validate_file_format(image_data, expected_format):
    if image_data.file_format == expected_format:
        return True
    elif image_data.file_format == 'vpc' and expected_format == 'vhd':
        # qemu-img still uses the legacy 'vpc' name for the vhd format.
        return True
    return False


def upload_volume(context, image_service, image_meta, volume_path,
                  volume_format='raw', run_as_root=True):
    image_id = image_meta['id']
    if (image_meta['disk_format'] == volume_format):
        LOG.debug("%s was %s, no need to convert to %s",
                  image_id, volume_format, image_meta['disk_format'])
        if os.name == 'nt' or os.access(volume_path, os.R_OK):
            with open(volume_path, 'rb') as image_file:
                image_service.update(context, image_id, {}, image_file)
        else:
            with utils.temporary_chown(volume_path):
                with open(volume_path) as image_file:
                    image_service.update(context, image_id, {}, image_file)
        return

    with temporary_file() as tmp:
        LOG.debug("%s was %s, converting to %s",
                  image_id, volume_format, image_meta['disk_format'])

        data = qemu_img_info(volume_path, run_as_root=run_as_root)
        backing_file = data.backing_file
        fmt = data.file_format
        if backing_file is not None:
            # Disallow backing files as a security measure.
            # This prevents a user from writing an image header into a raw
            # volume with a backing file pointing to data they wish to
            # access.
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("fmt=%(fmt)s backed by:%(backing_file)s")
                % {'fmt': fmt, 'backing_file': backing_file})

        convert_image(volume_path, tmp, image_meta['disk_format'],
                      run_as_root=run_as_root)

        data = qemu_img_info(tmp, run_as_root=run_as_root)
        if data.file_format != image_meta['disk_format']:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("Converted to %(f1)s, but format is now %(f2)s") %
                {'f1': image_meta['disk_format'], 'f2': data.file_format})

        with open(tmp, 'rb') as image_file:
            image_service.update(context, image_id, {}, image_file)


def is_xenserver_image(context, image_service, image_id):
    image_meta = image_service.show(context, image_id)
    return is_xenserver_format(image_meta)


def is_xenserver_format(image_meta):
    return (
        image_meta['disk_format'] == 'vhd'
        and image_meta['container_format'] == 'ovf'
    )


def set_vhd_parent(vhd_path, parentpath):
    utils.execute('vhd-util', 'modify', '-n', vhd_path, '-p', parentpath)


def extract_targz(archive_name, target):
    utils.execute('tar', '-xzf', archive_name, '-C', target)


def fix_vhd_chain(vhd_chain):
    for child, parent in zip(vhd_chain[:-1], vhd_chain[1:]):
        set_vhd_parent(child, parent)


def get_vhd_size(vhd_path):
    out, _err = utils.execute('vhd-util', 'query', '-n', vhd_path, '-v')
    return int(out)


def resize_vhd(vhd_path, size, journal):
    utils.execute(
        'vhd-util', 'resize', '-n', vhd_path, '-s', '%d' % size, '-j', journal)


def coalesce_vhd(vhd_path):
    utils.execute(
        'vhd-util', 'coalesce', '-n', vhd_path)


def create_temporary_file(*args, **kwargs):
    if (CONF.image_conversion_dir and not
            os.path.exists(CONF.image_conversion_dir)):
        os.makedirs(CONF.image_conversion_dir)

    fd, tmp = tempfile.mkstemp(dir=CONF.image_conversion_dir, *args, **kwargs)
    os.close(fd)
    return tmp


@contextlib.contextmanager
def temporary_file(*args, **kwargs):
    tmp = None
    try:
        tmp = create_temporary_file(*args, **kwargs)
        yield tmp
    finally:
        if tmp:
            fileutils.delete_if_exists(tmp)


def temporary_dir():
    if (CONF.image_conversion_dir and not
            os.path.exists(CONF.image_conversion_dir)):
        os.makedirs(CONF.image_conversion_dir)

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
        if os.path.exists(fpath):
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
        os.rename(coalesced, image_file)


class TemporaryImages(object):
    """Manage temporarily downloaded images to avoid downloading it twice.

    In the 'with TemporaryImages.fetch(image_service, ctx, image_id) as tmp'
    clause, 'tmp' can be used as the downloaded image path. In addition,
    image_utils.fetch() will use the pre-fetched image by the TemporaryImages.
    This is useful to inspect image contents before conversion.
    """

    def __init__(self, image_service):
        self.temporary_images = {}
        self.image_service = image_service
        image_service.temp_images = self

    @staticmethod
    def for_image_service(image_service):
        instance = image_service.temp_images
        if instance:
            return instance
        return TemporaryImages(image_service)

    @classmethod
    @contextlib.contextmanager
    def fetch(cls, image_service, context, image_id):
        tmp_images = cls.for_image_service(image_service).temporary_images
        with temporary_file() as tmp:
            fetch_verify_image(context, image_service, image_id, tmp)
            user = context.user_id
            if not tmp_images.get(user):
                tmp_images[user] = {}
            tmp_images[user][image_id] = tmp
            LOG.debug("Temporary image %(id)s is fetched for user %(user)s.",
                      {'id': image_id, 'user': user})
            yield tmp
            del tmp_images[user][image_id]
        LOG.debug("Temporary image %(id)s for user %(user)s is deleted.",
                  {'id': image_id, 'user': user})

    def get(self, context, image_id):
        user = context.user_id
        if not self.temporary_images.get(user):
            return None
        return self.temporary_images[user].get(image_id)
