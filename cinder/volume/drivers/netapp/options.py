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
from oslo_config import types

from cinder.volume import configuration as conf

NETAPP_SIZE_MULTIPLIER_DEFAULT = 1.2

netapp_proxy_opts = [
    cfg.StrOpt('netapp_storage_family',
               default='ontap_cluster',
               choices=['ontap_cluster'],
               help=('The storage family type used on the storage system; '
                     'the only valid value is ontap_cluster for using '
                     'clustered Data ONTAP.')),
    cfg.StrOpt('netapp_storage_protocol',
               choices=['iscsi', 'fc', 'nfs', 'nvme'],
               help=('The storage protocol to be used on the data path with '
                     'the storage system.')), ]

netapp_connection_opts = [
    cfg.StrOpt('netapp_server_hostname',
               help='The hostname (or IP address) for the storage system or '
                    'proxy server.'),
    cfg.IntOpt('netapp_server_port',
               help=('The TCP port to use for communication with the storage '
                     'system or proxy server. If not specified, Data ONTAP '
                     'drivers will use 80 for HTTP and 443 for HTTPS.')),
    cfg.BoolOpt('netapp_use_legacy_client',
                default=True,
                help=('Select which ONTAP client to use for retrieving and '
                      'modifying data on the storage. The legacy client '
                      'relies on ZAPI calls. If set to False, the new REST '
                      'client is used, which runs REST calls if supported, '
                      'otherwise falls back to the equivalent ZAPI call.')),
    cfg.IntOpt('netapp_async_rest_timeout',
               min=60,
               default=60,  # One minute
               help='The maximum time in seconds to wait for completing a '
                    'REST asynchronous operation.'), ]

netapp_transport_opts = [
    cfg.StrOpt('netapp_transport_type',
               default='http',
               choices=['http', 'https'],
               help=('The transport protocol used when communicating with '
                     'the storage system or proxy server.')),
    cfg.StrOpt('netapp_ssl_cert_path',
               help=("The path to a CA_BUNDLE file or directory with "
                     "certificates of trusted CA. If set to a directory, it "
                     "must have been processed using the c_rehash utility "
                     "supplied with OpenSSL. If not informed, it will use the "
                     "Mozilla's carefully curated collection of Root "
                     "Certificates for validating the trustworthiness of SSL "
                     "certificates. Only applies with new REST client.")), ]

netapp_basicauth_opts = [
    cfg.StrOpt('netapp_login',
               help=('Administrative user account name used to access the '
                     'storage system or proxy server.')),
    cfg.StrOpt('netapp_password',
               help=('Password for the administrative user account '
                     'specified in the netapp_login option.'),
               secret=True), ]

netapp_certificateauth_opts = [
    cfg.StrOpt('netapp_private_key_file',
               sample_default='/path/to/private_key.key',
               help=("""
                     This option is applicable for both self signed and ca
                     verified certificates.

                     For self signed certificate: Absolute path to the file
                     containing the private key associated with the self
                     signed certificate. It is a sensitive file that should
                     be kept secure and protected. The private key is used
                     to sign the certificate and establish the authenticity
                     and integrity of the certificate during the
                     authentication process.

                     For ca verified certificate: Absolute path to the file
                     containing the private key associated with the
                     certificate. It is generated when creating the
                     certificate signingrequest (CSR) and should be kept
                     secure and protected. The private key is used to sign
                     the CSR and later used to establish secure connections
                     and authenticate the entity.
                     """),
               secret=True),
    cfg.StrOpt('netapp_certificate_file',
               sample_default='/path/to/certificate.pem',
               help=("""
                     This option is applicable for both self signed and ca
                     verified certificates.

                     For self signed certificate: Absolute path to the file
                     containing the self-signed digital certificate itself.
                     It includes information about the entity such as the
                     common name (e.g., domain name), organization details,
                     validity period, and public key. The certificate file
                     is generated based on the private key and is used by
                     clients or systems to verify the entity identity during
                     the authentication process.

                     For ca verified certificate: Absolute path to the file
                     containing the digital certificate issued by the
                     trusted third-party certificate authority (CA). It
                     includes information about the entity identity, public
                     key, and the CA that issued the certificate. The
                     certificate file is used by clients or systems to verify
                     the authenticity and integrity of the entity during the
                     authentication process.
                     """),
               secret=True),
    cfg.StrOpt('netapp_ca_certificate_file',
               sample_default='/path/to/ca_certificate.crt',
               help=("""
                     This option is applicable only for a ca verified
                     certificate.

                     Ca verified file: Absolute path to the file containing
                     the public key certificate of the trusted third-party
                     certificate authority (CA) that issued the certificate.
                     It is used by clients or systems to validate the
                     authenticity of the certificate presented by the
                     entity. The CA certificate file is typically pre
                     configured in the trust store of clients or systems to
                     establish trust in certificates issued by that CA.
                     """),
               secret=True),
    cfg.BoolOpt('netapp_certificate_host_validation',
                default=False,
                help=('This option is used only if netapp_private_key_file'
                      ' and netapp_certificate_file files are passed in the'
                      ' configuration.'
                      ' By default certificate verification is disabled'
                      ' and to verify the certificates please set the value'
                      ' to True.')), ]

