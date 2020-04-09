# Copyright (c) 2017-2019 Dell Inc. or its subsidiaries.
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
Configuration options for Dell EMC VxFlex OS (formerly
named Dell EMC ScaleIO).
"""

from oslo_config import cfg

# deprecated options
SIO_REST_SERVER_PORT = "sio_rest_server_port"
SIO_VERIFY_SERVER_CERTIFICATE = "sio_verify_server_certificate"
SIO_SERVER_CERTIFICATE_PATH = "sio_server_certificate_path"
SIO_ROUND_VOLUME_CAPACITY = "sio_round_volume_capacity"
SIO_UNMAP_VOLUME_BEFORE_DELETION = "sio_unmap_volume_before_deletion"
SIO_STORAGE_POOLS = "sio_storage_pools"
SIO_SERVER_API_VERSION = "sio_server_api_version"
SIO_MAX_OVER_SUBSCRIPTION_RATIO = "sio_max_over_subscription_ratio"
SIO_ALLOW_NON_PADDED_VOLUMES = "sio_allow_non_padded_volumes"

# actual options
VXFLEXOS_REST_SERVER_PORT = "vxflexos_rest_server_port"
VXFLEXOS_ROUND_VOLUME_CAPACITY = "vxflexos_round_volume_capacity"
VXFLEXOS_UNMAP_VOLUME_BEFORE_DELETION = "vxflexos_unmap_volume_before_deletion"
VXFLEXOS_STORAGE_POOLS = "vxflexos_storage_pools"
VXFLEXOS_SERVER_API_VERSION = "vxflexos_server_api_version"
VXFLEXOS_MAX_OVER_SUBSCRIPTION_RATIO = "vxflexos_max_over_subscription_ratio"
VXFLEXOS_ALLOW_NON_PADDED_VOLUMES = "vxflexos_allow_non_padded_volumes"
VXFLEXOS_ALLOW_MIGRATION_DURING_REBUILD = (
    "vxflexos_allow_migration_during_rebuild"
)

deprecated_opts = [
    cfg.PortOpt(SIO_REST_SERVER_PORT,
                default=443,
                help='renamed to %s.' %
                     VXFLEXOS_REST_SERVER_PORT,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  VXFLEXOS_REST_SERVER_PORT),
    cfg.BoolOpt(SIO_VERIFY_SERVER_CERTIFICATE,
                default=False,
                help='Deprecated, use driver_ssl_cert_verify instead.',
                deprecated_for_removal=True,
                deprecated_reason='Replaced by driver_ssl_cert_verify'),
    cfg.StrOpt(SIO_SERVER_CERTIFICATE_PATH,
               help='Deprecated, use driver_ssl_cert_path instead.',
               deprecated_for_removal=True,
               deprecated_reason='Replaced by driver_ssl_cert_path'),
    cfg.BoolOpt(SIO_ROUND_VOLUME_CAPACITY,
                default=True,
                help='renamed to %s.' %
                     VXFLEXOS_ROUND_VOLUME_CAPACITY,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  VXFLEXOS_ROUND_VOLUME_CAPACITY),
    cfg.BoolOpt(SIO_UNMAP_VOLUME_BEFORE_DELETION,
                default=False,
                help='renamed to %s.' %
                     VXFLEXOS_UNMAP_VOLUME_BEFORE_DELETION,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  VXFLEXOS_UNMAP_VOLUME_BEFORE_DELETION),
    cfg.StrOpt(SIO_STORAGE_POOLS,
               help='renamed to %s.' %
                    VXFLEXOS_STORAGE_POOLS,
               deprecated_for_removal=True,
               deprecated_reason='Replaced by %s.' %
                                 VXFLEXOS_STORAGE_POOLS),
    cfg.StrOpt(SIO_SERVER_API_VERSION,
               help='renamed to %s.' %
                    VXFLEXOS_SERVER_API_VERSION,
               deprecated_for_removal=True,
               deprecated_reason='Replaced by %s.' %
                                 VXFLEXOS_SERVER_API_VERSION),
    cfg.FloatOpt(SIO_MAX_OVER_SUBSCRIPTION_RATIO,
                 # This option exists to provide a default value for the
                 # VxFlex OS driver which is different than the global default.
                 default=10.0,
                 help='renamed to %s.' %
                      VXFLEXOS_MAX_OVER_SUBSCRIPTION_RATIO,
                 deprecated_for_removal=True,
                 deprecated_reason='Replaced by %s.' %
                                   VXFLEXOS_MAX_OVER_SUBSCRIPTION_RATIO),
    cfg.BoolOpt(SIO_ALLOW_NON_PADDED_VOLUMES,
                default=False,
                help='renamed to %s.' %
                     VXFLEXOS_ALLOW_NON_PADDED_VOLUMES,
                deprecated_for_removal=True,
                deprecated_reason='Replaced by %s.' %
                                  VXFLEXOS_ALLOW_NON_PADDED_VOLUMES),
]

actual_opts = [
    cfg.PortOpt(VXFLEXOS_REST_SERVER_PORT,
                default=443,
                help='Gateway REST server port.',
                deprecated_name=SIO_REST_SERVER_PORT),
    cfg.BoolOpt(VXFLEXOS_ROUND_VOLUME_CAPACITY,
                default=True,
                help='Round volume sizes up to 8GB boundaries. '
                     'VxFlex OS/ScaleIO requires volumes to be sized '
                     'in multiples of 8GB. If set to False, volume '
                     'creation will fail for volumes not sized properly',
                deprecated_name=SIO_ROUND_VOLUME_CAPACITY
                ),
    cfg.BoolOpt(VXFLEXOS_UNMAP_VOLUME_BEFORE_DELETION,
                default=False,
                help='Unmap volumes before deletion.',
                deprecated_name=SIO_UNMAP_VOLUME_BEFORE_DELETION),
    cfg.StrOpt(VXFLEXOS_STORAGE_POOLS,
               help='Storage Pools. Comma separated list of storage '
                    'pools used to provide volumes. Each pool should '
                    'be specified as a '
                    'protection_domain_name:storage_pool_name value',
               deprecated_name=SIO_STORAGE_POOLS),
    cfg.StrOpt(VXFLEXOS_SERVER_API_VERSION,
               help='VxFlex OS/ScaleIO API version. This value should be '
                    'left as the default value unless otherwise instructed '
                    'by technical support.',
               deprecated_name=SIO_SERVER_API_VERSION),
    cfg.FloatOpt(VXFLEXOS_MAX_OVER_SUBSCRIPTION_RATIO,
                 # This option exists to provide a default value for the
                 # VxFlex OS driver which is different than the global default.
                 default=10.0,
                 help='max_over_subscription_ratio setting for the driver. '
                      'Maximum value allowed is 10.0.',
                 deprecated_name=SIO_MAX_OVER_SUBSCRIPTION_RATIO),
    cfg.BoolOpt(VXFLEXOS_ALLOW_NON_PADDED_VOLUMES,
                default=False,
                help='Allow volumes to be created in Storage Pools '
                     'when zero padding is disabled. This option should '
                     'not be enabled if multiple tenants will utilize '
                     'volumes from a shared Storage Pool.',
                deprecated_name=SIO_ALLOW_NON_PADDED_VOLUMES),
    cfg.BoolOpt(VXFLEXOS_ALLOW_MIGRATION_DURING_REBUILD,
                default=False,
                help='Allow volume migration during rebuild.'),
]
