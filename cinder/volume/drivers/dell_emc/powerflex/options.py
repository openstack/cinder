# Copyright (c) 2017-2020 Dell Inc. or its subsidiaries.
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
Configuration options for Dell EMC PowerFlex (formerly
named Dell EMC VxFlex OS).
"""

from oslo_config import cfg

# deprecated options
VXFLEXOS_REST_SERVER_PORT = "vxflexos_rest_server_port"
VXFLEXOS_ROUND_VOLUME_CAPACITY = "vxflexos_round_volume_capacity"
VXFLEXOS_UNMAP_VOLUME_BEFORE_DELETION = "vxflexos_unmap_volume_before_deletion"
VXFLEXOS_STORAGE_POOLS = "vxflexos_storage_pools"
VXFLEXOS_SERVER_API_VERSION = "vxflexos_server_api_version"
VXFLEXOS_MAX_OVER_SUBSCRIPTION_RATIO = "vxflexos_max_over_subscription_ratio"
VXFLEXOS_ALLOW_NON_PADDED_VOLUMES = "vxflexos_allow_non_padded_volumes"
VXFLEXOS_ALLOW_MIGRATION_DURING_REBUILD = (
    "vxflexos_allow_migration_during_rebuild")

# actual options
POWERFLEX_REST_SERVER_PORT = "powerflex_rest_server_port"
POWERFLEX_ROUND_VOLUME_CAPACITY = "powerflex_round_volume_capacity"
POWERFLEX_UNMAP_VOLUME_BEFORE_DELETION = (
    "powerflex_unmap_volume_before_deletion")
POWERFLEX_STORAGE_POOLS = "powerflex_storage_pools"
POWERFLEX_SERVER_API_VERSION = "powerflex_server_api_version"
POWERFLEX_MAX_OVER_SUBSCRIPTION_RATIO = "powerflex_max_over_subscription_ratio"
POWERFLEX_ALLOW_NON_PADDED_VOLUMES = "powerflex_allow_non_padded_volumes"
POWERFLEX_ALLOW_MIGRATION_DURING_REBUILD = (
    "powerflex_allow_migration_during_rebuild")

deprecated_opts = [
    cfg.PortOpt(VXFLEXOS_REST_SERVER_PORT,
                default=443,
                help='renamed to %s.' %
                     POWERFLEX_REST_SERVER_PORT,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  POWERFLEX_REST_SERVER_PORT),
    cfg.BoolOpt(VXFLEXOS_ROUND_VOLUME_CAPACITY,
                default=True,
                help='renamed to %s.' %
                     POWERFLEX_ROUND_VOLUME_CAPACITY,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  POWERFLEX_ROUND_VOLUME_CAPACITY),
    cfg.BoolOpt(VXFLEXOS_UNMAP_VOLUME_BEFORE_DELETION,
                default=False,
                help='renamed to %s.' %
                     POWERFLEX_ROUND_VOLUME_CAPACITY,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  POWERFLEX_ROUND_VOLUME_CAPACITY),
    cfg.StrOpt(VXFLEXOS_STORAGE_POOLS,
               help='renamed to %s.' %
                    POWERFLEX_STORAGE_POOLS,
               deprecated_for_removal=True,
               deprecated_reason='Replaced by %s.' %
                                 POWERFLEX_STORAGE_POOLS),
    cfg.StrOpt(VXFLEXOS_SERVER_API_VERSION,
               help='renamed to %s.' %
                    POWERFLEX_SERVER_API_VERSION,
               deprecated_for_removal=True,
               deprecated_reason='Replaced by %s.' %
                                 POWERFLEX_SERVER_API_VERSION),
    cfg.FloatOpt(VXFLEXOS_MAX_OVER_SUBSCRIPTION_RATIO,
                 # This option exists to provide a default value for the
                 # PowerFlex driver which is different than the global default.
                 default=10.0,
                 help='renamed to %s.' %
                      POWERFLEX_MAX_OVER_SUBSCRIPTION_RATIO,
                 deprecated_for_removal=True,
                 deprecated_reason='Replaced by %s.' %
                                   POWERFLEX_MAX_OVER_SUBSCRIPTION_RATIO),
    cfg.BoolOpt(VXFLEXOS_ALLOW_NON_PADDED_VOLUMES,
                default=False,
                help='renamed to %s.' %
                     POWERFLEX_ALLOW_NON_PADDED_VOLUMES,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  POWERFLEX_ALLOW_NON_PADDED_VOLUMES),
    cfg.BoolOpt(VXFLEXOS_ALLOW_MIGRATION_DURING_REBUILD,
                default=False,
                help='renamed to %s.' %
                     POWERFLEX_ALLOW_MIGRATION_DURING_REBUILD,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  POWERFLEX_ALLOW_MIGRATION_DURING_REBUILD),
]

actual_opts = [
    cfg.PortOpt(POWERFLEX_REST_SERVER_PORT,
                default=443,
                help='Gateway REST server port.',
                deprecated_name=VXFLEXOS_REST_SERVER_PORT),
    cfg.BoolOpt(POWERFLEX_ROUND_VOLUME_CAPACITY,
                default=True,
                help='Round volume sizes up to 8GB boundaries. '
                     'PowerFlex/VxFlex OS requires volumes to be sized '
                     'in multiples of 8GB. If set to False, volume '
                     'creation will fail for volumes not sized properly',
                deprecated_name=VXFLEXOS_ROUND_VOLUME_CAPACITY
                ),
    cfg.BoolOpt(POWERFLEX_UNMAP_VOLUME_BEFORE_DELETION,
                default=False,
                help='Unmap volumes before deletion.',
                deprecated_name=VXFLEXOS_UNMAP_VOLUME_BEFORE_DELETION),
    cfg.StrOpt(POWERFLEX_STORAGE_POOLS,
               help='Storage Pools. Comma separated list of storage '
                    'pools used to provide volumes. Each pool should '
                    'be specified as a '
                    'protection_domain_name:storage_pool_name value',
               deprecated_name=VXFLEXOS_STORAGE_POOLS),
    cfg.StrOpt(POWERFLEX_SERVER_API_VERSION,
               help='PowerFlex/ScaleIO API version. This value should be '
                    'left as the default value unless otherwise instructed '
                    'by technical support.',
               deprecated_name=VXFLEXOS_SERVER_API_VERSION),
    cfg.FloatOpt(POWERFLEX_MAX_OVER_SUBSCRIPTION_RATIO,
                 # This option exists to provide a default value for the
                 # PowerFlex driver which is different than the global default.
                 default=10.0,
                 help='max_over_subscription_ratio setting for the driver. '
                      'Maximum value allowed is 10.0.',
                 deprecated_name=VXFLEXOS_MAX_OVER_SUBSCRIPTION_RATIO),
    cfg.BoolOpt(POWERFLEX_ALLOW_NON_PADDED_VOLUMES,
                default=False,
                help='Allow volumes to be created in Storage Pools '
                     'when zero padding is disabled. This option should '
                     'not be enabled if multiple tenants will utilize '
                     'volumes from a shared Storage Pool.',
                deprecated_name=VXFLEXOS_ALLOW_NON_PADDED_VOLUMES),
    cfg.BoolOpt(POWERFLEX_ALLOW_MIGRATION_DURING_REBUILD,
                default=False,
                help='Allow volume migration during rebuild.',
                deprecated_name=VXFLEXOS_ALLOW_MIGRATION_DURING_REBUILD),
]
