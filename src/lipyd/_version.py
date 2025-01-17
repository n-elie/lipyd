#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  This file is part of the `lipyd` python module
#
#  Copyright (c) 2015-2017 - EMBL
#
#  File author(s):
#  Dénes Türei (turei.denes@gmail.com)
#  Igor Bulanov
#
#  Distributed under the GNU GPLv3 License.
#  See accompanying file LICENSE.txt or copy at
#      http://www.gnu.org/licenses/gpl-3.0.html
#
#  Website: http://denes.omnipathdb.org/
#

import os

def _get_version():
    """ """
    
    ROOT = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(ROOT, '__version__'), 'r') as v:
        return tuple([int(i) for i in v.read().strip().split('.')])


_MAJOR, _MINOR, _MICRO = _get_version()
__version__ = '%d.%d.%d' % (_MAJOR, _MINOR, _MICRO)
__release__ = '%d.%d' % (_MAJOR, _MINOR)
