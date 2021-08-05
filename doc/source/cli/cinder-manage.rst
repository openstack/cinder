=============
cinder-manage
=============

------------------------------------------
Control and manage OpenStack block storage
------------------------------------------

:Author: openstack-discuss@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

cinder-manage <category> <action> [<args>]

DESCRIPTION
===========

:command:`cinder-manage` provides control of cinder database migration,
and provides an interface to get information about the current state
of cinder.
More information about OpenStack Cinder is available at `OpenStack
Cinder <https://docs.openstack.org/cinder/latest/>`_.

OPTIONS
=======

The standard pattern for executing a cinder-manage command is:
``cinder-manage <category> <command> [<args>]``

For example, to obtain a list of the cinder services currently running:
``cinder-manage service list``

Run without arguments to see a list of available command categories:
``cinder-manage``

The categories are listed below, along with detailed descriptions.

You can also run with a category argument such as 'db' to see a list of all
commands in that category:
``cinder-manage db``

These sections describe the available categories and arguments for
cinder-manage.

Cinder Quota
~~~~~~~~~~~~

Cinder quotas sometimes run out of sync, and while there are some mechanisms
in place in Cinder that, with the proper configuration, try to do a resync
of the quotas, they are not perfect and are susceptible to race conditions,
so they may result in less than perfect accuracy in refreshed quotas.

The cinder-manage quota commands are meant to help manage these issues while
allowing a finer control of when and what quotas are fixed.

**Checking if quotas and reservations are correct.**

``cinder-manage quota check [-h] [--project-id PROJECT_ID] [--use-locks]``

Accepted arguments are:

.. code-block:: console

   --project-id PROJECT_ID
                         The ID of the project where we want to sync the quotas
                         (defaults to all projects).
   --use-locks           For precise results tables in the DB need to be
                         locked.

This command checks quotas and reservations, for a specific project (passing
``--project-id``) or for all projects, to see if they are out of sync.

The check will also look for duplicated entries.

By default it runs in the least accurate mode (where races have a higher
chance of happening) to minimize the impact on running cinder services.  This
means that false errors are more likely to be reported due to race conditions
when Cinder services are running.

Accurate mode is also supported, but it will lock many tables (affecting all
tenants) and is not recommended with services that are being used.

One way to use this action in combination with the sync action is to run the
check for all projects, take note of those that are out of sync, and the sync
them one by one at intervals to allow cinder to operate semi-normally.

**Fixing quotas and reservations**

``cinder-manage quota sync [-h] [--project-id PROJECT_ID] [--no-locks]``

Accepted arguments are:

.. code-block:: console

  --project-id PROJECT_ID
                        The ID of the project where we want to sync the quotas
                        (defaults to all projects).
  --no-locks            For less precise results, but also less intrusive.

This command refreshes existing quota usage and reservation count for a
specific project or for all projects.

The refresh will also remove duplicated entries.

This operation is best executed when Cinder is not running, as it requires
locking many tables (affecting all tenants) to make sure that then sync is
accurate.

If accuracy is not our top priority, or we know that a specific project is not
in use, we can disable the locking.

A different transaction is used for each project's quota sync, so an action
failure will only rollback the current project's changes.

Cinder Db
~~~~~~~~~

``cinder-manage db version``

Print the current database version.

``cinder-manage db sync [--bump-versions] [version]``

Sync the database up to the most recent version. This is the standard way to
create the db as well.

This command interprets the following options when it is invoked:

version          Database version

--bump-versions  Update RPC and Objects versions when doing offline
                 upgrades, with this we no longer need to restart the
                 services twice after the upgrade to prevent ServiceTooOld
                 exceptions.

``cinder-manage db purge [<number of days>]``

Purge database entries that are marked as deleted, that are older than the
number of days specified.

``cinder-manage db online_data_migrations [--max_count <n>]``

Perform online data migrations for database upgrade between releases in
batches.

This command interprets the following options when it is invoked:

