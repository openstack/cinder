# Copyright (C) 2015, Hitachi, Ltd.
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
"""HP XP driver options."""

from oslo_config import cfg

FC_VOLUME_OPTS = [
    cfg.BoolOpt(
        'hpxp_zoning_request',
        default=False,
        help='Request for FC Zone creating host group'),
]

COMMON_VOLUME_OPTS = [
    cfg.StrOpt(
        'hpxp_storage_cli',
        help='Type of storage command line interface'),
    cfg.StrOpt(
        'hpxp_storage_id',
        help='ID of storage system'),
    cfg.StrOpt(
        'hpxp_pool',
        help='Pool of storage system'),
    cfg.StrOpt(
        'hpxp_thin_pool',
        help='Thin pool of storage system'),
    cfg.StrOpt(
        'hpxp_ldev_range',
        help='Logical device range of storage system'),
    cfg.StrOpt(
        'hpxp_default_copy_method',
        default='FULL',
        help='Default copy method of storage system. '
             'There are two valid values: "FULL" specifies that a full copy; '
             '"THIN" specifies that a thin copy. Default value is "FULL"'),
    cfg.IntOpt(
        'hpxp_copy_speed',
        default=3,
        help='Copy speed of storage system'),
    cfg.IntOpt(
        'hpxp_copy_check_interval',
        default=3,
        help='Interval to check copy'),
    cfg.IntOpt(
        'hpxp_async_copy_check_interval',
        default=10,
        help='Interval to check copy asynchronously'),
    cfg.ListOpt(
        'hpxp_target_ports',
        help='Target port names for host group or iSCSI target'),
    cfg.ListOpt(
        'hpxp_compute_target_ports',
        help=(
            'Target port names of compute node '
            'for host group or iSCSI target')),
    cfg.BoolOpt(
        'hpxp_group_request',
        default=False,
        help='Request for creating host group or iSCSI target'),
]

HORCM_VOLUME_OPTS = [
    cfg.ListOpt(
        'hpxp_horcm_numbers',
        default=["200", "201"],
        help='Instance numbers for HORCM'),
    cfg.StrOpt(
        'hpxp_horcm_user',
        help='Username of storage system for HORCM'),
    cfg.BoolOpt(
        'hpxp_horcm_add_conf',
        default=True,
        help='Add to HORCM configuration'),
    cfg.StrOpt(
        'hpxp_horcm_resource_name',
        default='meta_resource',
        help='Resource group name of storage system for HORCM'),
    cfg.BoolOpt(
        'hpxp_horcm_name_only_discovery',
        default=False,
        help='Only discover a specific name of host group or iSCSI target'),
]

CONF = cfg.CONF
CONF.register_opts(FC_VOLUME_OPTS)
CONF.register_opts(COMMON_VOLUME_OPTS)
CONF.register_opts(HORCM_VOLUME_OPTS)
