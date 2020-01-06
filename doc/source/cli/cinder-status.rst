=============
cinder-status
=============

----------------------------------------
CLI interface for cinder status commands
----------------------------------------

:Author: openstack-discuss@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  cinder-status <category> <command> [<args>]

Description
===========

:program:`cinder-status` is a tool that provides routines for checking the
status of a Cinder deployment.

Options
=======

The standard pattern for executing a :program:`cinder-status` command is::

    cinder-status <category> <command> [<args>]

Run without arguments to see a list of available command categories::

    cinder-status

Categories are:

* ``upgrade``

Detailed descriptions are below.

You can also run with a category argument such as ``upgrade`` to see a list of
all commands in that category::

    cinder-status upgrade

These sections describe the available categories and arguments for
:program:`cinder-status`.

Upgrade
~~~~~~~

.. _cinder-status-checks:

``cinder-status upgrade check``
  Performs a release-specific readiness check before restarting services with
  new code. This command expects to have complete configuration and access
  to the database. It may also make requests to other services' REST API via
  the Keystone service catalog.

  **Return Codes**

  .. list-table::
     :widths: 20 80
     :header-rows: 1

     * - Return code
       - Description
     * - 0
       - All upgrade readiness checks passed successfully and there is nothing
         to do.
     * - 1
       - At least one check encountered an issue and requires further
         investigation. This is considered a warning but the upgrade may be OK.
     * - 2
       - There was an upgrade status check failure that needs to be
         investigated. This should be considered something that stops an
         upgrade.
     * - 255
       - An unexpected error occurred.

  **History of Checks**

  **14.0.0 (Stein)**

  * Check added to ensure the backup_driver setting is using the full driver
    class path and not just the module path.
  * Checks for the presence of a **policy.json** file have been added to warn
    if policy changes should be present in a **policy.yaml** file.
  * Ensure that correct volume_driver path is used for Windows iSCSI driver.
  * Ensure that none of the volume drivers removed in Stein are enabled.
    Please note that if a driver is in **cinder.conf** but not in the
    ``enabled_drivers`` config option this check will not catch the problem.
    If you have used the CoprHD, ITRI Disco or HGST drivers in the past you
    should ensure that any data from these backends is transferred to a
    supported storage array before upgrade.

  **15.0.0 (Train)**

  * Check added to make operators aware of new finer-grained configuration
    options affecting the periodicity of various Cinder tasks.  Triggered
    when the ``periodic_interval`` option is not set to its default value.
  * Added check for use of deprecated ``cinder.quota.NestedDbQuotaDriver``.

See Also
========

* `OpenStack Cinder <https://docs.openstack.org/cinder/>`_

Bugs
====

* Cinder bugs are managed at `Launchpad <https://bugs.launchpad.net/cinder>`_
