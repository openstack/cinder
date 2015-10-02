# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
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
Utilities for NetApp E-series drivers.
"""

import base64
import binascii
import uuid

from oslo_log import log as logging
import six


LOG = logging.getLogger(__name__)

MULTI_ATTACH_HOST_GROUP_NAME = 'cinder-multi-attach'
NULL_REF = '0000000000000000000000000000000000000000'
MAX_LUNS_PER_HOST = 256
MAX_LUNS_PER_HOST_GROUP = 256


def encode_hex_to_base32(hex_string):
    """Encodes hex to base32 bit as per RFC4648."""
    bin_form = binascii.unhexlify(hex_string)
    return base64.b32encode(bin_form)


def decode_base32_to_hex(base32_string):
    """Decodes base32 string to hex string."""
    bin_form = base64.b32decode(base32_string)
    return binascii.hexlify(bin_form)


def convert_uuid_to_es_fmt(uuid_str):
    """Converts uuid to e-series compatible name format."""
    uuid_base32 = encode_hex_to_base32(uuid.UUID(six.text_type(uuid_str)).hex)
    return uuid_base32.strip(b'=')


def convert_es_fmt_to_uuid(es_label):
    """Converts e-series name format to uuid."""
    if es_label.startswith('tmp-'):
        es_label = es_label[4:]
    es_label_b32 = es_label.ljust(32, '=')
    return uuid.UUID(binascii.hexlify(base64.b32decode(es_label_b32)))
