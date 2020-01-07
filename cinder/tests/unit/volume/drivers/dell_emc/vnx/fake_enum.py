# Copyright (c) 2016 EMC Corporation.
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

import enum

import six


class Enum(enum.Enum):
    @classmethod
    def verify(cls, value, allow_none=True):
        if value is None and not allow_none:
            raise ValueError(
                'None is not allowed here for %s.') % cls.__name__
        elif value is not None and not isinstance(value, cls):
            raise ValueError('%(value)s is not an instance of %(name)s.') % {
                'value': value, 'name': cls.__name__}

    @classmethod
    def get_all(cls):
        return list(cls)

    @classmethod
    def get_opt(cls, value):
        option_map = cls.get_option_map()
        if option_map is None:
            raise NotImplementedError(
                'Option map is not defined for %s.') % cls.__name__

        ret = option_map.get(value, None)
        if ret is None:
            raise ValueError('%(value)s is not a valid option for %(name)s.'
                             ) % {'value': value, 'name': cls.__name__}
        return ret

    @classmethod
    def parse(cls, value):
        if isinstance(value, six.string_types):
            ret = cls.from_str(value)
        elif isinstance(value, six.integer_types):
            ret = cls.from_int(value)
        elif isinstance(value, cls):
            ret = value
        elif value is None:
            ret = None
        else:
            raise ValueError(
                'Not supported value type: %s.') % type(value)
        return ret

    def is_equal(self, value):
        if isinstance(value, six.string_types):
            ret = self.value.lower() == value.lower()
        else:
            ret = self.value == value
        return ret

    @classmethod
    def from_int(cls, value):
        ret = None
        int_index = cls.get_int_index()
        if int_index is not None:
            try:
                ret = int_index[value]
            except IndexError:
                pass
        else:
            try:
                ret = next(i for i in cls.get_all() if i.is_equal(value))
            except StopIteration:
                pass
        if ret is None:
            raise ValueError
        return ret

    @classmethod
    def from_str(cls, value):
        ret = None
        if value is not None:
            for item in cls.get_all():
                if item.is_equal(value):
                    ret = item
                    break
            else:
                cls._raise_invalid_value(value)
        return ret

    @classmethod
    def _raise_invalid_value(cls, value):
        msg = ('%(value)s is not a valid value for %(name)s.'
               ) % {'value': value, 'name': cls.__name__}
        raise ValueError(msg)

    @classmethod
    def get_option_map(cls):
        raise None

    @classmethod
    def get_int_index(cls):
        return None

    @classmethod
    def values(cls):
        return [m.value for m in cls.__members__.values()]

    @classmethod
    def enum_name(cls):
        return cls.__name__


class VNXCtrlMethod(object):
    LIMIT_CTRL = 'limit'

    def __init__(self, method, metric, value):
        self.method = method
        self.metric = metric
        self.value = value
