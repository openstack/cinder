# Copyright (C) 2018 NTT DATA
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
Schema for V3 admin_actions API.

"""

import copy


from cinder.api.validation import parameter_types


reset = {
    'type': 'object',
    'properties': {
        'os-reset_status': {
            'type': 'object',
            'format': 'validate_volume_reset_body',
            'properties': {
                'status': {'type': ['string', 'null'],
                           'format': 'volume_status'},
                'attach_status': {'type': ['string', 'null'],
                                  'format': 'volume_attach_status'},
                'migration_status': {'type': ['string', 'null'],
                                     'format': 'volume_migration_status'},
            },
            'additionalProperties': False,
        },
    },
    'required': ['os-reset_status'],
    'additionalProperties': False,
}

force_detach = {
    'type': 'object',
    'properties': {
        'os-force_detach': {
            'type': 'object',
            'properties': {
                'connector': {'type': ['string', 'object', 'null']},
                'attachment_id': {'type': ['string', 'null']}
            },
            'additionalProperties': False,
        },
    },
    'required': ['os-force_detach'],
    'additionalProperties': False,
}


migrate_volume = {
    'type': 'object',
    'properties': {
        'os-migrate_volume': {
            'type': 'object',
            'properties': {
                'host': {'type': 'string', 'maxLength': 255},
                'force_host_copy': parameter_types.boolean,
                'lock_volume': parameter_types.boolean,
            },
            'required': ['host'],
            'additionalProperties': False,
        },
    },
    'required': ['os-migrate_volume'],
    'additionalProperties': False,
}


migrate_volume_v316 = {
    'type': 'object',
    'properties': {
        'os-migrate_volume': {
            'type': 'object',
            'properties': {
                'host': {'type': ['string', 'null'],
                         'maxLength': 255},
                'force_host_copy': parameter_types.boolean,
                'lock_volume': parameter_types.boolean,
                'cluster': parameter_types.name_allow_zero_min_length,
            },
            'additionalProperties': False,
        },
    },
    'required': ['os-migrate_volume'],
    'additionalProperties': False,
}


migrate_volume_completion = {
    'type': 'object',
    'properties': {
        'os-migrate_volume_completion': {
            'type': 'object',
            'properties': {
                'new_volume': parameter_types.uuid,
                'error': {'type': ['string', 'null', 'boolean']},
            },
            'required': ['new_volume'],
            'additionalProperties': False,
        },
    },
    'required': ['os-migrate_volume_completion'],
    'additionalProperties': False,
}


reset_status_backup = {
    'type': 'object',
    'properties': {
        'os-reset_status': {
            'type': 'object',
            'properties': {
                'status': {'type': 'string',
                           'format': 'backup_status'},
            },
            'required': ['status'],
            'additionalProperties': False,
        },
    },
    'required': ['os-reset_status'],
    'additionalProperties': False,
}

reset_status_snapshot = copy.deepcopy(reset_status_backup)
reset_status_snapshot['properties']['os-reset_status'][
    'properties']['status']['format'] = 'snapshot_status'
