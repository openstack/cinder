# Copyright 2014 IBM Corp.
# Copyright 2015 Clinton Knight
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

from cinder import utils


class VersionedMethod(utils.ComparableMixin):

    def __init__(self, name, start_version, end_version, experimental, func):
        """Versioning information for a single method.

        Minimum and maximums are inclusive.

        :param name: Name of the method
        :param start_version: Minimum acceptable version
        :param end_version: Maximum acceptable_version
        :param func: Method to call
        """
        self.name = name
        self.start_version = start_version
        self.end_version = end_version
        self.experimental = experimental
        self.func = func

    def __str__(self):
        args = {
            'name': self.name,
            'start': self.start_version,
            'end': self.end_version
        }
        return ("Version Method %(name)s: min: %(start)s, max: %(end)s" % args)

    def _cmpkey(self):
        """Return the value used by ComparableMixin for rich comparisons."""
        return self.start_version
