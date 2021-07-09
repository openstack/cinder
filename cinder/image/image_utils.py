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
import errno
import io
import math
import os
import re
import tempfile
from typing import (ContextManager, Dict, Generator,  # noqa: H301
                    List, Optional, Tuple)

import cryptography
from cursive import exception as cursive_exception
from cursive import signature_utils
from eventlet import tpool
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import imageutils
from oslo_utils import timeutils
from oslo_utils import units
import psutil

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.image import accelerator
from cinder.image import glance
from cinder import utils
from cinder.volume import throttling
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

image_opts = [
    cfg.StrOpt('image_conversion_dir',
               default='$state_path/conversion',
               help='Directory used for temporary storage '
               'during image conversion'),
    cfg.BoolOpt('image_compress_on_upload',
                default=True,
                help='When possible, compress images uploaded '
                'to the image service'),
    cfg.IntOpt('image_conversion_cpu_limit',
               default=60,
               help='CPU time limit in seconds to convert the image'),
    cfg.IntOpt('image_conversion_address_space_limit',
               default=1,
               help='Address space limit in gigabytes to convert the image'),
]

CONF = cfg.CONF
CONF.register_opts(image_opts)

QEMU_IMG_LIMITS = processutils.ProcessLimits(
    cpu_time=CONF.image_conversion_cpu_limit,
    address_space=CONF.image_conversion_address_space_limit * units.Gi)


QEMU_IMG_FORMAT_MAP = {
    # Convert formats of Glance images to how they are processed with qemu-img.
    'iso': 'raw',
    'vhd': 'vpc',
    'ploop': 'parallels',
}
QEMU_IMG_FORMAT_MAP_INV = {v: k for k, v in QEMU_IMG_FORMAT_MAP.items()}

QEMU_IMG_VERSION = None
QEMU_IMG_MIN_FORCE_SHARE_VERSION = [2, 10, 0]
QEMU_IMG_MIN_CONVERT_LUKS_VERSION = '2.10'

COMPRESSIBLE_IMAGE_FORMATS = ('qcow2',)


def validate_stores_id(context: context.RequestContext,
                       image_service_store_id: str) -> None:
    image_service = glance.get_default_image_service()
    stores_info = image_service.get_stores(context)['stores']
    for info in stores_info:
        if image_service_store_id == info['id']:
            if info.get('read-only') == "true":
                raise exception.GlanceStoreReadOnly(
                    store_id=image_service_store_id)
            return

    raise exception.GlanceStoreNotFound(store_id=image_service_store_id)


def fixup_disk_format(disk_format: str) -> str:
    """Return the format to be provided to qemu-img convert."""

    return QEMU_IMG_FORMAT_MAP.get(disk_format, disk_format)


def from_qemu_img_disk_format(disk_format: str) -> str:
    """Return the conventional format derived from qemu-img format."""

    return QEMU_IMG_FORMAT_MAP_INV.get(disk_format, disk_format)


def qemu_img_info(path: str,
                  run_as_root: bool = True,
                  force_share: bool = False) -> imageutils.QemuImgInfo:
    """Return an object containing the parsed output from qemu-img info."""
    cmd = ['env', 'LC_ALL=C', 'qemu-img', 'info']
    if force_share:
        if qemu_img_supports_force_share():
            cmd.append('--force-share')
        else:
            msg = _("qemu-img --force-share requested, but "
                    "qemu-img does not support this parameter")
            LOG.warning(msg)
    cmd.append(path)

    if os.name == 'nt':
        cmd = cmd[2:]
    out, _err = utils.execute(*cmd, run_as_root=run_as_root,
                              prlimit=QEMU_IMG_LIMITS)
    info = imageutils.QemuImgInfo(out)

    # From Cinder's point of view, any 'luks' formatted images
    # should be treated as 'raw'.
    if info.file_format == 'luks':
        info.file_format = 'raw'

    return info


def get_qemu_img_version() -> Optional[List[int]]:
    """The qemu-img version will be cached until the process is restarted."""

    global QEMU_IMG_VERSION
    if QEMU_IMG_VERSION is not None:
        return QEMU_IMG_VERSION

    info = utils.execute('qemu-img', '--version', check_exit_code=False)[0]
    pattern = r"qemu-img version ([0-9\.]*)"
    version = re.match(pattern, info)
    if not version:
        LOG.warning("qemu-img is not installed.")
        return None
    QEMU_IMG_VERSION = _get_version_from_string(version.groups()[0])
    return QEMU_IMG_VERSION


