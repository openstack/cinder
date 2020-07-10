# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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
import base64
import binascii
from distutils import version
import math

from oslo_log import log as logging
from oslo_utils import units

LOG = logging.getLogger(__name__)


def version_gte(ver1, ver2):
    return version.LooseVersion(ver1) >= version.LooseVersion(ver2)


def convert_kb_to_gib(size):
    return int(math.floor(float(size) / units.Mi))


def id_to_base64(_id):
    # Base64 encode the id to get a volume name less than 32 characters due
    # to PowerFlex limitation.
    name = str(_id).replace("-", "")
    try:
        name = base64.b16decode(name.upper())
    except (TypeError, binascii.Error):
        pass
    if isinstance(name, str):
        name = name.encode()
    encoded_name = base64.b64encode(name).decode()
    LOG.debug("Converted id %(id)s to PowerFlex OS name %(name)s.",
              {"id": _id, "name": encoded_name})
    return encoded_name


def round_to_num_gran(size, num=8):
    """Round size to nearest value that is multiple of `num`."""

    if size % num == 0:
        return size
    return size + num - (size % num)


def round_down_to_num_gran(size, num=8):
    """Round size down to nearest value that is multiple of `num`."""

    return size - (size % num)
