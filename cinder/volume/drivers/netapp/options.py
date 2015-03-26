# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Bob Callaway.  All rights reserved.
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

from oslo_config import cfg

netapp_proxy_opts = [
    cfg.StrOpt('netapp_storage_family',
               default='ontap_cluster',
               choices=['ontap_7mode', 'ontap_cluster', 'eseries'],
               help=('The storage family type used on the storage system; '
                     'valid values are ontap_7mode for using Data ONTAP '
                     'operating in 7-Mode, ontap_cluster for using '
                     'clustered Data ONTAP, or eseries for using E-Series.')),
    cfg.StrOpt('netapp_storage_protocol',
               choices=['iscsi', 'fc', 'nfs'],
               help=('The storage protocol to be used on the data path with '
                     'the storage system.')), ]

netapp_connection_opts = [
    cfg.StrOpt('netapp_server_hostname',
               default=None,
               help='The hostname (or IP address) for the storage system or '
                    'proxy server.'),
    cfg.IntOpt('netapp_server_port',
               default=None,
               help=('The TCP port to use for communication with the storage '
                     'system or proxy server. If not specified, Data ONTAP '
                     'drivers will use 80 for HTTP and 443 for HTTPS; '
                     'E-Series will use 8080 for HTTP and 8443 for HTTPS.')), ]

netapp_transport_opts = [
    cfg.StrOpt('netapp_transport_type',
               default='http',
               choices=['http', 'https'],
               help=('The transport protocol used when communicating with '
                     'the storage system or proxy server.')), ]

netapp_basicauth_opts = [
    cfg.StrOpt('netapp_login',
               default=None,
               help=('Administrative user account name used to access the '
                     'storage system or proxy server.')),
    cfg.StrOpt('netapp_password',
               default=None,
               help=('Password for the administrative user account '
                     'specified in the netapp_login option.'),
               secret=True), ]

netapp_provisioning_opts = [
    cfg.FloatOpt('netapp_size_multiplier',
                 default=1.2,
                 help=('The quantity to be multiplied by the requested '
                       'volume size to ensure enough space is available on '
                       'the virtual storage server (Vserver) to fulfill '
                       'the volume creation request.')),
    cfg.StrOpt('netapp_volume_list',
               default=None,
               help=('This option is only utilized when the storage protocol '
                     'is configured to use iSCSI or FC. This option is used '
                     'to restrict provisioning to the specified controller '
                     'volumes. Specify the value of this option to be a '
                     'comma separated list of NetApp controller volume names '
                     'to be used for provisioning.')), ]

netapp_cluster_opts = [
    cfg.StrOpt('netapp_vserver',
               default=None,
               help=('This option specifies the virtual storage server '
                     '(Vserver) name on the storage cluster on which '
                     'provisioning of block storage volumes should occur.')), ]

netapp_7mode_opts = [
    cfg.StrOpt('netapp_vfiler',
               default=None,
               help=('The vFiler unit on which provisioning of block storage '
                     'volumes will be done. This option is only used by the '
                     'driver when connecting to an instance with a storage '
                     'family of Data ONTAP operating in 7-Mode. Only use this '
                     'option when utilizing the MultiStore feature on the '
                     'NetApp storage system.')),
    cfg.StrOpt('netapp_partner_backend_name',
               default=None,
               help=('The name of the config.conf stanza for a Data ONTAP '
                     '(7-mode) HA partner.  This option is only used by the '
                     'driver when connecting to an instance with a storage '
                     'family of Data ONTAP operating in 7-Mode, and it is '
                     'required if the storage protocol selected is FC.')), ]

netapp_img_cache_opts = [
    cfg.IntOpt('thres_avl_size_perc_start',
               default=20,
               help=('If the percentage of available space for an NFS share '
                     'has dropped below the value specified by this option, '
                     'the NFS image cache will be cleaned.')),
    cfg.IntOpt('thres_avl_size_perc_stop',
               default=60,
               help=('When the percentage of available space on an NFS share '
                     'has reached the percentage specified by this option, '
                     'the driver will stop clearing files from the NFS image '
                     'cache that have not been accessed in the last M '
                     'minutes, where M is the value of the '
                     'expiry_thres_minutes configuration option.')),
    cfg.IntOpt('expiry_thres_minutes',
               default=720,
               help=('This option specifies the threshold for last access '
                     'time for images in the NFS image cache. When a cache '
                     'cleaning cycle begins, images in the cache that have '
                     'not been accessed in the last M minutes, where M is '
                     'the value of this parameter, will be deleted from the '
                     'cache to create free space on the NFS share.')), ]

netapp_eseries_opts = [
    cfg.StrOpt('netapp_webservice_path',
               default='/devmgr/v2',
               help=('This option is used to specify the path to the E-Series '
                     'proxy application on a proxy server. The value is '
                     'combined with the value of the netapp_transport_type, '
                     'netapp_server_hostname, and netapp_server_port options '
                     'to create the URL used by the driver to connect to the '
                     'proxy application.')),
    cfg.StrOpt('netapp_controller_ips',
               default=None,
               help=('This option is only utilized when the storage family '
                     'is configured to eseries. This option is used to '
                     'restrict provisioning to the specified controllers. '
                     'Specify the value of this option to be a comma '
                     'separated list of controller hostnames or IP addresses '
                     'to be used for provisioning.')),
    cfg.StrOpt('netapp_sa_password',
               default=None,
               help=('Password for the NetApp E-Series storage array.'),
               secret=True),
    cfg.StrOpt('netapp_storage_pools',
               default=None,
               help=('This option is used to restrict provisioning to the '
                     'specified storage pools. Only dynamic disk pools are '
                     'currently supported. Specify the value of this option to'
                     ' be a comma separated list of disk pool names to be used'
                     ' for provisioning.')),
    cfg.StrOpt('netapp_eseries_host_type',
               default='linux_dm_mp',
               help=('This option is used to define how the controllers in '
                     'the E-Series storage array will work with the '
                     'particular operating system on the hosts that are '
                     'connected to it.')), ]
netapp_nfs_extra_opts = [
    cfg.StrOpt('netapp_copyoffload_tool_path',
               default=None,
               help=('This option specifies the path of the NetApp copy '
                     'offload tool binary. Ensure that the binary has execute '
                     'permissions set which allow the effective user of the '
                     'cinder-volume process to execute the file.')), ]

CONF = cfg.CONF
CONF.register_opts(netapp_proxy_opts)
CONF.register_opts(netapp_connection_opts)
CONF.register_opts(netapp_transport_opts)
CONF.register_opts(netapp_basicauth_opts)
CONF.register_opts(netapp_cluster_opts)
CONF.register_opts(netapp_7mode_opts)
CONF.register_opts(netapp_provisioning_opts)
CONF.register_opts(netapp_img_cache_opts)
CONF.register_opts(netapp_eseries_opts)
CONF.register_opts(netapp_nfs_extra_opts)
