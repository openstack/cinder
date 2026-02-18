# Copyright 2026 DDN, Inc. All rights reserved.
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

"""Configuration options for VMstore Cinder driver."""

from oslo_config import cfg

from cinder.volume import configuration as config

VMSTORE_CONNECTION_OPTS = [
    cfg.StrOpt('vmstore_rest_protocol',
               default='https',
               choices=['http', 'https'],
               help='Vmstore RESTful API interface protocol.'),
    cfg.IntOpt('vmstore_rest_port',
               default=443,
               help='Vmstore RESTful API interface port'),
    cfg.StrOpt('vmstore_user',
               default='admin',
               help='User name to connect to Vmstore RESTful API '
                    'interface.'),
    cfg.StrOpt('vmstore_password',
               secret=True,
               help='User password to connect to Vmstore RESTful API '
                    'interface.'),
    cfg.StrOpt('vmstore_rest_address',
               help='IP address or hostname for management '
                    'communication with Vmstore RESTful API interface.'),
    cfg.FloatOpt('vmstore_rest_connect_timeout',
                 default=30,
                 help='Specifies the time limit (in seconds), within '
                      'which the connection to Vmstore RESTful '
                      'API interface must be established.'),
    cfg.FloatOpt('vmstore_rest_read_timeout',
                 default=300,
                 help='Specifies the time limit (in seconds), '
                      'within which Vmstore RESTful API '
                      'interface must send a response.'),
    cfg.FloatOpt('vmstore_rest_backoff_factor',
                 default=1,
                 help='Specifies the backoff factor to apply between '
                      'connection attempts to Vmstore RESTful '
                      'API interface.'),
    cfg.IntOpt('vmstore_rest_retry_count',
               default=5,
               help='Specifies the number of times to repeat Vmstore '
                    'RESTful API calls in case of connection errors '
                    'or Vmstore appliance retriable errors.'),
    cfg.StrOpt('vmstore_refresh_openstack_region',
               default='RegionOne',
               help='OpenStack region for Vmstore hypervisor refresh call.'),
    cfg.StrOpt('vmstore_openstack_hostname',
               help='OpenStack controller hostname or IP address. '
                    'Used for VMstore hypervisor refresh operations. '
                    'If not set, attempts to resolve from Keystone config.'),
    cfg.IntOpt('vmstore_refresh_retry_count',
               default=1,
               help='Specifies the number of times to repeat Vmstore RESTful '
                    'API call to cinder/host/refresh in case of connection '
                    'errors or Vmstore appliance retriable errors.'),
]

VMSTORE_NFS_OPTS = [
    cfg.BoolOpt('vmstore_qcow2_volumes',
                default=False,
                help='Use qcow2 volumes.'),
    cfg.StrOpt('vmstore_mount_point_base',
               default='$state_path/mnt',
               help='Base directory that contains NFS share mount points.'),
]

VMSTORE_DATASET_OPTS = [
    cfg.BoolOpt('vmstore_sparsed_volumes',
                default=True,
                help='Defines whether the volumes need to be '
                     'thin-provisioned.'),
    cfg.StrOpt('vmstore_dataset_description',
               default='',
               help='Human-readable description for the backend.')
]

VMSTORE_NFS_OPTS += (
    VMSTORE_CONNECTION_OPTS +
    VMSTORE_DATASET_OPTS
)

CONF = cfg.CONF
CONF.register_opts(VMSTORE_NFS_OPTS, group=config.SHARED_CONF_GROUP)