netapp_provisioning_opts = [
    cfg.FloatOpt('netapp_size_multiplier',
                 default=NETAPP_SIZE_MULTIPLIER_DEFAULT,
                 help=('The quantity to be multiplied by the requested '
                       'volume size to ensure enough space is available on '
                       'the virtual storage server (Vserver) to fulfill '
                       'the volume creation request.  Note: this option '
                       'is deprecated and will be removed in favor of '
                       '"reserved_percentage" in the Mitaka release.')),
    cfg.StrOpt('netapp_lun_space_reservation',
               default='enabled',
               choices=['enabled', 'disabled'],
               help=('This option determines if storage space is reserved '
                     'for LUN allocation. If enabled, LUNs are thick '
                     'provisioned. If space reservation is disabled, '
                     'storage space is allocated on demand.')),
    cfg.BoolOpt('netapp_driver_reports_provisioned_capacity',
                default=False,
                help=('Set to True for Cinder to query the storage system in '
                      'order to calculate volumes provisioned size, otherwise '
                      'provisioned_capacity_gb will corresponds to the '
                      'value of allocated_capacity_gb (calculated by Cinder '
                      'Core code). Enabling this feature increases '
                      'the number of API calls to the storage and '
                      'requires more processing on host, which may impact '
                      'volume report overall performance.')), ]

netapp_cluster_opts = [
    cfg.StrOpt('netapp_vserver',
               help=('This option specifies the virtual storage server '
                     '(Vserver) name on the storage cluster on which '
                     'provisioning of block storage volumes should occur.')), ]