def qemu_img_supports_force_share() -> bool:
    ver = get_qemu_img_version()
    if ver is None:
        return False
    else:
        return ver >= QEMU_IMG_MIN_FORCE_SHARE_VERSION


def _get_qemu_convert_luks_cmd(src: str,
                               dest: str,
                               out_format: str,
                               src_format: Optional[str] = None,
                               out_subformat: Optional[str] = None,
                               cache_mode: Optional[str] = None,
                               prefix: tuple = None,
                               cipher_spec: Optional[dict] = None,
                               passphrase_file: Optional[str] = None,
                               src_passphrase_file: str = None) -> List[str]:

    cmd = ['qemu-img', 'convert']

    if prefix:
        cmd = list(prefix) + cmd

    if cache_mode:
        cmd += ('-t', cache_mode)

    obj1 = ['--object',
            'secret,id=sec1,format=raw,file=%s' % src_passphrase_file]
    obj2 = ['--object',
            'secret,id=sec2,format=raw,file=%s' % passphrase_file]

    src_opts = 'encrypt.format=luks,encrypt.key-secret=sec1,' \
               'file.filename=%s' % src

    image_opts = ['--image-opts', src_opts]
    output_opts = ['-O', 'luks', '-o', 'key-secret=sec2', dest]

    command = cmd + obj1 + obj2 + image_opts + output_opts
    return command


def _get_qemu_convert_cmd(src: str,
                          dest: str,
                          out_format: str,
                          src_format: str = None,
                          out_subformat: str = None,
                          cache_mode: str = None,
                          prefix: tuple = None,
                          cipher_spec: dict = None,
                          passphrase_file: str = None,
                          compress: bool = False,
                          src_passphrase_file: str = None) -> List[str]:

    if src_passphrase_file is not None:
        if passphrase_file is None:
            message = _("Can't create unencrypted volume %(format)s "
                        "from an encrypted source volume."
                        ) % {'format': out_format}
            LOG.error(message)
            # TODO(enriquetaso): handle encrypted->unencrypted
            raise exception.NotSupportedOperation(operation=message)
        return _get_qemu_convert_luks_cmd(
            src,
            dest,
            out_format,
            src_format=src_format,
            out_subformat=out_subformat,
            cache_mode=cache_mode,
            prefix=None,
            cipher_spec=cipher_spec,
            passphrase_file=passphrase_file,
            src_passphrase_file=src_passphrase_file)

    if out_format == 'vhd':
        # qemu-img still uses the legacy vpc name
        out_format = 'vpc'

    cmd = ['qemu-img', 'convert', '-O', out_format]

    if prefix:
        cmd = list(prefix) + cmd

    if cache_mode:
        cmd += ('-t', cache_mode)

    if CONF.image_compress_on_upload and compress:
        if out_format in COMPRESSIBLE_IMAGE_FORMATS:
            cmd += ('-c',)

    if out_subformat:
        cmd += ('-o', 'subformat=%s' % out_subformat)

    # AMI images can be raw or qcow2 but qemu-img doesn't accept "ami" as
    # an image format, so we use automatic detection.
    # TODO(geguileo): This fixes unencrypted AMI image case, but we need to
    # fix the encrypted case.

    if (src_format or '').lower() not in ('', 'ami'):
        assert src_format is not None
        cmd += ['-f', src_format]  # prevent detection of format

    # NOTE(lyarwood): When converting to LUKS add the cipher spec if present
    # and create a secret for the passphrase, written to a temp file
    if out_format == 'luks':
        check_qemu_img_version(QEMU_IMG_MIN_CONVERT_LUKS_VERSION)
        if cipher_spec:
            cmd += ('-o', 'cipher-alg=%s,cipher-mode=%s,ivgen-alg=%s' %
                    (cipher_spec['cipher_alg'], cipher_spec['cipher_mode'],
                     cipher_spec['ivgen_alg']))
        cmd += ('--object',
                'secret,id=luks_sec,format=raw,file=%s' % passphrase_file,
                '-o', 'key-secret=luks_sec')

    cmd += [src, dest]

    return cmd


def _get_version_from_string(version_string: str) -> List[int]:
    return [int(x) for x in version_string.split('.')]


