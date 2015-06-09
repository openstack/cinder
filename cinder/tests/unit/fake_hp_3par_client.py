# (c) Copyright 2014 Hewlett-Packard Development Company, L.P.
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
"""Fake HP client for testing 3PAR without installing the client."""

import sys

import mock

from cinder.tests.unit import fake_hp_client_exceptions as hpexceptions

hp3par = mock.Mock()
hp3par.version = "3.1.2"
hp3par.exceptions = hpexceptions

sys.modules['hp3parclient'] = hp3par
