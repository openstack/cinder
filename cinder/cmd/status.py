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

CONF = cfg.CONF

SUCCESS = uc.Code.SUCCESS
FAILURE = uc.Code.FAILURE
WARNING = uc.Code.WARNING


class Checks(uc.UpgradeCommands):
    """Upgrade checks to run."""

    def _check_placeholder(self):
        """This is just a placeholder to test the test framework."""
        return uc.Result(SUCCESS, 'Some details')

    _upgrade_checks = (
        ('Placeholder', _check_placeholder),
    )


def main():
    return uc.main(CONF, 'cinder', Checks())


if __name__ == '__main__':
    sys.exit(main())
