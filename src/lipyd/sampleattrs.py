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

from future.utils import iteritems
from past.builtins import xrange, range

import collections

import numpy as np

import lipyd.common as common
import lipyd.sec as sec


def sample_id_processor(method = None, *args):
    """
    Creates a custom sample identifier class.
    
    :param callable method:
        A method which takes a single argument corresponding to the raw
        sample ID and returns a custom number of values.
    :param str *args:
        Names for the attributes representing the sample ID. These should
        correspond to the values returned by ``method``.
    """
    
    if not args:
        
        args = ['sample_id']
    
    class SampleId(collections.namedtuple('SampleIdBase', args)):
        
        def __new__(cls, raw):
            
            if isinstance(raw, cls):
                
                return raw
            
            values = cls.method(raw)
            
            if not isinstance(values, (list, tuple)):
                
                values = (values,)
            
            return super(SampleId, cls).__new__(
                cls,
                **dict(zip(args, values))
            )
    
    method = method or (lambda x: x)
    SampleId.method = method
    
    return SampleId


def plate_sample_id_processor():
    """
    Returns a sample ID processor which makes sure samples are represented
    by a tuple of one uppercase letter and an integer.
    This is convenient if samples correspond to wells on a plate.
    """

    def _plate_sample_id_processor(well):
        
        if isinstance(well, common.basestring):
            
            try:
                
                return (well[0].upper(), int(well[1:]))
                
            except (ValueError, IndexError):
                
                pass
        
        return well
    
    return sample_id_processor(_plate_sample_id_processor, 'row', 'col')


class SampleAttrs(object):
    
    def __init__(
            self,
            sample_id = None,
            attrs = None,
            proc = None,
            proc_method = None,
            proc_names = None,
        ):
        """
        Represents the ID and attributes of a sample.
        
        :param object,callable sample_id:
            Either an object (string or tuple) or a method which takes
            a dict of attributes as its argument and returns a unique
            identifier for the sample.
        :param dict attrs:
            A dictionary of sample attributes.
        :param SampleId proc:
            A sample ID processor class generated by ``sample_id_processor``.
        :param callable proc_method:
            A sample ID processing method for sample ID processor if ``proc``
            not given.
        :param list proc_names:
            Attribute names for the sample ID processor (passed to
            ``sample_id_processor if ``proc`` not given).
        """
        
        self.attrs = attrs or {}
        proc_names = proc_names or []
        self.proc  = proc or sample_id_processor(proc_method, *proc_names)
        self._sample_id = sample_id
        self._set_sample_id()
    
    def _get_sample_id(self):
        
        if self._sample_id is None and not self.attrs:
            
            # first if it's None we call the deafult method to
            # create sample ID from the sample attributes
            return common.random_string()
            
        elif callable(self._sample_id):
            
            # if a custom method has been provided we use
            # that instead
            return self._sample_id(self.attrs)
            
        else:
            
            # if it's not callable but any other kind of object
            # then we assume the sample ID is explicitely given
            return self._sample_id
    
    def _set_sample_id(self):
        
        self.sample_id = self.proc(self._get_sample_id())


