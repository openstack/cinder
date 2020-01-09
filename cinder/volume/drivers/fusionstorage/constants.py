# Copyright (c) 2016 Huawei Technologies Co., Ltd.
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

DEFAULT_TIMEOUT = 50
LOGIN_SOCKET_TIMEOUT = 32

CONNECT_ERROR = 403
ERROR_UNAUTHORIZED = 10000003
VOLUME_NOT_EXIST = (31000000, 50150005)

BASIC_URI = '/dsware/service/'
CONF_PATH = "/etc/cinder/cinder.conf"

CONF_ADDRESS = "dsware_rest_url"
CONF_MANAGER_IP = "manager_ips"
CONF_POOLS = "dsware_storage_pools"
CONF_PWD = "san_password"
CONF_USER = "san_login"
