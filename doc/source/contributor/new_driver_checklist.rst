===========================
New Driver Review Checklist
===========================

Reviewers can use this list for some common things to watch for when doing new
driver reviews. This list is by no means exhaustive, but does try to capture
some of things that have been found in past reviews.

.. note::

   Feel free to propose additional items to help make this a more complete
   list.

Review Checklist
----------------

* Driver Code

  * Passing all gate tests
  * Driver keeps all configuration in ``cinder.conf`` and not in separate
    vendor specific config file.

    * xml files for configs are forbidden

* Common gotchas

  * Handles detach where ``connector == None`` for force detach
  * Create from snapshot and clone properly account for new volume size being
    larger than original volume size
  * Volume not found in delete calls should return success
  * Ensure proper code format w/ pep8 (``tox -e pep8``), but start here first:
    https://docs.openstack.org/hacking/latest/user/hacking.html

    * ``tox -e fast8`` can be used as a quick check only against modified files


  * Unit tests included for all but trivial code in driver
  * All source code files contain Apache 2 copyright header

    * Stating copyright for vendor is optional
    * Don't attribute copyright to the OpenStack Foundation

  * Run ``tox -e compliance`` to make sure all required interfaces are
    implemented.
  * Required in driver:

    * Concrete driver implementation has decorator ``@interface.volumedriver``
    * ``VERSION`` constant defined in driver class
    * ``CI_WIKI_NAME`` constant defined in driver class
    * well documented version history in the comment block for the main driver
      class.
    * Support :ref:`minimum driver features <drivers_minimum_features>`.
    * Meet release deadline(s)
      (https://releases.openstack.org/train/schedule.html#t-cinder-driver-deadline )

  * Driver does not add unnecessary new config options

    * For example, adding vendor_username instead of using the common san_login

  * Driver specific exceptions inherit from ``VolumeDriverException`` or
    ``VolumeBackendAPIException``

    * Exceptions should be defined with driver code

  * Logging level is appropriate for content

    * General tracing should be at debug level
    * Things operators should be aware of should be at Info level
    * Issues that are of concern but may not have an impact on actual operation
      should be warning
    * Issues operators need to take action on or should definitely know about
      should be ERROR
    * Messages about a failure should include the snapshot or volume in
      question.

  * All exception messages that could be raised to users should be marked for
    translation with _()
  * Any additional libraries needed for a driver must be added to the global
    requirements.

    * https://wiki.openstack.org/wiki/Requirements#Adding_a_Requirement_to_an_OpenStack_Project
    * Pypi installable libraries should be added to driver section in setup.cfg
    * Binary dependencies need to be OSI licensed and added to bindep.txt

  * Third Party CI checks

    * Responds correctly to recheck from "run-<CI Name>"
    * Tempest run console log available
    * ``cinder.conf`` and all cinder service logs available
    * LVM driver is not being configured in ``local.conf/cinder.conf``
    * Only the driver in question should be in ``cinder.conf`` and enabled

      * ``default_volume_type`` and ``enabled_backends`` in ``cinder.conf``, OR
      * ``CINDER_DEFAULT_VOLUME_TYPE`` and ``CINDER_ENABLED_BACKENDS`` in
        ``local.conf``, OR
      * ``TEMPEST_VOLUME_DRIVER`` and ``TEMPEST_VOLUME_VENDER`` in
        ``local.conf``

    * specify correct patch for each CI run

      * ``CINDER_BRANCH`` in ``local.conf``, OR
      * ``git fetch https://review.opendev.org/openstack/cinder refs/changes/56/657856/2 && git checkout cherry-pick``
        (https://wiki.openstack.org/wiki/Cinder/tested-3rdParty-drivers )

  * CI runs ``tox -e all -- *volume*``

    * Any skipped tests need to be clearly documented why they are being
      skipped including the plan for getting rid of the need to skip them.
    * https://opendev.org/openstack/cinder-tempest-plugin needs to be installed
      so those tempest tests run as well.
    * ``tox`` | ``tempest`` with ``--subunit`` helps generate HTML output
      (https://docs.openstack.org/os-testr/latest/user/subunit2html.html )
    * ``tox`` | ``tempest`` with ``--concurrency=<n>`` for specifying ``<n>``
      number of test runners

  * CI must run Cinder services using Python 3.7.
  * CI does not report failures or exception due to the CI operation and not
    due to test failures due to code changes.
  * *optional, but highly recommended:* CI only runs on third party CI recheck
    trigger or on successful +1 from Zuul.
  * CI only runs on patches to the master branch unless they are intentionally
    set up to be able to properly run stable branch testing.

* Included with driver patch

  * Release note stating something like "New volume driver added for Blah blah
    blah storage"

    * See Reno usage information here:
      https://docs.openstack.org/reno/latest/user/usage.html
    * Make sure that the release note is in the correct subdirectory, namely,
      ``releasenotes/notes/`` in the repository root directory.  It should
      *not* be located in the driver's section of the code tree.

  * Driver added to ``doc/source/reference/support-matrix.ini`` and
    ``doc/source/reference/support-matrix.rst``
  * Driver configuration information added under
    ``doc/source/configuration/block-storage/drivers``
  * Update ``cinder/opts.py`` including the new driver library options using
    the command ``tox -e genopts``