class SampleSetAttrs(object):
    
    def __init__(
            self,
            sample_ids = None,
            attrs = None,
            proc = None,
            proc_method = None,
            proc_names = None,
            length = None,
        ):
        """
        A set of ``SampleAttrs`` i.e. attributes for each sample in a sample
        set. Arguments work a similar way like at ``SampleAttrs``.
        """
        
        proc_names = proc_names or []
        self.proc = proc or sample_id_processor(proc_method, *proc_names)
        
        if isinstance(sample_ids, (list, np.ndarray)):
            
            length = len(sample_ids)
            
        elif attrs is not None:
            
            # if sample attributes provided
            length = len(attrs)
        
        if length is None:
            
            raise RuntimeError(
                'SampleSetAttrs: number of samples not provided.'
            )
        
        if not hasattr(sample_ids, '__iter__'):
            
            # now it is either None or a method
            sample_ids = [sample_ids] * length
        
        # if attrs is still None make it a list of None's
        attrs = attrs or [attrs] * length
        
        self.attrs = np.array([
            SampleAttrs(
                sample_id = sample_id,
                attrs = attrs_,
                proc = proc,
                proc_method = proc_method,
                proc_names = proc_names,
            )
            for sample_id, attrs_ in zip(sample_ids, attrs)
        ])
        
        self._set_sample_ids()
    
    def __len__(self):
        
        return len(self.attrs)
    
    def _make_sample_id(self, sample_id):
        
        return self.proc(sample_id)
    
    def _set_sample_ids(self):
        # called by __init__()
        
        sample_index_to_id = []
        
        for attr in self.attrs:
            
            sample_index_to_id.append(attr.sample_id)
        
        self.sample_index_to_id = np.array(sample_index_to_id)
        
        self._update_id_to_index()
    
    def _update_id_to_index(self):
        # to keep this too in sync
        
        self.sample_id_to_index = dict(
            reversed(i)
            for i in enumerate(self.sample_index_to_id)
        )
    
    def get_sample_id(self, i):
        """
        Returns the ID of a sample by its index.
        """
        
        return self.sample_index_to_id[i]
    
    def get_sample_index(self, sample_id):
        """
        Returns the index of a sample by its ID.
        """
        
        return self.sample_id_to_index[sample_id]
    
    def sort_by_index(self, idx):
        
        idx = np.array(idx)
        
        self.attrs = self.attrs[idx]
        
        self._set_sample_ids()
    
    def argsort_by_sample_id(self, sample_ids):
        """
        Returns an index array which sorts the sample attributes according
        to the list of sample IDs provided.
        
        :param list sample_ids:
            A list of sample IDs, e.g. ``[('A', 1), ('A', 2), ...]``.
        """
        
        return np.array([
            self.sample_id_to_index[
                self._make_sample_id(sample_id)
            ]
            for sample_id in sample_ids
        ])
    
    def sort_by_sample_id(
            self,
            sample_ids,
            return_idx = False,
        ):
        """
        Sets the order of the sample attributes according to the list of
        sample IDs provided.
        
        :param list sample_ids:
            A list of sample IDs, e.g. ``[('A', 1), ('A', 2), ...]``.
        :param bool return_idx:
            Return the index array corresponding to the sort.
        """
        
        idx = self.argsort_by_sample_id(sample_ids = sample_ids)
        
        self.sort_by_index(idx)
        
        if return_idx:
            
            return idx
    
    def sort_by(self, other, return_idx = False):
        """
        Sorts the sample attributes according to an other ``SampleSetAttrs``
        object. The other object must have the same sample IDs.
        
        :param SampleSetAttrs other:
            An other ``SampleSetAttrs`` with the same sample IDs.
        :param bool return_idx:
            Return the index array corresponding to the sort.
        """
        
        return self.sort_by_sample_id(
            other.sample_index_to_id,
            return_idx = return_idx,
        )


