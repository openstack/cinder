# Copyright (c) 2011-2012 OpenStack, LLC.
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
Filter support
"""

import inspect

from stevedore import extension


class BaseFilter(object):
    """Base class for all filter classes."""
    def _filter_one(self, obj, filter_properties):
        """Return True if it passes the filter, False otherwise.
        Override this in a subclass.
        """
        return True

    def filter_all(self, filter_obj_list, filter_properties):
        """Yield objects that pass the filter.

        Can be overriden in a subclass, if you need to base filtering
        decisions on all objects.  Otherwise, one can just override
        _filter_one() to filter a single object.
        """
        for obj in filter_obj_list:
            if self._filter_one(obj, filter_properties):
                yield obj


class BaseFilterHandler(object):
    """ Base class to handle loading filter classes.

    This class should be subclassed where one needs to use filters.
    """
    def __init__(self, filter_class_type, filter_namespace):
        self.namespace = filter_namespace
        self.filter_class_type = filter_class_type
        self.filter_manager = extension.ExtensionManager(filter_namespace)

    def _is_correct_class(self, obj):
        """Return whether an object is a class of the correct type and
        is not prefixed with an underscore.
        """
        return (inspect.isclass(obj) and
                not obj.__name__.startswith('_') and
                issubclass(obj, self.filter_class_type))

    def get_all_classes(self):
        return [x.plugin for x in self.filter_manager
                if self._is_correct_class(x.plugin)]

    def get_filtered_objects(self, filter_classes, objs,
                             filter_properties):
        for filter_cls in filter_classes:
            objs = filter_cls().filter_all(objs, filter_properties)
        return list(objs)
