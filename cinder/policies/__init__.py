# Copyright (c) 2017 Huawei Technologies Co., Ltd.
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

import itertools

from cinder.policies import attachments
from cinder.policies import backup_actions
from cinder.policies import backups
from cinder.policies import base
from cinder.policies import capabilities
from cinder.policies import clusters
from cinder.policies import default_types
from cinder.policies import group_actions
from cinder.policies import group_snapshot_actions
from cinder.policies import group_snapshots
from cinder.policies import group_types
from cinder.policies import groups
from cinder.policies import hosts
from cinder.policies import limits
from cinder.policies import manageable_snapshots
from cinder.policies import manageable_volumes
from cinder.policies import messages
from cinder.policies import qos_specs
from cinder.policies import quota_class
from cinder.policies import quotas
from cinder.policies import scheduler_stats
from cinder.policies import services
from cinder.policies import snapshot_actions
from cinder.policies import snapshot_metadata
from cinder.policies import snapshots
from cinder.policies import type_extra_specs
from cinder.policies import volume_access
from cinder.policies import volume_actions
from cinder.policies import volume_metadata
from cinder.policies import volume_transfer
from cinder.policies import volume_type
from cinder.policies import volumes
from cinder.policies import workers


def list_rules():
    return itertools.chain(
        base.list_rules(),
        attachments.list_rules(),
        messages.list_rules(),
        clusters.list_rules(),
        workers.list_rules(),
        snapshot_metadata.list_rules(),
        snapshots.list_rules(),
        snapshot_actions.list_rules(),
        manageable_snapshots.list_rules(),
        backups.list_rules(),
        backup_actions.list_rules(),
        groups.list_rules(),
        group_types.list_rules(),
        group_snapshots.list_rules(),
        group_snapshot_actions.list_rules(),
        group_actions.list_rules(),
        qos_specs.list_rules(),
        quota_class.list_rules(),
        quotas.list_rules(),
        capabilities.list_rules(),
        services.list_rules(),
        scheduler_stats.list_rules(),
        hosts.list_rules(),
        limits.list_rules(),
        manageable_volumes.list_rules(),
        volume_type.list_rules(),
        volume_access.list_rules(),
        volume_actions.list_rules(),
        volume_transfer.list_rules(),
        volume_metadata.list_rules(),
        type_extra_specs.list_rules(),
        volumes.list_rules(),
        default_types.list_rules(),
    )
