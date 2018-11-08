#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  This file is part of the `lipyd` python module
#
#  Copyright (c) 2015-2018 - EMBL
#
#  File author(s): Dénes Türei (turei.denes@gmail.com)
#
#  Distributed under the GNU GPLv3 License.
#  See accompanying file LICENSE.txt or copy at
#      http://www.gnu.org/licenses/gpl-3.0.html
#
#  Website: http://www.ebi.ac.uk/~denes
#

from __future__ import print_function
from future.utils import iteritems
from past.builtins import xrange, range, reduce

import sys
import imp
import re
import math
import copy
import itertools
import collections
from argparse import Namespace
import numpy as np

from lipyd.common import *
import lipyd.mgf as mgf
import lipyd.mz as mzmod
import lipyd.session as session
import lipyd.settings as settings
import lipyd.lookup as lookup
import lipyd.fragdb as fragdb
import lipyd.moldb as moldb
import lipyd.lipproc as lipproc


ChainFragment = collections.namedtuple(
    'ChainFragment',
    ['c', 'u', 'fragtype', 'chaintype', 'i', 'intensity']
)


class MS2Identity(collections.namedtuple(
        'MS2IdentityBase',
        [
            'score', 'max_score', 'score_pct',
            'hg', 'chainsum', 'chains', 'chain_details',
            'scan_details',
        ]
    )):
    
    def __new__(
            cls,
            score = 0,
            max_score = 0,
            score_pct = 0,
            hg = None,
            chainsum = None,
            chains = None,
            chain_details = None,
            scan_details = None,
        ):
        
        return super(MS2Identity, cls).__new__(
            cls,
            score,
            max_score,
            score_pct,
            hg,
            chainsum = chainsum,
            chains = chains,
            chain_details = chain_details,
            scan_details = scan_details,
        )
    
    def __str__(self):
        
        return (
            lipproc.full_str(self.hg, self.chains)
                if self.chains else
            lipproc.summary_str(self.hg, self.chainsum)
        )
    
    def full_str(self):
        
        details = []
        
        details.append('score=%.01f' % self.score_pct)
        
        if self.scan_details:
            
            if self.scan_details.deltart is not None:
                details.append('deltart=%.02f' % self.scan_details.deltart)
            if self.scan_details.sample_id is not None:
                sample_id = self.scan_details.sample_id
                if isinstance(sample_id, tuple):
                    sample_id = ''.join(str(i) for i in sample_id)
                details.append('sample=%s' % sample_id)
            if self.scan_details.scan_id is not None:
                details.append('scan=%u' % self.scan_details.scan_id)
        
        return '%s[%s]' % (
            self.__str__(),
            ','.join(details),
        )
    
    def summary(self):
        
        return self.__str__(), self.score_pct
    
    def __eq__(self, other):
        
        return (
            isinstance(other, MS2Identity) and
            self.hg == other.hg and
            self.chainsum == other.chainsum and
            self.chains == other.chains
        )


ChainIdentificationDetails = collections.namedtuple(
    'ChainIdentificationDetails',
    ['rank', 'i', 'fragtype']
)
ChainIdentificationDetails.__new__.__defaults__ = (None, None, None)


ScanDetails = collections.namedtuple(
    'ScanDetails',
    ['sample_id', 'scan_id', 'source', 'deltart']
)
ChainIdentificationDetails.__new__.__defaults__ = (None, None, None, None)


class mz_sorted(object):
    
    def __init__(self, scan):
        
        self.scan = scan
    
    def __enter__(self):
        
        self.scan.sort_mz()
    
    def __exit__(self, extyp, exval, tb):
        
        self.scan.sort_intensity()


class intensity_sorted(object):
    
    def __init__(self, scan):
        
        self.scan = scan
    
    def __enter__(self):
        
        self.scan.sort_intensity()
    
    def __exit__(self, extyp, exval, tb):
        
        self.scan.sort_mz()


