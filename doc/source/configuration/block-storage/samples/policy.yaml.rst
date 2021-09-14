.. _policy-file:

===========
policy.yaml
===========

The ``policy.yaml`` file defines additional access controls that apply
to the Block Storage service.

Prior to Cinder 12.0.0 (the Queens release), a JSON policy file was required to
run Cinder.  From the Queens release onward, the following hold:

* It is possible to run Cinder safely without a policy file, as sensible
  default values are defined in the code.

* If you wish to run Cinder with policies different from the default, you may
  write a policy file.

  * Given that JSON does not allow comments, we recommend using YAML to write
    a custom policy file.  (Also, see next item.)

  * OpenStack has deprecated the use of a JSON policy file since the Wallaby
    release (Cinder 18.0.0).  If you are still using the JSON format, there
    is a `oslopolicy-convert-json-to-yaml`__ tool that will migrate your
    existing JSON-formatted policy file to YAML in a backward-compatible way.

    .. __: https://docs.openstack.org/oslo.policy/latest/cli/oslopolicy-convert-json-to-yaml.html

* If you supply a custom policy file, you only need to supply entries for the
  policies you wish to change from their default values.  For instance, if you
  want to change the default value of "volume:create", you only need to keep
  this single rule in your policy config file.

* The default policy file location is ``/etc/cinder/policy.yaml``.  You may
  override this by specifying a different file location as the value of the
  ``policy_file`` configuration option in the ``[oslo_policy]`` section of the
  the Cinder configuration file.

* Instructions for generating a sample ``policy.yaml`` file directly from the
  Cinder source code can be found in the file ``README-policy.generate.md``
  in the ``etc/cinder`` directory in the Cinder `source code repository
  <https://opendev.org/openstack/cinder>`_ (or its `github mirror
  <https://github.com/openstack/cinder>`_).

.. only:: html

   The following provides a listing of the default policies. It is not
   recommended to copy this file into ``/etc/cinder`` unless you are planning
   on providing a different policy for an operation that is not the default.

   The sample policy file can also be viewed in `file form
   <../../../_static/cinder.policy.yaml.sample>`_.

   .. literalinclude:: ../../../_static/cinder.policy.yaml.sample
      :language: ini

.. only:: latex

   A sample policy file is available in the online version of this
   documentation.  Make sure you are looking at the sample file for the
   OpenStack release you are running as the available policy rules and
   their default values may change from release to release.
