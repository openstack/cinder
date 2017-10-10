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
from cinder.policies import base
from cinder.policies import clusters
from cinder.policies import manageable_snapshots
from cinder.policies import messages
from cinder.policies import snapshot_actions
from cinder.policies import snapshot_metadata
from cinder.policies import snapshots
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
    )
