# (c) Copyright 2014-2015 Hewlett Packard Enterprise Development LP
#    All Rights Reserved.
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
"""Fake HPE client for testing 3PAR without installing the client."""

import sys

import mock

from cinder.tests.unit.volume.drivers.hpe \
    import fake_hpe_client_exceptions as hpeexceptions

hpe3par = mock.Mock()
hpe3par.version = "4.2.0"
hpe3par.exceptions = hpeexceptions

sys.modules['hpe3parclient'] = hpe3par
