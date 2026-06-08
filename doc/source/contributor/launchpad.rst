Project hosting with Launchpad
==============================

`Launchpad`_ hosts the Cinder project. The Cinder project homepage on Launchpad
is https://launchpad.net/cinder.

Launchpad credentials
---------------------

Creating a login on Launchpad is important even if you don't use the Launchpad
site itself, since Launchpad credentials are used for logging in on several
OpenStack-related sites. These sites include:

 * `Wiki`_
 * Gerrit (see :doc:`gerrit`)
 * Zuul (see :doc:`zuul`)

Mailing list
------------

The mailing list email is ``openstack-discuss@lists.openstack.org``.
This is a common mailing list across the OpenStack projects. To
participate in the mailing list:

#. Subscribe to the list at
   https://lists.openstack.org/cgi-bin/mailman/listinfo/openstack-discuss

The mailing list archives are at
https://lists.openstack.org/pipermail/openstack-discuss/.


Bug tracking
------------

Report Cinder bugs at https://bugs.launchpad.net/cinder

OpenStack Block Storage (cinder) bug reporting guidelines:

.. code-block:: text

  !!!!!!!!!!!!!!!!!!!!!!!!! READ THIS !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  Each bug report needs to provide a minimum of information without
  which we may not be able to address the issue you observed. It is crucial
  for other developers to have this information. You can use the
  template below, which asks for this information.

  You can ask in the #openstack-cinder IRC channel on OFTC, if you have questions about this.

  !!!!!!!!!!!!!!!!!!!!!!!!! READ THIS !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  Description
  ===========
  Some prose which explains more in detail what this bug report is
  about. If the headline of this report is descriptive enough, skip
  this section.

  Steps to reproduce
  ==================
  A chronological list of steps which will bring off the
  issue you noticed:
  * I did X
  * then I did Y
  * then I did Z
  A list of openstack client commands (with correct argument value)
  would be the most descriptive example. To get more information use:

      $ openstack volume <command> <arg1> <arg2=value> --debug


  Expected result
  ===============
  After the execution of the steps above, what should have
  happened if the issue wasn't present?

  Actual result
  =============
  What happened instead of the expected result?
  What did the issue look like?

  Environment
  ===========
  1. Exact version of OpenStack you are running. See the following
     list for all releases: http://docs.openstack.org/releases/

     If this is from a distro please provide
         $ dpkg -l | grep cinder
         or
         $ rpm -qa | grep cinder
     If this is from git, please provide
         $ git log -1

  2. Which storage backend did you use?
     (For example: LVM, Ceph/RBD, NetApp, SolidFire, Dell EMC, Pure Storage, ...)

  3. Which volume driver did you use?
     (For example: LVMVolumeDriver, RBDDriver, NFSDriver, NetAppDriver, ...)
     And how are volumes attached/connected? (iSCSI, FC, NFS, RBD, ...)

  4. Which deployment method did you use?
     (For example: DevStack, TripleO, RHOSO, Kolla, manual installation, ...)

  Logs & Configs
  ==============
  Please provide cinder service logs with DEBUG mode enabled.
  You can find the logs at:
  * For DevStack: /opt/stack/logs/c-* (c-api.log, c-vol.log, c-sch.log, c-bak.log)
  * For systemd: journalctl -u devstack@c-* or /var/log/cinder/
  * For other deployments: check your cinder.conf for log_dir location

  Also include your cinder.conf file (sanitized to remove any credentials).

  Optionally, if you want to provide more detailed logs and system information,
  you can use the sosreport tool:

     $ sudo sosreport -o openstack_cinder --batch

  When reporting backend-specific issues, please also include:
  * Backend driver configuration section from cinder.conf
  * Relevant backend logs if available

Feature requests (Blueprints)
-----------------------------

Cinder uses Launchpad Blueprints to track feature requests. Blueprints are at
https://blueprints.launchpad.net/cinder.

Technical support (Answers)
---------------------------

Cinder no longer uses Launchpad Answers to track Cinder technical support
questions.

Note that `Ask OpenStack`_ (which is not hosted on Launchpad) can
be used for technical support requests.

.. _Launchpad: https://launchpad.net
.. _Wiki: https://wiki.openstack.org/wiki/Main_Page
.. _Cinder Team: https://launchpad.net/~cinder
.. _OpenStack Team: https://launchpad.net/~openstack
.. _Ask OpenStack: https://ask.openstack.org
