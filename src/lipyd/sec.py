#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  This file is part of the `lipyd` python module
#
#  Copyright (c) 2014-2018 - EMBL
#
#  File author(s): Dénes Türei (turei.denes@gmail.com)
#
#  Distributed under the GNU GPLv3 License.
#  See accompanying file LICENSE.txt or copy at
#      http://www.gnu.org/licenses/gpl-3.0.html
#
#  Website: http://www.ebi.ac.uk/~denes
#

from past.builtins import xrange, range

import imp
import re
import collections
import mimetypes

import numpy as np

import lipyd.settings as settings
import lipyd.common as common
import lipyd.reader.xls as xls


refrac = re.compile(r'([A-Z])([0-9]{1,2})')


Fraction = collections.namedtuple(
    'Fraction',
    ['row', 'col', 'start', 'end', 'mean']
)
Fraction.__new__.__defaults__ = (None,)


class SECReader(object):
    
    def __init__(self, path):
        
        self.path = path
        self.read()
    
    def reload(self, children = False):
        
        modname = self.__class__.__module__
        mod = __import__(modname, fromlist=[modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)
    
    def read(self):
        
        self.guess_format()
        
        if self.format == 'asc':
            
            self.read_asc()
            
        elif self.format == 'xls':
            
            self.read_xls()
    
    def read_asc(self):
        """
        Reads SEC UV absorbance profile from asc file output produced by
        the Unicorn software from GE Healthcare.
        """
        
        start      = None
        end        = None
        frac       = None
        volume     = []
        absorbance = []
        fractions  = []
        
        with open(self.path, 'r') as fp:
            
            for l in fp:
                
                l = l.strip().split('\t')
                
                if len(l) < 2 or '.' not in l[0] or '.' not in l[1]:
                    
                    continue
                
                vol = common.to_float(l[0])
                ab_ = common.to_float(l[1])
                
                if isinstance(vol, float) and isinstance(ab_, float):
                    
                    volume.append(vol)
                    absorbance.append(ab_)
                
                if len(l) > 3:
                    
                    start = end
                    end   = common.to_float(l[2])
                    
                    if start and end and frac:
                        
                        fractions.append(
                            Fraction(frac[0], int(frac[1]), start, end)
                        )
                    
                    m = refrac.search(l[3])
                    
                    frac = m.groups() if m else None
        
        self.volume = np.array(volume)
        self.absorbance = np.array(absorbance)
        self.fractions = fractions
    
    def read_xls(self):
        """
        Reads SEC UV absorbance profile from MS Excel XLS file output
        produced by ???.
        """
        
        volume     = []
        absorbance = []
        
        tab = xls.read_xls(self.path)
        
        for l in tab:
            
            if len(l) < 2 or '.' not in l[0] or '.' not in l[1]:
                
                continue
            
            vol = common.to_float(l[0])
            ab_ = common.to_float(l[1])
            
            if isinstance(vol, float) and isinstance(ab_, float):
                
                volume.append(vol)
                absorbance.append(ab_)
        
        self.volume = np.array(volume)
        self.absorbance = np.array(absorbance)
    
    def auto_fractions(
            self,
            start_volume = .6,
            size = .15,
            start_row = 'A',
            start_col = 5,
            length = 9,
        ):
        """
        Autogenerates fraction volume boundaries according to the parameters
        provided.
        """
        
        fractions = []
        
        for i in xrange(length):
            
            start = start_volume + size * i
            end   = start + size
            well  = (ord(start_row) - 65) * 12 + start_col + i - 1
            row   = chr(well // 12 + 65)
            col   = well % 12 + 1
            
            fractions.append(Fraction(row, col, start, end))
        
        return fractions
    
    def guess_format(self):
        
        mime = mimetypes.guess_type(self.path)[0]
        
        self.format = (
            'xls' if 'excel' in mime or 'openxml' in mime else 'asc'
        )
    
    def get_fraction(self, frac):
        """
        Returns absorbances measured within a fraction.
        """
        
        return (
            self.absorbance[
                np.logical_and(
                    self.volume  < frac.end,
                    self.volume >= frac.start
                )
            ]
        )
    
    def fraction_mean(self, frac):
        """
        Returns the mean absorbance from a fraction.
        """
        
        return self.get_fraction(frac).mean()
    
    def profile(self, **kwargs):
        """
        Iterates fractions with their mean absorbance values.
        
        :param **kwargs:
            Arguments passed to ``auto_fractions`` (if necessary).
        """
        
        fractions = (
            self.fractions
                if hasattr(self, 'fractions') else
            self.auto_fractions(**kwargs)
        )
        
        for frac in fractions:
            
            yield Fraction(*frac[:-1], self.fraction_mean(frac))
