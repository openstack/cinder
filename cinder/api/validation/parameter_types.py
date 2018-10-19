# Copyright (C) 2017 NTT DATA
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

"""
Common parameter types for validating request Body.

"""

import copy
import re
import unicodedata

import six

from cinder.common import constants


def _is_printable(char):
    """determine if a unicode code point is printable.

    This checks if the character is either "other" (mostly control
    codes), or a non-horizontal space. All characters that don't match
    those criteria are considered printable; that is: letters;
    combining marks; numbers; punctuation; symbols; (horizontal) space
    separators.
    """
    category = unicodedata.category(char)
    return (not category.startswith("C") and
            (not category.startswith("Z") or category == "Zs"))


def _get_all_chars():
    for i in range(0xFFFF):
        yield six.unichr(i)


# build a regex that matches all printable characters. This allows
# spaces in the middle of the name. Also note that the regexp below
# deliberately allows the empty string. This is so only the constraint
# which enforces a minimum length for the name is triggered when an
# empty string is tested. Otherwise it is not deterministic which
# constraint fails and this causes issues for some unittests when
# PYTHONHASHSEED is set randomly.

def _build_regex_range(ws=True, invert=False, exclude=None):
    """Build a range regex for a set of characters in utf8.

    This builds a valid range regex for characters in utf8 by
    iterating the entire space and building up a set of x-y ranges for
    all the characters we find which are valid.

    :param ws: should we include whitespace in this range.
    :param exclude: any characters we want to exclude
    :param invert: invert the logic

    The inversion is useful when we want to generate a set of ranges
    which is everything that's not a certain class. For instance,
    produce all all the non printable characters as a set of ranges.
    """
    if exclude is None:
        exclude = []
    regex = ""
    # are we currently in a range
    in_range = False
    # last character we found, for closing ranges
    last = None
    # last character we added to the regex, this lets us know that we
    # already have B in the range, which means we don't need to close
    # it out with B-B. While the later seems to work, it's kind of bad form.
    last_added = None

    def valid_char(char):
        if char in exclude:
            result = False
        elif ws:
            result = _is_printable(char)
        else:
            # Zs is the unicode class for space characters, of which
            # there are about 10 in this range.
            result = (_is_printable(char) and
                      unicodedata.category(char) != "Zs")
        if invert is True:
            return not result
        return result

    # iterate through the entire character range. in_
    for c in _get_all_chars():
        if valid_char(c):
            if not in_range:
                regex += re.escape(c)
                last_added = c
            in_range = True
        else:
            if in_range and last != last_added:
                regex += "-" + re.escape(last)
            in_range = False
        last = c
    else:
        if in_range:
            regex += "-" + re.escape(c)
    return regex


valid_description_regex_base = '^[%s]*$'

valid_description_regex = valid_description_regex_base % (
    _build_regex_range())


name = {
    'type': 'string', 'minLength': 1, 'maxLength': 255,
    'format': 'name'
}


description = {
    'type': ['string', 'null'], 'minLength': 0, 'maxLength': 255,
    'pattern': valid_description_regex,
}


boolean = {
    'type': ['boolean', 'string'],
    'enum': [True, 'True', 'TRUE', 'true', '1', 'ON', 'On', 'on',
             'YES', 'Yes', 'yes', 'y', 't',
             False, 'False', 'FALSE', 'false', '0', 'OFF', 'Off', 'off',
             'NO', 'No', 'no', 'n', 'f'],
}


uuid = {
    'type': 'string', 'format': 'uuid'
}

extra_specs = {
    'type': 'object',
    'patternProperties': {
        '^[a-zA-Z0-9-_:. /]{1,255}$': {
            'type': 'string', 'maxLength': 255
        }
    },
    'additionalProperties': False
}


extra_specs_with_no_spaces_key = {
    'type': 'object',
    'patternProperties': {
        '^[a-zA-Z0-9-_:.]{1,255}$': {
            'type': ['string', 'null'], 'minLength': 0, 'maxLength': 255
        }
    },
    'additionalProperties': False
}


group_snapshot_status = {
    'type': 'string', 'format': 'group_snapshot_status'
}


extra_specs_with_null = copy.deepcopy(extra_specs)
extra_specs_with_null['patternProperties'][
    '^[a-zA-Z0-9-_:. /]{1,255}$']['type'] = ['string', 'null']


name_allow_zero_min_length = {
    'type': ['string', 'null'], 'minLength': 0, 'maxLength': 255
}


uuid_allow_null = {
    'oneOf': [uuid, {'type': 'null'}]
}


metadata_allows_null = copy.deepcopy(extra_specs)
metadata_allows_null['type'] = ['object', 'null']


container = {
    'type': ['string', 'null'], 'minLength': 0, 'maxLength': 255}


backup_url = {'type': 'string', 'minLength': 1, 'format': 'base64'}


backup_service = {'type': 'string', 'minLength': 0, 'maxLength': 255}


nullable_string = {
    'type': ('string', 'null'), 'minLength': 0, 'maxLength': 255
}


volume_size = {
    'type': ['integer', 'string'],
    'pattern': '^[0-9]+$',
    'minimum': 1,
    'maximum': constants.DB_MAX_INT
}
volume_size_allows_null = copy.deepcopy(volume_size)
volume_size_allows_null['type'] += ['null']


hostname = {
    'type': ['string', 'null'], 'minLength': 1, 'maxLength': 255,
    # NOTE: 'host' is defined in "services" table, and that
    # means a hostname. The hostname grammar in RFC952 does
    # not allow for underscores in hostnames. However, this
    # schema allows them, because it sometimes occurs in
    # real systems. As it is a cinder host, not a hostname,
    # and due to some driver needs, colons and forward slashes
    # were also included in the regex.
    'pattern': '^[a-zA-Z0-9-._#@:/+]*$'
}


resource_type = {'type': ['string', 'null'], 'minLength': 0, 'maxLength': 40}


service_id = {
    'type': ['integer', 'string', 'null'],
    'pattern': '^[0-9]*$', 'maxLength': 11
}


optional_uuid = {'oneOf': [{'type': 'null'},
                           {'type': 'string', 'format': 'uuid'}]}


quota_class_set = {
    'type': 'object',
    'format': 'quota_class_set',
    'patternProperties': {
        '^[a-zA-Z0-9-_:. ]{1,255}$': {
            'type': ['integer', 'string'],
            'pattern': '^[0-9]*$', 'minimum': -1, 'minLength': 1,
            'maximum': constants.DB_MAX_INT
        }
    },
    'additionalProperties': False
}


binary = {
    'type': 'string',
    'enum': [binary for binary in constants.LOG_BINARIES + ('', '*')]
}


key_size = {'type': ['string', 'integer', 'null'],
            'minimum': 0,
            'maximum': constants.DB_MAX_INT,
            'format': 'key_size'}


availability_zone = {
    'type': ['string', 'null'], 'minLength': 1, 'maxLength': 255
}


optional_boolean = {'oneOf': [{'type': 'null'}, boolean]}