netapp_img_cache_opts = [
    cfg.IntOpt('netapp_nfs_image_cache_cleanup_interval',
               default=600,
               min=60,
               help=('Sets time in seconds between NFS image cache '
                     'cleanup tasks.')),
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

netapp_nfs_extra_opts = [
    cfg.StrOpt('netapp_copyoffload_tool_path',
               help=('This option specifies the path of the NetApp copy '
                     'offload tool binary. Ensure that the binary has execute '
                     'permissions set which allow the effective user of the '
                     'cinder-volume process to execute the file.'),
               deprecated_for_removal=True,
               deprecated_reason='The CopyOfflload tool is no longer '
                                 'available for downloading.'), ]
netapp_san_opts = [
    cfg.StrOpt('netapp_lun_ostype',
               help=('This option defines the type of operating system that'
                     ' will access a LUN exported from Data ONTAP; it is'
                     ' assigned to the LUN at the time it is created.')),
    cfg.StrOpt('netapp_namespace_ostype',
               help=('This option defines the type of operating system that'
                     ' will access a namespace exported from Data ONTAP; it is'
                     ' assigned to the namespace at the time it is created.')),
    cfg.StrOpt('netapp_host_type',
               help=('This option defines the type of operating system for'
                     ' all initiators that can access a LUN. This information'
                     ' is used when mapping LUNs to individual hosts or'
                     ' groups of hosts.')),
    cfg.StrOpt('netapp_pool_name_search_pattern',
               deprecated_opts=[cfg.DeprecatedOpt(name='netapp_volume_list'),
                                cfg.DeprecatedOpt(name='netapp_storage_pools')
                                ],
               default="(.+)",
               help=('This option is used to restrict provisioning to the '
                     'specified pools. Specify the value of '
                     'this option to be a regular expression which will be '
                     'applied to the names of objects from the storage '
                     'backend which represent pools in Cinder. This option '
                     'is only utilized when the storage protocol is '
                     'configured to use iSCSI or FC.')),
    cfg.IntOpt('netapp_lun_clone_busy_timeout',
               min=0,
               default=30,
               help='Specifies the maximum time (in seconds) to retry'
                    ' the LUN clone operation when an ONTAP "device busy"'
                    ' error occurs.'),
    cfg.IntOpt('netapp_lun_clone_busy_interval',
               min=0,
               default=3,
               help='Specifies the time interval (in seconds) to retry'
                    ' the LUN clone operation when an ONTAP "device busy"'
                    ' error occurs.')]

netapp_replication_opts = [
    cfg.MultiOpt('netapp_replication_aggregate_map',
                 item_type=types.Dict(),
                 help="Multi opt of dictionaries to represent the aggregate "
                      "mapping between source and destination back ends when "
                      "using whole back end replication. For every "
                      "source aggregate associated with a cinder pool (NetApp "
                      "FlexVol/FlexGroup), you would need to specify the "
                      "destination aggregate on the replication target "
                      "device. "
                      "A replication target device is configured with the "
                      "configuration option replication_device. Specify this "
                      "option as many times as you have replication devices. "
                      "Each entry takes the standard dict config form: "
                      "netapp_replication_aggregate_map = "
                      "backend_id:<name_of_replication_device_section>,"
                      "src_aggr_name1:dest_aggr_name1,"
                      "src_aggr_name2:dest_aggr_name2,..."),
    cfg.IntOpt('netapp_snapmirror_quiesce_timeout',
               min=0,
               default=3600,  # One Hour
               help='The maximum time in seconds to wait for existing '
                    'SnapMirror transfers to complete before aborting '
                    'during a failover.'),
    cfg.IntOpt('netapp_replication_volume_online_timeout',
               min=60,
               default=360,  # Default to six minutes
               help='Sets time in seconds to wait for a replication volume '
                    'create to complete and go online.'),
    cfg.StrOpt('netapp_replication_policy',
               default='MirrorAllSnapshots',
               help='This option defines the replication policy to be used '
                    'while creating snapmirror relationship. Default is '
                    'MirrorAllSnapshots which is based on async-mirror.'
                    'User can pass values like Sync, StrictSync for '
                    'synchronous snapmirror relationship (SM-S) to achieve '
                    'zero RPO')]

netapp_support_opts = [
    cfg.StrOpt('netapp_api_trace_pattern',
               default='(.*)',
               help=('A regular expression to limit the API tracing. This '
                     'option is honored only if enabling ``api`` tracing '
                     'with the ``trace_flags`` option. By default, '
                     'all APIs will be traced.')),
]

netapp_migration_opts = [
    cfg.IntOpt('netapp_migrate_volume_timeout',
               default=3600,
               min=30,
               help='Sets time in seconds to wait for storage assisted volume '
                    'migration to complete.'),
]

CONF = cfg.CONF
CONF.register_opts(netapp_proxy_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_connection_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_transport_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_basicauth_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_certificateauth_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_cluster_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_provisioning_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_img_cache_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_nfs_extra_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_san_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_replication_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_support_opts, group=conf.SHARED_CONF_GROUP)
CONF.register_opts(netapp_migration_opts, group=conf.SHARED_CONF_GROUP)