def check_qemu_img_version(minimum_version: str) -> None:
    qemu_version = get_qemu_img_version()
    if (qemu_version is None
       or qemu_version < _get_version_from_string(minimum_version)):
        current_version: Optional[str]
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


def _convert_image(prefix: tuple,
                   source: str,
                   dest: str,
                   out_format: str,
                   out_subformat: str = None,
                   src_format: str = None,
                   run_as_root: bool = True,
                   cipher_spec: dict = None,
                   passphrase_file: str = None,
                   compress: bool = False,
                   src_passphrase_file: str = None) -> None:
    """Convert image to other format.

    NOTE: If the qemu-img convert command fails and this function raises an
    exception, a non-empty dest file may be left in the filesystem.
    It is the responsibility of the caller to decide what to do with this file.

    :param prefix: command prefix, i.e. cgexec for throttling
    :param source: source filename
    :param dest: destination filename
    :param out_format: output image format of qemu-img
    :param out_subformat: output image subformat
    :param src_format: source image format
    :param run_as_root: run qemu-img as root
    :param cipher_spec: encryption details
    :param passphrase_file: filename containing luks passphrase
    :param compress: compress w/ qemu-img when possible (best effort)
    :param src_passphrase_file: filename containing source volume's
                                luks passphrase
    """

    # Check whether O_DIRECT is supported and set '-t none' if it is
    # This is needed to ensure that all data hit the device before
    # it gets unmapped remotely from the host for some backends
    # Reference Bug: #1363016

    # NOTE(jdg): In the case of file devices qemu does the
    # flush properly and more efficiently than would be done
    # setting O_DIRECT, so check for that and skip the
    # setting for non BLK devs
    cache_mode: Optional[str]
    if (utils.is_blk_device(dest) and
            volume_utils.check_for_odirect_support(source,
                                                   dest,
                                                   'oflag=direct')):
        cache_mode = 'none'
    else:
        # use default
        cache_mode = None

    cmd = _get_qemu_convert_cmd(source, dest,
                                out_format=out_format,
                                src_format=src_format,
                                out_subformat=out_subformat,
                                cache_mode=cache_mode,
                                prefix=prefix,
                                cipher_spec=cipher_spec,
                                passphrase_file=passphrase_file,
                                compress=compress,
                                src_passphrase_file=src_passphrase_file)

    start_time = timeutils.utcnow()

    # If there is not enough space on the conversion partition, include
    # the partitions's name in the error message.
    try:
        utils.execute(*cmd, run_as_root=run_as_root)
    except processutils.ProcessExecutionError as ex:
        if "No space left" in ex.stderr and CONF.image_conversion_dir in dest:
            conversion_dir = CONF.image_conversion_dir
            while not os.path.ismount(conversion_dir):
                conversion_dir = os.path.dirname(conversion_dir)

            message = _("Insufficient free space on %(location)s for image "
                        "conversion.") % {'location': conversion_dir}
            LOG.error(message)

        raise
    duration = timeutils.delta_seconds(start_time, timeutils.utcnow())

    # NOTE(jdg): use a default of 1, mostly for unit test, but in
    # some incredible event this is 0 (cirros image?) don't barf
    if duration < 1:
        duration = 1
    try:
        image_size = qemu_img_info(source,
                                   run_as_root=run_as_root).virtual_size
    except ValueError as e:
        msg = ("The image was successfully converted, but image size "
               "is unavailable. src %(src)s, dest %(dest)s. %(error)s")
        LOG.info(msg, {"src": source,
                       "dest": dest,
                       "error": e})
        return

    fsz_mb = image_size / units.Mi
    mbps = (fsz_mb / duration)
    msg = ("Image conversion details: src %(src)s, size %(sz).2f MB, "
           "duration %(duration).2f sec, destination %(dest)s")
    LOG.debug(msg, {"src": source,
                    "sz": fsz_mb,
                    "duration": duration,
                    "dest": dest})

    msg = "Converted %(sz).2f MB image at %(mbps).2f MB/s"
    LOG.info(msg, {"sz": fsz_mb, "mbps": mbps})


