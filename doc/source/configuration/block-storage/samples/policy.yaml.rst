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
  write a policy file in either JSON or YAML.

  * Given that JSON does not allow comments, we recommend using YAML to write
    a custom policy file.

* If you supply a custom policy file, you only need to supply entries for the
  policies you wish to change from their default values.  For instance, if you
  want to change the default value of "volume:create", you only need to keep
  this single rule in your policy config file.

* The default policy file location is ``/etc/cinder/policy.yaml``.  You may
  override this by specifying a different file location as the value of the
  ``policy_file`` configuration option in the ``[oslo_policy]`` section of the
  the Cinder configuration file.

The following provides a listing of the default policies. It is not recommended
to copy this file into ``/etc/cinder`` unless you are planning on providing a
different policy for an operation that is not the default.

.. only:: html

   The sample policy file can also be viewed in `file form
   <../../../_static/cinder.policy.yaml.sample>`_.

.. literalinclude:: ../../../_static/cinder.policy.yaml.sample
