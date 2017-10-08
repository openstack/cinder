# Generate policy file
To generate the sample policy yaml file, run the following command from the top
level of the cinder directory:

    tox -egenpolicy

# Use generated policy file
Cinder recognizes ``/etc/cinder/policy.yaml`` as the default policy file.
To specify your own policy file in order to overwrite the default policy value,
add this in Cinder config file:

    [oslo_policy]
    policy_file = path/to/policy/file
