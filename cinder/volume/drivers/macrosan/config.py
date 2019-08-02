# Copyright (c) 2019 MacroSAN Technologies Co., Ltd.
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
"""Volume Drivers Config Registration documents for MacroSAN SAN."""

from oslo_config import cfg


macrosan_opts = [
    # sdas login_info
    cfg.ListOpt('macrosan_sdas_ipaddrs',
                help="MacroSAN sdas devices' ip addresses"),
    cfg.StrOpt('macrosan_sdas_username',
               help="MacroSAN sdas devices' username"),
    cfg.StrOpt('macrosan_sdas_password',
               secret=True,
               help="MacroSAN sdas devices' password"),
    # replication login_info
    cfg.ListOpt('macrosan_replication_ipaddrs',
                help="MacroSAN replication devices' ip addresses"),
    cfg.StrOpt('macrosan_replication_username',
               help="MacroSAN replication devices' username"),
    cfg.StrOpt('macrosan_replication_password',
               secret=True,
               help="MacroSAN replication devices' password"),
    cfg.ListOpt('macrosan_replication_destination_ports',
                sample_default="eth-1:0/eth-1:1, eth-2:0/eth-2:1",
                help="Slave device"),
    # device_features
    cfg.StrOpt('macrosan_pool', quotes=True,
               help='Pool to use for volume creation'),
    cfg.IntOpt('macrosan_thin_lun_extent_size',
               default=8,
               help="Set the thin lun's extent size"),
    cfg.IntOpt('macrosan_thin_lun_low_watermark',
               default=5,
               help="Set the thin lun's low watermark"),
    cfg.IntOpt('macrosan_thin_lun_high_watermark',
               default=20,
               help="Set the thin lun's high watermark"),
    cfg.BoolOpt('macrosan_force_unmap_itl',
                default=True,
                help="Force disconnect while deleting volume"),
    cfg.FloatOpt('macrosan_snapshot_resource_ratio',
                 default=1.0,
                 help="Set snapshot's resource ratio"),
    cfg.BoolOpt('macrosan_log_timing',
                default=True,
                help="Whether enable log timing"),
    # fc connection
    cfg.IntOpt('macrosan_fc_use_sp_port_nr',
               default=1,
               max=4,
               help="The use_sp_port_nr parameter is the number of "
                    "online FC ports used by the single-ended memory "
                    "when the FC connection is established in the switch "
                    "non-all-pass mode. The maximum is 4"),
    cfg.BoolOpt('macrosan_fc_keep_mapped_ports',
                default=True,
                help="In the case of an FC connection, the configuration "
                     "item associated with the port is maintained."),
    # iscsi connection
    cfg.ListOpt('macrosan_client',
                help="""Macrosan iscsi_clients list.
                You can configure multiple clients.
                You can configure it in this format:
                (host; client_name; sp1_iscsi_port; sp2_iscsi_port),
                (host; client_name; sp1_iscsi_port; sp2_iscsi_port)
                Important warning, Client_name has the following requirements:
                    [a-zA-Z0-9.-_:], the maximum number of characters is 31
                E.g:
                (controller1; device1; eth-1:0; eth-2:0),
                (controller2; device2; eth-1:0/eth-1:1; eth-2:0/eth-2:1),
                """),
    cfg.StrOpt('macrosan_client_default',
               help="This is the default connection ports' name for iscsi. "
                    "This default configuration is used "
                    "when no host related information is obtained."
                    "E.g: eth-1:0/eth-1:1; eth-2:0/eth-2:1")
]
