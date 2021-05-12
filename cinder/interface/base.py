# Copyright 2016 Dell Inc.
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
#

import abc
import inspect


def _get_arg_count(method):
    """Get the number of positional parameters for a method.

    :param method: The method to check.
    :returns: The number of positional parameters for the method.
    """
    if not method:
        return 0

    arg_spec = inspect.getfullargspec(method)
    return len(arg_spec[0])


def _get_method_info(cls):
    """Get all methods defined in a class.

    Note: This will only return public methods and their associated arg count.

    :param cls: The class to inspect.
    :returns: `Dict` of method names with a tuple of the method and their arg
              counts.
    """
    result = {}

    methods = inspect.getmembers(cls, inspect.ismethod)
    for (name, method) in methods:
        if name.startswith('_'):
            # Skip non-public methods
            continue
        result[name] = (method, _get_arg_count(method))

    return result


class CinderInterface(object, metaclass=abc.ABCMeta):
    """Interface base class for Cinder.

    Cinder interfaces should inherit from this class to support indirect
    inheritance evaluation.

    This can be used to validate compliance to an interface without requiring
    that the class actually be inherited from the same base class.
    """

    _method_cache = None

    @classmethod
    def _get_methods(cls):
        if not cls._method_cache:
            cls._method_cache = _get_method_info(cls)
        return cls._method_cache

    @classmethod
    def __subclasshook__(cls, other_cls):
        """Custom class inheritance evaluation.

        :param cls: The CinderInterface to check against.
        :param other_cls: The class to be checked if it implements
                          our interface.
        """
        interface_methods = cls._get_methods()
        driver_methods = _get_method_info(other_cls)

        interface_keys = interface_methods.keys()
        driver_keys = driver_methods.keys()

        matching_count = len(set(interface_keys) & set(driver_keys))
        if matching_count != len(interface_keys):
            # Missing some methods, does not implement this interface or is
            # missing something.
            return NotImplemented

        # TODO(smcginnis) Add method signature checking.
        # We know all methods are there, now make sure they look right.
        # Unfortunately the methods can be obfuscated by certain decorators,
        # so we need to find a better way to pull out the real method
        # signatures.
        # driver_methods[method_name][0].func_closure.cell_contents works
        # for most cases but not all.
        # AST might work instead of using introspect.

        return True