def convert_image(source: str,
                  dest: str,
                  out_format: str,
                  out_subformat: str = None,
                  src_format: str = None,
                  run_as_root: bool = True,
                  throttle=None,
                  cipher_spec: dict = None,
                  passphrase_file: str = None,
                  compress: bool = False,
                  src_passphrase_file: str = None) -> None:
    if not throttle:
        throttle = throttling.Throttle.get_default()
    with throttle.subcommand(source, dest) as throttle_cmd:
        _convert_image(tuple(throttle_cmd['prefix']),
                       source, dest,
                       out_format,
                       out_subformat=out_subformat,
                       src_format=src_format,
                       run_as_root=run_as_root,
                       cipher_spec=cipher_spec,
                       passphrase_file=passphrase_file,
                       compress=compress,
                       src_passphrase_file=src_passphrase_file)


def resize_image(source: str,
                 size: int,
                 run_as_root: bool = False,
                 file_format: str = None) -> None:
    """Changes the virtual size of the image."""
    cmd: Tuple[str, ...]
    if file_format:
        cmd = ('qemu-img', 'resize', '-f', file_format, source, '%sG' % size)
    else:
        cmd = ('qemu-img', 'resize', source, '%sG' % size)
    utils.execute(*cmd, run_as_root=run_as_root)


def _verify_image(img_file: io.RawIOBase, verifier) -> None:
    # This methods must be called from a native thread, as the file I/O may
    # not yield to other greenthread in some cases, and since the update and
    # verify operations are CPU bound there would not be any yielding either,
    # which could lead to thread starvation.
    while True:
        chunk = img_file.read(1024)
        if not chunk:
            break
        verifier.update(chunk)
    verifier.verify()


def verify_glance_image_signature(context: context.RequestContext,
                                  image_service: glance.GlanceImageService,
                                  image_id: str,
                                  path: str) -> bool:
    verifier = None
    image_meta = image_service.show(context, image_id)
    image_properties = image_meta.get('properties', {})
    img_signature = image_properties.get('img_signature')
    img_sig_hash_method = image_properties.get('img_signature_hash_method')
    img_sig_cert_uuid = image_properties.get('img_signature_certificate_uuid')
    img_sig_key_type = image_properties.get('img_signature_key_type')
    if all(m is None for m in [img_signature,
                               img_sig_cert_uuid,
                               img_sig_hash_method,
                               img_sig_key_type]):
        # NOTE(tommylikehu): We won't verify the image signature
        # if none of the signature metadata presents.
        return False
    if any(m is None for m in [img_signature,
                               img_sig_cert_uuid,
                               img_sig_hash_method,
                               img_sig_key_type]):
        LOG.error('Image signature metadata for image %s is '
                  'incomplete.', image_id)
        raise exception.InvalidSignatureImage(image_id=image_id)

    try:
        verifier = signature_utils.get_verifier(
            context=context,
            img_signature_certificate_uuid=img_sig_cert_uuid,
            img_signature_hash_method=img_sig_hash_method,
            img_signature=img_signature,
            img_signature_key_type=img_sig_key_type,
        )
    except cursive_exception.SignatureVerificationError:
        message = _('Failed to get verifier for image: %s') % image_id
        LOG.error(message)
        raise exception.ImageSignatureVerificationException(
            reason=message)
    if verifier:
        with fileutils.remove_path_on_error(path):
            with open(path, "rb") as tem_file:
                try:
                    tpool.execute(_verify_image, tem_file, verifier)
                    LOG.info('Image signature verification succeeded '
                             'for image: %s', image_id)
                    return True
                except cryptography.exceptions.InvalidSignature:
                    message = _('Image signature verification '
                                'failed for image: %s') % image_id
                    LOG.error(message)
                    raise exception.ImageSignatureVerificationException(
                        reason=message)
                except Exception as ex:
                    message = _('Failed to verify signature for '
                                'image: %(image)s due to '
                                'error: %(error)s ') % {'image': image_id,
                                                        'error': ex}
                    LOG.error(message)
                    raise exception.ImageSignatureVerificationException(
                        reason=message)
    return False


