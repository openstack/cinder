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

import sys

from oslo_config import cfg
from oslo_upgradecheck import upgradecheck as uc

import cinder.service  # noqa


CONF = cfg.CONF

SUCCESS = uc.Code.SUCCESS
FAILURE = uc.Code.FAILURE
WARNING = uc.Code.WARNING


class Checks(uc.UpgradeCommands):
    """Upgrade checks to run."""

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

    _upgrade_checks = (
        ('Backup Driver Path', _check_backup_module),
    )


def main():
    return uc.main(CONF, 'cinder', Checks())


if __name__ == '__main__':
    sys.exit(main())
