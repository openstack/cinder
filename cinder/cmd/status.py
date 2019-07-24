# Copyright 2018 Huawei Technologies Co., Ltd.
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

"""CLI interface for cinder status commands."""

import os
import sys

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder import service  # noqa
from oslo_config import cfg
from oslo_upgradecheck import upgradecheck as uc

from cinder.policy import DEFAULT_POLICY_FILENAME
import cinder.service  # noqa

# We must first register Cinder's objects. Otherwise
# we cannot import the volume manager.
objects.register_all()

import cinder.volume.manager as volume_manager

CONF = cfg.CONF

SUCCESS = uc.Code.SUCCESS
FAILURE = uc.Code.FAILURE
WARNING = uc.Code.WARNING
REMOVED_DRVRS = ["coprhd",
                 "disco",
                 "hgst", ]


def _get_enabled_drivers():
    """Returns a list of volume_driver entries"""
    volume_drivers = []
    if CONF.enabled_backends:
        for backend in filter(None, CONF.enabled_backends):
            # Each backend group needs to be registered first
            CONF.register_opts(volume_manager.volume_backend_opts,
                               group=backend)
            volume_driver = CONF[backend]['volume_driver']
            volume_drivers.append(volume_driver)

    return volume_drivers


class Checks(uc.UpgradeCommands):
    """Upgrade checks to run."""

    def __init__(self, *args, **kwargs):
        super(Checks, self).__init__(*args, **kwargs)
        self.context = context.get_admin_context()

    def _file_exists(self, path):
        """Helper for mocking check of os.path.exists."""
        return os.path.exists(path)

    def _check_backup_module(self):
        """Checks for the use of backup driver module paths.

        The use of backup modules for setting backup_driver was deprecated and
        we now only allow the full driver path. This checks that there are not
        any remaining settings using the old method.
        """
        # We import here to avoid conf loading order issues with cinder.service
        # above.
        import cinder.backup.manager  # noqa

        backup_driver = CONF.backup_driver

        # Easy check in that a class name will have mixed casing
        if backup_driver == backup_driver.lower():
            return uc.Result(
                FAILURE,
                'Backup driver configuration requires the full path to the '
                'driver, but current setting is using only the module path.')

        return uc.Result(SUCCESS)

    def _check_policy_file(self):
        """Checks if a policy.json file is present.

        With the switch to policy-in-code, policy files should be policy.yaml
        and should only be present if overriding default policy. Just checks
        and warns if the old file is present to make sure they are aware it is
        not being used.
        """
        # make sure we know where to look for the policy file
        config_dir = CONF.find_file('cinder.conf')
        if not config_dir:
            return uc.Result(
                WARNING,
                'Cannot locate your cinder configuration directory. '
                'Please re-run using the --config-dir <dirname> option.')

        policy_file = CONF.oslo_policy.policy_file
        json_file = os.path.join(os.path.dirname(config_dir), 'policy.json')

        if policy_file == DEFAULT_POLICY_FILENAME:
            # Default is being used, check for old json file
            if self._file_exists(json_file):
                return uc.Result(
                    WARNING,
                    'policy.json file is present. Make sure any changes from '
                    'the default policies are present in a policy.yaml file '
                    'instead. If you really intend to use a policy.json file, '
                    'make sure that its absolute path is set as the value of '
                    "the 'policy_file' configuration option in the "
                    '[oslo_policy] section of your cinder.conf file.')

        else:
            # They have configured a custom policy file. It is OK if it does
            # not exist, but we should check and warn about it while we're
            # checking.
            if not policy_file.startswith('/'):
                # policy_file is relative to config_dir
                policy_file = os.path.join(os.path.dirname(config_dir),
                                           policy_file)
            if not self._file_exists(policy_file):
                return uc.Result(
                    WARNING,
                    "Configured policy file '%s' does not exist. This may be "
                    "expected, but default policies will be used until any "
                    "desired overrides are added to the configured file." %
                    policy_file)

        return uc.Result(SUCCESS)

    def _check_legacy_windows_config(self):
        """Checks to ensure that the Windows driver path is properly updated.

        The WindowsDriver was renamed in the Queens release to
        WindowsISCSIDriver to avoid confusion with the SMB driver.
        The backwards compatibility for this has now been removed, so
        any cinder.conf settings still using
        cinder.volume.drivers.windows.windows.WindowsDriver
        must now be updated to use
        cinder.volume.drivers.windows.iscsi.WindowsISCSIDriver.
        """
        for volume_driver in _get_enabled_drivers():
            if (volume_driver ==
                    "cinder.volume.drivers.windows.windows.WindowsDriver"):
                return uc.Result(
                    FAILURE,
                    'Setting volume_driver to '
                    'cinder.volume.drivers.windows.windows.WindowsDriver '
                    'is no longer supported.  Please update to use '
                    'cinder.volume.drivers.windows.iscsi.WindowsISCSIDriver '
                    'in cinder.conf.')

        return uc.Result(SUCCESS)

    def _check_removed_drivers(self):
        """Checks to ensure that no removed drivers are configured.

        Checks start with drivers removed in the Stein release.
        """
        removed_drivers = []
        for volume_driver in _get_enabled_drivers():
            for removed_driver in REMOVED_DRVRS:
                if removed_driver in volume_driver:
                    removed_drivers.append(volume_driver)

        if removed_drivers:
            if len(removed_drivers) > 1:
                return uc.Result(
                    FAILURE,
                    'The following drivers, which no longer exist, were found '
                    'configured in your cinder.conf file:\n%s.\n'
                    'These drivers have been removed and all data should '
                    'be migrated off of the associated backends before '
                    'upgrading Cinder.' % ",\n".join(removed_drivers))
            else:
                return uc.Result(
                    FAILURE,
                    'Found driver %s configured in your cinder.conf file. '
                    'This driver has been removed and all data should '
                    'be migrated off of this backend before upgrading '
                    'Cinder.' % removed_drivers[0])

        return uc.Result(SUCCESS)

    def _check_service_uuid(self):
        try:
            db.service_get_by_uuid(self.context, None)
        except exception.ServiceNotFound:
            volumes = db.volume_get_all(self.context,
                                        limit=1,
                                        filters={'service_uuid': None})
            if not volumes:
                return uc.Result(SUCCESS)
        return uc.Result(
            FAILURE,
            'Services and volumes must have a service UUID. Please fix this '
            'issue by running Queens online data migrations.')

    def _check_attachment_specs(self):
        if db.attachment_specs_exist(self.context):
            return uc.Result(
                FAILURE,
                'There should be no more AttachmentSpecs in the system. '
                'Please fix this issue by running Queens online data '
                'migrations.')
        return uc.Result(SUCCESS)

    _upgrade_checks = (
        ('Backup Driver Path', _check_backup_module),
        ('Use of Policy File', _check_policy_file),
        ('Windows Driver Path', _check_legacy_windows_config),
        ('Removed Drivers', _check_removed_drivers),
        # added in Train
        ('Service UUIDs', _check_service_uuid),
        ('Attachment specs', _check_attachment_specs),
    )


def main():
    # TODO(rosmaita): need to do this because we suggest using the
    # --config-dir option, and if the user gives a bogus value, we
    # get a stacktrace.  Needs to be fixed in oslo_upgradecheck
    try:
        return uc.main(CONF, 'cinder', Checks())
    except cfg.ConfigDirNotFoundError:
        return('ERROR: cannot read the cinder configuration directory.\n'
               'Please re-run using the --config-dir <dirname> option '
               'with a valid cinder configuration directory.')

if __name__ == '__main__':
    sys.exit(main())