def fetch(context: context.RequestContext,
          image_service: glance.GlanceImageService,
          image_id: str,
          path: str,
          _user_id,
          _project_id) -> None:
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    start_time = timeutils.utcnow()
    with fileutils.remove_path_on_error(path):
        with open(path, "wb") as image_file:
            try:
                image_service.download(context, image_id,
                                       tpool.Proxy(image_file))
            except IOError as e:
                if e.errno == errno.ENOSPC:
                    params = {'path': os.path.dirname(path),
                              'image': image_id}
                    reason = _("No space left in image_conversion_dir "
                               "path (%(path)s) while fetching "
                               "image %(image)s.") % params
                    LOG.exception(reason)
                    raise exception.ImageTooBig(image_id=image_id,
                                                reason=reason)

                reason = ("IOError: %(errno)s %(strerror)s" %
                          {'errno': e.errno, 'strerror': e.strerror})
                LOG.error(reason)
                raise exception.ImageDownloadFailed(image_href=image_id,
                                                    reason=reason)

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
    msg = "Image download %(sz).2f MB at %(mbps).2f MB/s"
    LOG.info(msg, {"sz": fsz_mb, "mbps": mbps})


def get_qemu_data(image_id: str,
                  has_meta: bool,
                  disk_format_raw: bool,
                  dest: str,
                  run_as_root: bool,
                  force_share: bool = False) -> imageutils.QemuImgInfo:
    # We may be on a system that doesn't have qemu-img installed.  That
    # is ok if we are working with a RAW image.  This logic checks to see
    # if qemu-img is installed.  If not we make sure the image is RAW and
    # throw an exception if not.  Otherwise we stop before needing
    # qemu-img.  Systems with qemu-img will always progress through the
    # whole function.
    try:
        # Use the empty tmp file to make sure qemu_img_info works.
        data = qemu_img_info(dest,
                             run_as_root=run_as_root,
                             force_share=force_share)
    # There are a lot of cases that can cause a process execution
    # error, but until we do more work to separate out the various
    # cases we'll keep the general catch here
    except processutils.ProcessExecutionError:
        data = None
        if has_meta:
            if not disk_format_raw:
                raise exception.ImageUnacceptable(
                    reason=_("qemu-img is not installed and image is of "
                             "type %s.  Only RAW images can be used if "
                             "qemu-img is not installed.") %
                    disk_format_raw,
                    image_id=image_id)
        else:
            raise exception.ImageUnacceptable(
                reason=_("qemu-img is not installed and the disk "
                         "format is not specified.  Only RAW images "
                         "can be used if qemu-img is not installed."),
                image_id=image_id)
    return data


def fetch_verify_image(context: context.RequestContext,
                       image_service: glance.GlanceImageService,
                       image_id: str,
                       dest: str) -> None:
    fetch(context, image_service, image_id, dest,
          None, None)
    image_meta = image_service.show(context, image_id)

    with fileutils.remove_path_on_error(dest):
        has_meta = False if not image_meta else True
        try:
            format_raw = True if image_meta['disk_format'] == 'raw' else False
        except TypeError:
            format_raw = False
        data = get_qemu_data(image_id, has_meta, format_raw,
                             dest, True)
        # We can only really do verification of the image if we have
        # qemu data to use
        if data is not None:
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


def fetch_to_vhd(context: context.RequestContext,
                 image_service: glance.GlanceImageService,
                 image_id: str,
                 dest: str,
                 blocksize: int,
                 volume_subformat: Optional[str] = None,
                 user_id: Optional[str] = None,
                 project_id: Optional[str] = None,
                 run_as_root: bool = True) -> None:
    fetch_to_volume_format(context, image_service, image_id, dest, 'vpc',
                           blocksize, volume_subformat=volume_subformat,
                           user_id=user_id, project_id=project_id,
                           run_as_root=run_as_root)


def fetch_to_raw(context: context.RequestContext,
                 image_service: glance.GlanceImageService,
                 image_id: str,
                 dest: str,
                 blocksize: int,
                 user_id: Optional[str] = None,
                 project_id: Optional[str] = None,
                 size: Optional[int] = None,
                 run_as_root: bool = True) -> None:
    fetch_to_volume_format(context, image_service, image_id, dest, 'raw',
                           blocksize, user_id=user_id, project_id=project_id,
                           size=size, run_as_root=run_as_root)


