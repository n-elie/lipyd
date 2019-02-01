#!/usr/bin/env python

# -- 2019/01/22 --
import os
import imp

import lipyd.ms2 as ms2
import lipyd.common as common
import lipyd.plot as plot
import lipyd.settings as settings

mgfname = 'pos_examples.mgf'
ionmode = 'pos'
scan_id = 2397
scan_args = {}

mgfpath = os.path.join(common.ROOT, 'data', 'ms2_examples', mgfname)
scan = ms2.Scan.from_mgf(mgfpath, scan_id, ionmode, **scan_args)


importlib.reload(settings)
importlib.reload(ms2)
importlib.reload(plot)

p = plot.SpectrumPlot(
    mzs = scan.mzs,
    intensities = scan.intensities,
    annotations = scan.annot,
    scan_id = scan.scan_id,
    ionmode = ionmode,
    sample_name = 'BPI_invivo',
    grid_cols = 1,
    format = "pdf"
    )



p = plot.SpectrumPlot(
    fname = 'spectrum_plot_test_1.pdf',
    mzs = scan.mzs,
    intensities = scan.intensities,
    annotations = scan.annot,
    scan_id = scan.scan_id,
    ionmode = ionmode,
    sample_name = 'BPI_invivo',
    grid_cols = 1,
    format = "pdf",
    figsize = (5, 3),
    )

