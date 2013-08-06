# vim: tabstop=4 shiftwidth=4 softtabstop=4

# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Exceptions for the Brick library."""


class NoFibreChannelHostsFound(Exception):
    def __init__(self):
        message = _("We are unable to locate any Fibre Channel devices")
        super(NoFibreChannelHostsFound, self).__init__(message)


class NoFibreChannelVolumeDeviceFound(Exception):
    def __init__(self):
        message = _("Unable to find a Fibre Channel volume device")
        super(NoFibreChannelVolumeDeviceFound, self).__init__(message)


class VolumeDeviceNotFound(Exception):
    def __init__(self, device):
        message = _("Volume device not found at %s") % device
        super(VolumeDeviceNotFound, self).__init__(message)
