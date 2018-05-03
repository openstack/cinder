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
Schema for V3 volume_actions API.

"""

import copy

from cinder.api.validation import parameter_types


container_format = parameter_types.description

extend = {
    'type': 'object',
    'properties': {
        'os-extend': {
            'type': 'object',
            'properties': {
                'new_size': parameter_types.volume_size,
            },
            'required': ['new_size'],
            'additionalProperties': False,
        },
    },
    'required': ['os-extend'],
    'additionalProperties': False,
}


attach = {
    'type': 'object',
    'properties': {
        'os-attach': {
            'type': 'object',
            'properties': {
                'instance_uuid': parameter_types.uuid,
                'mountpoint': {
                    'type': 'string', 'minLength': 1,
                    'maxLength': 255
                },
                'host_name': {'type': 'string', 'maxLength': 255},
                'mode': {'type': 'string', 'enum': ['rw', 'ro']}
            },
            'required': ['mountpoint'],
            'anyOf': [{'required': ['instance_uuid']},
                      {'required': ['host_name']}],
            'additionalProperties': False,
        },
    },
    'required': ['os-attach'],
    'additionalProperties': False,
}


detach = {
    'type': 'object',
    'properties': {
        'os-detach': {
            'type': ['object', 'null'],
            'properties': {
                # NOTE(mriedem): This allows null for backward compatibility.
                'attachment_id': parameter_types.uuid_allow_null,
            },
            'additionalProperties': False,
        },
    },
    'required': ['os-detach'],
    'additionalProperties': False,
}


retype = {
    'type': 'object',
    'properties': {
        'os-retype': {
            'type': 'object',
            'properties': {
                'new_type': {'type': 'string'},
                'migration_policy': {
                    'type': ['string', 'null'],
                    'enum': ['on-demand', 'never']},
            },
            'required': ['new_type'],
            'additionalProperties': False,
        },
    },
    'required': ['os-retype'],
    'additionalProperties': False,
}


set_bootable = {
    'type': 'object',
    'properties': {
        'os-set_bootable': {
            'type': 'object',
            'properties': {
                'bootable': parameter_types.boolean
            },
            'required': ['bootable'],
            'additionalProperties': False,
        },
    },
    'required': ['os-set_bootable'],
    'additionalProperties': False,
}


volume_upload_image = {
    'type': 'object',
    'properties': {
        'os-volume_upload_image': {
            'type': 'object',
            'properties': {
                'image_name': {
                    'type': 'string', 'minLength': 1, 'maxLength': 255
                },
                'force': parameter_types.boolean,
                'disk_format': {
                    'type': 'string',
                    'enum': ['raw', 'vmdk', 'vdi', 'qcow2',
                             'vhd', 'vhdx', 'ploop']
                },
                'container_format': container_format
            },
            'required': ['image_name'],
            'additionalProperties': False,
        },
    },
    'required': ['os-volume_upload_image'],
    'additionalProperties': False,
}

volume_upload_image_v31 = copy.deepcopy(volume_upload_image)
volume_upload_image_v31['properties']['os-volume_upload_image']['properties'][
    'visibility'] = {'type': 'string',
                     'enum': ['community', 'public', 'private', 'shared']}
volume_upload_image_v31['properties']['os-volume_upload_image']['properties'][
    'protected'] = parameter_types.boolean


initialize_connection = {
    'type': 'object',
    'properties': {
        'os-initialize_connection': {
            'type': 'object',
            'properties': {
                'connector': {'type': ['object', 'string']},
            },
            'required': ['connector'],
            'additionalProperties': False,
        },
    },
    'required': ['os-initialize_connection'],
    'additionalProperties': False,
}


terminate_connection = {
    'type': 'object',
    'properties': {
        'os-terminate_connection': {
            'type': 'object',
            'properties': {
                'connector': {'type': ['string', 'object', 'null']},
            },
            'required': ['connector'],
            'additionalProperties': False,
        },
    },
    'required': ['os-terminate_connection'],
    'additionalProperties': False,
}

volume_readonly_update = {
    'type': 'object',
    'properties': {
        'os-update_readonly_flag': {
            'type': 'object',
            'properties': {
                'readonly': parameter_types.boolean
            },
            'required': ['readonly'],
            'additionalProperties': False,
        },
    },
    'required': ['os-update_readonly_flag'],
    'additionalProperties': False,
}
