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

Categories are shell, logs, migrate, db, volume, host, service, backup,
version, and config. Detailed descriptions are below.

You can also run with a category argument such as 'db' to see a list of all
commands in that category:
``cinder-manage db``

These sections describe the available categories and arguments for
cinder-manage.

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

Cinder Shell
~~~~~~~~~~~~

``cinder-manage shell bpython``

Starts a new bpython shell.

``cinder-manage shell ipython``

Starts a new ipython shell.

``cinder-manage shell python``

Starts a new python shell.

``cinder-manage shell run``

Starts a new shell using python.

``cinder-manage shell script <path/scriptname>``

Runs the named script from the specified path with flags set.

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
