#!/usr/bin/env bash

if [ ! -e cinder/opts.py ]; then
    echo -en "\n\n#################################################"
    echo -en "\nERROR: cinder/opts.py file is missing."
    echo -en "\n#################################################\n"
    exit 1
else
    mv cinder/opts.py cinder/opts.py.orig
    tox -e genopts &> /dev/null
    if [ $? -ne 0 ]; then
        echo -en "\n\n#################################################"
        echo -en "\nERROR: Non-zero exit from generate_cinder_opts.py."
        echo -en "\n       See output above for details.\n"
        echo -en "#################################################\n"
        mv cinder/opts.py.orig cinder/opts.py
        exit 1
    else
        diff cinder/opts.py.orig cinder/opts.py
        if [ $? -ne 0 ]; then
            echo -en "\n\n########################################################"
            echo -en "\nERROR: Configuration options change detected."
            echo -en "\n       A new cinder/opts.py file must be generated."
            echo -en "\n       Run 'tox -e genopts' from the base directory"
            echo -en "\n       and add the result to your commit."
            echo -en "\n########################################################\n\n"
            rm cinder/opts.py
            mv cinder/opts.py.orig cinder/opts.py
            exit 1
        else
            rm cinder/opts.py.orig
        fi
    fi
fi
