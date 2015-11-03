=============
cinder-manage
=============

------------------------------------------------------
Control and manage OpenStack block storage
------------------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2015-11-03
:Copyright: OpenStack Foundation
:Version: 7.0.0
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  cinder-manage <category> <action> [<args>]

DESCRIPTION
===========

cinder-manage provides control of cinder database migration, and provides an interface to get information about the current state of cinder.  More information about OpenStack Cinder is available at http://cinder.openstack.org.

OPTIONS
=======

The standard pattern for executing a cinder-manage command is:
``cinder-manage <category> <command> [<args>]``

For example, to obtain a list of the cinder services currently running:
``cinder-manage service list``

Run without arguments to see a list of available command categories:
``cinder-manage``

Categories are shell, logs, migrate, db, volume, host, service, backup, version, and config. Detailed descriptions are below.

You can also run with a category argument such as 'db' to see a list of all commands in that category:
``cinder-manage db``

These sections describe the available categories and arguments for cinder-manage.

Cinder Db
~~~~~~~~~

``cinder-manage db version``

    Print the current database version.

``cinder-manage db sync``

    Sync the database up to the most recent version. This is the standard way to create the db as well.

``cinder-manage db purge [<number of days>]``

    Purge database entries that are marked as deleted, that are older than the number of days specified.


Cinder Logs
~~~~~~~~~~~

``cinder-manage logs errors``

    Displays cinder errors from log files.

``cinder-manage logs syslog [<number>]``

    Displays cinder the most recent entries from syslog.  The optional number argument specifies the number of entries to display (default 10).

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

``cinder-manage volume update_host --currenthost <current host> --newhost <new host>``

    Updates the host name of all volumes currently associated with a specified host.

Cinder Host
~~~~~~~~~~~

``cinder-manage host list [<zone>]``

    Displays a list of all physical hosts and their zone.  The optional zone argument allows the list to be filtered on the requested zone.

Cinder Service
~~~~~~~~~~~~~~

``cinder-manage service list``

    Displays a list of all cinder services and their host, zone, status, state and when the information was last updated.

``cinder-manage service remove <service> <host>``

    Removes a specified cinder service from a specified host.

Cinder Backup
~~~~~~~~~~~~~

``cinder-manage backup list``

    Displays a list of all backups (including ones in progress) and the host on which the backup operation is running.

Cinder Version
~~~~~~~~~~~~~~

``cinder-manage version list``

    Displays the codebase version cinder is running upon.

Cinder Config
~~~~~~~~~~~~~

``cinder-manage config list [<param>]``

    Displays the current configuration parameters (options) for Cinder. The optional flag parameter may be used to display the configuration of one parameter.

FILES
=====

The cinder.conf file contains configuration information in the form of python-gflags.

The cinder-manage.log file logs output from cinder-manage.

SEE ALSO
========

* `OpenStack Cinder <http://cinder.openstack.org>`__

BUGS
====

* Cinder is hosted on Launchpad so you can view current bugs at `Bugs : Cinder <https://bugs.launchpad.net/cinder/>`__
