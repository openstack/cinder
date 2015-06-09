# Copyright 2010-2011 OpenStack Foundation
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

import datetime


class ViewBuilder(object):
    """OpenStack API base limits view builder."""

    def build(self, rate_limits, absolute_limits):
        rate_limits = self._build_rate_limits(rate_limits)
        absolute_limits = self._build_absolute_limits(absolute_limits)

        output = {
            "limits": {
                "rate": rate_limits,
                "absolute": absolute_limits,
            },
        }

        return output

    def _build_absolute_limits(self, absolute_limits):
        """Builder for absolute limits

        absolute_limits should be given as a dict of limits.
        For example: {"ram": 512, "gigabytes": 1024}.

        """
        limit_names = {
            "ram": ["maxTotalRAMSize"],
            "instances": ["maxTotalInstances"],
            "cores": ["maxTotalCores"],
            "gigabytes": ["maxTotalVolumeGigabytes"],
            "backup_gigabytes": ["maxTotalBackupGigabytes"],
            "volumes": ["maxTotalVolumes"],
            "snapshots": ["maxTotalSnapshots"],
            "backups": ["maxTotalBackups"],
            "key_pairs": ["maxTotalKeypairs"],
            "floating_ips": ["maxTotalFloatingIps"],
            "metadata_items": ["maxServerMeta", "maxImageMeta"],
            "injected_files": ["maxPersonality"],
            "injected_file_content_bytes": ["maxPersonalitySize"],
        }
        limits = {}
        for name, value in absolute_limits.iteritems():
            if name in limit_names and value is not None:
                for name in limit_names[name]:
                    limits[name] = value
        return limits

    def _build_rate_limits(self, rate_limits):
        limits = []
        for rate_limit in rate_limits:
            _rate_limit_key = None
            _rate_limit = self._build_rate_limit(rate_limit)

            # check for existing key
            for limit in limits:
                if (limit["uri"] == rate_limit["URI"] and
                        limit["regex"] == rate_limit["regex"]):
                    _rate_limit_key = limit
                    break

            # ensure we have a key if we didn't find one
            if not _rate_limit_key:
                _rate_limit_key = {
                    "uri": rate_limit["URI"],
                    "regex": rate_limit["regex"],
                    "limit": [],
                }
                limits.append(_rate_limit_key)

            _rate_limit_key["limit"].append(_rate_limit)

        return limits

    def _build_rate_limit(self, rate_limit):
        _get_utc = datetime.datetime.utcfromtimestamp
        next_avail = _get_utc(rate_limit["resetTime"])
        return {
            "verb": rate_limit["verb"],
            "value": rate_limit["value"],
            "remaining": int(rate_limit["remaining"]),
            "unit": rate_limit["unit"],
            "next-available": next_avail.isoformat(),
        }
