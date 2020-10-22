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

import abc

from oslo_config import cfg
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _

CONF = cfg.CONF

# NOTE(ZhengMa): The order of the option is improtant, accelerators
# are looked by this list order
# Be careful to edit it
_ACCEL_PATH_PREFERENCE_ORDER_LIST = [
    'cinder.image.accelerators.qat.AccelQAT',
    'cinder.image.accelerators.gzip.AccelGZIP',
]


class AccelBase(object, metaclass=abc.ABCMeta):
    def __init__(self):
        return

    @abc.abstractmethod
    def is_accel_exist(self):
        return

    @abc.abstractmethod
    def compress_img(self, run_as_root):
        return

    @abc.abstractmethod
    def decompress_img(self, run_as_root):
        return


class ImageAccel(object):

    def __init__(self, src, dest):
        self.src = src
        self.dest = dest
        self.compression_format = CONF.compression_format
        if(self.compression_format == 'gzip'):
            self._accel_engine_path = _ACCEL_PATH_PREFERENCE_ORDER_LIST
        else:
            self._accel_engine_path = None
        self.engine = self._get_engine()

    def _get_engine(self, *args, **kwargs):
        if self._accel_engine_path:
            for accel in self._accel_engine_path:
                engine_cls = importutils.import_class(accel)
                eng = engine_cls(*args, **kwargs)
                if eng.is_accel_exist():
                    return eng

        ex_msg = _("No valid accelerator")
        raise exception.CinderException(ex_msg)

    def is_engine_ready(self):

        if not self.engine:
            return False
        if not self.engine.is_accel_exist():
            return False
        return True

    def compress_img(self, run_as_root):
        if not self.is_engine_ready():
            return
        self.engine.compress_img(self.src,
                                 self.dest,
                                 run_as_root)

    def decompress_img(self, run_as_root):
        if not self.is_engine_ready():
            return
        self.engine.decompress_img(self.src,
                                   self.dest,
                                   run_as_root)


def is_gzip_compressed(image_file):
    # The first two bytes of a gzip file are: 1f 8b
    GZIP_MAGIC_BYTES = b'\x1f\x8b'
    with open(image_file, 'rb') as f:
        return f.read(2) == GZIP_MAGIC_BYTES
