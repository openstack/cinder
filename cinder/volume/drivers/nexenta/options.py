# Copyright 2016 Nexenta Systems, Inc.
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

from cinder.volume import configuration as conf

POLL_RETRIES = 5
DEFAULT_ISCSI_PORT = 3260
DEFAULT_HOST_GROUP = 'all'
DEFAULT_TARGET_GROUP = 'all'

NEXENTA_EDGE_OPTS = [
    cfg.StrOpt('nexenta_nbd_symlinks_dir',
               default='/dev/disk/by-path',
               help='NexentaEdge logical path of directory to store symbolic '
                    'links to NBDs'),
    cfg.StrOpt('nexenta_rest_user',
               default='admin',
               help='User name to connect to NexentaEdge.'),
    cfg.StrOpt('nexenta_rest_password',
               default='nexenta',
               help='Password to connect to NexentaEdge.',
               secret=True),
    cfg.StrOpt('nexenta_lun_container',
               default='',
               help='NexentaEdge logical path of bucket for LUNs'),
    cfg.StrOpt('nexenta_iscsi_service',
               default='',
               help='NexentaEdge iSCSI service name'),
    cfg.StrOpt('nexenta_client_address',
               deprecated_for_removal=True,
               deprecated_reason='iSCSI target address should now be set using'
                                 ' the common param target_ip_address.',
               default='',
               help='NexentaEdge iSCSI Gateway client '
               'address for non-VIP service'),
    cfg.IntOpt('nexenta_iops_limit',
               default=0,
               help='NexentaEdge iSCSI LUN object IOPS limit'),
    cfg.IntOpt('nexenta_chunksize',
               default=32768,
               help='NexentaEdge iSCSI LUN object chunk size'),
    cfg.IntOpt('nexenta_replication_count',
               default=3,
               help='NexentaEdge iSCSI LUN object replication count.'),
    cfg.BoolOpt('nexenta_encryption',
                default=False,
                help='Defines whether NexentaEdge iSCSI LUN object '
                     'has encryption enabled.')
]

NEXENTA_CONNECTION_OPTS = [
    cfg.StrOpt('nexenta_rest_address',
               deprecated_for_removal=True,
               deprecated_reason='Rest address should now be set using '
                                 'the common param depending on driver type, '
                                 'san_ip or nas_host',
               default='',
               help='IP address of NexentaEdge management REST API endpoint'),
    cfg.StrOpt('nexenta_host',
               default='',
               help='IP address of Nexenta SA'),
    cfg.IntOpt('nexenta_rest_port',
               deprecated_for_removal=True,
               deprecated_reason='Rest address should now be set using '
                                 'the common param san_api_port.',
               default=0,
               help='HTTP(S) port to connect to Nexenta REST API server. '
                    'If it is equal zero, 8443 for HTTPS and 8080 for HTTP '
                    'is used'),
    cfg.StrOpt('nexenta_rest_protocol',
               default='auto',
               choices=['http', 'https', 'auto'],
               help='Use http or https for REST connection (default auto)'),
    cfg.BoolOpt('nexenta_use_https',
                default=True,
                help='Use secure HTTP for REST connection (default True)'),
    cfg.BoolOpt('nexenta_lu_writebackcache_disabled',
                default=False,
                help='Postponed write to backing store or not'),
    cfg.StrOpt('nexenta_user',
               deprecated_for_removal=True,
               deprecated_reason='Common user parameters should be used '
                                 'depending on the driver type: '
                                 'san_login or nas_login',
               default='admin',
               help='User name to connect to Nexenta SA'),
    cfg.StrOpt('nexenta_password',
               deprecated_for_removal=True,
               deprecated_reason='Common password parameters should be used '
                                 'depending on the driver type: '
                                 'san_password or nas_password',
               default='nexenta',
               help='Password to connect to Nexenta SA',
               secret=True),
]

