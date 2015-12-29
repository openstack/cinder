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
"""HPE XP driver options."""

from oslo_config import cfg

FC_VOLUME_OPTS = [
    cfg.BoolOpt(
        'hpexp_zoning_request',
        default=False,
        help='Request for FC Zone creating host group',
        deprecated_name='hpxp_zoning_request'),
]

COMMON_VOLUME_OPTS = [
    cfg.StrOpt(
        'hpexp_storage_cli',
        help='Type of storage command line interface',
        deprecated_name='hpxp_storage_cli'),
    cfg.StrOpt(
        'hpexp_storage_id',
        help='ID of storage system',
        deprecated_name='hpxp_storage_id'),
    cfg.StrOpt(
        'hpexp_pool',
        help='Pool of storage system',
        deprecated_name='hpxp_pool'),
    cfg.StrOpt(
        'hpexp_thin_pool',
        help='Thin pool of storage system',
        deprecated_name='hpxp_thin_pool'),
    cfg.StrOpt(
        'hpexp_ldev_range',
        help='Logical device range of storage system',
        deprecated_name='hpxp_ldev_range'),
    cfg.StrOpt(
        'hpexp_default_copy_method',
        default='FULL',
        help='Default copy method of storage system. '
             'There are two valid values: "FULL" specifies that a full copy; '
             '"THIN" specifies that a thin copy. Default value is "FULL"',
        deprecated_name='hpxp_default_copy_method'),
    cfg.IntOpt(
        'hpexp_copy_speed',
        default=3,
        help='Copy speed of storage system',
        deprecated_name='hpxp_copy_speed'),
    cfg.IntOpt(
        'hpexp_copy_check_interval',
        default=3,
        help='Interval to check copy',
        deprecated_name='hpxp_copy_check_interval'),
    cfg.IntOpt(
        'hpexp_async_copy_check_interval',
        default=10,
        help='Interval to check copy asynchronously',
        deprecated_name='hpxp_async_copy_check_interval'),
    cfg.ListOpt(
        'hpexp_target_ports',
        help='Target port names for host group or iSCSI target',
        deprecated_name='hpxp_target_ports'),
    cfg.ListOpt(
        'hpexp_compute_target_ports',
        help=(
            'Target port names of compute node '
            'for host group or iSCSI target'),
        deprecated_name='hpxp_compute_target_ports'),
    cfg.BoolOpt(
        'hpexp_group_request',
        default=False,
        help='Request for creating host group or iSCSI target',
        deprecated_name='hpxp_group_request'),
]

HORCM_VOLUME_OPTS = [
    cfg.ListOpt(
        'hpexp_horcm_numbers',
        default=["200", "201"],
        help='Instance numbers for HORCM',
        deprecated_name='hpxp_horcm_numbers'),
    cfg.StrOpt(
        'hpexp_horcm_user',
        help='Username of storage system for HORCM',
        deprecated_name='hpxp_horcm_user'),
    cfg.BoolOpt(
        'hpexp_horcm_add_conf',
        default=True,
        help='Add to HORCM configuration',
        deprecated_name='hpxp_horcm_add_conf'),
    cfg.StrOpt(
        'hpexp_horcm_resource_name',
        default='meta_resource',
        help='Resource group name of storage system for HORCM',
        deprecated_name='hpxp_horcm_resource_name'),
    cfg.BoolOpt(
        'hpexp_horcm_name_only_discovery',
        default=False,
        help='Only discover a specific name of host group or iSCSI target',
        deprecated_name='hpxp_horcm_name_only_discovery'),
]

CONF = cfg.CONF
CONF.register_opts(FC_VOLUME_OPTS)
CONF.register_opts(COMMON_VOLUME_OPTS)
CONF.register_opts(HORCM_VOLUME_OPTS)
