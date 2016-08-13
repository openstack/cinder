# Copyright 2016
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

from oslo_config import cfg

service_available_group = cfg.OptGroup(name="service_available",
                                       title="Available OpenStack Services")


ServiceAvailableGroup = [
    cfg.BoolOpt("cinder",
                default=True,
                help="Whether or not cinder is expected to be available"),
]

# Use a new config group specific to the cinder in-tree tests to avoid
# any naming confusion with the upstream tempest config options.
cinder_group = cfg.OptGroup(name='cinder',
                            title='Cinder Tempest Config Options')

CinderGroup = [
    cfg.BoolOpt('consistency_group',
                default=False,
                help='Enable to run Cinder volume consistency group tests'),
]
