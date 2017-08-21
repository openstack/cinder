..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Storage Volumes, Disks
======================

.. note::
   TODO(todd or vish): rework after iSCSI merge (see 'Old Docs') (todd or vish)


The :mod:`cinder.volume.manager` Module
---------------------------------------

.. automodule:: cinder.volume.manager
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cinder.volume.driver` Module
--------------------------------------

.. automodule:: cinder.volume.driver
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

Tests
-----

The :mod:`cinder.tests.unit.volume` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.unit.volume
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

Old Docs
--------

Cinder uses iSCSI to export storage volumes from multiple storage nodes. These iSCSI exports are attached (using libvirt) directly to running instances.

Cinder volumes are exported over the primary system VLAN (usually VLAN 1), and not over individual VLANs.

The underlying volumes by default are LVM logical volumes, created on demand within a single large volume group.