NEXENTA_ISCSI_OPTS = [
    cfg.StrOpt('nexenta_iscsi_target_portal_groups',
               default='',
               help='Nexenta target portal groups'),
    cfg.StrOpt('nexenta_iscsi_target_portals',
               default='',
               help='Comma separated list of portals for NexentaStor5, in '
                    'format of IP1:port1,IP2:port2. Port is optional, '
                    'default=3260. Example: 10.10.10.1:3267,10.10.1.2'),
    cfg.StrOpt('nexenta_iscsi_target_host_group',
               default='all',
               help='Group of hosts which are allowed to access volumes'),
    cfg.IntOpt('nexenta_iscsi_target_portal_port',
               default=3260,
               help='Nexenta target portal port'),
    cfg.IntOpt('nexenta_luns_per_target',
               default=100,
               help='Amount of iSCSI LUNs per each target'),
    cfg.StrOpt('nexenta_volume',
               default='cinder',
               help='SA Pool that holds all volumes'),
    cfg.StrOpt('nexenta_target_prefix',
               default='iqn.1986-03.com.sun:02:cinder',
               help='IQN prefix for iSCSI targets'),
    cfg.StrOpt('nexenta_target_group_prefix',
               default='cinder',
               help='Prefix for iSCSI target groups on SA'),
    cfg.StrOpt('nexenta_host_group_prefix',
               default='cinder',
               help='Prefix for iSCSI host groups on SA'),
    cfg.StrOpt('nexenta_volume_group',
               default='iscsi',
               help='Volume group for NexentaStor5 iSCSI'),
]

NEXENTA_NFS_OPTS = [
    cfg.StrOpt('nexenta_shares_config',
               default='/etc/cinder/nfs_shares',
               help='File with the list of available nfs shares'),
    cfg.StrOpt('nexenta_mount_point_base',
               default='$state_path/mnt',
               help='Base directory that contains NFS share mount points'),
    cfg.BoolOpt('nexenta_sparsed_volumes',
                default=True,
                help='Enables or disables the creation of volumes as '
                     'sparsed files that take no space. If disabled '
                     '(False), volume is created as a regular file, '
                     'which takes a long time.'),
    cfg.BoolOpt('nexenta_nms_cache_volroot',
                default=True,
                help=('If set True cache NexentaStor appliance volroot option '
                      'value.'))
]

NEXENTA_DATASET_OPTS = [
    cfg.StrOpt('nexenta_dataset_compression',
               default='on',
               choices=['on', 'off', 'gzip', 'gzip-1', 'gzip-2', 'gzip-3',
                        'gzip-4', 'gzip-5', 'gzip-6', 'gzip-7', 'gzip-8',
                        'gzip-9', 'lzjb', 'zle', 'lz4'],
               help='Compression value for new ZFS folders.'),
    cfg.StrOpt('nexenta_dataset_dedup',
               default='off',
               choices=['on', 'off', 'sha256', 'verify', 'sha256, verify'],
               help='Deduplication value for new ZFS folders.'),
    cfg.StrOpt('nexenta_folder',
               default='',
               help='A folder where cinder created datasets will reside.'),
    cfg.StrOpt('nexenta_dataset_description',
               default='',
               help='Human-readable description for the folder.'),
    cfg.IntOpt('nexenta_blocksize',
               default=4096,
               help='Block size for datasets'),
    cfg.IntOpt('nexenta_ns5_blocksize',
               default=32,
               help='Block size for datasets'),
    cfg.BoolOpt('nexenta_sparse',
                default=False,
                help='Enables or disables the creation of sparse datasets'),
]

NEXENTA_RRMGR_OPTS = [
    cfg.IntOpt('nexenta_rrmgr_compression',
               default=0,
               help=('Enable stream compression, level 1..9. 1 - gives best '
                     'speed; 9 - gives best compression.')),
    cfg.IntOpt('nexenta_rrmgr_tcp_buf_size',
               default=4096,
               help='TCP Buffer size in KiloBytes.'),
    cfg.IntOpt('nexenta_rrmgr_connections',
               default=2,
               help='Number of TCP connections.'),
]

CONF = cfg.CONF
CONF.register_opts(NEXENTA_CONNECTION_OPTS, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(NEXENTA_ISCSI_OPTS, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(NEXENTA_DATASET_OPTS, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(NEXENTA_NFS_OPTS, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(NEXENTA_RRMGR_OPTS, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(NEXENTA_EDGE_OPTS, group=conf.SHARED_CONF_GROUP)
