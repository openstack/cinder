# (c) Copyright 2014-2016 Hewlett Packard Enterprise Development LP
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
"""Fake HPE client for testing LeftHand without installing the client."""

import sys

import mock

from cinder.tests.unit.volume.drivers.hpe \
    import fake_hpe_client_exceptions as hpeexceptions

hpelefthand = mock.Mock()
hpelefthand.version = "2.1.0"
hpelefthand.exceptions = hpeexceptions

sys.modules['hpelefthandclient'] = hpelefthand