class ScanBase(object):
    
    def __init__(
            self,
            mzs,
            ionmode,
            precursor = None,
            intensities = None,
            tolerance = None,
            scan_id = None,
        ):
        
        self.tolerance = tolerance or settings.get('ms2_tolerance')
        self.sorted_by = None
        self.mzs = mzs
        self.ionmode = ionmode
        self.adducts = {}
        self.intensities = (
            np.array([1.0] * len(self.mzs))
                if intensities is None else
            intensities
        )
        self.precursor = precursor
        self.scan_id = scan_id
        
        if self.mzs is not np.ndarray:
            
            self.mzs = np.array(self.mzs)
        
        if self.intensities is not np.ndarray:
            
            self.intensities = np.array(self.intensities)
        
        self.annotate()
        self.normalize_intensities()
        
        with mz_sorted(self):
            
            self.iisort = np.argsort(self.intensities)[::-1]
        
        self.irank = np.arange(len(self.mzs))
        self.imzsort  = np.argsort(self.mzs)
        self.sorted_by = 'intensities'
    
    def reload(self):
        
        modname = self.__class__.__module__
        mod = __import__(modname, fromlist = [modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)
    
    def __len__(self):
        
        return len(self.mzs)
    
    def sort_mz(self):
        """
        Sorts the scan by m/z values ascending.
        """
        
        if self.sorted_by == 'mzs':
            
            return
            
        elif hasattr(self, 'imzsort') and self.sorted_by == 'intensities':
            
            self.sort(self.imzsort)
            
        else:
            
            isort = np.argsort(self.mzs)
            self.sort(isort)
        
        self.sorted_by = 'mzs'
    
    def sort_intensity(self):
        """
        Sorts the scan by intensities descending.
        """
        
        if self.sorted_by == 'intensities':
            
            return
            
        elif hasattr(self, 'iisort') and self.sorted_by == 'mzs':
            
            self.sort(self.iisort)
            
        else:
            
            isort = np.argsort(self.intensities)[::-1]
            self.sort(isort)
        
        self.sorted_by = 'intensities'
    
    def sort(self, isort):
        """
        Applies sorted indices to the scan.
        """
        
        self.intensities = self.intensities[isort]
        self.mzs = self.mzs[isort]
        
        for attr in ('irank', 'annot', 'inorm'):
            
            if hasattr(self, attr):
                
                setattr(self, attr, getattr(self, attr)[isort])
        
        for ad, data in iteritems(self.adducts):
            
            data['annot'] = data['annot'][isort]
    
    def annotate(self):
        """
        Annotates the fragments in the scan with identities provided by
        the fragment database.
        """
        
        self.annot = self.get_annot()
    
    def get_annot(self, precursor = None, tolerance = None):
        """
        Returns array of annotations.
        Makes it possible to use different precursor or tolerance.
        """
        
        precursor = precursor or self.precursor
        tolerance = tolerance or self.tolerance
        
        annotator = fragdb.FragmentAnnotator(
            self.mzs,
            self.ionmode,
            precursor,
            tolerance = tolerance,
        )
        
        return np.array(list(annotator)) # this is array
                                         # only to be sortable
    
    def normalize_intensities(self):
        """
        Creates a vector of normalized intensities i.e. divides intensities
        by their maximum.
        """
        
        self.imax  = self.intensities.max()
        self.inorm = self.intensities / self.imax


class Scan(ScanBase):
    
    method_hg = {
        'fa_neg_1': ('FA', ()),
    }
    
    def __init__(
            self,
            mzs,
            ionmode,
            precursor = None,
            intensities = None,
            ms1_records = None,
            scan_id = None,
            sample_id = None,
            source = None,
            deltart = None,
            logger = None,
            verbose = False,
            tolerance = None,
            ms1_tolerance = None,
            rt = None,
        ):
        
        ScanBase.__init__(
            self,
            mzs,
            ionmode,
            precursor,
            intensities,
            tolerance = tolerance,
        )
        
        # get some settings
        self.ms1_tolerance = ms1_tolerance or settings.get('ms1_tolerance')
        self.check_ratio_g = settings.get(
            'even_chain_fragment_intensity_ratios_gl_gpl'
        )
        self.check_ratio_s = settings.get(
            'even_chain_fragment_intensity_ratios_sl'
        )
        self.iratio_logbase = settings.get(
            'chain_fragment_instensity_ratios_logbase'
        )
        self.chain_details = settings.get('ms2_scan_chain_details')
        
        if ms1_records is None and precursor is not None:
            
            # do the database lookup if not provided,
            # this is not efficient but makes possible
            # to easily use standalone `Scan` instances
            # for testing and such
            self.ms1_records = moldb.adduct_lookup(
                precursor, ionmode, tolerance = self.ms1_tolerance
            )
            
        else:
            
            # even if precursor is None, we end up with an empty dict
            self.ms1_records = ms1_records or {}
        
        self.scan_id   = scan_id
        self.sample_id = sample_id
        self.source    = source
        self.deltart   = deltart
        self.rt        = rt
        self.log       = logger
        self.verbose   = verbose
        
        self.scan_details = ScanDetails(
            sample_id = self.sample_id,
            scan_id   = self.scan_id,
            source    = self.source,
            deltart   = self.deltart,
        )
    
    @classmethod
    def from_mgf(
            cls,
            fname,
            scan_id,
            ionmode,
            sample_id = None,
            precursor = None,
            mgf_charge = None,
            **kwargs
        ):
        
        mgfreader = mgf.MgfReader(fname, charge = mgf_charge)
        sc = mgfreader.scan_by_id(scan_id)
        
        precursor = precursor or mgfreader.precursor_by_id(scan_id)
        
        if sc is not None:
            
            return cls(
                mzs = sc[:,0],
                intensities = sc[:,1],
                ionmode = ionmode,
                precursor = precursor,
                scan_id = scan_id,
                sample_id = sample_id,
                source = fname,
                **kwargs
            )
    
    def reload(self):
        
        modname = self.__class__.__module__
        mod = __import__(modname, fromlist=[modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)
    
    def print_scan(self):
        """
        Prints the list of fragments as an annotated table.
        """
        
        if self.log:
            
            self.log.msg(self.scan_str())
    
    def show(self):
        """
        Prints the scan table to standard output.
        """
        
        sys.stdout.write(self.scan_str())
    
    def scan_str(self):
        """
        Returns the scan table as string.
        """
        
        lindent = ' ' * 12
        
        header = '%s\n%s%s\n' % (
            ''.join((
                lindent,
                'Frag. m/z'.ljust(12),
                'Intensity'.ljust(12),
                'Identity'.ljust(36),
                'NL mass'.rjust(12)
            )),
            lindent,
            '=' * 12 * 6
        )
        
        table = '\n'.join((
            ''.join((
                lindent,
                '%12.4f' % self.mz[i],
                '%10u'   % self.intensities[i],
                ann.name,
                (
                    '%12.4f' % self.nl(mz[i])
                        if self.precursor else
                    'NA'.rjust(12)
                )
            ))
            for i in xrange(len(self.mz))
            for ann in (
                self.annot[i]
                    if self.annot[i] else
                (Namespace(name = 'Unknown'),)
            )
        ))
        
        return '%s\n%s\n\n' % (
            self.sample.__str__(),
            header,
            table
        )
    
    def html_table(self):
        
        # TODO
        pass
    
    def nl(self, mz, adduct = None):
        """
        For m/z returns the corresponding neutral loss m/z.
        If precursor ion mass is unknown returns `numpy.nan`.
        """
        
        if adduct is None:
            
            return self.precursor - mz if self.precursor else np.nan
            
        else:
            
            self.adduct(adduct)
            
            return self.adducts[adduct]['fake_precursor'] - mz
    
    def full_list_str(self):
        """
        Returns list of fragments as single string.
        """
        
        return '; '.join(
            '/'.join(
                '%s (%u)' % (
                    ann.name,
                    self.intensities[i]
                )
                    if ann is not None else
                'Unknown (%.03f) (%u)' % (
                    self.mzs[i],
                    self.intensities[i]
                )
            )
            for i in xrange(len(self))
            for ann in (
                self.annot[i]
                    if self.annot[i] else
                (None,)
            )
        )
    
    def most_abundant_mz(self):
        """
        Returns the m/z of the fragment with highest intensity.
        """
        
        result = self.mzs[0]
        
        if self.verbose:
            
            self.log.msg('\t\t  -- Most abundant m/z is %.03f' % result)
        
        return result
    
    def mz_match(self, mz_detected, mz):
        """
        Tests if two m/z's can be accepted to be equal.
        """
        
        return lookup.match(mz_detected, mz, self.tolerance)
    
    def mz_lookup(self, mz):
        """
        Returns the index of the closest m/z value
        detected in the scan if it is within the
        range of tolerance, otherwise None.
        """
        
        self.sort_mz()
        
        imz = lookup.find(self.mzs, mz, self.tolerance)
        i = self.imzsort[imz] if imz else None
        
        self.sort_intensity()
        
        return i
    
    def has_mz(self, mz):
        """
        Tells if an m/z exists in this scan.
        """
        
        result = self.mz_lookup(mz) is not None
        
        if self.verbose:
            
            self.log.msg(
                '\t\t  -- m/z %.03f occures in this scan? -- %s' % (
                    mz, str(result)
                )
            )
        
        return result
    
    def has_nl(self, nl, adduct = None):
        """
        Tells if a neutral loss exists in this scan.
        """
        
        result = self.has_mz(self.nl(nl, adduct = adduct))
        
        if self.verbose:
            
            self.feature.msg(
                '\t\t  -- neutral loss of %.03f occures in '
                'this scan? Looked up m/z %.03f - %.03f = %.03f -- %s' % (
                    nl,
                    self.precursor,
                    nl,
                    self.nl(nl, adduct = adduct),
                    str(result)
                )
            )
        
        return result
    
    def fragment_by_name(self, name, adduct = None):
        """
        Returns the index of a fragment by its name.
        Returns `None` if the fragment does not exist in the scan.
        Returns `False` if the fragment name could not be found in
        the database.
        
        The lookup still goes by m/z, the name first looked up in the
        fragment database and the scan searched for the corresponding m/z.
        The name makes if obvious if this is a charged fragment or a neutral
        loss, hence it is not necessary to provide this information.
        
        Args
        ----
        :param str name:
            Fragment full name as used in the database 2nd column,
            e.g. `PE [P+E] (140.0118)`.
        """
        
        frag = fragdb.by_name(name, self.ionmode)
        
        if frag is not None:
            
            if frag[6] == 0:
                
                return self.nl_lookup(frag[0], adduct = adduct)
                
            else:
                
                return self.mz_lookup(frag[0])
        
        return False
    
    def has_fragment(self, name, adduct = None):
        """
        Tells if a fragment exists in this scan by its name.
        
        Returns bool or `None` if fragment name could not be found
        in the database.
        """
        
        i = self.fragment_by_name(name, adduct = adduct)
        
        return None if i is False else i is not None
    
    def nl_lookup(self, nl, adduct = None):
        """
        Looks up if a neutral loss exists in this scan and returns its index.
        """
        
        return self.mz_lookup(self.nl(nl, adduct = adduct))
    
    def most_abundant_fragment_is(self, name, adduct = None):
        """
        Tells if the fragment name is the highest abundant.
        Returns `None` if the fragment name could not be
        found in the database.
        """
        
        frag = fragdb.by_name(name, self.ionmode)
        
        if frag is not None:
            
            mz = (
                self.nl(frag[0], adduct = adduct)
                    if frag[6] == 0 else
                frag[0]
            )
            
            return self.mz_match(self.mzs[0], mz)
    
    def fragment_among_most_abundant(self, name, n = 2, adduct = None):
        """
        Tells if the fragment is among the top `n`.
        """
        
        frag = fragdb.by_name(name, self.ionmode)
        
        if frag is not None:
            
            mz = (
                self.nl(frag[0], adduct = adduct)
                    if frag[6] == 0 else
                frag[0]
            )
            
            return self.mz_among_most_abundant(mz, n = n)
    
    def fragment_percent_of_most_abundant(
            self,
            name,
            percent = 80.0,
            adduct = None,
        ):
        """
        Tells if a fragment has at least certain percent of intensity
        compared to the highest peak.
        """
        
        frag = fragdb.by_name(name, self.ionmode)
        
        if frag is not None:
            
            mz = (
                self.nl(frag[0], adduct = adduct)
                    if frag[6] == 0 else
                frag[0]
            )
            
            return self.mz_percent_of_most_abundant(mz, percent = percent)
    
    def most_abundant_mz_is(self, mz):
        """
        Tells if the m/z with the highest intensity is `mz`.
        Returns `None` if the fragment name could not be
        found in the database.
        """
        
        result = self.mz_match(self.most_abundant_mz(), mz)
        
        if self.verbose:
            
            self.log.msg(
                '\t\t  -- Is m/z %.03f the most abundant one? -- %s' % (
                    mz,
                    str(result)
                )
            )
        
        return result
    
    def mz_among_most_abundant(self, mz, n = 2):
        """
        Tells if an m/z is among the most aboundant `n` fragments
        in a spectrum.
        
        Args
        ----
        :param float mz:
            The m/z value.
        :param int n:
            The number of most abundant fragments considered.
        """
        
        self.sort_mz()
        
        i = lookup.find(
            self.mzs[self.irank < n], # intensity rank < n
            mz,
            self.tolerance
        )
        
        self.sort_intensity()
        
        if self.verbose:
            
            self.log.msg(
                '\t\t  -- m/z %.03f is among the %u most abundant? -- %s' % (
                    mz, n, str(i is not None)
                )
            )
        
        return i is not None
    
    def nl_among_most_abundant(self, nl, n = 2, adduct = None):
        """
        Tells if a neutral loss corresponds to one of the
        most aboundant `n` fragments in a spectrum.
        
        Args
        ----
        :param float nl:
            The mass of the neutral loss.
        :param int n:
            The number of most abundant fragments considered.
        """
        
        result = self.mz_among_most_abundant(
            self.nl(nl, adduct = adduct),
            n = n,
        )
        
        if self.verbose:
            
            self.log.msg(
                '\t\t  -- neutral loss %.03f is among '
                'the %u most abundant? -- %s' % (
                    nl, n, str(result)
                )
            )
        
        return result
    
    def get_intensity(self, mz):
        """
        Returns the relative intensity of a fragment ion from its m/z.
        Value is `None` if m/z does not present.
        """
        
        i = self.mz_lookup(mz)
        
        if i is not None:
            
            return self.inorm[i]
        
        return None
    
    def get_nl_intensity(self, nl, adduct = None):
        """
        Returns the relative intensity of a neutral loss fragment ion.
        Value is `None` if neutral loss does not present.
        """
        
        return self.get_intensity(self.nl(nl, adduct = adduct))
    
    def mz_percent_of_most_abundant(self, mz, percent = 80.0):
        """
        Tells if an m/z has at least certain percent of intensity
        compared to the most intensive fragment.
        
        Args
        ----
        :param float mz:
            The m/z value.
        :param float percent:
            The threshold in percent of the highest intensity.
        
        """
        
        i = self.get_intensity(mz)
        result = i and i >= percent / 100.
        
        if self.verbose:
            
            self.feature.msg(
                '\t\t  -- m/z %.03f has abundance at least %.01f %% of'
                ' the highest abundance? -- %s\n' % (
                    mz, percent, str(result)
                )
            )
        
        return result
    
    @classmethod
    def match_chtype(cls, value, accepted):
        """
        Matches strings or strings to set of strings, optionally negative.
        Calls `match_chattr` with `typ = basestring`.
        """
        
        return cls.match_chattr(value, accepted, typ = basestring)
    
    @staticmethod
    def match_chattr(value, accepted, typ = int):
        """
        Args
        ----
        :param int value:
            The actual value.
        :param int,set accepted:
            A single value or a set of values to match against.
            Negative match is possible by providing a tuple with `False`
            as it's first element and the set of not acceptable values
            as the second element.
        """
        
        return (
            accepted is None or
            # simple match
            (isinstance(accepted, typ) and value == accepted) or
            (
                not isinstance(accepted, typ) and (
                    # multiple values
                    value in accepted or (
                        # negation
                        hasattr(accepted, '__getitem__') and
                        accepted[0] == False and
                        value not in accepted[1]
                    )
                )
            )
        )
    
    @classmethod
    def match_annot(
            cls,
            annot,
            frag_type = None,
            chain_type = None,
            c = None,
            u = None
        ):
        """
        Tests a fragment annotation against criteria of fragment type,
        chain type, carbon count and unsaturation.
        """
        
        return all((
            cls.match_chattr(annot.fragtype, frag_type, typ = basestring),
            cls.match_chattr(annot.chaintype, chain_type, typ = basestring),
            cls.match_chattr(annot.c, c),
            cls.match_chattr(annot.u, u),
        ))
    
    def highest_fragment_by_chain_type(
            self,
            head = None,
            frag_type = None,
            chain_type = None,
            c = None,
            u = None,
            adduct = None,
        ):
        """
        Returns the highest instensity fragment matching a particular
        chain type.
        Returns fragment index or `None` if no such fragment exists.
        
        Arguments passed to `chain_fragment_type_is`.
        """
        
        frags = self.fragments_by_chain_type(
            head = head,
            frag_type = frag_type,
            chain_type = chain_type,
            c = c,
            u = u,
            adduct = adduct,
        )
        
        try:
            
            return next(frags)
            
        except StopIteration:
            
            return None
    
    def fragments_by_chain_type(
            self,
            head = None,
            frag_type = None,
            chain_type = None,
            c = None,
            u = None,
            adduct = None,
        ):
        """
        Collects fragments matching a particular chain type.
        Yields indices.
        Arguments passed to `chain_fragment_type_is`.
        """
        
        head = len(self.mzs) if head is None else min(head, len(self.mzs))
        
        for i in xrange(head):
            
            if self.chain_fragment_type_is(
                i,
                frag_type = frag_type,
                chain_type = chain_type,
                c = c,
                u = u,
                return_annot = False,
                adduct = adduct,
            ):
                
                yield i
    
    def chain_fragment_type_among_most_abundant(
            self,
            n = 2,
            frag_type = None,
            chain_type = None,
            c = None,
            u = None,
            adduct = None,
        ):
        """
        Tells if a particular type of aliphatic chain fragment can be
        found among the `n` highest intensity fragments.
        
        Arguments passed to `chain_fragment_type_is`.
        """
        
        return bool(len(list(
            self.fragments_by_chain_type(
                head = n,
                frag_type = frag_type,
                chain_type = chain_type,
                c = c,
                u = u,
                adduct = adduct,
            )
        )))
    
    def chain_fragment_type_is(
            self,
            i,
            frag_type = None,
            chain_type = None,
            c = None,
            u = None,
            return_annot = False,
            adduct = None,
        ):
        """
        Tells if an aliphatic chain fragment is a specified type. The type
        should be the string representation of the fragment,
        e.g. `FA-O` for fatty acid minus oxygen fragments.
        
        Returns bool or fragment annotations if `return_annot = True`.
        
        Args
        ----
        :param int i:
            Index of the fragment.
        :param bool return_annot:
            Return iterator with the matching fragment annotations.
        """
        
        if i >= len(self.mzs):
            
            return False
        
        annot = self.annot if adduct is None else self.adduct_annot(adduct)
        
        result = any((
            self.match_annot(an, frag_type, chain_type, c, u)
            for an in annot[i]
        ))
        
        if self.verbose:
            
            criteria = []
            if frag_type is not None:
                criteria.append('of type `%s`' % frag_type)
            if chain_type is not None:
                criteria.append('of chain type `%s`' % chain_type)
            if c is not None:
                criteria.append('with carbon count of %a' % c)
            if u is not None:
                criteria.append('with unsaturation of %a' % u)
            
            self.log.msg(
                '\t\t  -- Fragment #%u (%.03f): '
                'is it a fragment %s? -- %s' % (
                    i,
                    self.mz[i],
                    ' and '.join(criteria),
                    str(result)
                )
            )
        
        if return_annot:
            
            result = (
                an
                for an in annot[i]
                if self.match_annot(an, frag_type, chain_type, c, u)
            )
        
        return result
    
    def chains_of_type(
            self,
            chain_type = None,
            frag_type = None,
            c = None,
            u = None,
            yield_annot = False,
            adduct = None,
        ):
        """
        Iterates chain fragments matching certain criteria.
        Yields fragment indices or indices with annotations.
        
        Args
        ----
        :param bool yield_annot:
            Yield tuples of indices and annotations instead of indices only.
        """
        
        for i in xrange(len(self.mzs)):
            
            if self.chain_fragment_type_is(
                i = i,
                chain_type = chain_type,
                frag_type = frag_type,
                c = c,
                u = u,
                adduct = adduct,
            ):
                
                if yield_annot:
                    
                    for annot in self.chain_fragment_type_is(
                        i = i,
                        chain_type = chain_type,
                        frag_type = frag_type,
                        c = c,
                        u = u,
                        return_annot = True,
                        adduct = adduct,
                    ):
                        
                        yield i, annot
                    
                else:
                    
                    yield i
    
    def has_chain_fragment_type(
            self,
            chain_type = None,
            frag_type = None,
            c = None,
            u = None,
            adduct = None,
        ):
        """
        Tells if at least one fragment matches certain criteria.
        Arguments passed to `chain_fragment_type_is`.
        """
        
        return self.highest_fragment_by_chain_type(
            chain_type = chain_type,
            frag_type = frag_type,
            c = c,
            u = u,
            adduct = adduct,
        ) is not None
    
    def matching_chain_combinations(
            self,
            record,
            head = None,
            intensity_threshold = None,
            expected_intensities = None,
            no_intensity_check = False,
            chain_param = (),
            adduct = None,
        ):
        """
        Provides a way to see if specific chain combinations exist.
        The database record defines the chain layout of the molecule.
        Further arguments are passed to `chain_combinations`.
        The `chain_param` tuple contains dicts to match against chain
        fragments. All of these dicts must match at least one fragment
        identification. Only combinations matching all criteria yielded.
        
        Args
        ----
        :param lipproc.LipidRecord record:
            A lipid database record matching the MS1 m/z.
        :param int head:
            Consider only the n most intensive fragments.
        :param float intensity_threshold:
            Consider only fragments with intensity higher than threshold.
            Relative to highest fragment, between 0 and 1.
        :param expected_intensities:
            See at `intensity_ratios`.
        :param bool no_intensity_check:
            Completely skip checking intensity ratios.
        :param tuple chain_param:
            Tuple of dicts. Each dict contains criteria for one chain moiety.
            Keys can be `chain_type`, `frag_type`, `c` and `u`.
            These can be single str or int values or sets of multiple
            values. If omitted or `None` any value will pass the filter.
            An empty tuple which is the default value will pass through
            everything, this is equivalent with calling `chain_combinations`.
        """
        
        def match(key, param, value):
            
            return (
                key not in param or
                param[key] is None or (
                    type(param[key]) in {int, str} and
                    value == param[key]
                ) or (
                    type(param[key]) in {set, list, tuple} and
                    value in param[key]
                )
            )
        
        if (
            record.chainsum and
            len(record.chainsum) > 1 and
            len(chain_param) == 1
        ):
            
            chain_param = chain_param * len(record.chainsum)
        
        for chains, details in self.chain_combinations(
            record,
            head = None,
            intensity_threshold = 0,
            expected_intensities = None,
            no_intensity_check = False,
            frag_types = None,
            fragment_details = True,
            adduct = adduct,
        ):
            
            if (
                not chain_param or
                all((
                    not param or
                    any((
                        all((
                            match('chain_type', param, ch.typ),
                            match('frag_type', param, details.fragtype[i]),
                            match('c', param, ch.c),
                            match('u', param, ch.u),
                        ))
                        for i, ch in enumerate(chains)
                    ))
                    for param in chain_param
                ))
            ):
                
                yield chains, details
    
    def has_chain_combination(
            self,
            record,
            head = None,
            intensity_threshold = None,
            expected_intensities = None,
            no_intensity_check = False,
            chain_param = (),
            adduct = None,
        ):
        """
        Tells if a certain chain combination exists in the scan.
        
        Arguments passed to `matching_chain_combinations`.
        """
        
        ccomb = self.matching_chain_combinations(
            record = record,
            head = head,
            intensity_threshold = intensity_threshold,
            expected_intensities = expected_intensities,
            no_intensity_check = no_intensity_check,
            chain_param = chain_param,
            adduct = adduct,
        )
        
        try:
            
            _ = next(ccomb)
            
            return True
            
        except StopIteration:
            
            return False
    
    def _matching_chain_pairs(
            self,
            record,
            chain_type = None,
            frag_type = None,
            c = None,
            u = None,
            partner_chain_types = None,
            partner_frag_types = None,
            count_only = False,
            adduct = None,
        ):
        
        # small caching of constraint matching
        type_pos = {}
        
        def get_positions(self, frag_type):
            
            if frag_type not in type_pos:
                
                type_pos[frag_type] = self.positions_for_frag_type(
                    record, frag_type
                )
            
            return type_pos[frag_type]
        # ##
        
        for i, iannot in self.chains_of_type(
            chain_type = chain_type,
            frag_type = frag_type,
            c = c,
            u = u,
            yield_annot = True,
            adduct = adduct,
        ):
            
            partner_c = record.chainsum.c - annot.c
            partner_u = record.chainsum.u - annot.u
            
            if partner_c < 1 or partner_u < 0:
                
                continue
            
            pos_i = get_positions(iannot.fragtype)
            
            for j, jannot in self.chains_of_type(
                c = partner_c,
                u = partner_u,
                yield_annot = True,
                adduct = adduct,
            ):
                
                if (
                    partner_chain_types is None or
                    jannot.chaintype in partner_chain_types
                ) and (
                    partner_frag_types is None or
                    jannot.fragtype in partner_frag_types
                ):
                    
                    pos_j = get_positions(jannot.fragtype)
                    
                    if (
                        not pos_i or
                        not pos_j or (
                            len(pos_i) == 1 and
                            len(pos_j) == 1 and
                            not pos_i - pos_j
                        )
                    ):
                        
                        continue
                    
                    yield (
                        lipproc.Chain(
                            
                        )
                    )
    
    def positions_for_frag_type(self, record, frag_type):
        """
        Returns the possible chain positions for a record and a fragment type.
        """
        
        # constraints for the fragment type
        constr = fragdb.constraints(frag_type, self.ionmode)
        # set of possible positions of the chain
        # which this fragment originates from
        return lipproc.match_constraints(record, constr)[1]
    
    def is_chain(self, i, adduct = None):
        """
        Examines if a fragment has an aliphatic chain.
        """
        
        annot = self.adduct_annot(adduct)
        
        result = any(not np.isnan(an.c) for an in annot[i])
        
        if self.verbose:
            
            self.log.msg(
                '\t\t -- Fragment #%u (%.03f)'
                'has an aliphatic chain? -- %s' % (
                    i,
                    self.mzs[i],
                    str(result)
                )
            )
        
        return result
    
    def is_chain_type(self, i, typ = 'FA', adduct = None):
        """
        Checks if a fragment might origin from a certain aliphatic
        chain type (e.g. `FA` -- fatty acyl, `FAL` -- fatty alkyl,
        `Sph` -- sphingosin base).
        """
        
        return self.chain_fragment_type_is(
            i, chain_type = typ, adduct = adduct
        )
    
    def is_fa(self, i, adduct = None):
        """
        Tells if a fragment origins from a fatty acyl moiety.
        """
        
        return self.is_chain_type(i, adduct = adduct)
    
    def is_fal(self, i, adduct = None):
        """
        Tells if a fragment origins from a fatty alkyl moiety.
        """
        
        return self.is_chain_type(i, 'FAL', adduct = adduct)
    
    def is_sph(self, i, adduct = None):
        """
        Tells if a fragment origins from a shpingosin backbone.
        """
        
        return self.is_chain_type(i, 'Sph', adduct = adduct)
    
    def is_type(self, i, typ, adduct = None):
        """
        Tells if a fragment is a certain type.
        """
        
        return self.chain_fragment_type_is(
            i, frag_type = typ, adduct = adduct
        )
    
    def annot_by_type(
            self,
            i,
            chain_type = None,
            frag_type = None,
            adduct = None,
        ):
        """
        Returns the annotations matching certain types.
        """
        
        annot = self.adduct_annot(adduct)
        
        return tuple(
            an
            for an in annot[i]
            if (
                self.match_chtype(an.chaintype, chain_type) and
                self.match_chtype(an.fragtype,  frag_type)
            )
        )
    
    def cu_by_type(
            self,
            i,
            chain_type = None,
            frag_type = None,
            adduct = None,
        ):
        """
        Returns `(carbon count, unsaturation)` tuples for fragment `i`
        considering only the the requested chain types and fragment types.
        """
        
        return tuple(
            (a.c, a.u)
            for a in
            self.annot_by_type(
                i,
                chain_type = chain_type,
                frag_type = frag_type,
                adduct = adduct,
            )
        )
    
    def _build_chain_list(self, annot = None):
        """
        Builds a list of chains which facilitates the anlysis of chain
        combinations.
        """
        
        annot = annot if type(annot) is np.ndarray else self.annot
        
        return tuple(
            ChainFragment(
                a.c, a.u, a.fragtype, a.chaintype, i, self.intensities[i]
            )
            for i, aa in enumerate(annot)
            for a in aa
            if a.c and not np.isnan(a.c)
        )
    
    def build_chain_list(self, rebuild = False):
        
        if (
            not rebuild and
            hasattr(self, 'chain_list')
        ):
            return
        
        self.chain_list = self._build_chain_list()
    
    def chain_among_most_abundant(
            self,
            head = 1,
            chain_type = None,
            frag_type = None,
            c = None,
            u = None,
            min_mass = None,
            skip_non_chains = False,
            adduct = None,
        ):
        """
        Returns `True` if the defined type of chain fragment can be found
        among the most abundant fragments.
        """
        
        if self.verbose:
            
            self.log.msg(
                '\t\t -- Checking for certain type of chain among the top '
                '%u fragments.' % head
            )
        
        result = any((
            self.chain_fragment_type_is(
                i,
                frag_type = frag_type,
                chain_type = chain_type,
                c = c,
                u = u,
                adduct = adduct,
            )
            for i in (
                xrange(head)
                    if not skip_non_chains else
                itertools.islice(
                    (
                        i for i in xrange(len(self.mzs))
                            if (
                                not skip_non_chains or self.is_chain(i)
                            ) and (
                                min_mass is None or self.mzs[i] >= min_mass
                            )
                    ),
                    head
                )
            )
        ))
        
        if self.verbose:
            
            self.log.msg(
                '\t\t -- Checked certain type of chain among the top '
                '%u fragments. -- %s' % (head, str(result))
            )
        
        return result
    
    def get_most_abundant_chain(
            self,
            head = 1,
            frag_type = None,
            chain_type = None,
            c = None,
            u = None,
            adduct = None,
        ):
        """
        Looks up the most abundant fatty acid fragment of the given type.
        Returns the fragment index.
        """
        
        for i in xrange(len(self)):
            
            if self.chain_fragment_type_is(
                i,
                frag_type = frag_type,
                chain_type = chain_type,
                c = c,
                u = u,
                adduct = adduct,
            ):
                
                return i
    
    def chain_percent_of_most_abundant(
            self,
            percent,
            frag_type = None,
            chain_type = None,
            c = None,
            u = None,
            adduct = None,
        ):
        """
        Tells if a certain chain present with an abundance at least the
        given percent of the most abundant fragment.
        
        Args
        ----
        :param float percent:
            Percentage, between 0 and 100.
        """
        
        result = any((
            self.chain_among_most_abundant(
                i,
                frag_type = frag_type,
                chain_type = chain_type,
                c = c,
                u = u,
                adduct = adduct,
            )
            for i in
            itertools.takewhile(
                lambda i:
                    self.inorm[i] > percent / 100.0,
                xrange(len(self.mzs))
            )
        ))
        
        return result
    
    def mz_most_abundant_fold(self, mz, fold):
        """
        Tells if an m/z is the most abundant fragment
        and it has at least a certain fold higher intensity
        than any other fragment.
        
        Args
        ----
        :param float mz:
            The m/z value.
        :param float fold:
            The m/z must be this times higher than any other.
        """
        
        result = (
            self.most_abundant_mz_is(mz) and (
                len(self.mzs) == 1 or
                self.intensities[1] * fold <= self.intensities[0]
            )
        )
        
        if self.verbose:
            
            self.log.msg(
                '\t\t  -- m/z %.03f is at least %u times higher than '
                'any other? -- %s\n' % (mz, fold, str(result))
            )
        
        return result
    
    def cer_fa_test(self, i_fa, i_sph, adduct = None):
        
        return (
            self.chain_fragment_type_is(
                i_fa,
                frag_type = 'FA+C2+NH2-O',
                adduct = adduct,
            ) and
            self.chain_fragment_type_id(
                i_sph,
                frag_type = 'Sph-C2H4-NH2-H2O',
                adduct = adduct,
            ) and
            self.intensities[i_fa] > self.intensities[i_sph] * 2
        )
    
    def has_chain_combinations(self, rec, adduct = None, **kwargs):
        """
        Calls `chain_combinations` only to check if at least one
        conbination explicitely confirmed.
        """
        
        ccomb = self.chain_combinations(rec, adduct = adduct, **kwargs)
        
        try:
            
            _ = next(ccomb)
            
            return True
            
        except StopIteration:
            
            return False
    
    def chain_combinations(
            self,
            rec,
            head = None,
            intensity_threshold = 0,
            expected_intensities = None,
            no_intensity_check = False,
            frag_types = None,
            fragment_details = None,
            adduct = None,
        ):
        """
        Finds all combinations of chain derived fragments matching the
        total carbon count and unsaturation in a database record.
        
        Yields tuple of chains (`lipproc.Chain` objects).
        
        Arguments not listed here explained at `frags_for_positions`.
        
        Args
        ----
        :param lipproc.LipidRecord rec:
            The database record to match against.
        :param bool no_intensity_check:
            Completely skip checking intensity ratios.
        :param float intensity_threshold:
            Only fragments with intensities above this threshold will be
            considered. Intensities relative to the highest, between 0 and 1.
        :param tuple frag_types:
            See at `frags_for_positions`.
        """
        
        if not rec.chainsum and not rec.chains:
            
            return
        
        self.build_chain_list()
        
        chainsum = rec.chainsum or lipproc.sum_chains(rec.chains)
        
        frags_for_position = self.frags_for_positions(
            rec,
            head = head,
            intensity_threshold = intensity_threshold,
            frag_types = frag_types,
            adduct = adduct,
        )
        
        if len(frags_for_position) != len(rec.chainsum.typ):
            # if one or more chains have no corresponding fragment
            # we do not yield anything;
            # for finding missing those chains `missing_chains`
            # can be used
            return
        
        # iterate all combinations
        for frag_comb in itertools.product(
            *(
                # making a sorted list of lists from the dict
                i[1] for i in
                sorted(frags_for_position.items(), key = lambda i: i[0])
            )
        ):
            
            if (
                sum(frag.c for frag in frag_comb) == chainsum.c and
                sum(frag.u for frag in frag_comb) == chainsum.u
            ):
                
                if (
                    # bypass intensity check
                    no_intensity_check or
                    self._intensity_check(
                        frag_comb, chainsum, expected_intensities
                    )
                ):
                    
                    # now all conditions satisfied:
                    yield self._chains_frag_comb(
                        frag_comb, chainsum, details = fragment_details
                    )
    
    def frags_for_positions(
            self,
            rec,
            head = None,
            intensity_threshold = 0,
            frag_types = None,
            adduct = None,
        ):
        """
        Returns the possible fragments for each positions (sn1, sn2 in
        glycerophospholipids, sphingosine base and N-acyl in sphingolipids,
        etc).
        
        :param int head:
            If `None` or `numpy.inf` all fragment ions will be considered,
            otherwise only the first most aboundant until the number `head`.
        :param float intensity_threshold:
            Only fragments with intensities above this threshold will be
            considered. Intensities relative to the highest, between 0 and 1.
        :param tuple frag_types:
            Limit the query to certain fragment types in addition to
            built in fragment constraints and other criteria.
            A tuple of tuples with fragment type names can be provided
            each for one position with None values where default fragment
            types should be used. E.g. `(('FA_mH', 'Lyso_PA'), None)` means
            the chain in first position might be found as fatty acid minus
            hydrogen fragment or lysophosphatidic acid fragment, while the
            second position could be anything allowed by the built in
            constraints.
        """
        
        frags_for_position = collections.defaultdict(list)
        
        chain_list = self.adduct_chain_list(adduct)
        
        for frag in chain_list:
            
            if (
                (head and frag.i >= head) or
                self.inorm[frag.i] < intensity_threshold
            ):
                
                break
            
            chpos = self.positions_for_frag_type(rec, frag.fragtype)
            
            for ci in chpos:
                
                if (
                    # frag_types constraints
                    not frag_types or
                    not frag_types[ci] or
                    frag.fragtype in frag_types[ci]
                ):
                    
                    frags_for_position[ci].append(frag)
        
        return dict(frags_for_position)
    
    def intensity_ratios(
            self,
            intensities,
            frag_indices = None,
            expected = None,
            logbase = None,
        ):
        """
        Tells if the ratio of a list of intensities fits the one in
        `expected` or is more or less even if `expected` is `None`.
        
        :param list intensities:
            List of intensities.
        :param list expected:
            List with expected intensity proportions. E.g. `[1, 1, 2]`
            means the third ion is twice higher intense than the 2 others.
        :param int logbase:
            The fold difference tolerance when comparing intensities.
            E.g. if this is 2, then an almost twice less or more intense
            ion will considered to have similar intensity.
        """
        
        logbase = settings.get('chain_fragment_instensity_ratios_logbase')
        
        if len(intensities) == 1:
            
            return True
        
        if any(i <= 0.0 for i in intensities):
            
            raise ValueError(
                'Negative intensity value encountered'
                '(sample=%s, ion mode=%s, scan=%u)' % (
                    str(self.sample), self.ionmode, self.scan_id
                )
            )
        
        frag_indices = frag_indices or list(range(len(intensities)))
        # to know if one fragment contributes more than one times;
        # intensities divided by the times the fragment is incident
        cntr = collections.Counter(frag_indices)
        
        # by default expecting more or less equal intensities
        if expected is None:
            
            expected = [1.0] * len(intensities)
        
        # intensities corrected by the expected and the counts
        intcorr = [
            ins / expected[i] / cntr[ind]
            for (i, ins), ind in zip(enumerate(intensities), frag_indices)
        ]
        
        return (
            all((
                math.log(co[0], logbase) - math.log(co[1], logbase) <= 1
                for co in itertools.combinations(intcorr, 2)
            ))
        )
    
    def _intensity_check(
            self,
            frag_comb,
            chainsum,
            expected_intensities = None
        ):
        """
        Performs the chain intensity ratio check according to settings.
        """
        
        return (
            not (
                # need to check intensity ratios
                (chainsum.typ[0] == 'Sph' and self.check_ratio_s) or
                (chainsum.typ[0] != 'Sph' and self.check_ratio_g) or
                expected_intensities
            ) or
            self.intensity_ratios(
                # intensity ratios are ok
                intensities = tuple(f.intensity for f in frag_comb),
                frag_indices = tuple(f.i for f in frag_comb),
                expected = expected_intensities,
                logbase = self.iratio_logbase
            )
        )
    
    def _chains_frag_comb(
            self,
            frag_comb,
            chainsum,
            details = None,
            missing_position = None,
            missing_chain = None,
        ):
        """
        Returns a tuple of chains from a fragment annotation combination
        and a database record chain summary object.
        
        Potentially includes a missing chain which does not yield any
        fragment.
        """
        
        # boolean: whether we provide details or not
        details = self.chain_details if details is None else details
        
        return (
            tuple(
                lipproc.Chain(
                    c = frag_comb[ifrag].c,
                    u = frag_comb[ifrag].u,
                    typ = frag_comb[ifrag].chaintype,
                    attr = lipproc.ChainAttr(
                        # take the sphingosine base type
                        # from the chainsum of the record
                        sph = chainsum.attr[ichain].sph,
                        ether = frag_comb[ifrag].chaintype == 'FAL',
                        oh = chainsum.attr[ichain].oh
                    )
                )
                if ifrag is not None else
                missing_chain
                # chain indices and fragment indices
                for ichain, ifrag in iterator_insert(
                    len(chainsum),
                    missing_position,
                )
            ),
            ChainIdentificationDetails(
                rank     = tuple(
                    frag_comb[ifrag].i
                    if ifrag is not None else None
                    for ichain, ifrag in iterator_insert(
                        len(chainsum),
                        missing_position,
                    )
                ),
                i        = tuple(
                    self.inorm[frag_comb[ifrag].i]
                    if ifrag is not None else None
                    for ichain, ifrag in iterator_insert(
                        len(chainsum),
                        missing_position,
                    )
                ),
                fragtype = tuple(
                    frag_comb[ifrag].fragtype
                    if ifrag is not None else None
                    for ichain, ifrag in iterator_insert(
                        len(chainsum),
                        missing_position,
                    )
                ),
            ) if details else None
        )
    
    def missing_chain(
            self,
            rec,
            missing_position = 1,
            head = None,
            intensity_threshold = 0,
            expected_intensities = None,
            no_intensity_check = False,
            frag_types = None,
            adduct = None,
        ):
        """
        Finds ''missing'' chains i.e. which could complement the chains
        identified among the fragments to fit the species in the record.
        
        Yields tuples with first element a tuple of identified chains and
        as second element the missing chain.
        
        Works a similar way to `chain_combinations`.
        
        Args
        ----
        :param int missing_position:
            Position of the missing chain. 0, 1, 2 are sn1, sn2 and sn3
            positions on glycerol, 0 and 1 are sphingosine base and
            N-acyl in sphingolipids, respectively.
            By default is 1 (sn2 or N-acyl).
        """
        
        chain_list = self.adduct_chain_list(adduct = adduct)
        
        chainsum = rec.chainsum or lipproc.sum_chains(rec.chains)
        
        frags_for_position = self.frags_for_positions(
            rec,
            head = head,
            intensity_threshold = intensity_threshold,
            frag_types = frag_types,
            adduct = adduct,
        )
        
        if missing_position >= len(rec.chainsum.typ):
            
            raise ValueError(
                'No chain known at position %u' % missing_position
            )
        
        if missing_position in frags_for_position:
            
            chains_at_missing = frags_for_position[missing_position]
            del frags_for_position[missing_position]
            
        else:
            
            chains_at_missing = []
        
        # iterate all combinations
        for frag_comb in itertools.product(
            *(
                # making a sorted list of lists from the dict
                i[1] for i in
                sorted(iteritems(frags_for_position), key = lambda i: i[0])
            )
        ):
            
            # if more than one chain missing
            if len(rec.chainsum) - len(frag_comb) > 1:
                
                continue
            
            missing_c = chainsum.c - sum(frag.c for frag in frag_comb)
            missing_u = chainsum.u - sum(frag.u for frag in frag_comb)
            
            # do not yield impossible values
            if missing_c < 1 or missing_u < 0 or missing_u > missing_c - 1:
                
                continue
            
            if (
                # bypass intensity check
                no_intensity_check or
                self._intensity_check(
                    frag_comb, chainsum, expected_intensities
                )
            ):
                
                missing_chain = lipproc.Chain(
                    c = missing_c,
                    u = missing_u,
                    typ = chainsum.typ[missing_position],
                    attr = chainsum.attr[missing_position]
                )
                
                # now all conditions satisfied:
                yield self._chains_frag_comb(
                    frag_comb,
                    chainsum,
                    missing_position = missing_position,
                    missing_chain = missing_chain,
                )
    
    def cu_complete(self, chainsum, chain = None, c = None, u = None):
        """
        Returns the carbon count and unsaturation needed to complete
        the `chain` or `c` and `u` to fit the `chainsum`.
        
        Returns tuple of c and u.
        """
        
        c = c or chain.c
        u = u or chain.u
        
        return chainsum.c - c, chainsum.u - u
    
    def iterrecords(self, adducts = None):
        """
        Iterates MS1 records.
        Yields tuple of adduct type and record.
        """
        
        for add, recs in iteritems(self.ms1_records):
            
            if adducts is None or add in adducts:
                
                for rec in recs[1]:
                    
                    yield add, rec
    
    def records_by_type(self, headgroup, sub = (), adducts = None):
        """
        Iterates MS1 database records with a certain headgroup and subtype.
        """
        
        sub = (
            sub
                if type (sub) is set else
            set(sub)
                if type(sub) is list or type(sub) is tuple else
            set([sub])
        )
        
        for add, rec in self.iterrecords(adducts = adducts):
            
            if rec.hg and rec.hg.main == headgroup and set(rec.hg.sub) == sub:
                
                yield rec
    
    def first_record(self, headgroup, sub = (), adducts = None):
        """
        Returns the first MS1 database record matching headgroup and subtype.
        """
        
        recbytyp = self.records_by_type(
            headgroup, sub = sub, adducts = adducts
        )
        
        try:
            
            return next(recbytyp)
            
        except StopIteration:
            
            return None
    
    def identify(self, adducts = None):
        
        result = {}
        
        for add, rec in self.iterrecords(adducts):
            
            if rec.hg is None:
                
                continue
            
            rec_str = rec.summary_str()
            
            if rec_str not in result and rec.hg in idmethods[self.ionmode]:
                
                method = idmethods[self.ionmode][rec.hg]
                
                adduct = None if add in {'[M+H]+', '[M-H]-'} else add
                
                result[rec_str] = tuple(
                    method(
                        record = rec,
                        scan = self,
                        adduct = adduct,
                    ).identify()
                )
        
        return result
    
    #
    # Sphingolipids
    #
    
    def cer1p_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Ceramide-1-phosphate.

        **Specimen:**
        
        - GLTPD1 - 616.47
      
        **Principle:**
        
        - The most abundant fragment is 78.9591 metaphosphate.
      - If 96.9696 phosphate present adds to the score.
        
        """
        
        score = 0
        fattya = set([])
        if self.most_abundant_mz_is(78.95905658):
            score += 5
            if self.has_mz(96.96962158):
                score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def hexcer_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Hexosyl-Ceramide.

        **Specimen:**
        
        - GLTP - 744.5627
      
        **Principle:**
        
        - Hexose fragments 71.0115, 89.0220 and 101.0219 must present.
      
        """
        
        score = 0
        fattya = set([])
        
        if all(map(lambda mz: self.mz_among_most_abundant(mz, n = 10),
                   # these are 3 fragments found at GLTP
                   [71.0115000, 89.0220000, 101.021900])):
            
            score += 5
        
        return {'score': score, 'fattya': fattya}
    
    def hexceroh_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Hexosyl-Ceramide-OH
        ('t'). This method is the same as `hexcer_neg_1`.

        **Specimen:**
        
        - GLTP - 760.557
      
        **Principle:**
        
        - Hexose fragments 71.0115, 89.0220 and 101.0219 must present.
      
        """
        
        return self.hexcer_neg_1()
    
    def sm_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Sphingomyeline.

        **Specimen:**
        
        - GLTPD1 - 745.55
      
        **Principle:**
        
        - Must have a neutral loss of CH3+COOH (60.0211).
      - Phosphate+choline-CH3 fragment 168.0431 must be present.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.mz_among_most_abundant(168.0431206) and self.has_nl(60.02113):
            score += 5
        
        return {'score': score, 'fattya': fattya}
    
    def sph1p_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Spingosine-1-phosphate.

        **Specimen:**
        
        - Only observed in standard.
      
        **Principle:**
        
        - Phosphate 78.9590 must be present.
      
        """
        
        score = 0
        fattya = set([])
        
        if self.has_mz(78.95905658):
            score += 5
        
        return {'score': score, 'fattya': fattya}
    
    def cer_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is Ceramide.

        **Specimen:**
        
        - SEC14L1 - 582.509
      
        **Principle:**
        
        - A Ceramide backbone fragment must be among the 2 most abundant.
      - Ceramide backbone fragments lighter by N or C2N but same carbon
          count and unsaturation add to the score.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.fa_among_most_abundant('CerFA', n = 2):
            
            score += 5
            fattya = self.fa_combinations('Cer', sphingo = True)
            fa_h_ccs = self.matching_fa_frags_of_type('Cer', 'CerFA(')
            
            for fa_h_cc in fa_h_ccs:
                
                for fa_other in [
                    '[CerFA-N(C%u:%u)-]-',
                    '[CerFA-C2N(C%u:%u)-]-']:
                    
                    if self.frag_name_present(fa_other % fa_h_cc):
                        
                        score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def cerp_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Ceramide-1-phosphate.
        Gives similar result as Sphingosine-1-phosphate.

        **Specimen:**
        
        - GLTPD1 - 616.47
      
        **Principle:**
        
        - The most abundant fragment must be 78.9591 metaphosphate.
      - Presence of 96.9696 phosphate increase the score.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.most_abundant_mz_is(78.95905658):
            
            score += 5
            
            if self.has_mz(96.96962158):
                
                score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def cerp_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Ceramide-1-phosphate.

        **Specimen:**
        
        - GLTPD1 + 728.59, 590.45, 702.58, 618.430, 616.415, 640.409
      
        **Principle:**
        
        - A sphingosine fragment with double H2O loss must be among the three
        highest abundant fragments.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.fa_among_most_abundant('-H2O-H2O+]+', n = 3, sphingo = True):
            score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def adduct(self, adduct, reset = False):
        """
        Creates a copy of the current scan assuming that the precursor
        is a certain adduct. The precursor will be converted to [M+H]+
        or [M-H]- adduct and neutral losses will be calculated accordingly.
        """
        
        if adduct in self.adducts and not reset:
            
            return
        
        ad2ex = settings.get('ad2ex')[1][self.ionmode][adduct]
        ex2ad = 'remove_h' if self.ionmode == 'neg' else 'add_h'
        
        fake_precursor = (
            getattr(
                mzmod.Mz(
                    getattr(
                        mzmod.Mz(self.precursor),
                        ad2ex
                    )()
                ),
                ex2ad
            )()
        )
        
        annot = self.get_annot(fake_precursor)
        
        chain_list = self._build_chain_list(annot = annot)
        
        self.adducts[adduct] = {
            'fake_precursor': fake_precursor,
            'annot': annot,
            'chain_list': chain_list,
        }
    
    def adduct_annot(self, adduct = None):
        """
        Gets the annotations for a certain adduct.
        """
        
        return self.adduct_data('annot', adduct = adduct)
    
    def adduct_chain_list(self, adduct = None):
        """
        Gets the chain list for a certain adduct.
        """
        
        return self.adduct_data('chain_list', adduct = adduct)
    
    def adduct_data(self, name, adduct = None):
        
        if adduct is None:
            
            return getattr(self, name)
        
        self.adduct(adduct)
        
        return self.adducts[adduct][name]
    
    def get_ms1_records(
            self,
            hg,
            subtype = None,
            sph = None,
            ether = None,
            oh = None,
            databases = None,
        ):
        """
        Iterates MS1 records for a given type.
        
        Yields tuples of record, adduct type and error in ppm
        """
        
        subtype = subtype or ()
        
        hg = (
            hg
            if isinstance(hg, lipproc.Headgroup) else
            lipproc.Headgroup(main = hg, sub = subtype)
        )
        
        for add, recs in iteritems(self.ms1_records):
            
            for rec_mz, rec, err_ppm in zip(*recs):
                
                if (
                    rec.hg == hg and (
                        databases is None or rec.lab.db in databases
                    ) and (
                        sph is None or rec.chainsum.attr.sph == sph
                    ) and (
                        ether is None or rec.chainsum.attr.ether == ether
                    ) and (
                        oh is None or rec.chainsum.attr.oh == oh
                    )
                ):
                    
                    yield rec, add, err_ppm


class AbstractMS2Identifier(object):
    
    class_methods = {}
    subclass_methods = {}
    
    def __init__(
            self,
            record,
            scan,
            adduct = None,
            missing_chains = None,
            explicit_and_implicit = False,
            must_have_chains = True,
            chain_comb_args = {},
            missing_chain_args = {},
        ):
        
        self.score = 0
        self.max_score = 0
        self.rec = record
        self.scn = scan
        self.add = adduct
        self.missing_chains = (
            missing_chains if missing_chains is not None else
            tuple(range(len(record.chainsum))) # any chain can be missing
        )
        self.chain_comb_args = chain_comb_args
        self.missing_chain_args = missing_chain_args or self.chain_comb_args
        self.explicit_and_implicit = explicit_and_implicit
        self.must_have_chains = must_have_chains
        
        self.scores = {}
    
    def identify(self):
        
        if not self.rec.hg:
            
            return
        
        self.confirm_class()
        
        chains_confirmed = False
        
        for chains in self.confirm_chains_explicit():
            
            yield MS2Identity(
                max(self.score, 0),
                self.max_score,
                self.percent_score(),
                self.rec.hg,
                self.rec.chainsum,
                chains = chains[0],
                chain_details = chains[1],
                scan_details = self.scn.scan_details,
            )
            chains_confirmed = True
        
        if not chains_confirmed or self.explicit_and_implicit:
            
            for chains in self.confirm_chains_implicit():
                
                yield MS2Identity(
                    max(self.score, 0),
                    self.max_score,
                    self.percent_score(),
                    self.rec.hg,
                    self.rec.chainsum,
                    chains = chains[0],
                    chain_details = chains[1],
                    scan_details = self.scn.scan_details,
                )
                
                chains_confirmed = True
        
        if not chains_confirmed and not self.must_have_chains and self.score:
            
            yield MS2Identity(
                max(self.score, 0),
                self.max_score,
                self.percent_score(),
                self.rec.hg,
                self.rec.chainsum,
                chains = None,
                chain_details = None,
                scan_details = self.scn.scan_details,
            )
    
    def percent_score(self):
        """
        Returns the score as a percentage of the maximum possible score.
        
        Zero maximum score means something is wrong, then it returns 200.
        """
        
        return (
            max(int(np.round(self.score / self.max_score * 100.)), 0)
            if self.max_score else
            200
        )
    
    def confirm_class(self):
        """
        In this base class pass through everything.
        Most of the subclasses should override this.
        """
        
        self.score = 0
        
        if self.rec.hg is not None and self.rec.hg.main in self.class_methods:
            
            score, max_score = getattr(
                self,
                self.class_methods[self.rec.hg.main]
            )()
            
            self.score += score
            self.max_score += max_score
    
    def confirm_subclass(self):
        
        subclasses = self.rec.hg.sub or ('empty',)
        
        if self.rec.hg is not None:
            
            for sub in subclasses:
                
                if sub not in self.scores and sub in self.subclass_methods:
                    
                    score, max_score = getattr(
                        self,
                        self.subclass_methods[sub]
                    )()
                    
                    self.scores[sub] = score
                    self.score += score
                    self.max_score += max_score
    
    def confirm_chains_explicit(self):
        
        return self.scn.chain_combinations(self.rec, **self.chain_comb_args)
    
    def confirm_chains_implicit(self):
        
        for missing in self.missing_chains:
            
            for chain_comb in self.scn.missing_chain(
                self.rec,
                missing_position = missing,
                **self.missing_chain_args
            ):
                
                yield chain_comb
    
    def matching_chain_combinations(
            self,
            chain_param1,
            chain_param2,
            score_method = lambda ccomb: (min(ccomb, 3) * 2, 6),
        ):
        
        ccomb = len(list(
            self.scn.matching_chain_combinations(
                self.rec,
                chain_param = (chain_param1, chain_param2),
            )
        ))
        
        score, max_score = score_method(ccomb)
        
        self.score += score
        self.max_score += score
    
    def check_lyso(self, score_threshold = 5):
        """
        Checks whether the this mass has been identified in the database
        as a lyso species and calls the corresponding lyso identification
        method.
        
        Returns ``True`` if the score from the lyso is larger than
        ``score_threshold``.
        """
        
        rec_lyso = self.scn.first_record(self.rec.hg.main, sub = ('Lyso',))
        
        if rec_lyso:
            
            lyso_hg = lipproc.Headgroup(
                main = self.rec.hg.main,
                sub = ('Lyso',),
            )
            lyso = idmethods[self.scn.ionmode][lyso_hg](rec_lyso, self.scn)
            lyso.confirm_class()
            
            return lyso.score > score_threshold
        
        return False


#
# Lipid identification methods
#

#
# Fatty acids
#

class FA_Negative(AbstractMS2Identifier):
    """
    Examines if a negative mode MS2 spectrum is a fatty acid.
    Here we only check if the most abundant fragment is the
    fatty acid itself.

    **Specimen:**
    
    - in vitro FABP1 -
    
    **Principle:**
    
    - The most abundant fragment must be a fatty acid which matches
      the carbon count and the unsaturation of the whole molecule.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {
                'head': 1,
                'frag_types': {
                    0: {'FA-H'}
                }
            },
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 10
        
        if (
            self.rec.chainsum and
            self.scn.chain_among_most_abundant(
                frag_type = 'FA-H',
                c = self.rec.chainsum.c,
                u = self.rec.chainsum.u,
            )
        ):
            
            self.score = 10


class FA_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a fatty acid.
    Here we only check if the most abundant fragment is the
    fatty acid itself.

    **Specimen:**
    
    - Not known
    
    **Principle:**
    
    - The most abundant fragment must be a fatty acid which matches
      the carbon count and the unsaturation of the whole molecule.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {
                'head': 1
            }
        )
    
    def confirm_class(self):
        
        self.max_score = 10
        
        if (
            self.rec.chainsum and
            self.scn.chain_among_most_abundant(
                frag_type = 'FA+H',
                c = self.rec.chainsum.c,
                u = self.rec.chainsum.u,
            )
        ):
            
            self.score = 10

#
# Glycerolipids
#

class DAG_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a DAG.

    **Specimen:**
    
    - in vivo: SEC14L2 + 584.52
    - in vitro: BNIP2 + 770.67
    
    **Principle:**
    
    - Combination of fatty acid fragments among the 10 most abundant
      fragments must match the expected carbon count and unsaturation.
    - If these are among the 5 highest fragments the score is higher.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 6
        
        if self.scn.has_chain_combinations(self.rec, head = 10):
            
            self.score += 4
        
        if self.scn.has_chain_combinations(self.rec, head = 6):
            
            self.score += 2


class DAG_Negative(AbstractMS2Identifier):
    """
    Examines if a negative mode MS2 spectrum is a DAG.

    **Specimen:**
    
    - We don't have yet.
    
    **Principle:**
    
    - Combination of fatty acid fragments among the 10 most abundant
      fragments must match the expected carbon count and unsaturation.
    - If these are among the 5 highest fragments the score is higher.
    
    (Same as in positive ionmode.)
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 6
        
        if self.scn.has_chain_combinations(self.rec, head = 10):
            
            self.score += 4
        
        if self.scn.has_chain_combinations(self.rec, head = 6):
            
            self.score += 2


class TAG_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a TAG.

    **Specimen:**
    
    - STARD11 + 818.7187
    
    **Principle:**
    
    - Combination of fatty acid fragments must match the expected
      carbon count and unsaturation.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 10
        
        if self.scn.has_chain_combinations(self.rec, head = 15):
            
            self.score += 5
        
        if self.scn.has_chain_combinations(self.rec, head = 7):
            
            self.score += 5


class TAG_Negative(AbstractMS2Identifier):
    """
    Examines if a negative mode MS2 spectrum is a TAG.

    **Specimen:**
    
    - We don't have yet.
    
    **Principle:**
    
    - Combination of fatty acid fragments must match the
      expected carbon count and unsaturation.
    
    (Same as in positive ionmode.)
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.score = 0
        self.max_score = 5
        
        if self.scn.has_chain_combinations(self.rec):
            
            self.score += 5


class GL_Positive(AbstractMS2Identifier):
    """
    Generic class for identification of glycerolipids.
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    class_methods = {
        'DGTS': 'dgts',
        'DGCC': 'dgcc',
        'DGTA': 'dgts',
        'DGDG': 'dgdg',
        'MGDG': 'mgdg',
        'SQDG': 'sqdg',
    }
    
    def confirm_class(self):
        
        if self.rec.hg.main in self.class_methods:
            
            getattr(self, self.class_methods[self.rec.hg.main])()
    
    def dgts(self):
        
        self.max_score += 30
        
        if self.scn.has_fragment('DGTS [G+TS] (236.1492)'):
            
            self.score += 10
            
            self.score += sum(map(bool,
                (
                    self.scn.has_fragment('DGTS [TS] (144.1019)'),
                    self.scn.has_chain_fragment_type('NL FA-H2O'),
                )
            )) * 10
    
    def dgcc(self):
        
        self.max_score += 20
        
        if self.scn.has_fragment('PC/SM [Ch+H2O] (104.107)'):
            
            self.score += 10
            
            if self.scn.has_fragment('DGCC [C2+Ch] (132.1388)'):
                
                self.score += 10
    
    def sqdg(self):
        
        self.max_score += 10
        
        if self.scn.has_fragment('NL [Hexose+SO3+H2O+H] (NL 261.0280)'):
            
            self.score += 10
    
    def mgdg(self):
        
        self.max_score += 10
        
        if self.scn.has_fragment('[Hexose+H2O-H] (NL 197.07)'):
            
            self.score += 10
    
    def dgdg(self):
        
        self.max_score += 10
        
        if self.scn.has_fragment('NL [2xHexose+H2O-H] (NL 359.1190)'):
            
            self.score += 10


class GL_Negative(AbstractMS2Identifier):
    """
    Generic class for identification of glycerolipids.
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score += 10
        
        if self.scn.has_chain_combination(
            record = self.rec,
            chain_param = (
                {'frag_type': {'FA-H', 'FA-'}},
            )
        ):
            
            self.score += 10

#
# Glycerophospholipids
#

class PE_Negative(AbstractMS2Identifier):
    """
    Examines if a negative mode MS2 spectrum is Phosphatidylethanolamine.

    **Specimen:**
    
    - GM2A - 714.507 and 716.523
    
    **Principle:**
    
    - The most abundant fragment is a fatty acid [M-H]- ion.
    - 140.0118 PE headgroup must be present.
    - Other headgroup ions 196.0380 and 178.0275 add to the score.
    - Lyso-PE and [M-H-CO2]- fatty acid fragments complementing the
      highest [M-H]- fatty acid increase the score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score += 11
        
        if (
            self.scn.chain_fragment_type_is(
                i = 0,
                chain_type = 'FA',
                frag_type  = 'FA-H'
            ) and
            self.scn.has_fragment('PE [P+E] (140.0118)')
        ):
            
            self.score += 5
            
            self.score += sum(map(bool, (
                self.scn.has_fragment('PE [G+P+E-H2O] (196.0380)'),
                self.scn.has_fragment('PE [G+P+E] (178.0275)'),
            ))) * 3
            
            # by default this returns max 6
            self.matching_chain_combinations(
                {'frag_type': 'FA-H'},
                {'frag_type': {
                        'LysoPE',
                        'LysoPEAlkyl',
                        'LysoPEAlkyl-H2O',
                        'FA-H2O-H'
                    }
                }
            )


class PE_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a
    Phosphatidylethanolamine.

    **Specimen:**
    
    - in vivo BPI + 718.536
    - Lyso-PE: in vitro FABP1 + 454.29
    
    **Principle:**
    
    - The PE headgroup neutral loss 141.0191 has the highest intensity.
    - If it is a Lyso-PE score will be zero.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 20
        
        if self.scn.has_fragment('NL PE [P+E] (NL 141.0191)'):
            
            if self.check_lyso():
                
                return
            
            if self.scn.has_fragment('PE [P+E] (142.0264)'):
                
                self.score += 5
            
            self.score += 15


class LysoPE_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a
    Lysophosphatidylethanolamine.

    **Specimen:**
    
    - in vitro FABP1 + 454.29
    
    **Principle:**
    
    - The PE headgroup neutral loss 141.0191 has the highest intensity.
    - A fatty acid-glycerol fragment should match the carbon count and
      unsaturation of the whole molecule.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 15
        
        if self.scn.has_fragment('NL PE [P+E] (NL 141.0191)'):
            
            self.score = 5
            
            if self.scn.has_fragment('PE [P+E] (142.0264)'):
                
                self.score += 5
            
            self.scn.build_chain_list()
            
            if (
                len(self.scn.chain_list) and
                self.scn.chain_fragment_type_is(
                    self.scn.chain_list[0].i,
                    frag_type = 'FA+Glycerol-OH',
                    c = self.rec.chainsum.c,
                    u = self.rec.chainsum.u,
                )
            ):
                
                self.score += 5


class PC_Negative(AbstractMS2Identifier):
    """
    Examines if a negative mode MS2 spectrum is a Phosphatidylcholine.

    **Specimen:**
    
    - BPI - 804.57 and 776.545
    
    **Principle:**
    
    - 168.0431 phosphate+choline-CH3 fragment must be present.
    - The highest abundant fragment must be a fatty acid [M-H]- fragment.
    - Lyso-PC fragments complementing the highest [M-H]- fatty acid
      increase the score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 17
        
        if (
            self.scn.chain_fragment_type_is(
                i = 0,
                chain_type = 'FA',
                frag_type = 'FA-H'
            ) and
            self.scn.has_fragment('PC/SM PO4+choline-CH3 (168.0431)')
        ):
            
            self.score += 5
            
            self.score += sum(map(bool, (
                self.scn.has_fragment('PE [G+P+E-H2O] (196.0380)'),
                self.scn.has_fragment('PE [G+P+E] (178.0275)'),
            ))) * 3
            
            self.matching_chain_combinations(
                {'frag_type': 'FA-H'},
                {'frag_type': 'LysoPC'},
                score_method = lambda ccomb: ((ccomb > 1) * 6, 6),
            )


class PC_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a Phosphatidylcholine.

    **Specimen:**
    
    - BPI + 786.607
    
    **Principle:**
    
    - The most abundant fragment must be choline+phosphate 184.0733.
    - The 86.0964 ethyl-trimetylammonium must be present.
    - The most abundant fatty acid can not have the same carbon count
      and unsaturation as the whole molecule (then it is Lyso-PC).
    - Fragments 104.1069, 124.9998, 60.0808 and 58.0651 increase the
      score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = False,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 13
        
        if (
            self.scn.fragment_percent_of_most_abundant(
                'PC/SM [P+Ch] (184.0733)', 10.0
            ) and
            self.scn.has_fragment('PC/SM [Ch] (86.096)')
        ):
            
            if self.check_lyso():
                
                return
            
            self.score += 5
            
            self.score += sum(map(bool, (
                self.scn.has_fragment('PC/SM [Ch+H2O] (104.107)'),
                self.scn.has_fragment('PC/SM [P+Et] (124.9998)'),
                self.scn.has_fragment('PC/SM [N+3xCH3] (60.0808)'),
                self.scn.has_fragment('PC/SM [Ch-Et] (58.0651)'),
            ))) * 2


class LysoPC_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a Lysophosphatidylcholine.
    
    **Specimen:**
    
    - in vitro FABP1 + 522.36
    
    **Principle:**
    
    - Choline-phosphate 184.0733, ethyl-trimethylammonium 86.0964 and
      neutral loss 183.0660 must be present.
    - The latter neutral loss corresponds to a fatty acid+glycerol ion.
    - The carbon count and unsaturation of this fragment should match
      that of the whole molecule.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = False,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 15
        
        if (
            self.scn.most_abundant_fragment_is('PC/SM [P+Ch] (184.0733)') and
            self.scn.has_fragment('PC/SM [Ch] (86.096)')
        ):
            
            self.score += 5
            
            if self.scn.has_fragment('NL PC/SM [P+Ch] (NL 183.066)'):
                
                self.score += 5
            
            if self.scn.has_chain_fragment_type(
                frag_type = {'FA+Glycerol-OH', 'NL FA-H2O'},
                c = self.rec.chainsum.c,
                u = self.rec.chainsum.u,
            ):
                
                self.score += 5


class PI_Negative(AbstractMS2Identifier):
    """
    Examines if a negative MS2 spectrum is Phosphatidylinositol.

    **Specimen:**
    
    - GM2A - 835.52
    
    **Principle:**
    
    - Inositolphosphate-H2O fragment 241.0119, metaphosphate 78.9591 and
      headgroup fragment 152.9958 must be present.
    - Additional headgroup fragments 96.9696, 259.0224 and 297.0381
      increase the score.
    - Presence of Lyso-PI fragments complementing other [M-H]- fatty
      acid fragments increase the score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 19
        
        if (
            self.scn.has_fragment('PI [InsP-H2O]- (241.01)') and
            self.scn.has_fragment('PA/PG/PI/PS [G+P] (152.9958)') and
            self.scn.has_fragment('Cer1P/PIP/PL metaphosphate (78.9591)')
        ):
            
            self.score += 5
            
            self.score += sum(map(bool, (
                self.scn.has_fragment('Cer1P/PI phosphate (96.9696)'),
                self.scn.has_fragment('PI [InsP-H]- (259.02)'),
                self.scn.has_fragment('PI [G+P+I] (297.04)'),
                self.scn.has_fragment('PI [InsP-2H2O]- (223.00)'),
            ))) * 2
            
            self.matching_chain_combinations(
                {'frag_type': 'FA-H'},
                {'frag_type': {
                        'LysoPI',
                        'LysoPI-H2O',
                    }
                },
                score_method = lambda ccomb: (min(ccomb, 2) * 3, 6),
            )


class PI_Positive(AbstractMS2Identifier):
    """
    Examines if a negative MS2 spectrum is Phosphatidylinositol.

    **Specimen:**
    
    - SEC14L2 + 906.60 and 882.6
    
    **Principle:**
    
    - Combinations of fatty acid fragments must match the expected
      carbon count and unsaturation for PI.
    - Presence of neutral losses 259.0219 and 277.0563 adds to the score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = True,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 9
        
        if self.scn.has_chain_combinations(self.rec):
            
            self.score += 1
            
            self.score += sum(map(bool, (
                self.scn.has_fragment('NL PI [P+Ins] (NL 259.0219)'),
                self.scn.has_fragment('NL PI [P+Ins+NH3] (NL 277.0563)'),
            ))) * 4


class PS_Negative(AbstractMS2Identifier):
    """
    Examines if a negative mode MS2 spectrum is a Phosphatidylserine.

    **Specimen:**
    
    - ORP9 - 788.54
    
    **Principle:**
    
    - The most abundant fragment is an [M-H]- fatty acid fragment.
    - Glycerophosphate fragment 152.9958 must be present.
    - Metaphosphate 78.9591 increases the score.
    - Serine-H2O neutral loss 87.0320 adds to the score.
    - Presence of Lyso-PS and Lyso-PA fragments complementing
      the highest [M-H]- fatty acid fragment increase the score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = True,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 17
        
        if (
            self.scn.has_chain_combinations(self.rec) and
            self.scn.chain_fragment_type_is(
                0, chain_type = 'FA', frag_type = 'FA-H'
            ) and
            self.scn.fragment_among_most_abundant(
                'PA/PG/PI/PS [G+P] (152.9958)', 5
            )
        ):
            
            self.score += 5
            
            self.score += sum(map(bool, (
                self.scn.has_fragment('Cer1P/PIP/PL metaphosphate (78.9591)'),
                self.scn.has_fragment('PS [Ser-H2O] (87.0320)'),
            ))) * 3
            
            self.matching_chain_combinations(
                {'frag_type': 'FA-H'},
                {'frag_type': {'LysoPS', 'LysoPA'}},
                score_method = lambda ccomb: (min(ccomb, 2) * 3, 6),
            )


class PS_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a Phosphatidylserine.

    **Specimen:**
    
    - BPI + 790.56
    
    **Principle:**
    
    - PS headgroup neutral loss 185.0089 must be the highest intensity.
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = True,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 5
        
        if self.scn.fragment_among_most_abundant('PS [P+S] (NL 185.0089)', 1):
            
            self.score += 5


class PG_Negative(AbstractMS2Identifier):
    """
    Examines if a negative mode MS2 spectrum is Phosphatidylglycerol.
    The result will be the same as `bmp_neg_1`, as in negative
    mode we do not know a way to distinguish these species.
    

    **Specimen:**
    
    - GM2A - 799.54
    - BPIFB2 - 773.5258 (might be BMP)
    
    **Principle:**
    
    - The most abundant fragment is a fatty acid [M-H]- ion.
    - The 152.9958 glycerophosphate fragment must be present.
    - If Lyso-PG fragment present with carbon count complementing
      the [M-H]- fatty acid score is higher.
    - Presence of 171.0064 headgroup fragment adds to the score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = True,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 14
        
        if (
            self.scn.has_chain_combinations(self.rec) and
            self.scn.chain_fragment_type_is(
                0, chain_type = 'FA', frag_type = 'FA-H'
            ) and
            self.scn.has_fragment('PA/PG/PI/PS [G+P] (152.9958)')
        ):
            
            self.score += 5
            
            if self.scn.has_fragment('PG headgroup (171.0064)'):
                
                self.score += 3
            
            self.matching_chain_combinations(
                {'frag_type': 'FA-H'},
                {'frag_type': {
                        'LysoPG',
                        'LysoPG-H2O',
                    }
                },
                score_method = lambda ccomb: (min(ccomb, 2) * 3, 6),
            )


class PG_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a Phosphatidylglycerol.
    At in vivo observed only in standard.
    
    **Principle:**
    
    - The PG headgroup neutral loss (189.0402) is the fragment ion
      with the highest intensity?
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 5
        
        if (
            self.scn.most_abundant_fragment_is(
                'NL PG [G+P+NH3] (NL 189.0402)'
            )
        ):
            
            self.score += 5
        
        # alternative for lyso
        if (
            self.rec.hg.sub == ('Lyso',) and
            self.scn.chain_fragment_type_among_most_abundant(
                n = 1,
                frag_type = {'FA+Glycerol-OH'},
                c = self.rec.chainsum.c,
                u = self.rec.chainsum.u,
            )
        ):
            
            self.score += 5
            self.max_score += 5


class BMP_Negative(PG_Negative):
    """
    Examines if a negative mode MS2 spectrum is Bismonoacylglycerophosphate.
    The result will be the same as for PG, as in negative
    mode we do not know a way to distinguish these species.
    

    **Specimen:**
    
    - GM2A - 799.54
    - BPIFB2 - 773.5258 (might be BMP)
    
    **Principle:**
    
    - The most abundant fragment is a fatty acid [M-H]- ion.
    - The 152.9958 glycerophosphate fragment must be present.
    - If Lyso-PG fragment present with carbon count complementing
      the [M-H]- fatty acid score is higher.
    - Presence of 171.0064 headgroup fragment adds to the score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        PG_Negative.__init__(self, record, scan, **kwargs)


class BMP_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum
    is a Bismonoacylglycerophosphate.

    **Specimen:**
    
    - BPIFB2 + 792.57
    
    **Principle:**
    
    - A glycerol+fatty acid fragment can be found among the 3 highest?
    - The PG headgroup neutral loss (189.0402) is among the fragments?
    - If so, does it have a lower intensity than half of the fatty
      acid+glycerol fragment?
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = True,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 10
        
        if (
            self.scn.has_chain_combinations(self.rec, head = 15) and
            self.scn.chain_fragment_type_among_most_abundant(
                chain_type = 'FA', frag_type = 'FA+Glycerol-OH', n = 3
            )
        ):
            
            self.score += 5
            
            i_hg = self.scn.fragment_by_name('NL PG [G+P+NH3] (NL 189.0402)')
            
            if i_hg is not None:
                
                i_gfa = self.scn.highest_fragment_by_chain_type(
                    head = 4, frag_type = 'FA+Glycerol-OH'
                )
                
                if self.scn.intensities[i_gfa] < self.scn.intensities[i_hg]:
                    
                    self.score = 0
                
                else:
                    
                    self.score += 5


class PA_Negative(AbstractMS2Identifier):
    """
    Examines if a negative mode MS2 spectrum is Phosphatidylglycerol.
    The result will be the same as `bmp_neg_1`, as in negative
    mode we do not know a way to distinguish these species.
    

    **Specimen:**
    
    - GM2A - 799.54
    - BPIFB2 - 773.5258 (might be BMP)
    
    **Principle:**
    
    - The most abundant fragment is a fatty acid [M-H]- ion.
    - The 152.9958 glycerophosphate fragment must be present.
    - If Lyso-PG fragment present with carbon count complementing
      the [M-H]- fatty acid score is higher.
    - Presence of 171.0064 headgroup fragment adds to the score.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = True,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 25
        
        if (
            self.scn.has_chain_combinations(self.rec) and
            self.scn.chain_fragment_type_is(
                0, chain_type = 'FA', frag_type = 'FA-H'
            ) and
            self.scn.fragment_among_most_abundant(
                'PA/PG/PI/PS [G+P] (152.9958)', 10
            ) and
            self.scn.fragment_among_most_abundant(
                'Cer1P/PIP/PL metaphosphate (78.9591)', 10
            )
        ):
            
            self.score += 20
            
            if self.scn.has_fragment('Cer1P/PI phosphate (96.9696)'):
                
                self.score += 5


class PA_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a Phosphatidylglycerol.
    At in vivo observed only in standard.
    
    **Principle:**
    
    - The PG headgroup neutral loss (189.0402) is the fragment ion
      with the highest intensity?
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 20
        
        if (
            self.scn.fragment_among_most_abundant(
                'NL [P] (NL 97.9769)', 3, adduct = self.add
            )
        ):
            
            self.score += 10
            
            if self.scn.has_chain_combination(
                self.rec,
                chain_param = ({
                    'frag_type': {
                        'FA+Glycerol-OH',
                        'FA-OH',
                        'FA-H2O-OH',
                    }
                },)
            ):
                
                self.score += 10

#
# Vitamins
#

class VA_Positive(AbstractMS2Identifier):
    """
    Examines if a positive MS2 spectrum is vitamin A (retinol).

    **Specimen:**
    
    - in vivo RBP1 + 269.2245
    - in vivo RBP4 + 269.2245
    
    **Principle:**
    
    - The most abundant ion is the whole molecule m/z = 269.224.
    - Presence off 3 other ions adds to the score but not
      mandatory: 213.165, 145.1027, 157.1028.
    
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = False,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 8
        
        if self.scn.fragment_among_most_abundant('Retinol I (269.2264)', 3):
            
            self.score += 5
            
            self.score += sum(map(bool, (
                self.scn.has_fragment('Retinol II (213.1637)'),
                self.scn.has_fragment('Retinol III (157.1012)'),
                self.scn.has_fragment('Retinol IV (145.1012)'),
            )))


class VA_Negative(AbstractMS2Identifier):
    """
    Examines if a positive MS2 spectrum is vitamin A (retinol).

    **Specimen:**
    
    - Standards 141020 negative scan 673
    
    **Principle:**
    
    - 3 fragments seems to always present and be among the most abundant:
      79.055, 119.087 and 255.212; presence of these is the main condition.
    - We also detected 125.061 in our standards which is special because
      contains 2 oxygens; presence of this increase the score.
    """
    
    def __init__(self, record, scan, **kwargs):
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = False,
            **kwargs,
        )
    
    def confirm_class(self):
        
        self.max_score = 8
        
        if all((
            self.scn.fragment_among_most_abundant(fragname, 7)
            for fragname in (
                'Retinoic acid I (79.0553)',
                'Retinoic acid II (119.0866)',
                'Retinoic acid IV (255.2118)',
            )
        )):
            
            self.score += 5
            
            if self.scn.has_fragment('Retinoic acid III (125.0608)'):
                
                self.score += 3

#
# Sphingolipids
#

class Cer_Positive(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a ceramide.
    Identifies ceramide varieties including sphingomyeline,
    ceramide-1-phosphare, ceramide-phosphoethanolamine,
    OH-acyl-ceramide, hexosyl and dihexosyl-ceramides,
    and d, t and DH long chain base varieties.
    
    dCer
    ====
    
    **Specimen:**
    
    - Sphingolipid standards scans 
    - SEC14L1 + 538.52
    - STARD11 + 538.526
    
    **Principle:**
    
    - A sphingosine backbone with two H2O loss must be among the
      10 most abundant fragments.
    - Fatty acid [M+H]+ or [M-O]+ fragments or neutral losses
      complementing the one above increase the score.
    - Sphingosine backbone fragments with same carbon count and
      unsaturation with the one with 2 water loss but [Sph-C-2(H2O)]+
      or [Sph-H2O]+ add to the score.
    - The score increases if the following choline fragments
      can not be found: 58.0651, 104.1070, 124.9998 and 184.0733.
    - The presence of the following fragments increase the score:
      60.0444, 70.0651, 82.0651, 96.0808, 107.0730, 121.0886,
      135.1042 and 149.1199.
    
    DHCer
    =====
    
    **Specimen:**
    
    - Standards 180626 m/z 568.56 scan 2367
    
    **Principle:**
    
    - Same pattern as at dCer but from the sphingosine derived fragments
      it becomes clear if it has no unsaturation.
    
    tCer
    ====
    
    **Specimen:**
    
    - Standards 180628 m/z 584.56 scan 2070
    
    **Principle:**
    
    - Has Sph+H2O-H fragment which does not occur at dCer.
    - Sph-H2O-H and Sph-H are much higher abundant than at dCer.
    - Strong fragment at 60.044 which is missing at dCer.
    - H2O and 2xH2O neutral losses are much higher than at dCer.
    
    dCer-2OH-acyl
    =============
    
    **Specimen:**
    
    - Standards 180615 m/z 584.22 scan 2421
    
    **Principle:**
    
    - Same as other ceramides. It's d and DH forms are isobaric with tCer
      but d and t are clearly distinguishable so this does not cause
      confusion.
    
    dCer-1-P
    ========
    
    **Specimen:**
    
    - in vivo GLTPD1 + 728.59
    
    **Principle:**
    
    - A shpingosine backbone with 2 H2O loss must be among the 3 highest
      intensity fragments.
    - Presence of any of the following fragments increases the score:
      82.0651, 115.9875.
      107.0729, 135.1043, 149.1199.
    
    Hex-dCer
    ========
    
    **Specimen:**
    
    - in vivo GLTP + 810.68
    
    **Principle:**
    
    - Hexose fragments 198.0740, 180.0634 and 162.0528 must present.
      These are neutral losses of hexose, hexose-H2O and hexose+H2O
    
    Hex-tCer
    ========
    
    **Specimen:**
    
    - in vivo GLTP + 826.67
    - in vitro GLTP + 826.67, 800.66,
    
    **Principle:**
    
    - Hexose fragments 198.0740, 180.0634 and 162.0528 must present.
      These are neutral losses of hexose, hexose-H2O and hexose+H2O
    
    Hex2-dCer
    =========
    
    **Specimen:**
    
    - in vivo GLTP + 988.73
    
    **Principle:**
    
    - Loss of double hexose with our without extra water or water loss
      are the characteristic fragments of this class.
    
    SHex-dCer
    =========
    
    **Specimen:**
    
    - in vitro 890.64
    
    dSM & DHSM
    ==========
    
    **Specimen:**
    
    - in vivo GLTPD1 + 703.57
    - in vitro GLTPD1 + 813.68
    
    **Principle:**
    
    - The following choline fragments must be present: 60.0808, 86.0964,
      104.1069, 124.9998 and 184.0733. The last one is the most intensive.
    - If 58.0651 can be found it adds to the score.
    - dSM and DHSM are not distinguishable in our settings. Maybe the
      [Sph-2xH2O+H]+ ion (264 @ 18:1) presents more often at d and only
      eventually at DH.
    
    PE-Cer
    ======
    
    We do not have this in standards or in screens so we can not test this.
    Based on Amiar 2016 and Narayanaswamy 2014.
    
    **Principle:**
    
    - Neutral loss of 141.0191 must be present.
    - 142.0264 phospho-ethanolamine fragment and neutral loss of
      phospho-ethanolamine+water might be present.
    - Sph-2xH2O fragment increases the score.
    
    """
    
    class_methods = {
        'SM': 'sm',
        'Sph': 'sph',
    }
    
    subclass_methods = {
        '1P': 'cer1p',
        'Hex': 'hexcer',
        'Hex2': 'hex2cer',
        'SHex': 'shexcer',
        'SHex2': 'shex2cer',
        'PE': 'pe_cer',
        'M2': 'm2',
        'M1': 'm1',
        'M3': 'm3',
        'PC': 'pc',
        'empty': 'cer',
    }
    
    def __init__(self, record, scan, **kwargs):
        
        self.nacyl = record.chainsum is not None and len(record.chainsum) > 1
        self.oacyl = record.chainsum is not None and len(record.chainsum) > 2
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (1,) if self.nacyl else (),
            chain_comb_args = {},
            must_have_chains = True,
            **kwargs,
        )
        
        self.sph_scores     = {}
        self.sph_max_scores = {}
        self.fa_scores      = {}
        self.fa_max_scores  = {}
    
    def confirm_class(self):
        
        AbstractMS2Identifier.confirm_class(self)
        
        self.max_score += 2
        
        self.score += sum(map(
            self.scn.has_fragment,
            (
                'NL [H2O] (NL 18.0106)',
                'NL [2xH2O] (NL 36.0211)',
            )
        ))
        
        self.confirm_subclass()
    
    def confirm_chains_explicit(self):
        """
        Most of the time we don't really have fatty acid derived
        fragments from ceramides in positive mode. However certain
        sphingosin base derived fragments correspond to neutral losses
        of fatty acids as the molecule is composed of a sphingosine
        and a fatty acid but this is redundant. Hence we call both
        explicit and implicit identification as practically the it
        is implicit anyways.
        """
        
        for chains in itertools.chain(
            AbstractMS2Identifier.confirm_chains_explicit(self),
            AbstractMS2Identifier.confirm_chains_implicit(self),
        ):
            
            if chains[0][0].attr.sph == self.rec.chainsum.attr[0].sph:
                
                # the sphingosin base and fatty acyl related part of the
                # score is valid only for the current chain combination
                # hence now we add these to the overall score, yield the
                # identification and then subtract them from the score
                sph_score, sph_max_score = self.sphingosine_base(
                    chains[0][0].attr.sph
                )
                
                self.score += sph_score
                self.max_score += sph_max_score
                
                if self.nacyl:
                    
                    fa_score, fa_max_score = self.fatty_acyl(chains[0][1])
                    self.score += fa_score
                    self.max_score += fa_max_score
                
                yield chains
                
                self.score -= sph_score
                self.max_score -= sph_max_score
                
                if self.nacyl:
                    
                    self.score -= fa_score
                    self.max_score -= fa_max_score
    
    def fatty_acyl(self, fa):
        
        score = 0
        max_score = 0
        
        if fa.attr.oh:
            
            if self.add == '[M-H2O+H]+':
                
                score -= 20
        
        return score, max_score
    
    def cer(self):
        
        
        score = 0
        max_score = 0
        
        non_hex_score, non_hex_max_score = self.non_hex()
        
        score += non_hex_score
        max_score += non_hex_max_score
        
        return score, max_score
    
    def non_hex(self):
        
        score = 0
        max_score = 0
        
        score -= sum(map(bool,
            (
                self.scn.has_fragment('NL [Hexose-H2O] (NL 162.05)'),
                self.scn.has_fragment('NL [Hexose] (NL 180.06)'),
                self.scn.has_fragment('NL [Hexose+H2O] (NL 198.07)'),
                self.scn.has_fragment('NL [2xHexose] (NL 342.1162)'),
                self.scn.has_fragment('NL [2xHexose+H2O] (NL 360.1268)'),
                self.scn.has_fragment('NL [2xHexose-H2O] (NL 324.1056)'),
                self.scn.has_fragment('NL [2xHexose+O] (NL 358.1111)'),
                self.scn.has_fragment('NL [2xHexose+C] (NL 372.1268)'),
                self.scn.has_fragment('NL [S] (NL 79.9568)'),
                self.scn.has_fragment('NL [S+H2O] (97.9674)'),
                self.scn.has_fragment('NL [Hexose+SO3] (NL 242.100)'),
                self.scn.has_fragment('NL [Hexose+SO3+H2O] (NL 260.0202)'),
                self.scn.has_fragment('NL [Hexose+SO3+2xH2O] (NL 278.0308)'),
                self.scn.has_fragment('NL [2xHexose+SO3] (NL 404.0625)'),
                self.scn.has_fragment('NL [2xHexose+SO3+H2O] (NL 422.0730)'),
                self.scn.has_fragment('NL [2xHexose+SO3+2xH2O] (NL 440.0836)'),
            )
        )) * 5
        
        return score, max_score
    
    def sm(self):
        
        score = 0
        max_score = 47
        
        if self.scn.most_abundant_fragment_is('PC/SM [P+Ch] (184.0733)'):
            
            score += 15
            
            score += sum(map(bool,
                (
                    self.scn.has_fragment('PC/SM [N+3xCH3] (60.0808)'),
                    self.scn.has_fragment('PC/SM [Ch] (86.096)'),
                    self.scn.has_fragment('PC/SM [Ch+H2O] (104.107)'),
                    self.scn.has_fragment('PC/SM [P+Et] (124.9998)'),
                    self.scn.has_fragment('PC/SM [Ch-Et] (58.0651)'),
                    self.scn.has_fragment('NL PC/SM [P+Ch] (NL 183.066)'),
                    self.scn.has_fragment('NL SM [P+Ch] (NL 201.0766)'),
                    self.scn.has_fragment('NL SM [N+3xCH3] (77.0841)'),
                    self.scn.has_fragment('NL [H2O] (NL 18.0106)'),
                )
            )) * 3
            
            if self.scn.has_chain_fragment_type(frag_type = 'Sph-2xH2O+H'):
                
                score += 5
            
            self.must_have_chains = False
        
        return score, max_score
    
    def pc(self):
        """
        Lyso-SM aka Sph-PC.
        
        Scherer 2010, Table 1.
        """
        
        score = 0
        max_score = 15
        
        if self.scn.most_abundant_fragment_is('PC/SM [P+Ch] (184.0733)'):
            
            score += 15
        
        return score, max_score
    
    def pe_cer(self):
        
        score = 0
        max_score = 30
        
        if self.scn.has_fragment('NL PE [P+E] (NL 141.0191)'):
            
            score += 15
            
            score += sum(map(bool,
                (
                    self.scn.has_fragment('PE [P+E] (142.0264)'),
                    self.scn.has_fragment('NL PE [P+E+H2O] (NL 159.0297)'),
                    self.scn.has_fragment('NL PE [P+E-H2O] (NL 123.0085)'),
                )
            )) * 5
        
        return score, max_score
    
    def cer1p(self):
        
        score = 0
        max_score = 31
        
        if self.scn.has_fragment('NL [P+H2O] (NL 115.9875)'):
            
            score += 10
        
        if self.scn.chain_among_most_abundant(3, frag_type = 'Sph-2xH2O-H'):
            
            score += 10
        
        if self.scn.has_chain_combination(
            self.rec,
            chain_param = (
                {'frag_type': {
                        'Sph-2xH2O+H',
                        'Sph-H2O+H',
                        'Sph-H2O-H'
                    }
                },
                {'frag_type': 'FA+NH+C2H2-OH'},
            )
        ):
            
            score += 5
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('NL [P] (NL 79.9663)'),
                self.scn.has_fragment('NL [P] (NL 97.9769)'),
            )
        )) * 3
        
        non_hex_score, non_hex_max_score = self.non_hex()
        
        score += non_hex_score
        
        return score, max_score
    
    def hexcer(self):
        
        score = 0
        max_score = 14
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('NL [Hexose-H2O] (NL 162.05)'),
                self.scn.has_fragment('NL [Hexose] (NL 180.06)'),
                self.scn.has_fragment('NL [Hexose+H2O] (NL 198.07)'),
            )
        )) * 3
        
        if self.hexcer_chain_combination():
            
            score += 5
        
        return score, max_score
    
    def hex2cer(self):
        
        score = 0
        max_score = 39
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('NL [2xHexose] (NL 342.1162)'),
                self.scn.has_fragment('NL [2xHexose+H2O] (NL 360.1268)'),
            )
        )) * 10
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('NL [2xHexose-H2O] (NL 324.1056)'),
                self.scn.has_fragment('NL [2xHexose+O] (NL 358.1111)'),
                self.scn.has_fragment('NL [2xHexose+C] (NL 372.1268)'),
            )
        )) * 3
        
        if self.hexcer_chain_combination():
            
            score += 10
        
        return score, max_score
    
    def hexcer_chain_combination(self):
        
        return self.scn.has_chain_combination(
            self.rec,
            chain_param = (
                {'frag_type': {
                        'Sph-2xH2O+H',
                        'Sph-2xH2O-H',
                        'Sph-H2O+H',
                        'Sph-H2O-H',
                        'Sph-C-2xH2O',
                    }
                },
                {'frag_type': {
                        'FA-OH',
                        'NL FA',
                        'FA+NH2-O',
                    }
                },
            )
        )
    
    def shexcer(self):
        
        score = 0
        max_score = 25
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('NL [S] (NL 79.9568)'),
                self.scn.has_fragment('NL [S+H2O] (97.9674)'),
                self.scn.has_fragment('NL [Hexose+SO3] (NL 242.100)'),
                self.scn.has_fragment('NL [Hexose+SO3+H2O] (NL 260.0202)'),
                self.scn.has_fragment('NL [Hexose+SO3+2xH2O] (NL 278.0308)'),
            )
        )) * 5
        
        return score, max_score
    
    def shex2cer(self):
        
        score = 0
        max_score = 25
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('NL [S] (NL 79.9568)'),
                self.scn.has_fragment('NL [S+H2O] (97.9674)'),
                self.scn.has_fragment('NL [2xHexose+SO3] (NL 404.0625)'),
                self.scn.has_fragment('NL [2xHexose+SO3+H2O] (NL 422.0730)'),
                self.scn.has_fragment('NL [2xHexose+SO3+2xH2O] (NL 440.0836)'),
            )
        )) * 5
        
        return score, max_score
    
    def m2(self):
        
        score = 0
        max_score = 46
        
        if self.scn.has_fragment('PC/SM [Ch-Et] (58.0651)'):
            
            score += 10
        
        if (
            self.rec.chainsum.u > 0 and
            self.scn.has_fragment('[C7+NH2] (110.0964)')
        ):
            
            score += 10
        
        score += sum(map(bool, (
            self.scn.has_fragment('[C5+NH2+2H] (84.0808)'),
            self.scn.has_fragment('[C6+NH2] (96.0808)'),
        ))) * 3
        
        if self.scn.has_chain_combination(
                self.rec,
                chain_param = (
                    {
                        'frag_type': {
                            'Sph-2xH2O+CH3',
                            'Sph-O-H2O+CH3+H',
                            'Sph-2xH2O+2xCh3+H',
                            'Sph-H2O+2xCH3+H',
                        }
                    },
                )
            ):
            
            score += 20
        
        return score, max_score
    
    def m1(self):
        
        score = 0
        max_score = 30
        
        if self.scn.has_fragment('PC/SM [Ch-Et] (58.0651)'):
            
            score += 10
        
        if self.scn.has_chain_combination(
                self.rec,
                head = 10,
                chain_param = (
                    {
                        'frag_type': {
                            'Sph-2xH2O+CH3',
                            'Sph-O-H2O+CH3+H',
                            'Sph-H2O+CH3+H',
                        }
                    },
                )
            ):
            
            score += 20
        
        if self.scn.has_chain_fragment_type(
                frag_type = {'Sph-2xH2O+2xCH3+H', 'Sph-H2O+2xCH3+H'},
                c = self.rec.chainsum.c - 1,
                u = self.rec.chainsum.u,
            ):
            
            score -= 20
        
        return score, max_score
    
    def m3(self):
        
        score = 0
        max_score = 20
        
        if self.scn.fragment_among_most_abundant(
            3, 'PC/SM [N+3xCH3] (60.0808)'
        ):
            
            score += 20
        
        return score, max_score
    
    def sph(self):
        
        score = 0
        max_score = 9
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('[C3+NH2] (56.0495)'),
                self.scn.has_fragment('[C2+NH2+O] (60.0444)'),
                self.scn.has_fragment('[C4+NH2+OH] (86.0600)'),
            )
        )) * 3
        
        return score, max_score
    
    def sphingosine_base(self, sph):
        
        if sph not in self.sph_scores:
            
            method = 'sphingosine_%s' % sph.lower()
            
            self.sph_scores[sph], self.sph_max_scores[sph] = (
                getattr(self, method)() if hasattr(self, method) else (0, 0)
            )
        
        return self.sph_scores[sph], self.sph_max_scores[sph]
    
    def sphingosine_d(self):
        
        score = 0
        max_score = 20
        
        if self.rec.chainsum and self.rec.chainsum.u == 0:
            
            return score, max_score
        
        if (
            self.nacyl and self.scn.chain_fragment_type_is(
                0,
                frag_type = 'Sph-2xH2O+H',
                u = (False, {0}),
            )
        ) or (
            not self.nacyl and self.scn.chain_fragment_type_is(
                0,
                frag_type = 'Sph-H2O+H',
                u = (False, {0}),
            )
        ) or (
            self.rec.hg.main == 'SM' and self.scn.chain_among_most_abundant(
                5,
                frag_type = 'Sph-2xH2O+H',
                u = (False, {0}),
                skip_non_chains = True,
            )
        ):
            
            score += 6
            
            score += sum(map(bool,
                (
                    not self.scn.has_fragment('[C2+NH2+O] (60.0444)'),
                    self.scn.has_fragment('NL [C+2xH2O] (NL 48.0211)')
                )
            )) * 2
            
            if (
                self.scn.chain_fragment_type_among_most_abundant(
                    4, frag_type = 'Sph-H2O+H', u = (False, {0})
                ) and
                self.scn.chain_fragment_type_among_most_abundant(
                    4, frag_type = 'Sph-C-O-H2O-H', u = (False, {0})
                ) and
                self.scn.chain_fragment_type_among_most_abundant(
                    4, frag_type = 'Sph-2xH2O+H', u = (False, {0})
                )
            ):
                score += 10
        
        return score, max_score
    
    def sphingosine_dh(self):
        
        score = 0
        max_score = 20
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('[C2+NH2+O] (60.0444)'),
                not self.scn.has_fragment('NL [C+2xH2O] (NL 48.0211)')
            )
        ))
        
        score += sum(map(bool,
            (
                self.scn.chain_fragment_type_among_most_abundant(
                    5, frag_type = 'Sph-H2O+H', u = 0
                ),
                self.scn.chain_fragment_type_among_most_abundant(
                    5, frag_type = 'FA+NH2-O', u = 0
                ),
                self.scn.chain_fragment_type_among_most_abundant(
                    10, frag_type = 'Sph-2xH2O+H', u = 0
                ),
                self.scn.has_chain_fragment_type(
                    frag_type = 'Sph-C-O-H2O-H', u = 0
                ),
                self.scn.has_chain_fragment_type(
                    frag_type = 'Sph+H', u = 0
                ),
                self.scn.has_chain_fragment_type(
                    frag_type = 'Sph-C-O-H2O-NH', u = 0
                )
            )
        )) * 3
        
        return score, max_score
    
    def sphingosine_t(self):
        
        score = 0
        max_score = 20
        
        if all((
            self.scn.chain_fragment_type_among_most_abundant(
                5, frag_type = 'Sph-H2O-H',
            ),
            self.scn.chain_fragment_type_among_most_abundant(
                10, frag_type = 'Sph-2xH2O-H',
            ),
            (
                self.scn.fragment_among_most_abundant(
                    '[C2+NH2+O] (60.0444)'
                ) or
                self.rec.hg.sub
            )
        )):
            
            score = 9
            
            score += sum(map(bool,
                (
                    not self.scn.has_fragment('NL [C+2xH2O] (NL 48.0211)'),
                    self.scn.has_fragment('NL [3xH2O] (NL 54.0317)')
                )
            ))
            
            score += sum(map(bool,
                (
                    self.scn.has_chain_fragment_type(
                        frag_type = 'Sph-C-2xH2O',
                    ),
                    self.scn.has_chain_fragment_type(
                        frag_type = 'Sph+H2O-H',
                    ),
                    self.scn.chain_fragment_type_among_most_abundant(
                        5, frag_type = 'Sph-H',
                    ),
                )
            )) * 3
        
        return score, max_score
    
    def sphingosine_k(self):
        
        score = 0
        max_score = 39
        
        if self.scn.has_chain_fragment_type(frag_type = 'Sph-NH2-H2O-2H'):
            
            score += 15
        
        score += sum(map(bool,
            (
                self.scn.has_fragment('[C2+NH2+O] (60.0444)'),
                self.scn.has_fragment('[C4+NH2+OH] (86.0600)'),
                self.scn.has_fragment('[C6+OH] (99.0804)'),
                self.scn.has_fragment('[C3+NH2] (56.0495)'),
            )
        )) * 3
        
        score += sum(map(bool,
            (
                self.scn.has_chain_fragment_type(
                    frag_type = 'Sph-C-2xH2O',
                ),
                self.scn.has_chain_fragment_type(
                    frag_type = 'Sph-H2O-H',
                ),
                self.scn.has_chain_fragment_type(
                    frag_type = 'Sph-H',
                ),
                self.scn.chain_fragment_type_among_most_abundant(
                    5, frag_type = 'Sph-H',
                ),
            )
        )) * 3
        
        return score, max_score


class Cer_Negative(AbstractMS2Identifier):
    """
    Examines if a positive mode MS2 spectrum is a ceramide.
    Identifies ceramide varieties including sphingomyeline,
    ceramide-1-phosphare, ceramide-phosphoethanolamine,
    OH-acyl-ceramide, hexosyl and dihexosyl-ceramides,
    and d, t and DH long chain base varieties.
    
    dCer
    ====
    
    **Specimen:**
    
    - in vivo SEC14L1 583, 554, 580 (formiate adduct)
    - in vivo STARD11 583, 554 (formiate adduct)
    - standards
    
    DHCer
    =====
    
    **Specimen:**
    
    - standards
    
    tCer
    ====
    
    **Specimen:**
    
    - standards
    
    """
    
    class_methods = {
        'Cer': 'cer',
        'SM':  'sm',
    }
    
    subclass_methods = {
        '1P': 'cer1p',
        'Hex': 'hexcer',
    }
    
    def __init__(self, record, scan, **kwargs):
        
        self.nacyl = record.chainsum is not None and len(record.chainsum) > 1
        self.oacyl = record.chainsum is not None and len(record.chainsum) > 2
        
        AbstractMS2Identifier.__init__(
            self,
            record,
            scan,
            missing_chains = (),
            chain_comb_args = {},
            must_have_chains = True,
            **kwargs,
        )
        
        self.sph_scores     = {}
        self.fa_scores      = {}
        self.sph_max_scores = {}
        self.fa_max_scores  = {}
    
    def confirm_class(self):
        
        AbstractMS2Identifier.confirm_class(self)
        
        self.confirm_subclass()
    
    def confirm_chains_explicit(self):
        
        for chains in itertools.chain(
            AbstractMS2Identifier.confirm_chains_explicit(self),
            AbstractMS2Identifier.confirm_chains_implicit(self),
        ):
            
            if chains[0][0].attr.sph == self.rec.chainsum.attr[0].sph:
                
                # the sphingosin base and fatty acyl related part of the
                # score is valid only for the current chain combination
                # hence now we add these to the overall score, yield the
                # identification and then subtract them from the score
                sph_score, sph_max_score = self.sphingosine_base(
                    chains[0][0].attr.sph
                )
                self.score += sph_score
                self.max_score += sph_max_score
                
                if self.nacyl:
                    
                    fa_score, fa_max_score = self.fatty_acyl(chains[0][1])
                    self.score += fa_score
                    self.max_score += fa_max_score
                
                yield chains
                
                self.score -= sph_score
                self.max_score -= sph_max_score
                
                if self.nacyl:
                    
                    self.score -= fa_score
                    self.max_score -= fa_max_score
    
    def fatty_acyl(self, fa):
        
        score = 0
        max_score = 0
        
        if len(fa.attr.oh) == 1:
            
            max_score = 30
            
            if self.scn.has_chain_combination(
                self.rec,
                head = 20, # to exclude tCer
                chain_param = (
                    {
                        'frag_type': {
                            'Sph-H', # b1
                            'Sph-C2H4-NH2-H2O', # b5
                        }
                    },
                    {
                        'frag_type': {
                            'FA+C2+NH2+O',  # a5 @ hydroxyacyl
                            'FA+CH2+NH2+O', # a1 @ hydroxyacyl
                        }
                    }
                )
            ):
                
                score += 30
        
        return score, max_score
    
    def cer(self):
        
        max_score = 23
        
        cer_nl = (
            'NL H2O (NL 18.0106)', # Hsu c1
            'NL 2xH2O (NL 36.0211)', # Hsu c4
            'NL C+H2O (NL 30.0106)', # Hsu c2
            'NL CH2+H2O (NL 32.0262)', # Hsu c3
            'NL C+2xH2O (NL 48.0211)', # Hsu c5
            'NL C+3xH2O (66.0455)', # Hsu c6
        )
        
        score = sum(
            self.scn.has_fragment(frag_name, adduct = self.add)
            for frag_name in cer_nl
        ) * 3
        
        if self.scn.has_chain_combinations(self.rec, adduct = self.add):
            
            score += 5
        
        return score, max_score
    
    def sphingosine_base(self, sph):
        
        if sph not in self.sph_scores:
            
            method = 'sphingosine_%s' % sph.lower()
            
            self.sph_scores[sph], self.sph_max_scores[sph] = (
                getattr(self, method)() if hasattr(self, method) else (0, 0)
            )
        
        return self.sph_scores[sph], self.sph_max_scores[sph]
    
    def sphingosine_d_dh(self):
        
        score = 0
        max_score = 20
        
        if self.scn.has_chain_combination(
            self.rec,
            chain_param = (
                {
                    'frag_type': {
                        'Sph-H', # b1
                        'Sph-C2H4-3H', # b2
                        'Sph-CH2-H2O-H', # b3
                        'Sph-H2O-NH2-2H', # b4
                        'Sph-C2H4-NH2-H2O', # b5
                    }
                },
                {
                    'frag_type': {
                        'FA+C2+NH2', # a2
                        'FA+C2+NH2-O', # a3
                    }
                }
            )
        ):
            
            score += 20
        
        return score, max_score
    
    def sphingosine_d(self):
        
        score = 0
        max_score = 20
        
        d_dh_score, d_dh_max_score = self.sphingosine_d_dh()
        
        score += d_dh_score
        max_score += d_dh_max_score
        
        if self.scn.has_fragment('NL C+H2O (NL 30.0106)', adduct = self.add):
            
            score += 20
        
        return score, max_score
    
    def sphingosine_dh(self):
        
        score = 0
        max_score = -20
        
        d_dh_score, d_dh_max_score = self.sphingosine_d_dh()
        
        score += d_dh_score
        max_score += d_dh_max_score
        
        if self.scn.has_fragment('NL C+H2O (NL 30.0106)', adduct = self.add):
            
            score -= 20
        
        return score, max_score
    
    def sphingosine_t(self):
        
        score = 0
        max_score = 28
        
        if self.scn.has_fragment('NL C+3xH2O (66.0455)', adduct = self.add):
            
            score += 5
        
        if self.scn.has_fragment('HexCer identity II'):
            
            score += 3
        
        if self.scn.has_chain_combination(
            self.rec,
            chain_param = (
                {
                    'frag_type': {
                        'Sph-CH2-NH2-4H', # b6
                    }
                },
                {
                    'frag_type': {
                        'FA+C2H2+NH2', # a1
                        'FA+C3H2+NH2', # a10
                    }
                }
            )
        ):
            
            score += 20
        
        # differentiate from hydroxyacyl-dCer
        if self.scn.chain_percent_of_most_abundant(
            frag_type = {'FA+C2H2+NH2+O', 'FA+C2+NH2+O'},
            percent = 5.0,
        ):
            
            score -= 10
        
        return score, max_score
    
    def cer1p(self):
        
        score = 0
        max_score = 70
        
        if any(map(bool, (
            self.scn.has_fragment('Cer1P/PIP/PL metaphosphate (78.9591)'),
            self.scn.has_fragment('Cer1P/PI phosphate (96.9696)'),
        ))):
            
            score += 20
            
            if self.scn.has_fragment(
                'NL H2O (NL 18.0106)', adduct = self.add
            ):
                
                score += 10
            
            if self.scn.has_chain_fragment_type(
                frag_type = {'NLFA_pH2O', 'NLFA_p2xH2O'},
                adduct = self.add
            ):
                
                score += 10
            
            self.must_have_chains = False
        
        if (
            self.rec.hg.main == 'Sph' and
            self.scn.fragment_among_most_abundant(
                'Cer1P/PIP/PL metaphosphate (78.9591)', 3
            )
        ):
            
            score += 20
            self.must_have_chains = False
            
            if self.scn.has_fragment('Cer1P/PI phosphate (96.9696)'):
                
                score += 10
        
        return score, max_score
    
    def sm(self):
        
        score = 0
        max_score = 45
        
        if self.scn.fragment_among_most_abundant(
            'NL CH2 (NL 14.0157)', 3, adduct = self.add
        ) and self.scn.fragment_among_most_abundant(
            'PC/SM PO4+choline-CH3 (168.0431)', 5
        ):
            
            score += 30
            
            score += sum(map(bool, (
                self.scn.has_fragment(
                    'Cer1P/PIP/PL metaphosphate (78.9591)'
                ),
                self.scn.has_fragment(
                    'NL choline+H2O', adduct = self.add
                ),
                self.scn.has_fragment(
                    'NL choline+H2O-CH3', adduct = self.add
                ),
            ))) * 5
            
            self.must_have_chains = False
        
        return score, max_score
    
    def hexcer(self):
        
        score = 0
        max_score = 90
        
        self.score += sum(map(bool, (
            self.scn.fragment_among_most_abundant('HexCer identity I', 10),
            self.scn.fragment_among_most_abundant('HexCer identity II', 10),
            self.scn.fragment_among_most_abundant('HexCer identity III', 10),
            self.scn.has_fragment('[Hexose] (179.0561)'),
            self.scn.has_fragment('[Hexose-H2O] (161.0455)'),
            self.scn.has_fragment('[Hexose-HCHO] (149.0455)'),
            self.scn.has_fragment('NL hexose (162.053)'),
            self.scn.has_fragment('NL hexose+H2O (180.063)'),
        ))) * 10
        
        if self.scn.has_chain_combinations(self.rec):
            
            score += 10
        
        return score, max_score
    
    def hex2cer(self):
        
        score = 0
        max_score = 140
        
        self.score += sum(map(bool, (
            self.scn.has_fragment('HexCer identity I'),
            self.scn.has_fragment('HexCer identity II'),
            self.scn.has_fragment('HexCer identity III'),
            self.scn.has_fragment('[Hexose] (179.0561)'),
            self.scn.has_fragment('[Hexose-H2O] (161.0455)'),
            self.scn.has_fragment('[Hexose-HCHO] (149.0455)'),
            self.scn.has_fragment('NL hexose (162.053)'),
            self.scn.has_fragment('NL hexose+H2O (180.063)'),
            self.scn.has_fragment('[2xHexose-HCHO] (311.0984)'),
            self.scn.has_fragment('[2xHexose-H2O] (323.0984)'),
            self.scn.has_fragment('[2xHexose] (341.1089)'),
            self.scn.has_fragment('NL 2xHexose (324.106)'),
            self.scn.has_fragment('NL 2xHexose+H2O (342.1162)'),
        ))) * 10
        
        if self.scn.has_chain_combinations(self.rec):
            
            score += 10
        
        return score, max_score
    
    def shexcer(self):
        
        score = 0
        max_score = 100
        
        self.missing_chains = (1,)
        
        if self.scn.has_fragment('Sulphate (96.9601)'):
            
            score += 20
        
        self.score += sum(map(bool, (
            self.scn.has_fragment('[Sulfohexose] (259.0129)'),
            self.scn.has_fragment('[Sulfohexose] (256.9972)'),
            self.scn.has_fragment('[Sulfohexose-H2O] (241.0024)'),
            self.scn.has_fragment('[Sulfohexose+Et+N] (300.0395)'),
        ))) * 10
        
        if self.scn.has_chain_fragment_type(
            frag_type = {
                'Sph+C6O5H8+SO3+H2O',
                'Sph+C6O5H8+SO3+CO+H2O',
            }
        ):
            
            score += 20
            
            if self.scn.has_chain_combination(
                self.rec,
                chain_param = (
                    {
                        'frag_type': {
                            'Sph+C6O5H8+SO3',
                            'Sph+C6O5H8+SO3+H2O',
                            'Sph+C6O5H8+SO3+CO+H2O',
                        }
                    },
                    {
                        'frag_type': {
                            'NLFA',
                            'NLFA_mH2O',
                        }
                    }
                )
            ):
                
                score += 20
        
        return score, max_score
    
    def shex2cer(self):
        
        score = 0
        max_score = 140
        
        self.missing_chains = (1,)
        
        if self.scn.has_fragment('Sulphate (96.9601)'):
            
            score += 20
        
        score += sum(map(bool, (
            self.scn.has_fragment('[Sulfohexose] (259.0129)'),
            self.scn.has_fragment('[Sulfohexose] (256.9972)'),
            self.scn.has_fragment('[Sulfohexose-H2O] (241.0024)'),
            self.scn.has_fragment('[Sulfohexose+Et+N] (300.0395)'),
            self.scn.has_fragment('[2xHexose-H2O+SO3] (403.0552)'),
            self.scn.has_fragment('[2xHexose+SO3] (419.0501)'),
            self.scn.has_fragment('[2xHexose+SO3] (421.0658)'),
            self.scn.has_fragment('[2xHexose+SO3+Et+N] (462.0923)'),
        ))) * 10
        
        if self.scn.has_chain_fragment_type(
            frag_type = {
                'Sph+C12O10H18+SO3',
                'Sph+C12O10H18+SO3+H2O',
                'Sph+C12O10H18+SO3+CO+H2O',
            }
        ):
            
            score += 20
            
            if self.scn.has_chain_combination(
                self.rec,
                chain_param = (
                    {
                        'frag_type': {
                            'Sph+C12O10H18+SO3',
                            'Sph+C12O10H18+SO3+H2O',
                            'Sph+C12O10H18+SO3+CO+H2O',
                        }
                    },
                    {
                        'frag_type': {
                            'NLFA',
                            'NLFA_mH2O',
                        }
                    }
                )
            ):
                
                score += 20
        
        return score, max_score
    
    def pe_cer(self):
        
        score = 0
        max_score = 30
        
        score += sum(map(bool, (
            self.scn.has_fragment('PE [P+E] (140.0118)'),
            self.scn.has_fragment('NL PE [P+E] (141.0191)'),
            self.scn.has_fragment('PE [P+E-H2O] (122.0013)'),
        ))) * 10
        
        return score, max_score

#
# Scan.identify() dispatches identification methods as below
#

idmethods = {
    'neg': {
        lipproc.Headgroup(main = 'FA'):  FA_Negative,
        lipproc.Headgroup(main = 'DAG'): DAG_Negative,
        lipproc.Headgroup(main = 'TAG'): TAG_Negative,
        lipproc.Headgroup(main = 'DGTA'): GL_Negative,
        lipproc.Headgroup(main = 'DGTS'): GL_Negative,
        lipproc.Headgroup(main = 'DGCC'): GL_Negative,
        lipproc.Headgroup(main = 'SQDG'): GL_Negative,
        lipproc.Headgroup(main = 'MGDG'): GL_Negative,
        lipproc.Headgroup(main = 'DGDG'): GL_Negative,
        lipproc.Headgroup(main = 'DGTA', sub = ('Lyso',)): GL_Negative,
        lipproc.Headgroup(main = 'DGTS', sub = ('Lyso',)): GL_Negative,
        lipproc.Headgroup(main = 'DGCC', sub = ('Lyso',)): GL_Negative,
        lipproc.Headgroup(main = 'SQDG', sub = ('Lyso',)): GL_Negative,
        lipproc.Headgroup(main = 'MGDG', sub = ('Lyso',)): GL_Negative,
        lipproc.Headgroup(main = 'DGDG', sub = ('Lyso',)): GL_Negative,
        lipproc.Headgroup(main = 'PE'):  PE_Negative,
        lipproc.Headgroup(main = 'PE', sub = ('Lyso',)): PE_Negative,
        lipproc.Headgroup(main = 'PC'):  PC_Negative,
        lipproc.Headgroup(main = 'PC', sub = ('Lyso',)): PC_Negative,
        lipproc.Headgroup(main = 'PI'):  PI_Negative,
        lipproc.Headgroup(main = 'PI', sub = ('Lyso',)):  PI_Negative,
        lipproc.Headgroup(main = 'PS'):  PS_Negative,
        lipproc.Headgroup(main = 'PS', sub = ('Lyso',)): PS_Negative,
        lipproc.Headgroup(main = 'PG'):  PG_Negative,
        lipproc.Headgroup(main = 'PG', sub = ('Lyso',)):  PG_Negative,
        lipproc.Headgroup(main = 'BMP'): BMP_Negative,
        lipproc.Headgroup(main = 'PA'):  PA_Negative,
        lipproc.Headgroup(main = 'PA', sub = ('Lyso',)):  PA_Negative,
        lipproc.Headgroup(main = 'VA'): VA_Negative,
        lipproc.Headgroup(main = 'Cer'): Cer_Negative,
        lipproc.Headgroup(main = 'Cer', sub = ('1P',)): Cer_Negative,
        lipproc.Headgroup(main = 'SM'): Cer_Negative,
        lipproc.Headgroup(main = 'Cer', sub = ('Hex',)): Cer_Negative,
        lipproc.Headgroup(main = 'Cer', sub = ('Hex2',)): Cer_Negative,
        lipproc.Headgroup(main = 'Cer', sub = ('SHex',)): Cer_Negative,
        lipproc.Headgroup(main = 'Cer', sub = ('SHex2',)): Cer_Negative,
        lipproc.Headgroup(main = 'Cer', sub = ('PE',)): Cer_Negative,
        lipproc.Headgroup(main = 'Sph'): Cer_Negative,
        lipproc.Headgroup(main = 'Sph', sub = ('1P',)): Cer_Negative,
    },
    'pos': {
        lipproc.Headgroup(main = 'FA'):  FA_Positive,
        lipproc.Headgroup(main = 'DAG'): DAG_Positive,
        lipproc.Headgroup(main = 'DGTA'): GL_Positive,
        lipproc.Headgroup(main = 'DGTS'): GL_Positive,
        lipproc.Headgroup(main = 'DGCC'): GL_Positive,
        lipproc.Headgroup(main = 'SQDG'): GL_Positive,
        lipproc.Headgroup(main = 'MGDG'): GL_Positive,
        lipproc.Headgroup(main = 'DGDG'): GL_Positive,
        lipproc.Headgroup(main = 'DGTA', sub = ('Lyso',)): GL_Positive,
        lipproc.Headgroup(main = 'DGTS', sub = ('Lyso',)): GL_Positive,
        lipproc.Headgroup(main = 'DGCC', sub = ('Lyso',)): GL_Positive,
        lipproc.Headgroup(main = 'SQDG', sub = ('Lyso',)): GL_Positive,
        lipproc.Headgroup(main = 'MGDG', sub = ('Lyso',)): GL_Positive,
        lipproc.Headgroup(main = 'DGDG', sub = ('Lyso',)): GL_Positive,
        lipproc.Headgroup(main = 'TAG'): TAG_Positive,
        lipproc.Headgroup(main = 'PE'):  PE_Positive,
        lipproc.Headgroup(main = 'PE', sub = ('Lyso',)):  LysoPE_Positive,
        lipproc.Headgroup(main = 'PC'):  PC_Positive,
        lipproc.Headgroup(main = 'PC', sub = ('Lyso',)):  LysoPC_Positive,
        lipproc.Headgroup(main = 'PI'):  PI_Positive,
        lipproc.Headgroup(main = 'PI', sub = ('Lyso',)):  PI_Positive,
        lipproc.Headgroup(main = 'PS'):  PS_Positive,
        lipproc.Headgroup(main = 'PS', sub = ('Lyso',)):  PS_Positive,
        lipproc.Headgroup(main = 'PG'):  PG_Positive,
        lipproc.Headgroup(main = 'PG', sub = ('Lyso',)):  PG_Positive,
        lipproc.Headgroup(main = 'BMP'): BMP_Positive,
        lipproc.Headgroup(main = 'PA'):  PA_Positive,
        lipproc.Headgroup(main = 'PA', sub = ('Lyso',)):  PA_Positive,
        lipproc.Headgroup(main = 'VA'): VA_Positive,
        lipproc.Headgroup(main = 'Cer'): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('1P',)): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('Hex',)): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('Hex2',)): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('SHex',)): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('SHex2',)): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('PE',)): Cer_Positive,
        lipproc.Headgroup(main = 'SM'): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('1P', 'Lyso')): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('Hex', 'Lyso')): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('Hex2', 'Lyso')): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('SHex', 'Lyso')): Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('SHex2', 'Lyso')):
            Cer_Positive,
        lipproc.Headgroup(main = 'Cer', sub = ('PE', 'Lyso')): Cer_Positive,
        lipproc.Headgroup(main = 'SM',  sub = ('Lyso',)): Cer_Positive,
        lipproc.Headgroup(main = 'Sph'): Cer_Positive,
        lipproc.Headgroup(main = 'Sph', sub = ('1P',)): Cer_Positive,
        lipproc.Headgroup(main = 'Sph', sub = ('M1',)): Cer_Positive,
        lipproc.Headgroup(main = 'Sph', sub = ('M2',)): Cer_Positive,
        lipproc.Headgroup(main = 'Sph', sub = ('M3',)): Cer_Positive,
    }
}


class MS2Feature(object):
    
    scan_methods = {
        'mgf':  'mgf_iterscans',
        'mzml': 'mzml_iterscans',
    }
    
    def __init__(
            self,
            mz,
            ionmode,
            resources,
            rt,
            ms1_records = None,
            rt_range = .5,
            check_rt = True,
        ):
        """
        Collects the MS2 scans from the provided resources for a single
        feature. Calls identification methods on all scans collected.
        
        :param float mz:
            m/z value of the precursor ion.
        :param str ionmode:
            Ion mode of the experiment. Either ``pos`` or ``neg``.
        :param dict resources:
            ``dict`` of MS2 scan resources. These are either ``mgf.MgfReader``
            objects or paths to MGF files. Later more resource types
            will be available, for example MzML format. Keys of the ``dict``
            are used as sample labels. Thes can be strings or tuples.
        :param dict ms1_records:
            A data structure resulted by ``moldb.adduct_lookup``. If ``None``
            the lookup will be done here.
        :param float rt_range:
            If a single retention time value provided this is the largest
            accepted difference between an MS2 scan's RT and the precursor's
            RT. E.g. if ``rt = 8.3`` and ``rt_range = 0.5``, scans between
            7.8 and 8.8 will be considered. If a tuple of floats provided
            for RT, scans between these two values will be considered.
        :param bool check_rt:
            Check if the retention time of the scan is enough close to the
            precursor's RT. If ``False``, scans will be matched only by the
            m/z value of the precursor and scans with any large RT difference
            will be analysed.
        """
        
        self.mz = mz
        self.ionmode = ionmode
        self.ms1_records = ms1_records or moldb.adduct_lookup(mz, ionmode)
        self.resources = resources
        self.rt = (rt - rt_range, rt + rt_range) if type(rt) is float else rt
        self.rtmean = sum(self.rt) / 2.0
        self.rt_range = rt_range
        self.check_rt = check_rt
    
    def main(self):
        
        self.ms1_lookup()
        self.build_scans()
        self.identify()
    
    def iterscans(self):
        
        for sample_id, resources in iteritems(self.resources):
            
            for resource in resources:
                
                res_type = self.guess_resouce_type(resource)
                
                if res_type not in self.scan_methods:
                    
                    raise ValueError(
                        'Unknown MS2 resource type: %s' % str(resource)
                    )
                
                scan_method = getattr(self, self.scan_methods[res_type])
                
                for scan in scan_method(resource, sample_id):
                    
                    yield scan
    
    def mgf_iterscans(self, mgf_resource, sample_id = None):
        
        if isinstance(mgf_resource, basestring):
            
            mgffile = mgf.MgfReader(mgfname, charge = None)
            
        elif isinstance(mgf_resource, mgf.MgfReader):
            
            mgffile = mgf_resource
            
        else:
            
            raise ValueError(
                'Mgf files should be lipyd.mgf.MgfReader '
                'instances of file names.'
            )
        
        idx, rtdiff = mgffile.lookup(self.mz, rt = self.rtmean)
        
        for i, rtd in zip(idx, rtdiff):
            
            if self.check_rt:
                
                scan_rt = self.rtmean + rtd
                
                if scan_rt < self.rt[0] or scan_rt > self.rt[1]:
                    
                    continue
            
            sc = mgffile.get_scan(i)
            
            yield Scan(
                mzs = sc[:,0],
                intensities = sc[:,1],
                ionmode = self.ionmode,
                precursor = self.mz,
                ms1_records = self.ms1_records,
                scan_id = mgffile.mgfindex[i,3],
                sample_id = sample_id,
                source = mgffile.fname,
                deltart = rtd,
                rt = mgffile.mgfindex[i,2],
            )
    
    def mzml_iterscans(self, mzml_resource, sample_id = None):
        
        raise NotImplementedError
    
    @staticmethod
    def guess_resouce_type(res):
        
        if isinstance(res, basestring) and os.path.exists(res):
            
            if res[-3:].lower() == 'mgf':
                
                return 'mgf'
            
        elif isinstance(res, mgf.MgfReader):
            
            return 'mgf'
    
    def build_scans(self):
        
        self.scans = np.array(list(self.iterscans()))
        self.deltart = np.array([sc.rt - self.rtmean for sc in self.scans])
        
        rtsort = [
            it[0]
            for it in sorted(
                (it for it in enumerate(self.deltart)),
                key = lambda it: abs(it[1])
            )
        ]
        
        self.scans = self.scans[rtsort]
        self.deltart = self.deltart[rtsort]
    
    def identify(self):
        
        self.identities = []
        
        for scan in self.scans:
            
            identity = scan.identify()
            
            if identity:
                
                self.identities.append(identity)
    
    def identity_summary(
            self,
            scores = True,
            drt = True,
            sample_ids = False,
            scan_ids = False,
        ):
        
        identities = set()
        
        for i, scan_i in enumerate(self.identities):
            
            for sum_str, varieties in iteritems(scan_i):
                
                for var in varieties:
                    
                    summary = [var.__str__()]
                    
                    if scores:
                        
                        summary.append(var.score_pct)
                        
                    else:
                        
                        if var.score == 0:
                            
                            continue
                    
                    if drt:
                        
                        summary.append(self.deltart[i])
                    
                    if sample_ids:
                        
                        summary.append(self.scans[i].sample_id)
                    
                    if scan_ids:
                        
                        summary.append(self.scans[i].scan_id)
                    
                    identities.add(tuple(summary))
        
        return identities
    
    def ms1_lookup(self):
        
        if self.ms1_records is None:
            
            self.ms1_records = moldb.adduct_lookup(self.mz)

##############################################################################


class MS2FeatureOld(object):
    """
    Provides additional, more sophisticated methods
    for identification of a single feature.
    
    In the original concept all methods for identification
    based on MS1 and MS2 took place in class Screening(),
    as those could simply iterate through the arrays.
    
    Later more complex methods became necessary, so
    I created this class to group them.
    """
    
    def __init__(self, main, protein, mode, oi, log = True):
        """
        @main : ltp.Screening() instance
            One Screening() instance with MS1 and MS2 processing already done.
        
        @protein : str
            Protein name
        
        @mode : str
            MS mode (`pos` or `neg`)
        
        @oi : int
            Original index of one feature.
        
        @log : bool
            Whether output verbose messages to logfile.
        """
        self.main = main
        self.log = log
        self.protein = protein
        self.mode = mode
        self.oi = oi
        self.ifracs = self.main.fraction_indices(self.protein)
        self.fracsi = dict(map(lambda fr: (fr[1][0], fr[0]),
                               iteritems(self.ifracs)))
        self.tbl = self.main.valids[self.protein][self.mode]
        self.ms2 = self.tbl['ms2'][self.oi]
        self.i = self.main.oi2i(self.protein, self.mode, self.oi)
        self.fa = {}
        self.scans_fractions = map(
            lambda tpl: tuple(map(int, tpl)),
            uniqList(
                map(
                    tuple,
                    # scan ID, fraction ID
                    self.ms2[:,[12,14]]
                )
            )
        )
        self.classes = ['PA', 'PC', 'PE', 'PG', 'PS']
        self.classes2 = ['PA', 'PC', 'PE', 'PG', 'PS', 'PI', 'SM', 'BMP',
                         'Cer', 'Cer1P', 'HexCer', 'HexCerOH',
                         'DAG', 'TAG', 'FA', 'VA', 'LysoPE', 'LysoPC']
        self.identities = set([])
        self.identities2 = {}
        # get carbon counts from MS1
        self.ms1fa = self.tbl['ms1fa'][oi]
        # sorting by fractions/scans
        self.scans = dict(
            map(
                lambda sc_fr:
                    (
                        # scan ID, fraction ID: key
                        (sc_fr[0], sc_fr[1]),
                        # MS2 array slice: value
                        self.ms2[
                            np.where(
                                np.logical_and(
                                    self.ms2[:,12] == sc_fr[0],
                                    self.ms2[:,14] == sc_fr[1]
                                )
                            )
                        ]
                    ),
                self.scans_fractions
            )
        )
        # sorting by intensity desc
        self.scans = dict(
            map(
                lambda i:
                    (
                        i[0],
                        i[1][i[1][:,2].argsort()[::-1],:]
                    ),
                iteritems(self.scans)
            )
        )
        self.deltart = dict(
            map(
                lambda i:
                    (
                        i[0],
                        self.tbl['rtm'][self.i] - i[1][0,11]
                    ),
                iteritems(self.scans)
            )
        )
        self._scans = dict(
            map(
                lambda i:
                    (
                        i[0],
                        # i[0]: (scan ID, fraction ID)
                        # i[1]: MS2 array slice
                        MS2Scan(i[1], i[0], self)
                    ),
                iteritems(self.scans)
            )
        )
        self.maxins = dict(
            map(
                lambda i:
                    (
                        i[0],
                        i[1][0,2]
                    ),
                iteritems(self.scans)
            )
        )
        self.medins = dict(
            map(
                lambda i:
                    (
                        i[0],
                        np.median(i[1][:,2])
                    ),
                iteritems(self.scans)
            )
        )
        self.sort_scans()
        self.select_best_scan()
        self.msg('\n::: Analysing feature: %s :: %s :: index = %u ::'\
                ' m/z = %.03f :: number of MS2 scans: %u\n' % \
            (self.protein, self.mode, self.oi, self.tbl['mz'][self.i],
                len(self._scans))
        )
        self.msg('\n::: Database lookup resulted '\
            'the following species: %s\n' % self.print_db_species())
        self.msg('\n::: Intensities:\n%s%s\n' % \
            (' ' * 24, '          '.join(['A09', 'A10', 'A11', 'A12', 'B01'])))
        self.msg('%s%s' % (' ' * 16, '=' * 63))
        self.msg('\n    - absolute:  %s' % '   '.join(
          map(lambda x: '%10.01f' % x, self.tbl['fe'][self.i,:]))
        )
        self.msg('\n    - relative: %s\n' % \
          '  '.join(
                map(
                    lambda xx:
                        '%10.02f%%' % (xx * 100.0),
                    map(
                        lambda x:
                            x / np.nanmax(self.tbl['fe'][self.i,:]),
                        self.tbl['fe'][self.i,:]
                    )
                )
            )
        )
        self.msg('\n::: MS2 scans available (%u):\n\n' % len(self.scans))
        
        for sc in self._scans.values():
            sc.print_scan()
    
    def sort_scans(self):
        """
        Groups the scans in 3 groups: highest consists of those from the
        fractions with the highest protein level (there might be more than
        one the highest, because the fraction offset limits); the secondary
        contains scans from other protein containing fractions; while the
        other contains the scans from non protein containing fractions.
        Within the groups the scans are sorted from lowest to highest
        deltaRT.
        """
        
        self.highest = []
        self.secondary = []
        self.other = []
        with_protein = self.main.protein_containing_fractions(self.protein)
        for scan_num, fr in self.scans.keys():
            fr_name = 'a%u' % fr if fr != 13 and fr != 1 else 'b1'
            if fr_name in with_protein:
                if fr_name == self.main.fracs_orderL[self.protein][0][0] or \
                    fr_name == self.main.fracs_orderU[self.protein][0][0]:
                    self.highest.append((scan_num, fr))
                else:
                    self.secondary.append((scan_num, fr))
            else:
                self.other.append((scan_num, fr))
        self.highest = sorted(self.highest, key = lambda sc: abs(self._scans[sc].deltart))
        self.secondary = sorted(self.secondary, key = lambda sc: abs(self._scans[sc].deltart))
        self.other = sorted(self.other, key = lambda sc: abs(self._scans[sc].deltart))
    
    def select_best_scan(self):
        self.best_scan = \
            self.highest[0] if len(self.highest) else \
            self.secondary[0] if len(self.secondary) else \
            self.other[0] if len(self.other) else \
            None
    
    def print_db_species(self):
        return ', '.join(
            map(
                lambda hg:
                    '%s' % (
                        hg \
                            if hg not in self.tbl['ms1fa'][self.oi] \
                            or not len(self.tbl['ms1fa'][self.oi][hg]) \
                            else \
                        ', '.join(
                            map(
                                lambda fa:
                                    '%s(%s)' % (hg, fa),
                                self.tbl['ms1fa'][self.oi][hg]
                            )
                        )
                    ),
                self.tbl['ms1hg'][self.oi]
            )
        ) \
        if len(self.tbl['ms1hg'][self.oi]) \
        else 'none'
    
    def reload(self, children = False):
        modname = self.__class__.__module__
        mod = __import__(modname, fromlist=[modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)
        
        if children:
            
            for sc in self._scans.values():
                
                sc.reload()
    
    def __str__(self):
        return ', '.join(
            map(
                lambda hgfas:
                    ', '.join(
                        map(
                            lambda fa:
                                '%s(%s)' % (hgfas[0], fa),
                            hgfas[1]
                        )
                    ),
                iteritems(self.fa)
            )
        )
    
    def get_header_div(self):
        return '\t\t<div class="ms2hdr">\n\t\t'\
            'MS2 scans of feature %.04f'\
            '\n\t\t\t|<span class="scansbutton morescans1"'\
                ' title="Show/hide scans from fractions with '\
                'highest protein concentration">scans+</span>\n'\
            '\n\t\t\t|<span class="scansbutton morescans2"'\
                ' title="Show/hide scans from other protein '\
                'containing fractions">scans++</span>\n'\
            '\n\t\t\t|<span class="scansbutton morescans3"'\
                ' title="Show/hide scans from non protein '\
                'containing fractions">scans+++</span>\n'\
            '\n\t\t\t|<span class="scansbutton morefrags"'\
                ' title="Show/hide fragments after 5 highest'\
                '">frags+</span>\n'\
            '\n\t\t\t|<span class="scansbutton remove"'\
                ' title="Remove scans of this feature'\
                '">remove</span>\n'\
            '\t\t</div>\n' % \
            self.tbl['mz'][self.i]
    
    def html_table(self):
        container = '\t<div id="%s" class="ms2tblcontainer">\n%s%s\n\t</div>'
        header = self.get_header_div()
        html = []
        if self.best_scan is not None:
            html.append(self._scans[self.best_scan].html_table())
        else:
            html.append('<div class="noscans">No scans '\
                'from fractions with highest protein concentration.</div>')
        for sc in sorted(self._scans.values(), key = lambda sc: abs(sc.deltart)):
            if sc.in_primary and sc.scan_id != self.best_scan:
                html.append(sc.html_table())
        for sc in sorted(self._scans.values(), key = lambda sc: abs(sc.deltart)):
            if not sc.in_primary and sc.scan_id != self.best_scan:
                html.append(sc.html_table())
        for sc in sorted(self._scans.values(), key = lambda sc: abs(sc.deltart)):
            if not sc.in_primary and not sc.in_secondary:
                html.append(sc.html_table())
        html = '\n'.join(html)
        return container % ('ms2c_%u_%u' % \
            (int(self.tbl['aaa'][self.i]), self.oi), header, html)
    
    def html_table_b64(self):
        return base64.encodestring(self.html_table()).replace('\n', '')
    
    def msg(self, text):
        if self.log:
            with open(self.main.ms2log, 'a') as f:
                f.write(text)
    
    def _any_scan(self, method, **kwargs):
        for i, sc in iteritems(self._scans):
            self.msg('\t\t:: Calling method %s() on scan #%u\n' % (method, i[0]))
            if getattr(sc, method)(**kwargs):
                return True
        return False
    
    def identify(self):
        for hg in self.classes:
            self.msg('\t>>> Attempting to identify %s in all scans\n' % (hg))
            if self._any_scan('is_%s' % hg.lower()):
                self.identities.add(hg)
                self.msg('\t<<< Result: identified as %s\n' % hg)
            else:
                self.msg('\t<<< Result: not %s\n' % hg)
    
    def identify2(self, num = 1):
        
        for scanid, scan in iteritems(self._scans):
            
            for hg in self.classes2:
                
                self.msg('\t>>> Attempting to identify %s in scan %u\n' %
                         (hg, scanid[0]))
                
                identified = False
                
                if hg not in self.identities2:
                    self.identities2[hg] = []
                
                method = '%s_%s_%u' % (hg.lower(), self.mode, num)
                
                if hasattr(scan, method):
                    
                    self.identities2[hg].append(getattr(scan, method)())
                    
                    identified = any(
                        map(
                            lambda i: i['score'] >= 5,
                            self.identities2[hg]
                        )
                    )
                
                if identified:
                    self.msg('\t<<< Result: identified as %s\n' % hg)
                else:
                    self.msg('\t<<< Result: not %s\n' % hg)
            
            if hasattr(scan, 'fa_co_2'):
                del scan.fa_co_2
            
            if hasattr(scan, 'fa_list'):
                scan.fa_list = None


class MS2Scan(object):
    """
    This class represents one MS2 scan and provides methods for its analysis.
    """
    
    def __init__(self, scan, scan_id, feature):
        
        self.scan = scan
        self.scan_id = scan_id
        self.feature = feature
        self.deltart = self.feature.deltart[self.scan_id]
        self.frac_id = self.scan_id[1]
        self.frac_name = self.feature.fracsi[self.frac_id]
        
        self.ms2_file = self.feature.main.ms2files\
            [self.feature.protein][self.feature.mode][self.frac_name]
        self.in_primary = self.frac_name in \
            self.feature.main.fracs_order[self.feature.protein]['prim']
        self.in_secondary = self.frac_name in \
            self.feature.main.fracs_order[self.feature.protein]['sec']
        self.i = self.feature.i
        self.tbl = self.feature.tbl
        self.insmax = self.scan[0,2]
        self.recc = re.compile(r'.*?([0-9]{1,2}):([0-9]).*')
        self.fa = {}
        self.fa1 = {}
        self._order = None
        self.sort_by_i()
        self.fa_list = None
        self.build_fa_list()
    
    def reload(self):
        modname = self.__class__.__module__
        mod = __import__(modname, fromlist=[modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)
    
    def print_identities(self, fname = None):
        """
        Prints identities to standard output or file.
        """
        
        if fname is None:
            sys.stdout.write(self.identities_str())
        else:
            with open(fname, 'w') as fp:
                fp.write(self.identities_str())
    
    def identities_str(self, num = 1):
        """
        Returns table of all identification attempts as string.
        """
        
        result = ['=== Scan #%u (fraction %s) ===' % (
            self.scan_id[0], self.frac_name)]
        
        for hg in self.feature.classes2:
            
            method = '%s_%s_%u' % (
                hg.lower(), self.feature.mode, num
            )
            
            if not hasattr(self, method):
                continue
            
            idd = getattr(self, method)()
            
            result.append('%s\t%u\t%s' % (
                hg,
                idd['score'],
                ', '.join(idd['fattya'])
            ))
        
        return '%s\n' % '\n'.join(result)
    
    def print_scan(self):
        """
        Prints the list of fragments as an annotated table.
        """
        
        self.feature.msg(self.scan_str())
    
    def show(self):
        """
        Prints the scan table to standard output.
        """
        
        sys.stdout.write(self.scan_str())
    
    def scan_str(self):
        """
        Returns the scan table as string.
        """
        
        ms1mz = self.tbl['mz'][self.i]
        header = '\tFrag. m/z\tIntensity\tIdentity%sNL mass\n'\
            '\t%s\n' % (' ' * 26, '=' * 73)
        table = '\n\t'.join(
            map(
                lambda sc:
                    '%9.4f\t%10.2f\t%s%s%9.4f' % \
                        tuple(list(sc[[1, 2, 7]]) + \
                            [' ' * (32 - len(sc[7])), ms1mz - sc[1]]),
                self.scan
            )
        )
        
        fri = self.scan_id[1] - 9 if self.scan_id[1] != 1 else 4
        
        return (
            '\tScan %u (fraction %s%u; %s %s; '\
            'intensity = %.01f (%.02f%%)):\n\n%s\t%s\n\n' % \
            (self.scan_id[0],
             self.frac_name,
             self.frac_id,
             'contains' \
                if self.feature.ifracs[self.frac_name][1] \
                else 'does not contain',
             self.feature.protein,
             self.tbl['fe'][self.i, self.frac_id] \
                 if self.frac_id < self.tbl['fe'].shape[1] else np.nan,
             (self.tbl['fe'][self.i, self.frac_id] \
                 if self.frac_id < self.tbl['fe'].shape[1] else np.nan) / \
                 np.nanmax(self.tbl['fe'][self.i, :]) * 100.0,
             header,
             table)
        )
    
    def html_table(self):
        table = '\t\t<table id="%s" class="scantbl %s">\n%s\n\t\t</table>\n'
        th = '\t\t\t\t<th>\n\t\t\t\t\t%s\n\t\t\t\t</th>\n'
        ttl = '\t\t\t<tr class="%s">\n\t\t\t\t<th colspan="4">\n\t\t\t\t\t%s'\
            '\n\t\t\t\t</th>\n\t\t\t</tr>\n'
        tr = '\t\t\t<tr class="%s">\n%s\n\t\t\t</tr>\n'
        td = '\t\t\t\t<td>\n\t\t\t\t\t%s\n\t\t\t\t</td>\n'
        ms1mz = self.tbl['mz'][self.i]
        rows = ttl % (
            'scantitle',
            'Scan %u (%s, %s; '\
            'intensity = %.01f (%.02f%%); dRT = %.03f min)' % (
                self.scan_id[0],
                self.frac_name,
                'the highest fraction' if self.in_primary \
                    else 'not the highest, but contains %s' % \
                        self.feature.protein if self.in_secondary \
                    else 'does not contain %s' % \
                        self.feature.protein,
                self.tbl['fe'][self.i, self.frac_id] \
                    if fri < self.tbl['fe'].shape[1] else np.nan,
                (self.tbl['fe'][self.i, self.frac_id] \
                    if fri < self.tbl['fe'].shape[1] else np.nan) / \
                    np.nanmax(self.tbl['fe'][self.i, :]) * 100.0,
                self.deltart
            )
        )
        rows += tr % (
            'scanhdr',
            ''.join(
                map(
                    lambda cname:
                        th % cname,
                    ['Frag m/z', 'Intensity', 'Identity', 'NL mass']
                )
            )
        )
        for rn, row in enumerate(self.scan):
            rows += tr % (
                'fragrow %s' % ('first5' if rn < 5 else 'after5'),
                ''.join([
                    td % ('%.04f' % row[1]),
                    td % ('%.02f' % row[2]),
                    td % row[7],
                    td % ('%.04f' % (ms1mz - row[1]))
                ])
        )
        return table % ('%u_%u_%u' % (
            self.tbl['i'][self.i], self.scan_id[0], self.scan_id[1]),
            'best' if self.scan_id == self.feature.best_scan \
                else 'primary' if self.in_primary \
                else 'secondary' if self.in_secondary \
                else 'noprotein',
            rows
        )
    
    def get_by_rank(self, rank = 1, min_mz = 0.0):
        this_rank = 0
        return_next = False
        prev_mz = 0.0
        intensity = ''
        ids = []
        for r in self.scan:
            if r[1] < min_mz:
                continue
            if abs(r[1] - prev_mz) > 0.0001:
                prev_mz = r[1]
                this_rank += 1
            if this_rank == rank:
                return_next = True
                intensity = '%.04f(%u)' % (r[1], r[2])
                ids.append('%s (%.03f)' % (r[7], r[1]))
            elif this_rank != rank and return_next:
                return intensity, '; '.join(ids)
        return '', ''
    
    def full_list_str(self):
        result = []
        prev_mz = self.scan[0,1]
        intensity = self.scan[0,2]
        names = set([])
        for i, r in enumerate(self.scan):
            if abs(r[1] - prev_mz) > 0.0001:
                if len(names) == 1 and  list(names)[0] == 'unknown':
                    result.append('%s (%.03f) (%u)' % ('/'.join(sorted(list(names))), r[1], intensity))
                else:
                    result.append('%s (%u)' % ('/'.join(sorted(list(names))), intensity))
                names = set([])
                intensity = r[2]
                prev_mz = r[1]
            names.add(r[7])
        result.append('%s (%u)' % ('/'.join(sorted(list(names))), intensity))
        return '; '.join(result)
    
    def most_abundant_mz(self):
        result = self.scan[0,1]
        self.feature.msg('\t\t  -- Most abundant m/z is %.03f\n' % result)
        return result
    
    def mz_match(self, mz_detected, mz):
        return abs(mz_detected - mz) <= self.feature.main.ms2_tlr
    
    def sort_by_mz(self):
        """
        Sorts the scan array by m/z increasing.
        """
        self._order = self._order[self.scan[:,1].argsort()]
        self.scan = self.scan[self.scan[:,1].argsort(),:]
    
    def sort_by_i(self, return_order = False):
        """
        Sorts the scan array by intensity decreasing.
        """
        if self._order is None:
            order = self.scan[:,2].argsort()[::-1]
            self.scan = self.scan[order,:]
            self._order = np.array(xrange(self.scan.shape[0]), dtype = np.int)
        else:
            order = self._order.argsort()
            self.scan = self.scan[order,:]
            self._order = self._order[order]
        if return_order:
            return order
    
    def mz_lookup(self, mz):
        """
        Returns the index of the closest m/z value
        detected in the scan if it is within the
        range of tolerance, otherwise None.
        """
        du = 999.0
        dl = 999.0
        self.sort_by_mz()
        ui = self.scan[:,1].searchsorted(mz)
        if ui < self.scan.shape[0]:
            du = self.scan[ui,1] - mz
        if ui > 0:
            dl = mz - self.scan[ui - 1,1]
        i = ui if du < dl else ui - 1
        i = i if self.mz_match(self.scan[i,1], mz) else None
        sort = self.sort_by_i(return_order = True)
        if i is not None:
            i = np.where(sort == i)[0][0]
        return i
    
    def has_mz(self, mz):
        """
        Tells if an m/z exists in this scan.
        """
        
        result = self.mz_lookup(mz) is not None
        
        self.feature.msg('\t\t  -- m/z %.03f occures in this scan? -- %s\n' % \
            (mz, str(result)))
        
        return result
    
    def has_nl(self, nl):
        """
        Tells if a neutral loss exists in this scan.
        """
        
        result = self.has_mz(self.ms1_mz() - nl)
        
        self.feature.msg('\t\t  -- neutral loss of %.03f occures in '\
            'this scan? Looked up m/z %.03f - %.03f = %.03f -- %s\n' % \
            (nl, self.feature.tbl['mz'][self.feature.i], nl,
             self.feature.tbl['mz'][self.feature.i] - nl, str(result)))
        
        return result
    
    def ms1_mz(self):
        """
        Returns the MS1 m/z (which should be the precursor ion).
        """
        
        return self.feature.tbl['mz'][self.feature.i]
    
    def nl_lookup(self, nl):
        """
        Looks up if a neutral loss exists in this scan and returns its index.
        """
        
        return self.mz_lookup(self.feature.tbl['mz'][self.feature.i] - nl)
    
    def most_abundant_mz_is(self, mz):
        """
        Tells if the m/z with the highest intensity is `mz`.
        """
        
        result = self.mz_match(self.most_abundant_mz(), mz)
        self.feature.msg('\t\t  -- m/z %.03f is the most abundant? -- %s\n' % \
            (mz, str(result)))
        return result
    
    def mz_among_most_abundant(self, mz, n = 2):
        """
        Tells if an m/z is among the most aboundant `n` fragments
        in a spectrum.
        
        :param float mz: The m/z value.
        :param int n: The number of most abundant fragments considered.
        
        """
        
        result = False
        
        for i in xrange(min(n, self.scan.shape[0])):
            
            if self.mz_match(self.scan[i,1], mz):
                
                result = True
                break
        
        self.feature.msg('\t\t  -- m/z %.03f is among the %u most abundant? -- '\
            '%s\n' % (mz, n, str(result)))
        
        return result
    
    def nl_among_most_abundant(self, nl, n = 2):
        """
        Tells if a neutral loss corresponds to one of the
        most aboundant `n` fragments in a spectrum.
        
        :param float nl: The mass of the neutral loss.
        :param int n: The number of most abundant fragments considered.
        
        """
        
        result = False
        
        for i in xrange(min(n, self.scan.shape[0])):
            
            if self.mz_match(self.scan[i,1], self.ms1_mz() - nl):
                
                result = True
                break
        
        self.feature.msg('\t\t  -- neutral loss %.03f is among '\
            'the %u most abundant? -- '\
            '%s\n' % (nl, n, str(result)))
        
        return result
    
    def get_intensity(self, mz):
        """
        Returns the intensity of a fragment ion from its m/z.
        Value is `None` if m/z does not present.
        """
        
        i = self.mz_lookup(mz)
        
        if i is not None:
            
            return self.intensities[i,2]
        
        return None
    
    def get_nl_intensity(self, nl):
        """
        Returns the intensity of a fragment ion from its a neutral loss.
        Value is `None` if neutral loss does not present.
        """
        
        return self.get_intensity(self.ms1_mz() - nl)
    
    def mz_percent_of_most_abundant(self, mz, percent = 80.0):
        """
        Tells if an m/z has at least certain percent of intensity
        compared to the most intensive fragment.
        
        :param float mz: The m/z value.
        :param float percent: The threshold in percent
                              of the highest intensity.
        
        """
        
        insmax = self.scan[0,2]
        result = False
        
        for frag in self.scan:
            
            if self.mz_match(frag[1], mz):
                
                result = True
                break
            
            if frag[2] < insmax * 100.0 / percent:
                result = False
                break
        
        self.feature.msg('\t\t  -- m/z %.03f has abundance at least %.01f %% of'\
            ' the highest abundance? -- %s\n' % \
            (mz, percent, str(result)))
        
        return result
    
    def fa_type_is(self, i, fa_type, sphingo = False, uns = None,
                   scan_index = True):
        """
        Tells if a fatty acid fragment is a specified type. The type
        should be a part of the string representation of the fragment,
        e.g. `-O]` for fragments with one oxygen loss.
        """
        
        ifa = None
        
        if not scan_index:
            ifa = i
            i   = self.fa_list[ifa][5]
        
        result = (
            (fa_type in self.scan[i,8] or fa_type in self.scan[i,7]) and
            (not sphingo or 'Sphingosine' in self.scan[i,7]) and
            (uns is None or ifa is None or self.fa_list[ifa][0][1] <= uns)
        )
        
        self.feature.msg('\t\t  -- Fragment #%u (%s, %s): fatty acid type '\
            'is %s?  -- %s\n' % \
                (i, self.scan[i,7], self.scan[i,8], fa_type, str(result)))
        
        return result
    
    def is_fa(self, i, sphingo = False):
        """
        Examines whether a fragment is fatty acid-like or not.
        In the labels of fatty acid fragments we always 
        """
        
        result = 'FA' in self.scan[i,7] or 'Lyso' in self.scan[i,7] or \
            (sphingo and 'Sphi' in self.scan[i,7])
        
        self.feature.msg('\t\t  -- Fragment #%u (%s): is fatty acid? '\
            '-- %s\n' % (i, self.scan[i,7], str(result)))
        
        return result
    
    def most_abundant_fa(self, fa_type, head = 1, sphingo = False):
        """
        Returns `True` if there is a fatty acid among the most abundant
        fragments and it is of the defined type; `False` if there is no
        fatty acid, or it is different type.
        
        :param str fa_type: The type of the fatty acid fragment ion.
        :param int head: The number of most abundant fragments considered.
        :param bool sphingo: Look for a sphingolipid backbone.
        """
        
        result = False
        
        for i in xrange(self.scan.shape[0]):
            
            if i == head:
                
                break
            
            if self.is_fa(i, sphingo = sphingo):
                
                result = self.fa_type_is(i, fa_type, sphingo = sphingo)
        
        self.feature.msg('\t\t  -- Having fatty acid %s among %u most abundant '\
            'features? -- %s\n' % (fa_type, head, str(result)))
        
        return result
    
    def get_most_abundant_fa(self, fa_type = None, head = 1, sphingo = False):
        """
        Looks up the most abundant fatty acid fragment of the given type.
        Returns tuple with mz, intensity, carbon count and unsaturation, index.
        """
        
        self.build_fa_list()
        
        for fa_frag in self.fa_list[:head]:
            
            if (
                fa_type is None  or
                self.fa_type_is(fa_frag[5], fa_type, sphingo)
            ):
                
                return self.scan[fa_frag[5],1], fa_frag[4], fa_frag[0], fa_frag[5]
        
        return None, None, None, None
    
    def fa_cc_among_most_abundant(self, cc, hg, n = 2, sphingo = False):
        """
        Returns `True` if there is one  fatty acid with the defined
        carbon count and unsaturation and compatible with the given
        headgroup among the most abundant `n` fragments.
        """
        
        self.build_fa_list()
        
        for fa_frag in self.fa_list:
            
            if fa_frag[5] >= n:
                
                break
            
            if (
                fa_frag[0] == cc and
                (fa_frag[1] is None or hg in fa_frag[1]) and
                (sphingo or fa_frag[3])
            ):
                
                return True
        
        return False
    
    def fa_among_most_abundant(self, fa_type, n = 2,
                               min_mass = None, sphingo = False,
                               uns = None):
        """
        Returns `True` if there is one of the defined type of fatty acid
        fragments among the given number of most abundant fragments, and
        it has a mass greater than the given threhold.
        """
        
        self.build_fa_list()
        result = False
        
        for i, fa in enumerate(self.fa_list):
            
            if not sphingo or fa[3] and (
                    min_mass is None or
                    self.scan[fa[5],1] >= min_mass
                ):
                
                if min_mass is not None:
                    
                    self.feature.msg('\t\t\t-- Fragment #%u having mass larger '\
                        'than %.01f\n' % (i, min_mass))
                
                if self.fa_type_is(i, fa_type, sphingo = sphingo,
                                   uns = uns, scan_index = False):
                    result = True
            
            if i == n:
                break
            
            elif min_mass is not None:
                self.feature.msg('\t\t\t-- Fragment #%u having mass lower '\
                        'than %.01f\n' % (i, min_mass))
        
        self.feature.msg('\t\t  -- Having fatty acid fragment %s among %u most '\
            'abundant -- %s\n' % (fa_type, n, str(result)))
        
        return result
    
    def fa_percent_of_most_abundant(self, fa_type, percent = 80.0, sphingo = False):
        for i in xrange(self.scan.shape[0]):
            if self.is_fa(i, sphingo = sphingo):
                if self.fa_type_is(i, fa_type, sphingo = sphingo):
                    return True
            if self.scan[i,2] < self.insmax * 100.0 / percent:
                return False
        return False
    
    def mz_most_abundant_fold(self, mz, fold):
        """
        Tells if an m/z is the most abundant fragment
        and it has at least a certain
        fold higher intensity than any other fragment.
        
        :param float mz: The m/z value.
        :param float fold: The m/z must be this times higher than any other.
        """
        
        result = False
        if self.most_abundant_mz_is(mz):
            result = self.scan.shape[0] == 1 or \
                self.scan[1,2] * fold <= self.scan[0,2]
        self.feature.msg('\t\t  -- m/z %.03f is at least %u times higher than '\
            'any other? -- %s\n' % (mz, fold, str(result)))
        return result
    
    def sum_cc_is(self, cc1, cc2, cc):
        """
        Returns `True` if the sum of the 2 carbon counts and
        unsaturations is equal with the third one.
        
        :param tuple cc1: Carbon count and unsaturation 1.
        :param tuple cc2: Carbon count and unsaturation 2.
        :param str cc: Expected total carbon count and unsaturation.
        """
        
        return self.cc2str(self.sum_cc([cc1, cc2])) == cc
    
    def cer_fa_test(self, frag1, frag2):
        return \
            self.fa_type_is(frag1[5], 'CerFA(') and \
            self.fa_type_is(frag2[5], 'CerSphi-N(') and \
            frag1[4] > frag2[4] * 2
    
    def fa_combinations3(self, hg, head = None, expected_intensities = None):
        """
        Finds all combinations of 3 fatty acids which match the
        total carbon count and unsaturation resulted by database
        lookups of the MS1 precursor mass.
        This can be used for example at TAG.
        
        :param str hg: The short name of the headgroup, e.g. `TAG`.
        :param int head: If `None` or `numpy.inf` all fragment ions
                         will be considered, otherwise only the first
                         most aboundant until the number `head`.
        """
        
        result = set([])
        
        if hg in self.feature.ms1fa and len(self.feature.ms1fa[hg]):
            ccs = list(self.feature.ms1fa[hg])
        else:
            return result
        
        head = np.inf if head is None else head
        
        for cc in ccs:
            
            try:
                icc = self.cc2int(cc)
            except AttributeError:
                continue
            
            for frag0 in self.fa_list:
                
                if frag0[5] >= head:
                    break
                
                cc0 = frag0[0]
                
                cc12e = '%u:%u' % tuple(map(lambda x: x[0] - x[1],
                                            zip(*[icc, cc0])))
                
                cc12s = self.fa_combinations_tuples(cc12e, head = head, by_cc = True)
                
                for cc12 in cc12s:
                    
                    cc012 = '/'.join(sorted(list(cc12[0]) + [self.cc2str(cc0)]))
                    
                    if self.sum_cc_str(cc012) == icc:
                    
                        if self.intensity_ratios([
                            (cc12[1][0], cc12[2][0]),
                            (cc12[1][1], cc12[2][1]),
                            (frag0[4], frag0[5])],
                            expected = expected_intensities
                        ):
                            
                            result.add(cc012)
        
        return result
    
    def intensity_ratios(self, intensities, expected = None, logbase = 1.5):
        """
        Tells if the ratio of a list of intensities fits
        the one in `expected` or is even if `expected` is `None`.
        
        :param list intensities: List of tuples, first element is the
                                 intensity, the second is an uniqe
                                 identifier of the fragments.
        :param list expected: List with expected intensity proportions.
                              E.g. `[1, 1, 2]` means the third ion is
                              twice higher intense than the 2 others.
        :param int logbase: The fold difference tolerance when comparing
                            intensities. E.g. if this is 2, then an almost
                            twice less or more intense ion will considered
                            to have similar intensity.
        
        """
        
        if len(intensities) == 1:
            
            return True
        
        i = intensities
        
        if any(map(lambda ii: ii[0] <= 0.0, i)):
            
            return False
        
        # to know if one fragment contributes more than one times;
        # intensities divided by the times the fragment is incident
        cntr = collections.Counter(map(lambda ii: ii[1], i))
        
        # by default expecting more or less equal intensities
        if expected is None:
            
            expected = [1.0] * len(i)
        
        i = list(
            map(
                lambda ii:
                    (ii[1][0] / (expected[ii[0]] * cntr[ii[1][1]]), ii[1][1]),
                enumerate(i)
            )
        )
        
        return (
            all(
                map(
                    lambda co:
                        (
                            (math.log(co[0][0], logbase) -
                            math.log(co[1][0], logbase)) <= 1
                        ),
                    itertools.combinations(i, 2)
                )
            )
        )
    
    def fa_combinations_old(self, hg, sphingo = False,
                            head = None, by_cc = False):
        """
        Finds all combinations of 2 fatty acids which match the
        total carbon count and unsaturation resulted by database
        lookups of the MS1 precursor mass.
        Alternatively a carbon count and unsaturation can be provided
        if `by_cc` is set to `True`.
        
        :param str hg: Short name of the headgroup, e.g. `PC`; or cc:unsat e.g.
                       `32:1` if `by_cc` is `True`.
        :param bool sphingo: Assume sphingolipid.
        :param int head: If `None` the total fragment list used, if a number,
                         only the most intensive fragments accordingly.
        :param bool by_cc: Use the MS1 database identification to find out
                           the possible carbon counts and unsaturations for
                           the given headgroup, or a cc:uns provided and
                           search combinations accordingly.
        
        """
        
        result = set([])
        if hg in self.feature.ms1fa and len(self.feature.ms1fa[hg]):
            ccs = list(self.feature.ms1fa[hg])
        elif by_cc:
            ccs = [hg]
        else:
            return result
        
        head = np.inf if head is None else head
        
        self.build_fa_list()
        
        for cc in ccs:
            
            for frag1 in self.fa_list:
                
                for frag2 in self.fa_list:
                    
                    result.update(
                        self.get_fa_combinations(frag1, frag2, hg,
                                                cc, sphingo, head)
                    )
        
        return result
    
    def fa_combinations_preprocess(self, regenerate = False):
        """
        Generates a lookup table for all possible combinations of two
        fatty acids.
        """
        
        if not hasattr(self, 'fa_co_2') or regenerate:
            
            self.fa_co_2 = {}
            l = self.fa_list
            
            for i, j in itertools.combinations_with_replacement(
                xrange(len(self.fa_list)), 2):
                
                key = self.sum_cc([(l[i][0][0], l[i][0][1]),
                                   (l[j][0][0], l[j][0][1])])
                
                if key not in self.fa_co_2:
                    self.fa_co_2[key] = set([])
                
                self.fa_co_2[key].add((i, j))
    
    def fa_combinations(self, hg, sphingo = False,
                               head = None, by_cc = False):
        """
        Finds all combinations of 2 fatty acids which match the
        total carbon count and unsaturation resulted by database
        lookups of the MS1 precursor mass.
        Alternatively a carbon count and unsaturation can be provided
        if `by_cc` is set to `True`.
        
        This method does the same as `fa_combinations` but works with
        a preprocessed lookup table.
        
        Returns set of strings.
        
        :param str hg: Short name of the headgroup, e.g. `PC`; or cc:unsat e.g.
                       `32:1` if `by_cc` is `True`.
        :param bool sphingo: Assume sphingolipid.
        :param int head: If `None` the total fragment list used, if a number,
                         only the most intensive fragments accordingly.
        :param bool by_cc: Use the MS1 database identification to find out
                           the possible carbon counts and unsaturations for
                           the given headgroup, or a cc:uns provided and
                           search combinations accordingly.
        
        """
        
        return set(map(lambda co: '%s/%s' % co[0],
                       self.fa_combinations_tuples(hg, sphingo, head, by_cc)))
    
    
    def fa_combinations_tuples(self, hg, sphingo = False,
                               head = None, by_cc = False):
        """
        Finds all combinations of 2 fatty acids which match the
        total carbon count and unsaturation resulted by database
        lookups of the MS1 precursor mass.
        Alternatively a carbon count and unsaturation can be provided
        if `by_cc` is set to `True`.
        
        Returns tuples of tuples with carbon count/unsaturation,
        intensities and indices.
        
        :param str hg: Short name of the headgroup, e.g. `PC`; or cc:unsat e.g.
                       `32:1` if `by_cc` is `True`.
        :param bool sphingo: Assume sphingolipid.
        :param int head: If `None` the total fragment list used, if a number,
                         only the most intensive fragments accordingly.
        :param bool by_cc: Use the MS1 database identification to find out
                           the possible carbon counts and unsaturations for
                           the given headgroup, or a cc:uns provided and
                           search combinations accordingly.
        
        """
        
        result = []
        if hg in self.feature.ms1fa and len(self.feature.ms1fa[hg]):
            ccs = list(self.feature.ms1fa[hg])
        elif by_cc:
            ccs = [hg]
        else:
            return result
        
        head = np.inf if head is None else head
        
        self.build_fa_list()
        self.fa_combinations_preprocess()
        
        for cc in ccs:
            
            icc = self.cc2int(cc)
            
            if icc in self.fa_co_2:
                
                for i, j in self.fa_co_2[icc]:
                    
                    frag1 = self.fa_list[i]
                    frag2 = self.fa_list[j]
                    
                    result.extend(
                        self.get_fa_combinations(frag1, frag2, hg,
                                                 cc, sphingo, head)
                    )
        
        return result
    
    def get_fa_combinations(self, frag1, frag2, hg, cc, sphingo, head):
        """
        Processes two fatty acid fragments to decide
        if their combination is valid.
        """
        
        result = []
        
        if frag1[5] >= head or frag2[5] >= head:
            return result
        
        if hg == 'Cer' and not self.cer_fa_test(frag1, frag2):
            # where not the 'CerFA' is the most intensive
            # those are clearly false
            return result
        
        if frag1[0][0] is not None and frag2[0][0] is not None and \
            (frag1[1] is None or hg in frag1[1]) and \
            (frag2[1] is None or hg in frag2[1]) and \
            (not sphingo or frag1[3] or frag2[3]):
            if self.sum_cc_is(frag1[0], frag2[0], cc):
                ether_1 = 'O-' if frag1[2] else ''
                ether_2 = 'O-' if frag2[2] else ''
                fa_1 = '%s%u:%u' % (ether_1, frag1[0][0], frag1[0][1])
                fa_2 = '%s%u:%u' % (ether_2, frag2[0][0], frag2[0][1])
                if frag1[3]:
                    fa_1 = 'd%s' % fa_1
                elif frag2[3]:
                    sph = 'd%s' % fa_2
                    fa_2 = fa_1
                    fa_1 = sph
                if not frag1[3] and not frag2[3]:
                    fa = tuple(sorted([fa_1, fa_2]))
                else:
                    fa = (fa_1, fa_2)
                
                result.append((
                    fa,
                    (frag1[4], frag2[4]),
                    (frag1[5], frag2[5])
                ))
        
        return result
    
    def matching_fa_frags_of_type(self, hg, typ, sphingo = False,
        return_details = False):
        """
        Returns carbon counts of those fragments which are of the given type
        and have complement fatty acid fragment of any type.
        
        Details is a dict with carbon counts as keys
        and fragment names as values.
        """
        result = set([])
        details = {}
        
        if hg in self.feature.ms1fa and len(self.feature.ms1fa[hg]):
            
            for cc in self.feature.ms1fa[hg]:
                
                self.build_fa_list()
                
                for frag1 in self.fa_list:
                    
                    for frag2 in self.fa_list:
                        
                        if frag1[0][0] is not None and \
                            frag2[0][0] is not None and \
                            (frag1[1] is None or hg in frag1[1]) and \
                            (frag2[1] is None or hg in frag2[1]) and \
                            (not sphingo or frag1[3]):
                            
                            if self.fa_type_is(frag1[5], typ) and \
                                self.sum_cc_is(frag1[0], frag2[0], cc):
                                
                                result.add(frag1[0])
                                
                                if return_details:
                                    
                                    if frag1[0] not in details:
                                        
                                        details[frag1[0]] = set([])
                                    
                                    details[frag1[0]].add(self.scan[frag2[5],7])
        
        if return_details:
            return (result, details)
        else:
            return result
    
    def cer_missing_fa(self, cer_hg):
        """
        Infers the fatty acid carbon count and unsaturation
        by subtracting the sphingoid backbone from the total.
        This works with Cer, CerP and HexCer.
        """
        
        result = set([])
        
        cer_ccs = set([])
        
        for frag in self.scan[:5]:
            
            if 'phingo' in frag[7]:
                
                cer_ccs.add(self.get_cc(frag[7]))
        
        if cer_hg in self.feature.ms1fa:
            
            for cc in self.feature.ms1fa[cer_hg]:
                
                cc = self.get_cc(cc)
                
                for cer_cc in cer_ccs:
                    
                    carb = cc[0] - cer_cc[0]
                    unsat = cc[1] - cer_cc[1]
                    
                    result.add('d%u:%u/%u:%u' % (
                        cer_cc[0], cer_cc[1], carb, unsat))
        
        return result
    
    def cer_matching_fa(self, cer_fa):
        score = 0
        if 'Cer' in self.feature.ms1fa:
            cer_cc = self.get_cc(cer_fa)
            for cc in self.feature.ms1fa['Cer']:
                cc = self.get_cc(cc)
                carb = cc[0] - cer_cc[0]
                unsat = cc[1] - cer_cc[1] + 2
                if self.frag_name_present(
                    '[FA-alkyl(C%u:%u)-H]-' % (carb, unsat)):
                    score += 1
                carb = cc[0] - cer_cc[0] - 2
                unsat = cc[1] - cer_cc[1] + 1
                if self.frag_name_present(
                    '[FA-alkyl(C%u:%u)-H]-' % (carb, unsat)):
                    score += 1
        return score
    
    def build_fa_list(self, rebuild = False):
        """
        Returns list with elements:
            carbon count, headgroups (set or None),
            esther (False) or ether (True),
            sphingosine (True) or fatty acid (False),
            fragment intensity and row index
        """
        if self.fa_list is None or rebuild:
            self.fa_list = []
            for i, frag in enumerate(self.scan):
                if frag[7] != 'unknown' and self.is_fa(i, sphingo = True):
                    cc = self.get_cc(frag[7])
                    hgs = self.get_hg(frag[7])
                    is_ether = 'alk' in frag[7]
                    is_sphingo = 'Sphi' in frag[7]
                    self.fa_list.append([cc, hgs, is_ether, is_sphingo, frag[2], i])
    
    def get_hg(self, frag_name):
        hgfrags = self.feature.main.nHgfrags \
            if self.feature.mode == 'neg' \
            else self.feature.main.pHgfrags
        return hgfrags[frag_name] \
            if frag_name in hgfrags and \
                len(hgfrags[frag_name]) \
            else None
    
    def get_cc(self, fa):
        """
        Extracts carbon count from any string, for example fatty acid names.
        Recognizes the pattern [number:number].
        E.g. from `Phosphatidylcholine (36:1)` returns the tuple `(36, 1)`.
        To convert pure cc:uns strings, use the method `cc2int` instead,
        as that one is faster.
        
        :param str fa: Any string containing carbon count and unsaturation.
        
        """
        
        m = self.recc.match(fa)
        
        if m is not None:
            return tuple(map(int, m.groups()))
        
        return (None, None)
    
    def most_abundant_fa_cc(self, fa_type = None, head = 2):
        fa_cc = []
        for i, frag in enumerate(self.scan):
            if i == head:
                break
            if self.is_fa(i) and (
                    fa_type is None or
                    self.fa_type_is(i, fa_type)
                ):
                
                cc = self.get_cc(frag[7])
                if cc[0] is not None:
                    fa_cc.append((cc, frag[2]))
        
        return fa_cc
    
    def cc2str(self, cc):
        """
        Converts carbon count and unsaturation from tuple of integers
        to string. E.g. `(18, 1)` results `18:1`.
        
        :param tuple cc: Tuple of 2 integers representing carbon count
                         and unsaturation.
        """
        
        return '%u:%u' % cc
    
    def ccs2str(self, ccs):
        """
        Converts multiple carbon counts and unsaturations from tuples
        of integers format to string. E.g. `[(18, 1), (18, 0)]` results
        `18:1/18:0`.
        
        :param list ccs: List of tuples of integers.
        """
        
        return '/'.join(map(self.cc2str, sorted(ccs)))
    
    def cc2int(self, cc):
        """
        Converts carbon count and unsaturation from string format to
        tuple of integers. E.g. `18:1` results `(18, 1)`.
        
        :param str cc: String representing carbon count and unsaturation
                       separated by colon.
        """
        
        return tuple(map(int, cc.split(':')))
    
    def ccs2int(self, ccs):
        """
        Converts a string of multiple carbon counts and unsaturations
        to a list of tuples of integers.
        
        :param str ccs: Multiple carbon counts and unsaturations in string
                        representation, e.g. `18:1/16:0`.
        
        """
        
        return list(map(self.cc2int, ccs.split('/')))
    
    def sum_cc_str(self, ccs):
        """
        Returns the sum of multiple carbon counts and unsaturations.
        Accepts string format and results string format.
        
        :param str ccs: Multiple carbon counts and unsaturations in string
                        representation, e.g. `18:1/16:0`.
        """
        
        return self.sum_cc(self.ccs2int(ccs))
    
    def sum_cc(self, ccs):
        """
        Adds numeric carbon counts and unsaturations.
        Accepts a list of tuples of integers, returns
        a tuple of integers.
        
        :param list ccs: A list with tuples of integers,
                         e.g. `[(14, 1), (16, 0)]`.
        """
        
        return (
            tuple(
                reduce(
                    lambda cu1, cu2:
                        # here `cu`: carbon count and unsaturation
                        (cu1[0] + cu2[0], cu1[1] + cu2[1]),
                    ccs
                )
            )
        )
    
    def sum_cc2(self, ccs):
        """
        Returns the total carbon count and unsaturation in tuple
        format from a list of tuples where the first element of
        the tuple is another tuple with the cc and uns, and the
        second is the intensity, which is discarded here.
        
        :param list ccs: List of the format described above. E.g.
                         `[((16, 0), 1000.0), ((18, 1), 722)]`, this
                         results `(34, 1)`.
        """
        
        return self.sum_cc(map(lambda cci: cci[0], ccs))
    
    def sum_cc2str(self, ccs):
        """
        Returns the total carbon count and unsaturation in string
        format from a list of tuples where the first element of
        the tuple is another tuple with the cc and uns, and the
        second is the intensity, which is discarded here.
        
        :param list ccs: List of the format described above. E.g.
                         `[((16, 0), 1000.0), ((18, 1), 722)]`, this
                         results `34:1`.
        """
        
        return self.cc2str(self.sum_cc2(ccs))
    
    def add_fa1(self, fa, hg):
        if hg not in self.fa1:
            self.fa1[hg] = set([])
            self.fa1[hg].add(
                tuple(
                    map(
                        lambda fai:
                            fai[0],
                        fa
                    )
                )
            )
            fastr = ', '.join(
                    map(
                        lambda fai:
                            self.cc2str(fai[0]),
                        fa
                    )
                )
            self.feature.msg('\t\t  -- Adding fatty acids %s at headgroup '\
                '%s\n' % (fastr, hg))
    
    def fa_ccs_agree_ms1(self, hg, fa_type = None, head = 2):
        fa_cc = self.most_abundant_fa_cc(fa_type = fa_type, head = head)
        if len(fa_cc) > 0:
            cc = self.sum_cc2str([fa_cc[0]] * 2)
            agr = self.fa_cc_agrees_ms1(cc, hg)
            if agr:
                self.add_fa1(fa_cc[:1], hg)
            if len(fa_cc) > 1:
                cc = self.sum_cc2str(fa_cc[:2])
                agr = self.fa_cc_agrees_ms1(cc, hg)
                if agr:
                    self.add_fa1(fa_cc[:2], hg)
        return hg in self.fa
    
    def fa_cc_agrees_ms1(self, cc, hg):
        result = False
        if hg in self.feature.ms1fa and cc in self.feature.ms1fa[hg]:
            if hg not in self.feature.fa:
                self.feature.fa[hg] = set([])
            if hg not in self.fa:
                self.fa[hg] = set([])
            self.feature.fa[hg].add(cc)
            self.fa[hg].add(cc)
            result = True
        self.feature.msg('\t\t  -- Carbon count from MS2: %s; from databases '\
            'lookup: %s -- Any of these matches: %s\n' % \
                (
                    cc,
                    str(self.feature.ms1fa[hg]) \
                        if hg in self.feature.ms1fa else '-',
                    str(result))
                )
        return result
    
    def frag_name_present(self, name):
        
        return name in self.scan[:,7]
    
    #### New methods
    
    def cer1p_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Ceramide-1-phosphate.

        **Specimen:**
        
        - GLTPD1 - 616.47
      
        **Principle:**
        
        - The most abundant fragment is 78.9591 metaphosphate.
      - If 96.9696 phosphate present adds to the score.
        
        """
        
        score = 0
        fattya = set([])
        if self.most_abundant_mz_is(78.95905658):
            score += 5
            if self.has_mz(96.96962158):
                score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def hexcer_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Hexosyl-Ceramide.

        **Specimen:**
        
        - GLTP - 744.5627
      
        **Principle:**
        
        - Hexose fragments 71.0115, 89.0220 and 101.0219 must present.
      
        """
        
        score = 0
        fattya = set([])
        
        if all(map(lambda mz: self.mz_among_most_abundant(mz, n = 10),
                   # these are 3 fragments found at GLTP
                   [71.0115000, 89.0220000, 101.021900])):
            
            score += 5
        
        return {'score': score, 'fattya': fattya}
    
    def hexceroh_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Hexosyl-Ceramide-OH
        ('t'). This method is the same as `hexcer_neg_1`.

        **Specimen:**
        
        - GLTP - 760.557
      
        **Principle:**
        
        - Hexose fragments 71.0115, 89.0220 and 101.0219 must present.
      
        """
        
        return self.hexcer_neg_1()
    
    def hexcer_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Hexosyl-Ceramide.

        **Specimen:**
        
        - GLTP + 810.68
      
        **Principle:**
        
        - Hexose fragments 198.0740, 180.0634 and 162.0528 must present.
      
        """
        
        score = 0
        fattya = set([])
        
        hexfrags = sum(map(lambda nl: self.nl_among_most_abundant(nl, n = 15),
                           [198.073955, 180.06339, 162.052825]))
        
        if hexfrags:
            score += hexfrags + 4
        
        if score:
            
            fattya.update(self.cer_missing_fa('HexCer'))
        
        return {'score': score, 'fattya': fattya}
    
    def hexceroh_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Hexosyl-Ceramide-OH
        (`t`). This method is the same as `hexcer_pos_1`.

        **Specimen:**
        
        - GLTP + 826.67
      
        **Principle:**
        
        - Hexose fragments 198.0740, 180.0634 and 162.0528 must present.
      
        """
        
        return self.hexcer_pos_1()
    
    def cer1p_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Ceramide-1-phosphate.

        **Specimen:**
        
        - GLTPD1 + 728.59
      
        **Principle:**
        
        - A shpingosine backbone with 2 H2O loss must be among the 3 highest
        intensity fragments.
        - Presence of any of the following fragments increases the score:
        82.0651, 107.0729, 135.1043, 149.1199.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.fa_among_most_abundant('-H2O-H2O+]+', n = 3, sphingo = True):
            score += 4
            
            if any(map(self.has_mz,
                       # these present at Cer too
                       # a specific difference needed!
                       [82.0651257, 107.072951, 135.104251, 149.119901])):
                score += 1
            
            fattya.update(self.cer_missing_fa('Cer1P'))
        
        return {'score': score, 'fattya': fattya}
    
    def dag_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a DAG.

        **Specimen:**
        
        - SEC14L2 + 584.52
      - in vitro: BNIP2 + 770.67
        
        **Principle:**
        
        - Combination of fatty acid fragments among the 10 most abundant
        fragments must match the expected carbon count and unsaturation.
        - If these are among the 5 highest fragments the score is higher.
      
        """
        
        score = 0
        fattya = set([])
        
        if(self.fa_combinations('DAG', head = 10)):
            score += 4
            
            if(self.fa_combinations('DAG', head = 6)):
                
                score += 2
            
            fattya.update(self.fa_combinations('DAG'))
        
        return {'score': score, 'fattya': fattya}
    
    def dag_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a DAG.

        **Specimen:**
        
        - We don't have yet.
      
        **Principle:**
        
        - Combination of fatty acid fragments among the 10 most abundant
        fragments must match the expected carbon count and unsaturation.
        - If these are among the 5 highest fragments the score is higher.
      
        """
        
        score = 0
        fattya = set([])
        
        if(self.fa_combinations('DAG', head = 10)):
            score += 4
            
            if(self.fa_combinations('DAG', head = 6)):
                
                score += 2
            
            fattya.update(self.fa_combinations('DAG'))
        
        return {'score': score, 'fattya': fattya}
    
    def tag_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a TAG.

        **Specimen:**
        
        - We don't have yet.
      
        **Principle:**
        
        - Combination of fatty acid fragments must match the
        expected carbon count and unsaturation.
        
        """
        
        score = 0
        fattya = set([])
        
        fattya.update(self.fa_combinations3('TAG'))
        
        if fattya:
            score += 5
        
        return {'score': score, 'fattya': fattya}
    
    def tag_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a TAG.

        **Specimen:**
        
        - STARD11 + 818.7187
      
        **Principle:**
        
        - Combination of fatty acid fragments must match the expected
        carbon count and unsaturation.
        
        """
        
        score = 0
        fattya = set([])
        
        fattya.update(self.fa_combinations3('TAG'))
        
        if fattya:
            score += 5
        
        return {'score': score, 'fattya': fattya}
    
    def pi_pos_1(self):
        """
        Examines if a negative MS2 spectrum is Phosphatidylinositol.

        **Specimen:**
        
        - SEC14L2 + 906.60 and 882.6
      
        **Principle:**
        
        - Combinations of fatty acid fragments must match the expected
        carbon count and unsaturation for PI.
        - Presence of neutral losses 259.0219 and 277.0563 adds to the score.
      
        """
        
        score = 0
        fattya = set([])
        
        fattya.update(self.fa_combinations('PI'))
        if fattya:
            score += 1
            if self.has_nl(259.021894):
                score += 4
            if self.has_nl(277.056272):
                score += 4
        
        return {'score': score, 'fattya': fattya}
    
    def ps_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Phosphatidylserine.

        **Specimen:**
        
        - BPI + 790.56
      
        **Principle:**
        
        - PS headgroup neutral loss 185.0089 must be the highest intensity.
      
        """
        
        score = 0
        fattya = set([])
        
        if self.nl_among_most_abundant(185.008927, 1):
            
            score += 5
            
            fattya.update(self.fa_combinations('PS'))
        
        return {'score': score, 'fattya': fattya}
    
    def bmp_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum
        is a Bismonoacylglycerophosphate.

        **Specimen:**
        
        - BPIFB2 + 792.57
      
        **Principle:**
        
        - A glycerol+fatty acid fragment can be found among the 3 highest?
      - The PG headgroup neutral loss (189.0402) is among the fragments?
        - If so, does it have a lower intensity than half of the fatty
        acid+glycerol fragment?
        
        """
        
        score = 0
        fattya = set([])
        
        if self.fa_among_most_abundant('+G(', 3):
            fattya.update(self.fa_combinations('BMP'))
            if fattya:
                score += 4
            
            hg_int = self.get_nl_intensity(189.0402)
            
            if hg_int:
                
                gfa_highest = self.get_most_abundant_fa('+G(', head = 4)
                
                if gfa_highest[1] < hg_int * 2:
                    
                    score = 0
                    fattya = set([])
        
        return {'score': score, 'fattya': fattya}
    
    def pg_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum
        is a Phosphatidylglycerol.
        At in vivo observed only in standard.
        
        **Principle:**
        
        - The PG headgroup neutral loss (189.0402) is the fragment ion
        with the highest intensity?
        
        """
        
        score = 0
        fattya = set([])
        
        if self.nl_among_most_abundant(189.0402, 1):
            
            score += 5
            
            fattya.update(self.fa_combinations('PG'))
            if fattya:
                score += 4
        
        return {'score': score, 'fattya': fattya}
    
    def va_pos_1(self):
        """
        Examines if a positive MS2 spectrum is vitamin A (retinol).

        **Specimen:**
        
        - RBP1 + 269.2245
      - RBP4 + 269.2245
        
        **Principle:**
        
        - The most abundant ion is the whole molecule m/z = 269.224.
      - Presence off 3 other ions adds to the score but not
          mandatory: 213.165, 145.1027, 157.1028.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.mz_among_most_abundant(269.224, 3):
            score += 5
            score += sum(map(self.has_mz, [213.165, 145.1027, 157.1028]))
        
        return {'score': score, 'fattya': fattya}
    
    def bmp_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is Phosphatidylglycerol.
        The result will be the same as `bmp_neg_1`, as in negative
        mode we do not know a way to distinguish these species.
        

        **Specimen:**
        
        - GM2A - 799.54
      - BPIFB2 - 773.5258 (might be BMP)
        
        **Principle:**
        
        - The most abundant fragment is a fatty acid [M-H]- ion.
      - The 152.9958 glycerophosphate fragment must be present.
        - If Lyso-PG fragment present with carbon count complementing
        the [M-H]- fatty acid score is higher.
        - Presence of 171.0064 headgroup fragment adds to the score.
      
        """
        
        return self.pg_neg_1()
    
    #### End: new methods
    
    def pe_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is Phosphatidylethanolamine.

        **Specimen:**
        
        - GM2A - 714.507
      
        **Principle:**
        
        - The most abundant fragment is a fatty acid [M-H]- ion.
      - 140.0118 PE headgroup must be present.
        - Other headgroup ions 196.0380 and 178.0275 add to the score.
      - Lyso-PE and [M-H-CO2]- fatty acid fragments complementing the
          highest [M-H]- fatty acid increase the score.
        
        """
        
        score = 0
        fattya = set([])
        
        if (
            self.is_fa(0) and
            self.fa_type_is(0, '-H]-') and
            self.has_mz(140.0118206) and
            not self.lysope_neg_1()['score']
        ):
            
            score += 5
            fattya = self.fa_combinations('PE')
            
            if self.has_mz(196.0380330):
                score += 1
            
            if self.has_mz(178.0274684):
                score += 1
            
            fa_h_ccs = self.matching_fa_frags_of_type('PE', '-H]-')
            
            for fa_h_cc in fa_h_ccs:
                
                for fa_other in [
                    '[Lyso-PE(C%u:%u)-]-',
                    '[Lyso-PE-alkyl(C%u:%u)-H2O]-',
                    '[Lyso-PE-alkyl(C%u:%u)-]-',
                    '[FA(C%u:%u)-H-CO2]-'
                ]:
                    
                    if self.frag_name_present(fa_other % fa_h_cc):
                        score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def lysope_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is
        Lysophosphatidylethanolamine.

        **Specimen:** 
        
        - in vitro FABP1 - 464.27
      
        **Principle:**
        
        - The most abundant fragment is a fatty acid [M-H]- ion.
      - 140.0118 PE headgroup must be present.
        - The carbon count and unsaturation of the highest fatty acid
        fragment must be the same as it is expected for the whole PE molecule.
        - Other headgroup ions 196.0380 and 178.0275 add to the score.
      
        """
        
        score = 0
        fattya = set([])
        
        if (
            self.is_fa(0) and
            self.fa_type_is(0, '-H]-') and
            self.has_mz(140.0118206)
        ):
            score += 5
            
            if self.has_mz(196.0380330):
                score +=1
            
            if self.has_mz(178.0274684):
                score += 1
            
            ccs = self.ms1_cc(['PE', 'LysoPE'])
            
            for cc in ccs:
                
                if len(self.fa_list) and self.fa_list[0][0] == self.cc2int(cc):
                    
                    score += 3
                    fattya.add(cc)
            
            if not fattya:
                score = 0
        
        return {'score': score, 'fattya': fattya}
    
    def pc_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Phosphatidylcholine.

        **Specimen:**
        
        - BPI - 804.57
      
        **Principle:**
        
        - 168.0431 phosphate+choline-CH3 fragment must be present.
      - The highest abundant fragment must be a fatty acid [M-H]- fragment.
        - Lyso-PC fragments complementing the highest [M-H]- fatty acid
        increase the score.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.is_fa(0) and self.fa_type_is(0, '-H]-') and self.has_mz(168.0431206):
            
            score += 5
            fattya = self.fa_combinations('PC')
            fa_h_ccs = self.matching_fa_frags_of_type('PC', '-H]-')
        
            for fa_h_cc in fa_h_ccs:
                
                if self.frag_name_present('[Lyso-PC(c%u:%u)-]-' % fa_h_cc):
                    score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def pi_neg_1(self):
        """
        Examines if a negative MS2 spectrum is Phosphatidylinositol.

        **Specimen:**
        
        - GM2A - 835.52
      
        **Principle:**
        
        - Inositolphosphate-H2O fragment 241.0119, metaphosphate 78.9591 and
        headgroup fragment 152.9958 must be present.
        - Additional headgroup fragments 96.9696, 259.0224 and 297.0381
        increase the score.
        - Presence of Lyso-PI fragments complementing other [M-H]- fatty
        acid fragments increase the score.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.has_mz(241.0118779) and self.has_mz(152.9958366) and \
            self.has_mz(78.95905658):
            
            score += 5
            fattya = self.fa_combinations('PI')
            for hgfrag_mz in [96.96962158, 259.0224425, 297.0380926]:
                if self.has_mz(hgfrag_mz):
                    score += 1
            fa_h_ccs = self.matching_fa_frags_of_type('PI', '-H]-')
            for fa_h_cc in fa_h_ccs:
                for fa_other in [
                    '[Lyso-PI(C%u:%u)-]-',
                    '[Lyso-PI(C%u:%u)-H2O]-]']:
                    if self.frag_name_present(fa_other % fa_h_cc):
                        score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def ps_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Phosphatidylserine.

        **Specimen:**
        
        - ORP9 - 788.54
      
        **Principle:**
        
        - The most abundant fragment is an [M-H]- fatty acid fragment.
      - Glycerophosphate fragment 152.9958 must be present.
        - Metaphosphate 78.9591 increases the score.
      - Serine-H2O neutral loss 87.0320 adds to the score.
        - Presence of Lyso-PS and Lyso-PA fragments complementing
        the highest [M-H]- fatty acid fragment increase the score.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.is_fa(0) and self.fa_type_is(0, '-H]-') and \
            self.mz_among_most_abundant(152.9958366, 5):
            
            score += 5
            fattya = self.fa_combinations('PS')
            
            if not fattya:
                score = 0
                return {'score': score, 'fattya': fattya}
            
            if self.has_mz(87.03202840):
                score += 1
            
            if self.has_mz(78.95905658):
                score += 1
            
            fa_h_ccs = self.matching_fa_frags_of_type('PS', '-H]-')
            
            for fa_h_cc in fa_h_ccs:
                
                for fa_other in [
                    '[Lyso-PS(C%u:%u)-]-',
                    '[Lyso-PA(C%u:%u)-]-']:
                    
                    if self.frag_name_present(fa_other % fa_h_cc):
                        score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def pg_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is Phosphatidylglycerol.
        The result will be the same as `bmp_neg_1`, as in negative
        mode we do not know a way to distinguish these species.
        

        **Specimen:**
        
        - GM2A - 799.54
      - BPIFB2 - 773.5258 (might be BMP)
        
        **Principle:**
        
        - The most abundant fragment is a fatty acid [M-H]- ion.
      - The 152.9958 glycerophosphate fragment must be present.
        - If Lyso-PG fragment present with carbon count complementing
        the [M-H]- fatty acid score is higher.
        - Presence of 171.0064 headgroup fragment adds to the score.
      
        """
        
        score = 0
        fattya = set([])
        
        if self.is_fa(0) and self.fa_type_is(0, '-H]-') and \
            self.has_mz(152.9958366):
            
            score += 5
            
            #if self.mz_among_most_abundant(152.9958366, 5):
            #   score -= 3
            
            fattya = self.fa_combinations('PG')
            
            if self.has_mz(171.0064016):
                score += 1
            
            fa_h_ccs = self.matching_fa_frags_of_type('PG', '-H]-')
            
            for fa_h_cc in fa_h_ccs:
                
                for fa_other in [
                    'Lyso-PG(C%u:%u)-]-',
                    'Lyso-PG(C%u:%u)-H2O]-']:
                    
                    if self.frag_name_present(fa_other % fa_h_cc):
                        score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def sm_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Sphingomyeline.

        **Specimen:**
        
        - GLTPD1 - 745.55
      
        **Principle:**
        
        - Must have a neutral loss of CH3+COOH (60.0211).
      - Phosphate+choline-CH3 fragment 168.0431 must be present.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.mz_among_most_abundant(168.0431206) and self.has_nl(60.02113):
            score += 5
        
        return {'score': score, 'fattya': fattya}
    
    def sph1p_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Spingosine-1-phosphate.

        **Specimen:**
        
        - Only observed in standard.
      
        **Principle:**
        
        - Phosphate 78.9590 must be present.
      
        """
        
        score = 0
        fattya = set([])
        
        if self.has_mz(78.95905658):
            score += 5
        
        return {'score': score, 'fattya': fattya}
    
    def cer_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is Ceramide.

        **Specimen:**
        
        - SEC14L1 - 582.509
      
        **Principle:**
        
        - A Ceramide backbone fragment must be among the 2 most abundant.
      - Ceramide backbone fragments lighter by N or C2N but same carbon
          count and unsaturation add to the score.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.fa_among_most_abundant('CerFA', n = 2):
            
            score += 5
            fattya = self.fa_combinations('Cer', sphingo = True)
            fa_h_ccs = self.matching_fa_frags_of_type('Cer', 'CerFA(')
            
            for fa_h_cc in fa_h_ccs:
                
                for fa_other in [
                    '[CerFA-N(C%u:%u)-]-',
                    '[CerFA-C2N(C%u:%u)-]-']:
                    
                    if self.frag_name_present(fa_other % fa_h_cc):
                        
                        score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def cerp_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a Ceramide-1-phosphate.
        Gives similar result as Sphingosine-1-phosphate.

        **Specimen:**
        
        - GLTPD1 - 616.47
      
        **Principle:**
        
        - The most abundant fragment must be 78.9591 metaphosphate.
      - Presence of 96.9696 phosphate increase the score.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.most_abundant_mz_is(78.95905658):
            
            score += 5
            
            if self.has_mz(96.96962158):
                
                score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def pc_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Phosphatidylcholine.

        **Specimen:**
        
        - BPI + 786.607
      
        **Principle:**
        
        - The most abundant fragment must be choline+phosphate 184.0733.
      - The 86.0964 ethyl-triethylammonium must be present.
        - The most abundant fatty acid can not have the same carbon count
        and unsaturation as the whole molecule (then it is Lyso-PC).
        - Fragments 104.1069, 124.9998, 60.0808 and 58.0651 increase the
        score.
        
        """
        
        score = 0
        fattya = set([])
        
        if (
            self.most_abundant_mz_is(184.073323) and
            self.has_mz(86.096425) and
            not self.lysopc_pos_1()['score']
        ):
            
            score += 5
            fattya = self.fa_combinations('PC')
            
            if self.has_mz(104.106990):
                score += 1
            if self.has_mz(124.999822):
                score += 1
            if self.has_mz(60.080776):
                score +=1
            if self.has_mz(58.065126):
                score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def lysopc_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Lysophosphatidylcholine.
        
        **Specimen:**
        
        - in vitro FABP1 + 522.36
      
        **Principle:**
        
        - Choline-phosphate 184.0733, ethyl-triethylammonium 86.0964 and
        neutral loss 183.0660 must be present.
        - The latter neutral loss corresponds to a fatty acid+glycerol ion.
      - The carbon count and unsaturation of this fragment should match
          that of the whole molecule.
        
        """
        
        score = 0
        fattya = set([])
        
        if (
            self.most_abundant_mz_is(184.073323) and
            self.has_mz(86.096425) and
            self.has_nl(183.066045)
        ):
            
            score += 5
            
            fa_mz = self.scan[self.nl_lookup(183.066045),1]
            
            ccs = self.ms1_cc(['PC', 'LysoPC'])
            
            for cc in ccs:
                
                for fa_frag in self.fa_list:
                    
                    if (
                        fa_frag[0] == self.cc2int(cc) and
                        abs(self.scan[fa_frag[5],1] - fa_mz) < 0.0001 and
                        'FA+G(' in self.scan[fa_frag[5],7] and
                        self.cc2int(cc)[0] < 21
                    ):
                        
                        score += 5
                        fattya.add(cc)
            
            if not fattya:
                score = 0
        
        return {'score': score, 'fattya': fattya}
    
    def sm_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Sphingomyeline.
        
        **Specimen:**
        
        - GLTPD1 + 703.57
      - GLTPD1 + 813.68 (in vitro)
        
        **Principle:**
        
        - The following choline fragments must be present: 60.0808, 86.0964,
        104.1069, 124.9998 and 184.0733. The last one is the most intensive.
        - If 58.0651 can be found it adds to the score.
      
        """
        
        score = 0
        fattya = set([])
        
        if all(
            map(
                lambda mz:
                    self.has_mz(mz),
                [
                    60.080776,
                    86.096425,  #
                    104.106990, #
                    124.999822, #
                    184.073323  #
                ]
            )
        ):
            
            score += 5
            
            if self.has_mz(58.0651):
                
                score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def fa_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a fatty acid.
        Here we only check if the most abundant fragment is the
        fatty acid itself.

        **Specimen:**
        
        - in vitro FABP1 +
      
        **Principle:**
        
        - The most abundant fragment must be a fatty acid which matches
        the carbon count and the unsaturation of the whole molecule.
        
        """
        score = 0
        fattya = set([])
        
        self.build_fa_list()
        
        if self.is_fa(0):
            
            if 'FA' in self.feature.ms1fa:
                
                for cc in self.feature.ms1fa['FA']:
                    
                    if len(self.fa_list) and self.cc2int(cc) == self.fa_list[0][0]:
                        
                        score += 5
                        fattya.add(cc)
        
        return {'score': score, 'fattya': fattya}
    
    def fa_neg_1(self):
        """
        Examines if a negative mode MS2 spectrum is a fatty acid.
        Here we only check if the most abundant fragment is the
        fatty acid itself.

        **Specimen:**
        
        - in vitro FABP1 -
      
        **Principle:**
        
        - The most abundant fragment must be a fatty acid which matches
        the carbon count and the unsaturation of the whole molecule.
        
        """
        
        # these are the same
        return self.fa_pos_1()
    
    def cerp_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Ceramide-1-phosphate.

        **Specimen:**
        
        - GLTPD1 + 728.59, 590.45, 702.58, 618.430, 616.415, 640.409
      
        **Principle:**
        
        - A sphingosine fragment with double H2O loss must be among the three
        highest abundant fragments.
        
        """
        
        score = 0
        fattya = set([])
        
        if self.fa_among_most_abundant('-H2O-H2O+]+', n = 3, sphingo = True):
            score += 1
        
        return {'score': score, 'fattya': fattya}
    
    def pe_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a
        Phosphatidylethanolamine.

        **Specimen:**
        
        - BPI + 718.536
      
        **Principle:**
        
        - The PE headgroup neutral loss 141.0191 has the highest intensity.
      - If it is a Lyso-PE score will be zero.
        
        """
        
        score = 0
        fattya = set([])
        if self.nl_among_most_abundant(141.019097, 1):
            score += 5
            fattya = self.fa_combinations('PE')
            if not fattya and self.lysope_pos_1()['score']:
                score = 0
        
        return {'score': score, 'fattya': fattya}
    
    def lysope_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a
        Lysophosphatidylethanolamine.

        **Specimen:**
        
        - in vitro FABP1 + 454.29
      
        **Principle:**
        
        - The PE headgroup neutral loss 141.0191 has the highest intensity.
      - A fatty acid-glycerol fragment should match the carbon count and
          unsaturation of the whole molecule.
        
        """
        
        score  = 0
        fattya = set([])
        
        if self.nl_among_most_abundant(141.019097, 2):
            
            score += 6
            
            if len(self.fa_list):
            
                frag1 = self.fa_list[0]
            
                ccs = self.ms1_cc(['PE', 'LysoPE'])
                
                for cc in ccs:
                    
                    if (frag1[0] == self.cc2int(cc) and
                        self.fa_type_is(frag1[5], 'FA+G(')):
                        
                        score += 1
                        fattya.add(cc)
                        
                    
                    else:
                        score -= 1
            
            else:
                score -= 1
        
        return {'score': score, 'fattya': fattya}
    
    def cer_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a Ceramide.

        **Specimen:**
        
        - SEC14L1 + 538.52
      - STARD11 + 538.526
        
        **Principle:**
        
        - A sphingosine backbone with two H2O loss must be among the
        10 most abundant fragments.
        - Fatty acid [M+H]+ or [M-O]+ fragments or neutral losses
        complementing the one above increase the score.
        - Sphingosine backbone fragments with same carbon count and
        unsaturation with the one with 2 water loss but [Sph-C-2(H2O)]+
          or [Sph-H2O]+ add to the score.
        - The score increases if the following choline fragments
        can not be found: 58.0651, 104.1070, 124.9998 and 184.0733.
        - The presence of the following fragments increase the score:
        60.0444, 70.0651, 82.0651, 96.0808, 107.0730, 121.0886,
          135.1042 and 149.1199.
        
        """
        
        score = 0
        fattya = set([])
        
        if 'Cer' not in self.feature.ms1fa:
            ms1uns = None
            
        else:
            # larger unsaturation than the whole molecule
            # does not make sense
            ms1uns = max(map(lambda _cc: self.cc2int(_cc)[1],
                             self.feature.ms1fa['Cer']))
        
        if self.fa_among_most_abundant('-H2O-H2O+]+', n = 10,
                                       sphingo = True, uns = ms1uns):
            
            score += 5
            fattya = self.fa_combinations('Cer', sphingo = True)
            
            sph_ccs, fa_frags = self.matching_fa_frags_of_type('Cer',
                '-H2O-H2O+]+', sphingo = True, return_details = True)
            
            for cc, fa_frag_names in iteritems(fa_frags):
                
                for fa_frag_name in fa_frag_names:
                    
                    if '+H]+' in fa_frag_name:
                        score += 1
                    if '-O]+' in fa_frag_name:
                        score += 1
                    if 'NL' in fa_frag_name:
                        score += 1
            
            for sph_cc in sph_ccs:
                for fa_other in [
                    '[Sphingosine(C%u:%u)-C-H2O-H2O+]+',
                    '[Sphingosine(C%u:%u)-H2O+]+']:
                    if self.frag_name_present(fa_other % sph_cc):
                        
                        score += 1
            
            if not len(
                list(
                    filter(
                        lambda mz:
                            self.has_mz(mz),
                        [58.065126, 104.106990, 124.999822, 184.073323]
                    )
                )
            ):
                
                score += 1
            
            score += len(
                list(
                    filter(
                        lambda mz:
                            self.has_mz(mz),
                        [60.0443902, 70.0651257, 82.0651257, 96.0807757,
                        107.072951, 121.088601, 135.104251, 149.119901]
                    )
                )
            )
        
        return {'score': score, 'fattya': fattya}
    
    def vd_pos_1(self):
        """
        Examines if a positive mode MS2 spectrum is a vitamin D.
        This method is not implemented, does nothing.
        """
        
        score = 0
        fattya = set([])
        
        return {'score': score, 'fattya': fattya}
    
    def ms1_cc(self, hgs):
        """
        For a list of headgroups returns the possible carbon counts
        based on database lookups of MS1 m/z's.
        Returns set of strings.
        """
        
        ccs = set([])
        
        for hg in hgs:
            
            if hg in self.feature.ms1fa:
                ccs.update(self.feature.ms1fa[hg])
            
            if hg in self.feature.ms1fa:
                ccs.update(self.feature.ms1fa[hg])
        
        return ccs
    
    def is_pe(self):
        if self.feature.mode == 'pos':
            return self.pa_pe_ps_pg_pos('PE')
        else:
            return self.pe_pc_pg_neg('PE')
    
    def is_pc(self):
        if self.feature.mode == 'pos':
            return self.pc_pos('PC')
        else:
            return self.pe_pc_pg_neg('PC')
    
    def is_pa(self):
        if self.feature.mode == 'pos':
            return self.pa_pe_ps_pg_pos('PA')
        else:
            return self.pa_ps_neg('PA')
    
    def is_ps(self):
        if self.feature.mode == 'pos':
            return self.pa_pe_ps_pg_pos('PS')
        else:
            return self.pa_ps_neg('PS')
    
    def is_pg(self):
        if self.feature.mode == 'pos':
            return self.pa_pe_ps_pg_pos('PG')
        else:
            return self.pe_pc_pg_neg('PG')
    
    def pa_pe_ps_pg_pos(self, hg):
        return self.mz_among_most_abundant(141.0191) \
            and self.fa_among_most_abundant('-O]+', min_mass = 140.0) \
            and self.fa_ccs_agree_ms1(hg, '-O]+')
    
    def pa_ps_neg(self, hg):
        return self.has_mz(152.9958366) and self.has_mz(78.95905658) \
            and self.most_abundant_fa('-H]-') \
            and self.fa_ccs_agree_ms1(hg, '-H]-')
    
    def pe_pc_pg_neg(self, hg):
        return self.most_abundant_fa('-H]-') \
            and self.fa_ccs_agree_ms1(hg, '-H]-')
    
    def pc_pos(self, hg):
        return self.mz_most_abundant_fold(184.0733, 3) \
            and self.fa_ccs_agree_ms1(hg, head = 4)