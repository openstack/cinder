# Copyright (c) 2016 EMC Corporation.
# All Rights Reserved.
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
"""
VNX Constants

This module includes re-declaration from storops which directly used
by driver in module scope. That's to say:
If a constant from storops is used in class level, function signature,
module level, a re-declaration is needed in this file to avoid some static
import error when storops is not installed.
"""

from oslo_utils import importutils

storops = importutils.try_import('storops')

if storops:
    from storops import exception as storops_ex
    VNXLunPreparingError = storops_ex.VNXLunPreparingError
    VNXTargetNotReadyError = storops_ex.VNXTargetNotReadyError
    MIGRATION_RATE_HIGH = storops.VNXMigrationRate.HIGH
    PROVISION_THICK = storops.VNXProvisionEnum.THICK
else:
    VNXLunPreparingError = None
    MIGRATION_RATE_HIGH = None
    PROVISION_THICK = None
    VNXTargetNotReadyError = None
