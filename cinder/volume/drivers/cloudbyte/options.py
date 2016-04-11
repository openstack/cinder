# Copyright 2015 CloudByte Inc.
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

cloudbyte_connection_opts = [
    cfg.StrOpt("cb_apikey",
               help="Driver will use this API key to authenticate "
                    "against the CloudByte storage's management interface."),
    cfg.StrOpt("cb_account_name",
               help="CloudByte storage specific account name. "
                    "This maps to a project name in OpenStack."),
    cfg.StrOpt("cb_tsm_name",
               help="This corresponds to the name of "
                    "Tenant Storage Machine (TSM) in CloudByte storage. "
                    "A volume will be created in this TSM."),
    cfg.IntOpt("cb_confirm_volume_create_retry_interval",
               default=5,
               help="A retry value in seconds. Will be used by the driver "
                    "to check if volume creation was successful in "
                    "CloudByte storage."),
    cfg.IntOpt("cb_confirm_volume_create_retries",
               default=3,
               help="Will confirm a successful volume "
                    "creation in CloudByte storage by making "
                    "this many number of attempts."),
    cfg.IntOpt("cb_confirm_volume_delete_retry_interval",
               default=5,
               help="A retry value in seconds. Will be used by the driver "
                    "to check if volume deletion was successful in "
                    "CloudByte storage."),
    cfg.IntOpt("cb_confirm_volume_delete_retries",
               default=3,
               help="Will confirm a successful volume "
                    "deletion in CloudByte storage by making "
                    "this many number of attempts."),
    cfg.StrOpt("cb_auth_group",
               help="This corresponds to the discovery authentication "
                    "group in CloudByte storage. "
                    "Chap users are added to this group. "
                    "Driver uses the first user found for this group. "
                    "Default value is None."), ]

cloudbyte_add_qosgroup_opts = [
    cfg.DictOpt('cb_add_qosgroup',
                default={
                    'iops': '10',
                    'latency': '15',
                    'graceallowed': 'false',
                    'networkspeed': '0',
                    'memlimit': '0',
                    'tpcontrol': 'false',
                    'throughput': '0',
                    'iopscontrol': 'true'
                },
                help="These values will be used for CloudByte storage's "
                     "addQos API call."), ]

cloudbyte_create_volume_opts = [
    cfg.DictOpt('cb_create_volume',
                default={
                    'blocklength': '512B',
                    'compression': 'off',
                    'deduplication': 'off',
                    'sync': 'always',
                    'recordsize': '16k',
                    'protocoltype': 'ISCSI'
                },
                help="These values will be used for CloudByte storage's "
                     "createVolume API call."), ]

cloudbyte_update_volume_opts = [
    cfg.ListOpt('cb_update_qos_group',
                default=["iops", "latency", "graceallowed"],
                help="These values will be used for CloudByte storage's "
                     "updateQosGroup API call."),
    cfg.ListOpt('cb_update_file_system',
                default=["compression", "sync", "noofcopies", "readonly"],
                help="These values will be used for CloudByte storage's "
                     "updateFileSystem API call."), ]

CONF = cfg.CONF
CONF.register_opts(cloudbyte_add_qosgroup_opts)
CONF.register_opts(cloudbyte_create_volume_opts)
CONF.register_opts(cloudbyte_connection_opts)
CONF.register_opts(cloudbyte_update_volume_opts)
