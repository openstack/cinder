# Copyright (c) 2020 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Configuration options for Dell EMC PowerStore Cinder driver."""

from oslo_config import cfg

POWERSTORE_APPLIANCES = "powerstore_appliances"
POWERSTORE_PORTS = "powerstore_ports"

POWERSTORE_OPTS = [
    cfg.ListOpt(POWERSTORE_APPLIANCES,
                default=[],
                help="Appliances names. Comma separated list of PowerStore "
                     "appliances names used to provision volumes.",
                deprecated_for_removal=True,
                deprecated_reason="Is not used anymore. "
                                  "PowerStore Load Balancer is used to "
                                  "provision volumes instead.",
                deprecated_since="Wallaby"),
    cfg.ListOpt(POWERSTORE_PORTS,
                default=[],
                help="Allowed ports. Comma separated list of PowerStore "
                     "iSCSI IPs or FC WWNs (ex. 58:cc:f0:98:49:22:07:02) "
                     "to be used. If option is not set all ports are allowed.")
]