class SampleSorter(object):
    
    def __init__(
            self,
            sample_data = None,
            sample_ids = None,
            sample_id_proc = None,
            sample_id_proc_method = None,
            sample_id_proc_names = None,
            sample_axis = 0,
            attr_args = None,
        ):
        """
        Keeps the order of samples synchronized between multiple objects.
        These objects represent sets of the same samples such as
        ``sample.SampleSet`` or ``feature.SampleData``.
        
        :param list,set sample_data:
            Other ``sample.SampleSet`` or ``feature.SampleData`` derived
            objects that should keep the same order of samples.
        :param list sample_ids:
            A list of sample IDs which determines the initial ordering. All
            objects in ``sample_data`` will be sorted according to this order.
            If not provided the ordering in the first object in
            ``sample_data`` will be used. You must provide at least
            ``sample_ids`` or ``sample_data``.
        :param int sample_axis:
            Which axis in the arrays corresponds to the samples.
            In ``sample.SampleSet`` objects this is axis 1 as axis 0
            corresponds to the features. In ``feature.SampleData`` derived
            objects this is axis 0.
        """
        
        self._sample_data = {}
        self._sample_axis = sample_axis
        
        if sample_data is None:
            
            sample_data = []
        
        if not isinstance(sample_data, (list, set)):
            
            sample_data = [sample_data]
        
        if not hasattr(self, 'attrs'):
            
            if not sample_ids:
                
                if sample_data:
                    
                    sample_ids = self._get_sample_ids(sample_data)
                    
                else:
                    
                    raise RuntimeError(
                        'SampleSorter: `sample_data` or `sample_ids` '
                        'must be provided.'
                    )
            
            if not sample_id_proc:
                
                sample_id_proc = self._get_sample_id_proc(sample_data)
            
            attr_args = attr_args or {
                'sample_ids': sample_ids,
                'proc': sample_id_proc,
                'proc_method': sample_id_proc_method,
                'proc_names': sample_id_proc_names,
            }
            
            self._set_attrs(**attr_args)
        
        for s in sample_data:
            
            self.register(s)
    
    def __len__(self):
        """
        Tells number of samples.
        """
        
        return len(self.attrs)
    
    def _set_attrs(self, **kwargs):
        
        if 'sample_id' in kwargs:
            
            # rename this arg as it is specific for SampleSetAttrs
            kwargs['sample_ids'] = kwargs['sample_id']
            del kwargs['sample_id']
        
        self.attrs = SampleSetAttrs(**kwargs)
    
    def _get_sample_ids(self, sample_data):
        
        first = sample_data[0]
        
        return first.sample_id_to_index
    
    def _get_sample_id_proc(self, sample_data):
        
        if sample_data:
            
            first = sample_data[0]
            
            return first.attrs.proc
    
    def sort_by(self, s):
        """
        Sorts the current object according to another ``SampleSorter``
        derived object.
        
        :param SampleSorter s:
            A ``SampleSorter`` derived object such as ``sample.SampleSet``,
            ``feature.SampleData`` etc.
        """
        
        idx = self.attrs.sort_by(s.attrs, return_idx = True)
        
        self._sort(idx)
    
    def sort_to(self, s):
        """
        Makes sure object ``s`` has the same ordering as all in this sorter.
        
        :param SampleSorter s:
            A ``SampleSorter`` derived object such as ``sample.SampleSet``,
            ``feature.SampleData`` etc.
        """
        
        idx = s.attrs.sort_by(self.attrs, return_idx = True)
        
        s._sort(idx)
    
    def _sort(self, idx):
        """
        Sorts only variables in this object by indices.
        """
        
        if hasattr(self, 'var'):
            
            numof_samples = len(self.attrs)
            
            for var in self.var:
                
                arr = getattr(self, var)
                
                if (
                    len(arr.shape) <= self._sample_axis or
                    arr.shape[self._sample_axis] != numof_samples
                ):
                    
                    continue
                
                setattr(
                    self,
                    var,
                    np.take(arr, idx, axis = self._sample_axis),
                )
    
    def register(self, s):
        """
        Registers a ``sample.SampleSet`` or ``feature.SampleData`` derived
        object ensuring it will keep the same order of samples.
        
        :param SampleSet,SampleData s:
            A ``sample.SampleSet`` or ``feature.SampleData`` derived
            object.
        """
        
        self.sort_by(s)
        
        self._sample_data[id(s)] = s
        
        if id(self) not in s._sample_data:
            
            s.register(self)
    
    def sort_by_sample_ids(self, sample_ids):
        """
        Sorts all connected objects by a list of sample IDs.
        
        :param list sample_ids:
            A list of sample ids in the desired order, e.g.
            ``[('A', 1), ('A', 2), ...]``.
        :param bool process:
            Use the ``sample_id_processor`` methods to convert the sample IDs
            provided.
        """
        
        idx = self.attrs.argsort_by_sample_id(sample_ids)
        
        self.sort(idx)
    
    def sort(self, idx, _done = None):
        """
        Sorts all connected objects by indices.
        
        :param list idx:
            A list of indices.
        :param set _done:
            As the sorting propagates across objects this ``set`` keeps track
            which objects have been already sorted. Should be ``None`` when
            called by user.
        """
        
        _done = set() if _done is None else _done
        
        if id(self) in _done:
            
            return
        
        numof_samples = self.numof_samples
        
        if len(idx) != numof_samples:
            
            raise RuntimeError(
                'Invalid index length: %u while number of samples is %u.' % (
                    len(idx), numof_samples
                )
            )
        
        self.attrs.sort_by_index(idx)
        self._sort(idx)
        
        _done.add(id(self))
        
        for sd_id, sd in iteritems(self._sample_data):
            
            if sd_id not in _done:
                
                sd.sort(idx = idx, _done = _done)
    
    def index_previous(self, i):
        """
        An index or sample ID provided it returns the index of the sample
        preceding in the series. Returns ``None`` if the first sample
        is queried.
        """
        
        if not isinstance(i, (int, np.int_)):
            
            i = self.attrs.sample_id_to_index[i]
        
        if i > 0:
            
            return i - 1
    
    def id_previous(self, i):
        """
        An index or sample ID provided it returns the ID of the sample
        preceding in the series. Returns ``None`` if the first sample
        is queried.
        """
        
        i = self.index_previous(i)
        
        if i is not None:
            
            return self.attrs.sample_index_to_id[i]
        
    def index_next(self, i):
        """
        An index or sample ID provided it returns the index of the sample
        following in the series. Returns ``None`` if the first sample
        is queried.
        """
        
        if not isinstance(i, (int, np.int_)):
            
            i = self.attrs.sample_id_to_index[i]
        
        if i < self.numof_samples:
            
            return i + 1
    
    def id_next(self, i):
        """
        An index or sample ID provided it returns the ID of the sample
        following in the series. Returns ``None`` if the first sample
        is queried.
        """
        
        i = self.index_next(i)
        
        if i is not None:
            
            return self.attrs.sample_index_to_id[i]


