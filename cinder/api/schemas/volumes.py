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
Schema for V3 Volumes API.

"""
import copy

from cinder.api.validation import parameter_types


create = {
    'type': 'object',
    'properties': {
        'volume': {
            'type': 'object',
            'properties': {
                'name': {'type': ['string', 'null'],
                         'format': 'name_non_mandatory_remove_white_spaces'},
                'description': {
                    'type': ['string', 'null'],
                    'format': 'description_non_mandatory_remove_white_spaces'},
                'display_name': {
                    'type': ['string', 'null'],
                    'format': 'name_non_mandatory_remove_white_spaces'},
                'display_description': {
                    'type': ['string', 'null'],
                    'format':
                        'description_non_mandatory_remove_white_spaces'},
                # volume_type accepts 'id' as well as 'name' so do lazy schema
                # validation for it.
                'volume_type': parameter_types.name_allow_zero_min_length,
                'metadata': parameter_types.metadata_allows_null,
                'snapshot_id': parameter_types.optional_uuid,
                'source_volid': parameter_types.optional_uuid,
                'consistencygroup_id': parameter_types.optional_uuid,
                'size': parameter_types.volume_size_allows_null,
                'availability_zone': parameter_types.availability_zone,
                'multiattach': parameter_types.optional_boolean,
                'image_id': {'type': ['string', 'null'], 'minLength': 0,
                             'maxLength': 255},
                'imageRef': {'type': ['string', 'null'], 'minLength': 0,
                             'maxLength': 255},
            },
            'additionalProperties': True,
        },
        'OS-SCH-HNT:scheduler_hints': {
            'type': ['object', 'null']
        },
    },
    'required': ['volume'],
    'additionalProperties': False,
}


create_volume_v313 = copy.deepcopy(create)
create_volume_v313['properties']['volume']['properties'][
    'group_id'] = {'type': ['string', 'null'], 'minLength': 0,
                   'maxLength': 255}

create_volume_v347 = copy.deepcopy(create_volume_v313)
create_volume_v347['properties']['volume']['properties'][
    'backup_id'] = parameter_types.optional_uuid

create_volume_v353 = copy.deepcopy(create_volume_v347)
create_volume_v353['properties']['volume']['additionalProperties'] = False


update = {
    'type': 'object',
    'properties': {
        'volume': {
            'type': 'object',
            'properties': {
                # The 'name' and 'description' are required to be compatible
                # with v2.
                'name': {
                    'type': ['string', 'null'],
                    'format': 'name_non_mandatory_remove_white_spaces'},
                'description': {
                    'type': ['string', 'null'],
                    'format':
                        'description_non_mandatory_remove_white_spaces'},
                'display_name': {
                    'type': ['string', 'null'],
                    'format': 'name_non_mandatory_remove_white_spaces'},
                'display_description': {
                    'type': ['string', 'null'],
                    'format':
                        'description_non_mandatory_remove_white_spaces'},
                'metadata': parameter_types.extra_specs,
            },
            'additionalProperties': False,
        },
    },
    'required': ['volume'],
    'additionalProperties': False,
}


update_volume_v353 = copy.deepcopy(update)
update_volume_v353['properties']['volume']['anyOf'] = [
    {'required': ['name']},
    {'required': ['description']},
    {'required': ['display_name']},
    {'required': ['display_description']},
    {'required': ['metadata']}]