def fetch_to_volume_format(context: context.RequestContext,
                           image_service: glance.GlanceImageService,
                           image_id: str,
                           dest: str,
                           volume_format: str,
                           blocksize: int,
                           volume_subformat: Optional[str] = None,
                           user_id: Optional[str] = None,
                           project_id: Optional[str] = None,
                           size: Optional[int] = None,
                           run_as_root: bool = True) -> None:
    qemu_img = True
    image_meta = image_service.show(context, image_id)

    allow_image_compression = CONF.allow_compression_on_image_upload
    if image_meta and (image_meta.get('container_format') == 'compressed'):
        if allow_image_compression is False:
            compression_param = {'container_format':
                                 image_meta.get('container_format')}
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("Image compression disallowed, "
                         "but container_format is "
                         "%(container_format)s.") % compression_param)

    # NOTE(avishay): I'm not crazy about creating temp files which may be
    # large and cause disk full errors which would confuse users.
    # Unfortunately it seems that you can't pipe to 'qemu-img convert' because
    # it seeks. Maybe we can think of something for a future version.
    with temporary_file(prefix='image_download_%s_' % image_id) as tmp:
        has_meta = False if not image_meta else True
        try:
            format_raw = True if image_meta['disk_format'] == 'raw' else False
        except TypeError:
            format_raw = False
        data = get_qemu_data(image_id, has_meta, format_raw,
                             tmp, run_as_root)
        if data is None:
            qemu_img = False

        tmp_images = TemporaryImages.for_image_service(image_service)
        tmp_image = tmp_images.get(context, image_id)
        if tmp_image:
            tmp = tmp_image
        else:
            fetch(context, image_service, image_id, tmp, user_id, project_id)

        if is_xenserver_format(image_meta):
            replace_xenserver_image_with_coalesced_vhd(tmp)

        if not qemu_img:
            # qemu-img is not installed but we do have a RAW image.  As a
            # result we only need to copy the image to the destination and then
            # return.
            LOG.debug('Copying image from %(tmp)s to volume %(dest)s - '
                      'size: %(size)s', {'tmp': tmp, 'dest': dest,
                                         'size': image_meta['size']})
            image_size_m = math.ceil(float(image_meta['size']) / units.Mi)
            volume_utils.copy_volume(tmp, dest, image_size_m, blocksize)
            return

        data = qemu_img_info(tmp, run_as_root=run_as_root)

        # NOTE(xqueralt): If the image virtual size doesn't fit in the
        # requested volume there is no point on resizing it because it will
        # generate an unusable image.
        if size is not None:
            check_virtual_size(data.virtual_size, size, image_id)

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

        # NOTE(ZhengMa): This is used to do image decompression on image
        # downloading with 'compressed' container_format. It is a
        # transparent level between original image downloaded from
        # Glance and Cinder image service. So the source file path is
        # the same with destination file path.
        if image_meta.get('container_format') == 'compressed':
            LOG.debug("Found image with compressed container format")
            if not accelerator.is_gzip_compressed(tmp):
                raise exception.ImageUnacceptable(
                    image_id=image_id,
                    reason=_("Unsupported compressed image format found. "
                             "Only gzip is supported currently"))
            accel = accelerator.ImageAccel(tmp, tmp)
            accel.decompress_img(run_as_root=run_as_root)

        # NOTE(jdg): I'm using qemu-img convert to write
        # to the volume regardless if it *needs* conversion or not
        # TODO(avishay): We can speed this up by checking if the image is raw
        # and if so, writing directly to the device. However, we need to keep
        # check via 'qemu-img info' that what we copied was in fact a raw
        # image and not a different format with a backing file, which may be
        # malicious.
        disk_format = fixup_disk_format(image_meta['disk_format'])
        LOG.debug("%s was %s, converting to %s", image_id, fmt, volume_format)

        convert_image(tmp, dest, volume_format,
                      out_subformat=volume_subformat,
                      src_format=disk_format,
                      run_as_root=run_as_root)


