# Copyright (C) 2017 NTT DATA
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
Internal implementation of request Body validating middleware.

"""

import re

import jsonschema
from jsonschema import exceptions as jsonschema_exc
from oslo_serialization import base64
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
import webob.exc

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.objects import fields as c_fields
from cinder import quota
from cinder import utils


QUOTAS = quota.QUOTAS
GROUP_QUOTAS = quota.GROUP_QUOTAS
NON_QUOTA_KEYS = quota.NON_QUOTA_KEYS


def _soft_validate_additional_properties(
        validator, additional_properties_value, param_value, schema):
    """Validator function.

    If there are not any properties on the param_value that are not specified
    in the schema, this will return without any effect. If there are any such
    extra properties, they will be handled as follows:

    - if the validator passed to the method is not of type "object", this
      method will return without any effect.
    - if the 'additional_properties_value' parameter is True, this method will
      return without any effect.
    - if the schema has an additionalProperties value of True, the extra
      properties on the param_value will not be touched.
    - if the schema has an additionalProperties value of False and there
      aren't patternProperties specified, the extra properties will be stripped
      from the param_value.
    - if the schema has an additionalProperties value of False and there
      are patternProperties specified, the extra properties will not be
      touched and raise validation error if pattern doesn't match.
    """
    if (not validator.is_type(param_value, "object") or
            additional_properties_value):
        return

    properties = schema.get("properties", {})
    patterns = "|".join(schema.get("patternProperties", {}))
    extra_properties = set()
    for prop in param_value:
        if prop not in properties:
            if patterns:
                if not re.search(patterns, prop):
                    extra_properties.add(prop)
            else:
                extra_properties.add(prop)

    if not extra_properties:
        return

    if patterns:
        error = "Additional properties are not allowed (%s %s unexpected)"
        if len(extra_properties) == 1:
            verb = "was"
        else:
            verb = "were"
        yield jsonschema_exc.ValidationError(
            error % (", ".join(repr(extra) for extra in extra_properties),
                     verb))
    else:
        for prop in extra_properties:
            del param_value[prop]


def _validate_string_length(value, entity_name, mandatory=False,
                            min_length=0, max_length=None,
                            remove_whitespaces=False):
    """Check the length of specified string.

    :param value: the value of the string
    :param entity_name: the name of the string
    :mandatory: string is mandatory or not
    :param min_length: the min_length of the string
    :param max_length: the max_length of the string
    :param remove_whitespaces: True if trimming whitespaces is needed
                                   else False
    """
    if not mandatory and not value:
        return True

    if mandatory and not value:
        msg = _("The '%s' can not be None.") % entity_name
        raise webob.exc.HTTPBadRequest(explanation=msg)

    if remove_whitespaces:
        value = value.strip()

    utils.check_string_length(value, entity_name,
                              min_length=min_length,
                              max_length=max_length)


@jsonschema.FormatChecker.cls_checks('date-time')
def _validate_datetime_format(param_value):
    try:
        timeutils.parse_isotime(param_value)
    except ValueError:
        return False
    else:
        return True


@jsonschema.FormatChecker.cls_checks('name', exception.InvalidName)
def _validate_name(param_value):
    if not param_value:
        msg = _("The 'name' can not be None.")
        raise exception.InvalidName(reason=msg)
    elif len(param_value.strip()) == 0:
        msg = _("The 'name' can not be empty.")
        raise exception.InvalidName(reason=msg)
    return True


@jsonschema.FormatChecker.cls_checks('name_skip_leading_trailing_spaces',
                                     exception.InvalidName)
def _validate_name_skip_leading_trailing_spaces(param_value):
    if not param_value:
        msg = _("The 'name' can not be None.")
        raise exception.InvalidName(reason=msg)
    param_value = param_value.strip()
    if len(param_value) == 0:
        msg = _("The 'name' can not be empty.")
        raise exception.InvalidName(reason=msg)
    elif len(param_value) > 255:
        msg = _("The 'name' can not be greater than 255 characters.")
        raise exception.InvalidInput(reason=msg)
    return True


@jsonschema.FormatChecker.cls_checks('uuid')
def _validate_uuid_format(instance):
    return uuidutils.is_uuid_like(instance)


@jsonschema.FormatChecker.cls_checks('group_snapshot_status')
def _validate_status(param_value):
    if len(param_value.strip()) == 0:
        msg = _("The 'status' can not be empty.")
        raise exception.InvalidGroupSnapshotStatus(reason=msg)
    elif param_value.lower() not in c_fields.GroupSnapshotStatus.ALL:
            msg = _("Group snapshot status: %(status)s is invalid, "
                    "valid statuses are: "
                    "%(valid)s.") % {'status': param_value,
                                     'valid': c_fields.GroupSnapshotStatus.ALL}
            raise exception.InvalidGroupSnapshotStatus(reason=msg)
    return True


@jsonschema.FormatChecker.cls_checks('progress')
def _validate_progress(progress):
    if progress:
        try:
            integer = int(progress[:-1])
        except ValueError:
            msg = _('progress must be an integer percentage')
            raise exception.InvalidInput(reason=msg)
        if integer < 0 or integer > 100 or progress[-1] != '%':
            msg = _('progress must be an integer percentage between'
                    ' 0 and 100')
            raise exception.InvalidInput(reason=msg)
    return True


@jsonschema.FormatChecker.cls_checks('base64')
def _validate_base64_format(instance):
    try:
        if isinstance(instance, six.text_type):
            instance = instance.encode('utf-8')
        base64.decode_as_bytes(instance)
    except TypeError:
        # The name must be string type. If instance isn't string type, the
        # TypeError will be raised at here.
        return False

    return True


@jsonschema.FormatChecker.cls_checks('disabled_reason',
                                     exception.InvalidInput)
def _validate_disabled_reason(param_value):
    _validate_string_length(param_value, 'disabled_reason',
                            mandatory=False, min_length=1, max_length=255,
                            remove_whitespaces=True)
    return True


@jsonschema.FormatChecker.cls_checks(
    'name_non_mandatory_remove_white_spaces')
def _validate_name_non_mandatory_remove_white_spaces(param_value):
    _validate_string_length(param_value, 'name',
                            mandatory=False, min_length=0, max_length=255,
                            remove_whitespaces=True)
    return True


@jsonschema.FormatChecker.cls_checks(
    'description_non_mandatory_remove_white_spaces')
def _validate_description_non_mandatory_remove_white_spaces(param_value):
    _validate_string_length(param_value, 'description',
                            mandatory=False, min_length=0, max_length=255,
                            remove_whitespaces=True)
    return True


@jsonschema.FormatChecker.cls_checks('quota_set')
def _validate_quota_set(quota_set):
    bad_keys = []
    for key, value in quota_set.items():
        if (key not in QUOTAS and key not in GROUP_QUOTAS and key not in
                NON_QUOTA_KEYS):
            bad_keys.append(key)
            continue

        if key in NON_QUOTA_KEYS:
            continue

        utils.validate_integer(value, key, min_value=-1,
                               max_value=db.MAX_INT)

    if len(bad_keys) > 0:
        msg = _("Bad key(s) in quota set: %s") % ", ".join(bad_keys)
        raise exception.InvalidInput(reason=msg)

    return True


@jsonschema.FormatChecker.cls_checks('quota_class_set')
def _validate_quota_class_set(instance):
    bad_keys = []
    for key in instance:
        if key not in QUOTAS and key not in GROUP_QUOTAS:
            bad_keys.append(key)

    if len(bad_keys) > 0:
        msg = _("Bad key(s) in quota class set: %s") % ", ".join(bad_keys)
        raise exception.InvalidInput(reason=msg)

    return True


@jsonschema.FormatChecker.cls_checks(
    'group_status', webob.exc.HTTPBadRequest)
def _validate_group_status(param_value):
    if param_value is None:
        msg = _("The 'status' can not be None.")
        raise webob.exc.HTTPBadRequest(explanation=msg)
    if len(param_value.strip()) == 0:
        msg = _("The 'status' can not be empty.")
        raise exception.InvalidGroupStatus(reason=msg)
    if param_value.lower() not in c_fields.GroupSnapshotStatus.ALL:
        msg = _("Group status: %(status)s is invalid, valid status "
                "are: %(valid)s.") % {'status': param_value,
                                      'valid': c_fields.GroupStatus.ALL}
        raise exception.InvalidGroupStatus(reason=msg)
    return True


@jsonschema.FormatChecker.cls_checks('availability_zone')
def _validate_availability_zone(param_value):
    if param_value is None:
        return True
    _validate_string_length(param_value, "availability_zone",
                            mandatory=True, min_length=1,
                            max_length=255, remove_whitespaces=True)
    return True


@jsonschema.FormatChecker.cls_checks(
    'group_type', (webob.exc.HTTPBadRequest, exception.InvalidInput))
def _validate_group_type(param_value):
    _validate_string_length(param_value, 'group_type',
                            mandatory=True, min_length=1, max_length=255,
                            remove_whitespaces=True)
    return True


@jsonschema.FormatChecker.cls_checks('level')
def _validate_log_level(level):
    utils.get_log_method(level)
    return True


@jsonschema.FormatChecker.cls_checks('validate_volume_reset_body')
def _validate_volume_reset_body(instance):
    status = instance.get('status')
    attach_status = instance.get('attach_status')
    migration_status = instance.get('migration_status')

    if not status and not attach_status and not migration_status:
        msg = _("Must specify 'status', 'attach_status' or 'migration_status'"
                " for update.")
        raise exception.InvalidParameterValue(err=msg)

    return True


@jsonschema.FormatChecker.cls_checks('volume_status')
def _validate_volume_status(param_value):
    if param_value and param_value.lower() not in c_fields.VolumeStatus.ALL:
        msg = _("Volume status: %(status)s is invalid, "
                "valid statuses are: "
                "%(valid)s.") % {'status': param_value,
                                 'valid': c_fields.VolumeStatus.ALL}
        raise exception.InvalidParameterValue(err=msg)
    return True


@jsonschema.FormatChecker.cls_checks('volume_attach_status')
def _validate_volume_attach_status(param_value):
    valid_attach_status = [c_fields.VolumeAttachStatus.ATTACHED,
                           c_fields.VolumeAttachStatus.DETACHED]
    if param_value and param_value.lower() not in valid_attach_status:
        msg = _("Volume attach status: %(status)s is invalid, "
                "valid statuses are: "
                "%(valid)s.") % {'status': param_value,
                                 'valid': valid_attach_status}
        raise exception.InvalidParameterValue(err=msg)
    return True


@jsonschema.FormatChecker.cls_checks('volume_migration_status')
def _validate_volume_migration_status(param_value):
    if param_value and (
            param_value.lower() not in c_fields.VolumeMigrationStatus.ALL):
        msg = _("Volume migration status: %(status)s is invalid, "
                "valid statuses are: "
                "%(valid)s.") % {'status': param_value,
                                 'valid': c_fields.VolumeMigrationStatus.ALL}
        raise exception.InvalidParameterValue(err=msg)
    return True


@jsonschema.FormatChecker.cls_checks('snapshot_status')
def _validate_snapshot_status(param_value):
    if not param_value or (
            param_value.lower() not in c_fields.SnapshotStatus.ALL):
        msg = _("Snapshot status: %(status)s is invalid, "
                "valid statuses are: "
                "%(valid)s.") % {'status': param_value,
                                 'valid': c_fields.SnapshotStatus.ALL}
        raise exception.InvalidParameterValue(err=msg)
    return True


@jsonschema.FormatChecker.cls_checks('backup_status')
def _validate_backup_status(param_value):
    valid_status = [c_fields.BackupStatus.AVAILABLE,
                    c_fields.BackupStatus.ERROR]
    if not param_value or (
            param_value.lower() not in valid_status):
        msg = _("Backup status: %(status)s is invalid, "
                "valid statuses are: "
                "%(valid)s.") % {'status': param_value,
                                 'valid': valid_status}
        raise exception.InvalidParameterValue(err=msg)
    return True


@jsonschema.FormatChecker.cls_checks('key_size')
def _validate_key_size(param_value):
    if param_value is not None:
        if not strutils.is_int_like(param_value):
            raise exception.InvalidInput(reason=(
                _('key_size must be an integer.')))
    return True


class FormatChecker(jsonschema.FormatChecker):
    """A FormatChecker can output the message from cause exception

    We need understandable validation errors messages for users. When a
    custom checker has an exception, the FormatChecker will output a
    readable message provided by the checker.
    """

    def check(self, param_value, format):
        """Check whether the param_value conforms to the given format.

        :argument param_value: the param_value to check
        :type: any primitive type (str, number, bool)
        :argument str format: the format that param_value should conform to
        :raises: :exc:`FormatError` if param_value does not conform to format
        """

        if format not in self.checkers:
            return

        # For safety reasons custom checkers can be registered with
        # allowed exception types. Anything else will fall into the
        # default formatter.
        func, raises = self.checkers[format]
        result, cause = None, None

        try:
            result = func(param_value)
        except raises as e:
            cause = e
        if not result:
            msg = "%r is not a %r" % (param_value, format)
            raise jsonschema_exc.FormatError(msg, cause=cause)


class _SchemaValidator(object):
    """A validator class

    This class is changed from Draft4Validator to validate minimum/maximum
    value of a string number(e.g. '10'). This changes can be removed when
    we tighten up the API definition and the XML conversion.
    Also FormatCheckers are added for checking data formats which would be
    passed through cinder api commonly.

    """
    validator = None
    validator_org = jsonschema.Draft4Validator

    def __init__(self, schema, relax_additional_properties=False):
        validators = {
            'minimum': self._validate_minimum,
            'maximum': self._validate_maximum,
        }
        if relax_additional_properties:
            validators[
                'additionalProperties'] = _soft_validate_additional_properties

        validator_cls = jsonschema.validators.extend(self.validator_org,
                                                     validators)
        format_checker = FormatChecker()
        self.validator = validator_cls(schema, format_checker=format_checker)

    def validate(self, *args, **kwargs):
        try:
            self.validator.validate(*args, **kwargs)
        except jsonschema.ValidationError as ex:
            if isinstance(ex.cause, exception.InvalidName):
                detail = ex.cause.msg
            elif len(ex.path) > 0:
                detail = _("Invalid input for field/attribute %(path)s."
                           " Value: %(value)s. %(message)s") % {
                    'path': ex.path.pop(), 'value': ex.instance,
                    'message': ex.message
                }
            else:
                detail = ex.message
            raise exception.ValidationError(detail=detail)
        except TypeError as ex:
            # NOTE: If passing non string value to patternProperties parameter,
            #       TypeError happens. Here is for catching the TypeError.
            detail = six.text_type(ex)
            raise exception.ValidationError(detail=detail)

    def _number_from_str(self, param_value):
        try:
            value = int(param_value)
        except (ValueError, TypeError):
            try:
                value = float(param_value)
            except (ValueError, TypeError):
                return None
        return value

    def _validate_minimum(self, validator, minimum, param_value, schema):
        param_value = self._number_from_str(param_value)
        if param_value is None:
            return
        return self.validator_org.VALIDATORS['minimum'](validator, minimum,
                                                        param_value, schema)

    def _validate_maximum(self, validator, maximum, param_value, schema):
        param_value = self._number_from_str(param_value)
        if param_value is None:
            return
        return self.validator_org.VALIDATORS['maximum'](validator, maximum,
                                                        param_value, schema)