class SampleData(SampleSorter):
    
    def __init__(
            self,
            samples = None,
            sample_ids = None,
            sample_data = None,
            sample_id_proc = None,
            sample_id_proc_method = None,
            sample_id_proc_names = None,
            **kwargs,
        ):
        """
        Represents data about a series of samples. Samples are LC MS/MS runs.
        Data might be a binary, qualitative or quantitative attribute about
        these samples. E.g. disease status of a patient, time of sampling,
        quantity of a protein, etc. The data might have more than one
        dimensions but the first axis is always considered to be the sample
        identity and the number of samples must agree with the number of
        samples in the sampleset. If no ``sample_ids`` provided the order of
        sample data assumed to be the same as the order of samples in the
        sampleset. Otherwise it will be ordered according to the labels.
        
        :param list,numpy.array **kwargs:
            Data associated to samples. First dimension of each array must
            agree with the samples in the sampleset. Multiple variables
            might be provided each will be set as an attribute of the object.
        :param lipyd.samples.SampleSet samples:
            A ``SampleSet`` object.
        :param list sample_ids:
            A list of sample IDs. Will be used to reorder the sample data
            in order to have the same ordering as the samples in sampleset.
        :param callable sample_id_processor:
            A method to process elements in ``sample_ids``.
        """
        
        if (not sample_ids and not samples) or not hasattr(samples, 'attrs'):
            
            raise RuntimeError(
                'SampleData: either `samples` or '
                '`sample_ids` must be provided.'
            )
        
        sample_ids = sample_ids or samples.attrs.sample_index_to_id
        
        self.numof_samples = len(sample_ids)
        
        if isinstance(samples, SampleSorter):
            
            sample_data = sample_data or []
            sample_data.append(samples)
        
        self.var = set()
        
        for attr, data in iteritems(kwargs):
            
            self._add_var(data, attr)
        
        SampleSorter.__init__(
            self,
            sample_data = sample_data,
            sample_ids = sample_ids,
            sample_axis = 0,
            sample_id_proc = sample_id_proc,
            sample_id_proc_method = sample_id_proc_method,
            sample_id_proc_names = sample_id_proc_names,
        )
    
    def _add_var(self, data, attr):
        """
        Adds a new variable to the data handler object.
        The first dimension of the array must agree with
        the number of samples.
        """
        
        if isinstance(data, list):
            
            data = np.array(data)
        
        if data.shape[0] != self.numof_samples:
            
            raise RuntimeError(
                'SampleData: first dimension of each array must agree with '
                'the number of samples. `%s` has length %u while numof '
                'samples is %u.' % (
                    attr, data.shape[0], self.numof_samples,
                )
            )
        
        setattr(self, attr, data)
        self.var.add(attr)
    
    @staticmethod
    def _bool_array(
            selection,
            proc = None,
            sample_ids = None,
        ):
        """
        This method helps to set up a sample selection but placed here as
        staticmethod to make it usable in other derived classes.
        """
        
        if not isinstance(selection[0], (bool, np.bool_)):
            
            if proc:
                
                selection = [proc(s) for s in selection]
            
            selection = np.array([s in selection for s in sample_ids])
        
        return selection
    
    def get_selection(self, selection = None, **kwargs):
        """
        Returns a ``SampleSelection`` object with samples corresponding to
        the samples in this object.
        
        :param list,numpy.ndarray selection:
            A list of sample IDs or a boolean array with the same length as
            the number of samples.
        :param **kwargs:
            Arguments passed to ``make_selection`` if ``selection`` not
            provided.
        """
        
        if selection is None:
            
            selection = self.make_selection(**kwargs)
        
        return SampleSelection(
            selection = selection,
            sample_data = self._sample_data + [self],
            sample_id_proc = self.attrs.proc,
        )
    
    def make_selection(
            self,
            manual = None,
            include = None,
            exclude = None,
            logic = 'AND',
            **kwargs,
        ):
        """
        Creates a boolean array based on the filters and criteria provided.
        First the manual selection is evaluated, then the methods provided
        in ``**kwargs``, after the samples in ``include`` added and finally
        those in ``exclude`` removed from the selection.
        
        :param **kwargs:
            Variable names and methods or boolean arrays. If boolean arrays
            provided these will be used to select the samples.
            Methods will be applied to each element of the variable in the
            slot to obtain a boolean array.
            E.g. ``profile = lambda x: x > 0.3`` will be ``True`` for values
            in the profile array above 0.3.
        """
        
        selected = np.array([True] * self.numof_samples)
        consensus = np.array([True] * self.numof_samples)
        
        if manual:
            
            selected = {self.attrs.proc(sample_id) for sample_id in manual}
        
        if kwargs:
            
            bool_arrays = []
            
            for var, method in iteritems(kwargs):
                
                if isinstance(method, (list, np.ndarray)):
                    
                    bool_arrays.append(method)
                    continue
                
                values = getattr(self, var)
                bool_array = []
                
                for i in xrange(values.shape[self._sample_axis]):
                    
                    val = np.take(arr, i, axis = self._sample_axis)
                    bool_array.append(method(val))
                
                bool_arrays.append(bool_array)
            
            bool_arrays = np.vstack(bool_arrays)
            
            consensus = (
                np.any(bool_arrays, 0)
                    if logic.upper() == 'AND' else
                np.all(bool_arrays, 0)
            )
        
        if include:
            
            incl = {self.attrs.proc(sample_id) for sample_id in include}
            selected = selected | incl
        
        if exclude:
            
            excl = {self.attrs.proc(sample_id) for sample_id in exclude}
            selected = selected - excl
        
        selected = [
            self.sample_index_to_id[i] in selected
            for i in xrange(self.numof_samples)
        ]
        
        return np.all(np.vstack((selected, consensus)), 0)