.. code-block:: console

   --max_count     Maximum number of objects to migrate. If not specified, all
                   possible migrations will be completed, in batches of 50 at a
                   time.

Returns exit status 0 if no (further) updates are possible, 1 if the
``--max_count`` option was used and some updates were completed successfully
(even if others generated errors), 2 if some updates generated errors and no
other migrations were able to take effect in the last batch attempted, or 127
if invalid input is provided (e.g. non-numeric max-count).

This command should be run after upgrading the database schema. If it exits
with partial updates (exit status 1) it should be called again, even if some
updates initially generated errors, because some updates may depend on others
having completed. If it exits with status 2, intervention is required to
resolve the issue causing remaining updates to fail. It should be considered
successfully completed only when the exit status is 0.

Cinder Logs
~~~~~~~~~~~

``cinder-manage logs errors``

Displays cinder errors from log files.

``cinder-manage logs syslog [<number>]``

Displays cinder the most recent entries from syslog.  The optional number
argument specifies the number of entries to display (default 10).

Cinder Volume
~~~~~~~~~~~~~

``cinder-manage volume delete <volume_id>``

Delete a volume without first checking that the volume is available.

``cinder-manage volume update_host --currenthost <current host>
--newhost <new host>``

Updates the host name of all volumes currently associated with a specified
host.

Cinder Host
~~~~~~~~~~~

``cinder-manage host list [<zone>]``

Displays a list of all physical hosts and their zone.  The optional zone
argument allows the list to be filtered on the requested zone.

Cinder Service
~~~~~~~~~~~~~~

``cinder-manage service list``

Displays a list of all cinder services and their host, zone, status, state and
when the information was last updated.

``cinder-manage service remove <service> <host>``

Removes a specified cinder service from a specified host.

Cinder Backup
~~~~~~~~~~~~~

``cinder-manage backup list``

Displays a list of all backups (including ones in progress) and the host on
which the backup operation is running.

``cinder-manage backup update_backup_host --currenthost <current host>
--newhost <new host>``

Updates the host name of all backups currently associated with a specified
host.

Cinder Version
~~~~~~~~~~~~~~

``cinder-manage version list``

Displays the codebase version cinder is running upon.

Cinder Config
~~~~~~~~~~~~~

``cinder-manage config list [<param>]``

Displays the current configuration parameters (options) for Cinder. The
optional flag parameter may be used to display the configuration of one
parameter.

Cinder Util
~~~~~~~~~~~

``cinder-manage util clean_locks [-h] [--services-offline]``

Clean file locks on the current host that were created and are used by drivers
and cinder services for volumes, snapshots, and the backup service on the
current host.

Should be run on any host where we are running a Cinder service (API,
Scheduler, Volume, Backup) and can be run with the Cinder services running or
stopped.

If the services are running it will check existing resources in the Cinder
database in order to only remove resources that are no longer present (it's
safe to delete the files).

For backups, the way to know if we can remove the startup lock is by checking
if the PGRP in the file name is currently running cinder-backup.

Deleting locks while the services are offline is faster as there's no need to
check the database or the running processes.

Default assumes that services are online, must pass ``--services-offline`` to
specify that they are offline.

The common use case for running the command with ``--services-offline`` is to
be called on startup as a service unit before any cinder service is started.
Command will be usually called without the ``--services-offline`` parameter
manually or from a cron job.

.. warning::

   Passing ``--services-offline`` when the Cinder services are still running
   breaks the locking mechanism and can lead to undesired behavior in ongoing
   Cinder operations.

.. note::

   This command doesn't clean DLM locks (except when using file locks), as
   those don't leave lock leftovers.

FILES
=====

The cinder.conf file contains configuration information in the form of
python-gflags.

The cinder-manage.log file logs output from cinder-manage.

SEE ALSO
========

* `OpenStack Cinder <https://docs.openstack.org/cinder/latest/>`__

BUGS
====

* Cinder is hosted on Launchpad so you can view current bugs at `Bugs :
  Cinder <https://bugs.launchpad.net/cinder/>`__