def upload_volume(context: context.RequestContext,
                  image_service: glance.GlanceImageService,
                  image_meta: dict,
                  volume_path: str,
                  volume_format: str = 'raw',
                  run_as_root: bool = True,
                  compress: bool = True,
                  store_id: str = None,
                  base_image_ref: Optional[str] = None) -> None:
    # NOTE: You probably want to use volume_utils.upload_volume(),
    # not this function.
    image_id = image_meta['id']
    if image_meta.get('container_format') != 'compressed':
        if (image_meta['disk_format'] == volume_format):
            LOG.debug("%s was %s, no need to convert to %s",
                      image_id, volume_format, image_meta['disk_format'])
            if os.name == 'nt' or os.access(volume_path, os.R_OK):
                with open(volume_path, 'rb') as image_file:
                    image_service.update(context, image_id, {},
                                         tpool.Proxy(image_file),
                                         store_id=store_id,
                                         base_image_ref=base_image_ref)
            else:
                with utils.temporary_chown(volume_path):
                    with open(volume_path, 'rb') as image_file:
                        image_service.update(context, image_id, {},
                                             tpool.Proxy(image_file),
                                             store_id=store_id,
                                             base_image_ref=base_image_ref)
            return

    with temporary_file(prefix='vol_upload_') as tmp:
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

        out_format = fixup_disk_format(image_meta['disk_format'])
        convert_image(volume_path, tmp, out_format,
                      run_as_root=run_as_root,
                      compress=compress)

        data = qemu_img_info(tmp, run_as_root=run_as_root)
        if data.file_format != out_format:
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("Converted to %(f1)s, but format is now %(f2)s") %
                {'f1': out_format, 'f2': data.file_format})

        # NOTE(ZhengMa): This is used to do image compression on image
        # uploading with 'compressed' container_format.
        # Compress file 'tmp' in-place
        if image_meta.get('container_format') == 'compressed':
            LOG.debug("Container_format set to 'compressed', compressing "
                      "image before uploading.")
            accel = accelerator.ImageAccel(tmp, tmp)
            accel.compress_img(run_as_root=run_as_root)
        with open(tmp, 'rb') as image_file:
            image_service.update(context, image_id, {},
                                 tpool.Proxy(image_file),
                                 store_id=store_id,
                                 base_image_ref=base_image_ref)


def check_virtual_size(virtual_size: float,
                       volume_size: int,
                       image_id: str) -> int:
    virtual_size = int(math.ceil(float(virtual_size) / units.Gi))

    if virtual_size > volume_size:
        params = {'image_size': virtual_size,
                  'volume_size': volume_size}
        reason = _("Image virtual size is %(image_size)dGB"
                   " and doesn't fit in a volume of size"
                   " %(volume_size)dGB.") % params
        raise exception.ImageUnacceptable(image_id=image_id,
                                          reason=reason)
    return virtual_size


def check_available_space(dest: str, image_size: int, image_id: str) -> None:
    # TODO(e0ne): replace psutil with shutil.disk_usage when we drop
    # Python 2.7 support.
    if not os.path.isdir(dest):
        dest = os.path.dirname(dest)

    free_space = psutil.disk_usage(dest).free
    if free_space <= image_size:
        msg = ('There is no space on %(dest_dir)s to convert image. '
               'Requested: %(image_size)s, available: %(free_space)s.'
               ) % {'dest_dir': dest,
                    'image_size': image_size,
                    'free_space': free_space}
        raise exception.ImageTooBig(image_id=image_id, reason=msg)


def is_xenserver_format(image_meta: dict) -> bool:
    return (
        image_meta['disk_format'] == 'vhd'
        and image_meta['container_format'] == 'ovf'
    )


def set_vhd_parent(vhd_path: str, parentpath: str) -> None:
    utils.execute('vhd-util', 'modify', '-n', vhd_path, '-p', parentpath)


def extract_targz(archive_name: str, target: str) -> None:
    utils.execute('tar', '-xzf', archive_name, '-C', target)


def fix_vhd_chain(vhd_chain: List[str]) -> None:
    for child, parent in zip(vhd_chain[:-1], vhd_chain[1:]):
        set_vhd_parent(child, parent)


def get_vhd_size(vhd_path: str) -> int:
    out, _err = utils.execute('vhd-util', 'query', '-n', vhd_path, '-v')
    return int(out)


def resize_vhd(vhd_path: str, size: int, journal: str) -> None:
    utils.execute(
        'vhd-util', 'resize', '-n', vhd_path, '-s', '%d' % size, '-j', journal)


def coalesce_vhd(vhd_path: str) -> None:
    utils.execute(
        'vhd-util', 'coalesce', '-n', vhd_path)


def create_temporary_file(*args: str, **kwargs: str) -> str:
    fileutils.ensure_tree(CONF.image_conversion_dir)

    fd, tmp = tempfile.mkstemp(dir=CONF.image_conversion_dir,
                               *args, **kwargs)  # type: ignore
    os.close(fd)
    return tmp


