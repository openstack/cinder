===========
policy.json
===========

The ``policy.json`` file defines additional access controls that apply
to the Block Storage service.

The following provides the default policies. It is not recommended to copy this
file into ``/etc/cinder`` unless you are planning on providing a different
policy for an operation that is not the default. For instance, if you want to
change the default value of "volume:create", you only need to keep this single
rule in your policy config file.

The sample policy file can also be viewed in `file form
<../../../_static/cinder.policy.yaml.sample>`_.

.. literalinclude:: ../../../_static/cinder.policy.yaml.sample
