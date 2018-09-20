#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  This file is part of the `lipyd` python module
#
#  Copyright (c) 2015-2018 - EMBL
#
#  File author(s): Dénes Türei (turei.denes@gmail.com)
#
#  This code is not for public use.
#  Please do not redistribute.
#  For permission please contact me.
#
#  Website: http://www.ebi.ac.uk/~denes
#

from __future__ import print_function
from future.utils import iteritems
from past.builtins import xrange, range, reduce

import sys
import imp
import itertools
import collections
import copy
import numpy as np

import lipyd.fragment as fragment
import lipyd.formula as formula
import lipyd.settings as settings
import lipyd.lookup as lookup_
import lipyd.session as session


class FragmentDatabaseAggregator(object):
    
    default_args = {
        'Sph': 'sph_default',
        'FA': 'fa_default',
        'FAL': 'fal_default'
    }
    
    def __init__(
            self,
            ionmode = 'pos',
            tolerance = 50,
            files = None,
            include = None,
            exclude = None,
            fa_default  = None,
            sph_default = None,
            fal_default = None,
            build = True
        ):
        """
        Builds and serves a database of MS2 fragment ions according to
        certain criteria.
        
        Fragments data can be either read from built in or user provided
        files, or homolog series of alkyl chain containing fragments
        can be generated by classes provided in the `fragment` module.
        You can select which of these homolog series should be generated
        and by which parameters. By default fragments from the built in
        list are read to avoid this provide a value for `files` argument.
        This might be an empty list or a list of files with your custom
        fragments, or a single filename string.
        
        Args
        ----
        :param str ionmode:
            Ion mode, either `pos` or `neg`.
        :param int tolerance:
            Tolerance at lookup in ppm.
        :param str,list files:
            Fragment list filenames. List of filenames or a single
            filename. If `None` the built in fragment list file used.
        :param list include:
            List of homolog series classes. Names of class defined in
            the `fragment` module, optionally tuples of class names
            and dict of arguments.
        :param list exclude:
            List of class names not to be used to generate fragment
            series.
        :param dict fa_default:
            Default arguments for fatty acyl derived fragment series.
        :param dict fa_default:
            Default arguments for fatty alkyl derived fragment series.
        :param dict sph_default:
            Default arguements for sphingoid long chain base derived
            fragment series.
        :param bool build:
            Build the fragment database at initialization.
        """
        
        self.fragments = []
        self.ionmode  = ionmode
        self.tolerance = tolerance
        self.files = files
        self.include = include
        self.exclude = exclude or []
        self.fa_default  = fa_default  or {
            'c': range(2, 37),
            'u': range(0, 7)
        }
        self.fal_default = fal_default or self.fa_default
        self.sph_default = sph_default or {
            # added 8 here as for kSph we have C8 standard
            # TODO: find a better solution for this
            'c': [8, 14, 16, 17, 18, 19, 20, 21],
            'u': (0, 1)
        }
        
        self.constraints = {}
        
        if build:
            
            self.build()
    
    def reload(self):
        
        modname = self.__class__.__module__
        mod = __import__(modname, fromlist=[modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)
    
    def build(self):
        """
        Builds the fragment list.
        
        Reads files and auto-generates programmatically calculated
        homolog series.
        """
        
        self.fragments = []
        
        self.set_filenames()
        self.fragments = self.read_files()
        self.fragments.extend(self.generate_series())
        self.fragments = np.array(
            sorted(
                self.fragments,
                key = lambda x: x[0]
            ),
            dtype = np.object
        )
        self.frags_by_name = dict(
            (frag[1], i)
            for i, frag in enumerate(self.fragments)
        )
    
    def __iter__(self):
        
        return self.fragments.__iter__()
    
    def set_filenames(self):
        """
        Sets the `files` attribute to be a list of filenames.
        If no `files` argument provided the built in default
        fragment list files will be used.
        """
        
        self.files = (
                [self.files]
            if hasattr(self.files, 'lower') else
                [self.get_default_file()]
            if self.files is None else
                self.files
        )
    
    def get_default_file(self):
        """
        Returns the file name of the default fragment lists.
        
        These are stored in the `pfragmentsfile` and `nfragmentsfile`
        settings for positive and negative ion modes, respectively.
        The fragment list files should have at least 4 columns:
        * m/z as float
        * formula -- either formula or m/z should be provided,
        mass calculation from formula has priority over the
        mass in first column
        * human readable name
        * type: e.g. `[M+H]+`; importantly, for neutral losses
        this value must start with `NL`
        * headgroups (lipid classes), e.g.`PC;SM`
        
        See the built in fragment lists for examples.
        """
        
        return settings.get('%sfragmentsfile' % (
            'p' if self.ionmode == 'pos' else 'n'
        ))
    
    def read_files(self):
        """
        Returns the list of fragments read from all files.
        """
        
        return (
            list(
                itertools.chain(
                    *(self.read_file(fname) for fname in self.files)
                )
            )
        )
    
    def read_file(self, fname = None):
        """
        Reads a list of MS2 fragments from a file.
        Returns list of fragments.
        
        If no filename provided the default fragment lists will be read.
        The fragment list files should have at least 4 columns:
        * m/z as float
        * formula -- either formula or m/z should be provided,
        mass calculation from formula has priority over the
        mass in first column
        * human readable name
        * type: e.g. `[M+H]+`; importantly, for neutral losses
        this value must start with `NL`
        * headgroups (lipid classes), e.g.`PC;SM`
        
        See the built in fragment lists for examples.
        """
        
        def get_charge(typ):
            
            return (
                0  if typ.startswith('NL') else
                -1 if self.ionmode == 'neg' else
                1
            )
        
        def process_line(l):
            
            l = l.split('\t')
            
            mass = (
                    formula.Formula(l[1]).mass
                if l[1] else
                    float(l[0])
                if l[0] else
                    None
            )
            
            self.constraints[l[2]] = (
                tuple(
                    fragment.FragConstraint(
                        hg = constr.split(',')[0],
                        sub = (
                            tuple(constr.split(',')[1:])
                                if ',' in constr else
                            ()
                        ),
                        sph = constr.split('|')[1] if '|' in constr else None,
                        # no way at the moment to define chain
                        # type in file but later can be added easily
                        chaintype = None
                    )
                    for constr in l[4].strip().split(';')
                )
                    if l[4].strip() else
                (
                    # an empty constraint to make sure anything matches
                    fragment.FragConstraint(),
                )
            )
            
            return [
                mass, l[2], l[3], np.nan, np.nan, np.nan, get_charge(l[3])
            ]
        
        fname = fname or self.get_default_file()
        
        with open(fname, 'r') as fp:
            
            return [
                ll for ll in
                    (
                        process_line(l) for l in
                        filter(bool, fp.read().split('\n'))
                    )
                if ll and ll[0]
            ]
    
    def set_series(self):
        """
        Selects the homolog series to be generated and their parameters.
        See details in docs of `exclude` and `include` arguments for
        `__init__()`.
        """
        
        def get_class(name):
            
            # TODO be able to use classes defined elsewhere
            return getattr(fragment, name)
        
        self.specific_args = collections.defaultdict(dict)
        
        if self.include is not None:
            
            # a set of fragment class names
            self.series = set(
                i[0] if type(i) is tuple else i for i in self.include
            )
            # a dict with class specific arguments
            # whereever it's provided
            self.specific_args.update(
                dict(filter(lambda x: type(x) is tuple, self.include))
            )
            
        else:
            
            # all fragment classes by default except those in `exclude`
            self.series = fragment.fattyfragments - set(self.exclude)
        
        self.series = map(get_class, self.series)
        self.series = [
            cls for cls in self.series if cls.ionmode == self.ionmode
        ]
    
    def get_series_args(self, cls):
        """
        Provides a dict of arguments for fragment homolog series.
        
        Args
        ----
        :param class cls:
            Fragment homolog series class
            e.g. `fragment.FA_mH` -- fatty acid minus hydrogen.
        """
        
        args = (
            copy.copy(getattr(self, self.default_args[cls.chaintype]))
                if cls.chaintype in self.default_args else
            {}
        )
        
        args.update(self.specific_args[cls])
        
        return args
    
    def generate_series(self):
        """
        Generates homologous series fragments.
        """
        
        result = []
        
        self.set_series()
        
        for cls in self.series:
            
            args = self.get_series_args(cls)
            
            result.extend(list(cls(**args).iterfraglines()))
            
            self.add_constraints(cls)
        
        return result
    
    def add_constraints(self, cls):
        
        self.constraints[cls.name] = cls.constraints
    
    def get_constraints(self, fragtype):
        
        return self.constraints.get(fragtype, ())
    
    def __getitem__(self, i):
        
        return self.fragments[i,:]
    
    def __len__(self):
        
        return self.fragments.shape[0]
    
    def lookup(self, mz, nl = False, tolerance = None):
        """
        Searches for fragments in the database matching the `mz` within the
        actual range of tolerance. To change the tolerance set the
        `tolerance` attribute to the desired ppm value.
        
        Args
        ----
        :param bool nl:
            The m/z is a neutral loss.
        """
        
        idx = lookup_.findall(
            self.fragments[:,0],
            mz,
            tolerance or self.tolerance
        )
        # filtering for NL or not NL
        idx = [
            i for i in idx
            if (
                nl and self.fragments[i, 6] == 0
            ) or (
                not nl and self.fragments[i, 6] != 0
            )
        ]
        
        return self.fragments[idx,:]
    
    def lookup_nl(self, mz, precursor, tolerance = None):
        """
        Searches for neutral loss fragments in the database matching the
        m/z within the actual range of tolerance.
        """
        
        nlmz = precursor - mz
        nl_tolerance = mz / nlmz * (tolerance or self.tolerance)
        
        return self.lookup(nlmz, nl = True, tolerance = nl_tolerance)
    
    def by_name(self, name):
        """
        Returns fragment data by its name.
        `None` if the name not in the database.
        
        Args
        ----
        :param str name:
            The full name of a fragment, e.g. `PE [P+E] (140.0118)`.
        """
        
        i = self.frags_by_name.get(name, None)
        
        return self.fragments[i] if i is not None else None
    
    def mz_by_name(self, name):
        """
        Returns the m/z of a fragment by its name.
        `None` if the name not in the database.
        
        Args
        ----
        :param str name:
            The full name of a fragment, e.g. `PE [P+E] (140.0118)`.
        """
        
        i = self.frags_by_name.get(name, None)
        
        return self.fragments[i][0] if i is not None else None


def init_db(ionmode, **kwargs):
    """
    Creates a fragment database.
    """
    
    mod = sys.modules[__name__]
    attr = 'db_%s' % ionmode
    
    setattr(mod, attr, FragmentDatabaseAggregator(ionmode, **kwargs))

def get_db(ionmode, **kwargs):
    """
    Returns fragment database for the ion mode requested.
    Creates a database with the keyword arguments provided if no database
    has been initialized yet.
    """
    
    mod = sys.modules[__name__]
    attr = 'db_%s' % ionmode
    
    if not hasattr(mod, attr):
        
        init_db(ionmode, **kwargs)
    
    return getattr(mod, attr)

def lookup(mz, ionmode, nl = False, tolerance = None):
    """
    Looks up an m/z in the fragment database, returns all fragment identities
    within range of tolerance.
    
    Args
    ----
    :param float mz:
        Measured MS2 fragment m/z value.
    :param str ionmode:
        MS ion mode; `pos` or `neg`.
    :param bool nl:
        Look up charged ion or neutral loss m/z.
    """
    
    db = get_db(ionmode)
    return db.lookup(mz, nl = nl, tolerance = tolerance)

def lookup_nl(mz, precursor, ionmode, tolerance = None):
    """
    Looks up an MS2 neutral loss in the fragment database.
    """
    
    db = get_db(ionmode)
    return db.lookup_nl(mz, precursor, tolerance = tolerance)

def lookup_pos(mz, tolerance = None):
    
    return lookup(mz, 'pos', tolerance = tolerance)

def lookup_neg(mz, tolerance = None):
    
    return lookup(mz, 'neg', tolerance = tolerance)

def lookup_pos_nl(mz, precursor, tolerance = None):
    
    return lookup_nl(mz, precursor, 'pos', tolerance = tolerance)

def lookup_neg_nl(mz, precursor):
    
    return lookup_nl(mz, precursor, 'neg')

def constraints(fragtype, ionmode):
    """
    Returns the constraints for a given fragment type.
    """
    
    db = get_db(ionmode)
    return db.get_constraints(fragtype)

def mz_by_name(name, ionmode):
    """
    Returns the m/z of a fragment by its name.
    `None` if name not in the database.
    """
    
    db = get_db(ionmode)
    return db.mz_by_name(name)

def by_name(name, ionmode):
    """
    Returns fragment data by its name.
    `None` if name not in the database.
    """
    
    db = get_db(ionmode)
    return db.by_name(name)



FragmentAnnotation = collections.namedtuple(
    'FragmentAnnotation',
    ['mz', 'name', 'fragtype', 'chaintype', 'c', 'u', 'charge']
)


class FragmentAnnotator(object):
    
    def __init__(
            self,
            mzs,
            ionmode,
            precursor = None,
            tolerance = None,
        ):
        """
        Annotates all fragmenta in MS2 scan with possible identites.
        
        Args
        ----
        :param np.ndarray mzs:
            MS2 scan fragment m/z's.
        :param str ionmode:
            MS ion mode; `pos` or `neg`.
        :param float precursor:
            Precursor ion m/z.
        :param tuple of arrays
        """
        
        self.mzs = mzs
        self.ionmode = ionmode
        self.precursor = precursor
        self.tolerance = tolerance or settings.get('ms2_tolerance')
    
    def reload(self):
        
        modname = self.__class__.__module__
        mod = __import__(modname, fromlist=[modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)
    
    def __iter__(self):
        
        for mz in self.mzs:
            
            yield self.annotate(mz)
    
    def annotate(self, mz):
        """
        Annotates the fragments in MS2 scan with possible identities taken
        from the fragment database.
        """
        
        result = []
        
        if self.precursor:
            
            nl_annot = lookup_nl(
                mz, self.precursor, self.ionmode, tolerance = self.tolerance
            )
            
            result.extend(FragmentAnnotation(*a) for a in nl_annot)
        
        annot = lookup(mz, self.ionmode, tolerance = self.tolerance)
        
        result.extend(FragmentAnnotation(*a) for a in annot)
        
        return tuple(result)
