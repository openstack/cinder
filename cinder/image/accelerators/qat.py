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


class AccelQAT(accelerator.AccelBase):
    def is_accel_exist(self):
        cmd = ['which', 'qzip']
        try:
            utils.execute(*cmd)
        except processutils.ProcessExecutionError:
            LOG.error("QATzip package is not installed.")
            return False

        return True

    # NOTE(ZhengMa): QATzip compresses a file in-place and adds a .gz
    # extension to the filename, so we rename the compressed file back
    # to the name Cinder expects it to have.
    # (Cinder expects to have A to upload)
    # Follow these steps:
    # 1. compress A to A.gz (src to qat_out_file)
    # 2. mv A.gz to A (qat_out_file to dest)
    def compress_img(self, src, dest, run_as_root):
        try:
            qat_compress_cmd = ['qzip', '-k', src, '-o', dest]
            utils.execute(*qat_compress_cmd, run_as_root=run_as_root)
        except processutils.ProcessExecutionError as ex:
            raise exception.CinderAcceleratorError(
                accelerator='QAT',
                description=_("Volume compression failed while "
                              "uploading to glance. QAT compression "
                              "command failed."),
                cmd=qat_compress_cmd,
                reason=ex.stderr)
        try:
            qat_output_filename = src + '.gz'
            mv_cmd = ['mv', qat_output_filename, dest]
            utils.execute(*mv_cmd, run_as_root=run_as_root)
        except processutils.ProcessExecutionError as ex:
            fnames = {'i_fname': qat_output_filename, 'o_fname': dest}
            raise exception.CinderAcceleratorError(
                accelerator='QAT',
                description = _("Failed to rename %(i_fname)s "
                                "to %(o_fname)s") % fnames,
                cmd=mv_cmd,
                reason=ex.stderr)

    # NOTE(ZhengMa): QATzip can only decompresses a file with a .gz
    # extension to the filename, so we rename the original file so
    # that it can be accepted by QATzip.
    # Follow these steps:
    # 1. mv A to A.gz (qat_in_file is A.gz)
    # 2. decompress A.gz to A (qat_in_file to dest)
    def decompress_img(self, src, dest, run_as_root):
        try:
            qat_input_filename = dest + '.gz'
            mv_cmd = ['mv', src, qat_input_filename]
            utils.execute(*mv_cmd, run_as_root=run_as_root)
        except processutils.ProcessExecutionError as ex:
            fnames = {'i_fname': src, 'o_fname': qat_input_filename}
            raise exception.CinderAcceleratorError(
                accelerator='QAT',
                description = _("Failed to rename %(i_fname)s "
                                "to %(o_fname)s") % fnames,
                cmd=mv_cmd,
                reason=ex.stderr)
        try:
            qat_decompress_cmd = ['qzip', '-d', qat_input_filename]
            utils.execute(*qat_decompress_cmd, run_as_root=run_as_root)
        except processutils.ProcessExecutionError as ex:
            raise exception.CinderAcceleratorError(
                accelerator='QAT',
                description = _("Image decompression failed while "
                                "downloading from glance. QAT "
                                "decompression command failed."),
                cmd=qat_decompress_cmd,
                reason=ex.stderr)