class SampleSelection(SampleData):
    
    def __init__(
            self,
            selection,
            samples = None,
            sample_ids = None,
            sample_data = None,
            sample_id_proc = None,
            sample_id_proc_method = None,
            sample_id_proc_names = None,
            **kwargs,
        ):
        """
        Represents a binary selection of samples. You can provide either a
        boolean array or a list of sample IDs to be selected.
        """
        
        SampleData.__init__(
            self,
            samples = samples,
            sample_ids = sample_ids,
            sample_data = sample_data,
            sample_id_proc = sample_id_proc,
            sample_id_proc_method = sample_id_proc_method,
            sample_id_proc_names = sample_id_proc_names,
        )
        
        proc = self.attrs.proc
        sample_ids = self.attrs.sample_index_to_id
        
        sel = self._bool_array(
            selection = selection,
            proc = proc,
            sample_ids = sample_ids,
        )
        
        self._add_var(sel, 'selection')
    
    def sample_ids_selected(self):
        """
        Returns a list IDs of selected samples.
        """
        
        return [
            sample_id
            for i, sample_id in enumerate(self.attrs.sample_index_to_id)
            if self.selection[i]
        ]


class SECProfile(SampleData):
    
    def __init__(
            self,
            sec_path,
            start_volume = .6,
            size = .15,
            start_row = None,
            start_col = None,
            length = None,
            sample_id_method = None,
            offsets = None,
            samples = None,
            sample_data = None,
            sample_ids = None,
            sample_id_proc = None,
            sample_id_proc_method = None,
            sample_id_proc_names = None,
            **kwargs,
        ):
        """
        Reads protein abundance from size exclusion chromatography UV
        absorbance profile.
        
        :param str sec_path:
            Path to SEC file.
        :param float start_volume:
            The start volume in ml. Above this volume the collected fractions
            have been analysed by LC MS/MS.
        :param int length:
            The number of fractions analyzed.
        :param str start_row:
            The row of the first well analyzed.
        :param int start_col:
            The column number of the first well analysed.
        :param float size:
            The volume collected in one fraction (in ml).
        :param callable sample_id_method:
            A method to process sample IDs from the data provided by the
            SEC reader object.
        :param tuple offsets:
            A range of offsets to be applied to volume data in ml.
            E.g. ``(0.015, 0.045)`` means the boundaries of the fractions
            might be 0.015-0.045 ml later than it is stated in the file.
        :param sample_ids:
            Ignored here as sample IDs taken from the SEC profile reader.
        
        All other arguments passed to ``SampleData``.
        """
        
        self.sec_path = sec_path
        self.start_volume = start_volume
        self.size = size
        self.start_row = (
            start_row or
            sorted(s.row for s in samples.attrs.sample_index_to_id)[0]
        )
        self.start_col = (
            start_col or
            sorted(s for s in samples.attrs.sample_index_to_id)[0].col
        )
        self.length = length
        self.sample_id_method = (
            sample_id_method or
            self._default_sample_id_method
        )
        self.offsets = offsets
        self._sampleset_numof_samples = samples.numof_samples
        
        profiles = {}
        
        if not offsets:
            
            profiles['profile'] = self.read_sec()
            
        else:
            
            for offset in offsets:
                
                profiles['profile%03u' % int(offset * 1000)] = (
                    self.read_sec(offset)
                )
        
        SampleData.__init__(
            self,
            samples = samples,
            sample_ids = self.sample_ids,
            sample_data = sample_data,
            sample_id_proc = sample_id_proc,
            sample_id_proc_method = sample_id_proc_method,
            sample_id_proc_names = sample_id_proc_names,
            **profiles,
            **kwargs,
        )
    
    def read_sec(self, offset = None):
        
        start_volume = (
            self.start_volume
                if offset is None else
            self.start_volume + offset
        )
        
        self.reader = sec.SECReader(path = self.sec_path)
        profile = self.reader.profile(
            start_volume = start_volume,
            size = self.size,
            start_col = self.start_col,
            start_row = self.start_row,
            length = self.length,
        )
        
        sample_ids = []
        values = []
        
        for i, fr in enumerate(profile):
            
            if (fr.row, fr.col) < (self.start_row, self.start_col):
                
                continue
            
            sample_ids.append(self.sample_id_method(fr))
            values.append(fr.mean)
        
        self.sample_ids = sample_ids[:self._sampleset_numof_samples]
        
        return values[:self._sampleset_numof_samples]
    
    @staticmethod
    def _default_sample_id_method(fraction):
        
        return fraction.row, fraction.col
    
    def protein_containing_samples(
            self,
            threshold = .33,
            manual = None,
        ):
        
        pass
