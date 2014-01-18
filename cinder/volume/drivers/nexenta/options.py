# Copyright 2013 Nexenta Systems, Inc.
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
:mod:`nexenta.options` -- Contains configuration options for Nexenta drivers.
=============================================================================

.. automodule:: nexenta.options
.. moduleauthor:: Victor Rodionov <victor.rodionov@nexenta.com>
.. moduleauthor:: Yuriy Taraday <yorik.sar@gmail.com>
"""

from oslo.config import cfg


NEXENTA_CONNECTION_OPTIONS = [
    cfg.StrOpt('nexenta_host',
               default='',
               help='IP address of Nexenta SA'),
    cfg.IntOpt('nexenta_rest_port',
               default=2000,
               help='HTTP port to connect to Nexenta REST API server'),
    cfg.StrOpt('nexenta_rest_protocol',
               default='auto',
               help='Use http or https for REST connection (default auto)'),
    cfg.StrOpt('nexenta_user',
               default='admin',
               help='User name to connect to Nexenta SA'),
    cfg.StrOpt('nexenta_password',
               default='nexenta',
               help='Password to connect to Nexenta SA',
               secret=True),
]

NEXENTA_ISCSI_OPTIONS = [
    cfg.IntOpt('nexenta_iscsi_target_portal_port',
               default=3260,
               help='Nexenta target portal port'),
    cfg.StrOpt('nexenta_volume',
               default='cinder',
               help='SA Pool that holds all volumes'),
    cfg.StrOpt('nexenta_target_prefix',
               default='iqn.1986-03.com.sun:02:cinder-',
               help='IQN prefix for iSCSI targets'),
    cfg.StrOpt('nexenta_target_group_prefix',
               default='cinder/',
               help='Prefix for iSCSI target groups on SA'),
]

NEXENTA_NFS_OPTIONS = [
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
    cfg.StrOpt('nexenta_volume_compression',
               default='on',
               help='Default compression value for new ZFS folders.'),
    cfg.BoolOpt('nexenta_nms_cache_volroot',
                default=True,
                help=('If set True cache NexentaStor appliance volroot option '
                      'value.'))
]

NEXENTA_VOLUME_OPTIONS = [
    cfg.StrOpt('nexenta_blocksize',
               default='',
               help='Block size for volumes (default=blank means 8KB)'),
    cfg.BoolOpt('nexenta_sparse',
                default=False,
                help='Enables or disables the creation of sparse volumes'),
]

NEXENTA_RRMGR_OPTIONS = [
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
CONF.register_opts(NEXENTA_CONNECTION_OPTIONS)
CONF.register_opts(NEXENTA_ISCSI_OPTIONS)
CONF.register_opts(NEXENTA_VOLUME_OPTIONS)
CONF.register_opts(NEXENTA_NFS_OPTIONS)
CONF.register_opts(NEXENTA_RRMGR_OPTIONS)
