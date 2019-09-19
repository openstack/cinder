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


from oslo_concurrency import processutils
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder.image import accelerator
from cinder import utils

LOG = logging.getLogger(__name__)


class AccelGZIP(accelerator.AccelBase):
    def is_accel_exist(self):
        cmd = ['which', 'gzip']
        try:
            utils.execute(*cmd)
        except processutils.ProcessExecutionError:
            LOG.error("GZIP package is not installed.")
            return False

        return True

    # NOTE(ZhengMa): Gzip compresses a file in-place and adds a .gz
    # extension to the filename, so we rename the compressed file back
    # to the name Cinder expects it to have.
    # (Cinder expects to have A to upload)
    # Follow these steps:
    # 1. compress A to A.gz (gzip_out_file is A.gz)
    # 2. mv A.gz to A (gzip_out_file to dest)
    def compress_img(self, src, dest, run_as_root):
        try:
            gzip_compress_cmd = ['gzip', '-k', src]
            utils.execute(*gzip_compress_cmd, run_as_root=run_as_root)
        except processutils.ProcessExecutionError as ex:
            raise exception.CinderAcceleratorError(
                accelerator='GZIP',
                description=_("Volume compression failed while "
                              "uploading to glance. GZIP compression "
                              "command failed."),
                cmd=gzip_compress_cmd,
                reason=ex.stderr)
        try:
            gzip_output_filename = src + '.gz'
            mv_cmd = ['mv', gzip_output_filename, dest]
            utils.execute(*mv_cmd, run_as_root=run_as_root)
        except processutils.ProcessExecutionError as ex:
            fnames = {'i_fname': gzip_output_filename, 'o_fname': dest}
            raise exception.CinderAcceleratorError(
                accelerator='GZIP',
                description = _("Failed to rename %(i_fname)s "
                                "to %(o_fname)s") % fnames,
                cmd=mv_cmd,
                reason=ex.stderr)

    # NOTE(ZhengMa): Gzip can only decompresses a file with a .gz
    # extension to the filename, so we rename the original file so
    # that it can be accepted by Gzip.
    # Follow these steps:
    # 1. mv A to A.gz (gzip_in_file is A.gz)
    # 2. decompress A.gz to A (gzip_in_file to dest)
    def decompress_img(self, src, dest, run_as_root):
        try:
            gzip_input_filename = dest + '.gz'
            mv_cmd = ['mv', src, gzip_input_filename]
            utils.execute(*mv_cmd, run_as_root=run_as_root)
        except processutils.ProcessExecutionError as ex:
            fnames = {'i_fname': src, 'o_fname': gzip_input_filename}
            raise exception.CinderAcceleratorError(
                accelerator='GZIP',
                description = _("Failed to rename %(i_fname)s "
                                "to %(o_fname)s") % fnames,
                cmd=mv_cmd,
                reason=ex.stderr)
        try:
            gzip_decompress_cmd = ['gzip', '-d', gzip_input_filename]
            utils.execute(*gzip_decompress_cmd, run_as_root=run_as_root)
        except processutils.ProcessExecutionError as ex:
            raise exception.CinderAcceleratorError(
                accelerator='GZIP',
                description = _("Image decompression failed while "
                                "downloading from glance. GZIP "
                                "decompression command failed."),
                cmd=gzip_decompress_cmd,
                reason=ex.stderr)