def cleanup_temporary_file(backend_name: str) -> None:
    temp_dir = CONF.image_conversion_dir
    if (not temp_dir or not os.path.exists(temp_dir)):
        LOG.debug("Configuration image_conversion_dir is None or the path "
                  "doesn't exist.")
        return
    try:
        # TODO(wanghao): Consider using os.scandir for better performance in
        # future when cinder only supports Python version 3.5+.
        files = os.listdir(CONF.image_conversion_dir)
        # NOTE(wanghao): For multi-backend case, if one backend was slow
        # starting but another backend is up and doing an image conversion,
        # init_host should only clean the tmp files which belongs to its
        # backend.
        for tmp_file in files:
            if tmp_file.endswith(backend_name):
                path = os.path.join(temp_dir, tmp_file)
                os.remove(path)
    except OSError as e:
        LOG.warning("Exception caught while clearing temporary image "
                    "files: %s", e)


@contextlib.contextmanager
def temporary_file(*args: str, **kwargs) -> Generator[str, None, None]:
    tmp = None
    try:
        tmp = create_temporary_file(*args, **kwargs)
        yield tmp
    finally:
        if tmp:
            fileutils.delete_if_exists(tmp)


def temporary_dir() -> ContextManager[str]:
    fileutils.ensure_tree(CONF.image_conversion_dir)

    return utils.tempdir(dir=CONF.image_conversion_dir)


def coalesce_chain(vhd_chain: List[str]) -> str:
    for child, parent in zip(vhd_chain[:-1], vhd_chain[1:]):
        with temporary_dir() as directory_for_journal:
            size = get_vhd_size(child)
            journal_file = os.path.join(
                directory_for_journal, 'vhd-util-resize-journal')
            resize_vhd(parent, size, journal_file)
            coalesce_vhd(child)

    return vhd_chain[-1]


def discover_vhd_chain(directory: str) -> List[str]:
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


def replace_xenserver_image_with_coalesced_vhd(image_file: str) -> None:
    with temporary_dir() as tempdir:
        extract_targz(image_file, tempdir)
        chain = discover_vhd_chain(tempdir)
        fix_vhd_chain(chain)
        coalesced = coalesce_chain(chain)
        fileutils.delete_if_exists(image_file)
        os.rename(coalesced, image_file)


def decode_cipher(cipher_spec: str, key_size: int) -> Dict[str, str]:
    """Decode a dm-crypt style cipher specification string

       The assumed format being cipher-chainmode-ivmode, similar to that
       documented under
       linux/Documentation/admin-guide/device-mapper/dm-crypt.txt in the
       kernel source tree.  Cinder does not support the [:keycount] or
       [:ivopts] options.
    """
    try:
        cipher_alg, cipher_mode, ivgen_alg = cipher_spec.split('-')
    except ValueError:
        raise exception.InvalidVolumeType(
            reason="Invalid cipher field in encryption type")

    cipher_alg = cipher_alg + '-' + str(key_size)

    return {'cipher_alg': cipher_alg,
            'cipher_mode': cipher_mode,
            'ivgen_alg': ivgen_alg}


class TemporaryImages(object):
    """Manage temporarily downloaded images to avoid downloading it twice.

    In the 'with TemporaryImages.fetch(image_service, ctx, image_id) as tmp'
    clause, 'tmp' can be used as the downloaded image path. In addition,
    image_utils.fetch() will use the pre-fetched image by the TemporaryImages.
    This is useful to inspect image contents before conversion.
    """

    def __init__(self, image_service: glance.GlanceImageService):
        self.temporary_images: Dict[str, dict] = {}
        self.image_service = image_service
        image_service.temp_images = self

    @staticmethod
    def for_image_service(
            image_service: glance.GlanceImageService) -> 'TemporaryImages':
        instance = image_service.temp_images
        if instance:
            return instance
        return TemporaryImages(image_service)

    @classmethod
    @contextlib.contextmanager
    def fetch(cls,
              image_service: glance.GlanceImageService,
              context: context.RequestContext,
              image_id: str,
              suffix: Optional[str] = '') -> Generator[str, None, None]:
        tmp_images = cls.for_image_service(image_service).temporary_images
        with temporary_file(prefix='image_fetch_%s_' % image_id,
                            suffix=suffix) as tmp:
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

    def get(self, context: context.RequestContext, image_id: str):
        user = context.user_id
        if not self.temporary_images.get(user):
            return None
        return self.temporary_images[user].get(image_id)
