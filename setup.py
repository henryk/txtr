#!/usr/bin/env python
#-*- coding: utf-8 -*-

import ez_setup
ez_setup.use_setuptools()

from setuptools import setup

setup(name='python-txtr',
    version='0.5',
    description='txtr Uploader for Linux',
    author='Henryk Plötz',
    author_email='henryk@ploetzli.ch',
    url="http://svn.ploetzli.ch/txtr/",
    
    install_requires=["simplejson"],
    
    package_dir={'':'src'},
    packages=["txtr", "txtr/gui"],
    
    package_data={
        "txtr/gui": ["bg_txtrSynchronizer.png", "uploader_logo.png", "uploader.glade",
            "locale/*/LC_MESSAGES/txtr_uploader.mo"],
    },
    include_package_data=False,
    zip_safe=False,
    
    entry_points = {
        "gui_scripts": [
            "txtr_uploader = txtr.gui.uploader:main",
        ],
    }
)
