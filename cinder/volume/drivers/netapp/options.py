# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2012 OpenStack Foundation
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

"""Contains configuration options for NetApp drivers.

Common place to hold configuration options for all NetApp drivers.
Options need to be grouped into granular units to be able to be reused
by different modules and classes. This does not restrict declaring options in
individual modules. If options are not re usable then can be declared in
individual modules. It is recommended to Keep options at a single
place to ensure re usability and better management of configuration options.
"""

from oslo.config import cfg

netapp_proxy_opts = [
    cfg.StrOpt('netapp_storage_family',
               default='ontap_cluster',
               help='Storage family type.'),
    cfg.StrOpt('netapp_storage_protocol',
               default=None,
               help='Storage protocol type.'), ]

netapp_connection_opts = [
    cfg.StrOpt('netapp_server_hostname',
               default=None,
               help='Host name for the storage controller'),
    cfg.IntOpt('netapp_server_port',
               default=80,
               help='Port number for the storage controller'), ]

netapp_transport_opts = [
    cfg.StrOpt('netapp_transport_type',
               default='http',
               help='Transport type protocol'), ]

netapp_basicauth_opts = [
    cfg.StrOpt('netapp_login',
               default=None,
               help='User name for the storage controller'),
    cfg.StrOpt('netapp_password',
               default=None,
               help='Password for the storage controller',
               secret=True), ]

netapp_provisioning_opts = [
    cfg.FloatOpt('netapp_size_multiplier',
                 default=1.2,
                 help='Volume size multiplier to ensure while creation'),
    cfg.StrOpt('netapp_volume_list',
               default=None,
               help='Comma separated volumes to be used for provisioning'), ]

netapp_cluster_opts = [
    cfg.StrOpt('netapp_vserver',
               default=None,
               help='Cluster vserver to use for provisioning'), ]

netapp_7mode_opts = [
    cfg.StrOpt('netapp_vfiler',
               default=None,
               help='Vfiler to use for provisioning'), ]

netapp_img_cache_opts = [
    cfg.IntOpt('thres_avl_size_perc_start',
               default=20,
               help='Threshold available percent to start cache cleaning.'),
    cfg.IntOpt('thres_avl_size_perc_stop',
               default=60,
               help='Threshold available percent to stop cache cleaning.'),
    cfg.IntOpt('expiry_thres_minutes',
               default=720,
               help='Threshold minutes after which '
               'cache file can be cleaned.'), ]
