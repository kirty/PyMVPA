# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:

'''Support for ANFI SUMA surface specification (.spec) files
Includes I/O support and generating spec files that combine both hemispheres'''


import re, datetime, os, copy
import utils, surf_fs_asc

_COMPREFIX = 'CoM' #  for surfaces that were rotated around center of mass

class SurfaceSpec(object):
    def __init__(self, surfaces, states=None, groups=None, indir=None):
        self.surfaces = surfaces
        self.indir = indir

        if states is None:
            states = list(set(surface['SurfaceState'] for surface in surfaces))

        self.states = states

        if groups is None:
            groups = ['all']

        self.groups = groups
        self._fix()

    def _fix(self):
        # performs replacements of aliases to ensure consistent naming
        repls = [('freesurfersurface', 'SurfaceName')]


        for s in self.surfaces:
            for src, trg in repls:
                keys = s.keys()
                for i in xrange(len(keys)):
                    key = keys[i]
                    if key.lower() == src:
                        v = s.pop(key)
                        s[trg] = v



    def __repr__(self):
        return '%d surfaces' % len(self.surfaces)

    def as_string(self):
        lines = []
        lines.append('# Created %s' % str(datetime.datetime.now()))
        lines.append('')
        lines.append('# Define the group')
        lines.extend('    Group = %s' % g for g in self.groups)
        lines.append('')
        lines.append('# Define the states')
        lines.extend('    StateDef = %s' % s for s in self.states)
        lines.append('')
        for surface in self.surfaces:
            lines.append('NewSurface')
            lines.extend('    %s = %s' % kv for kv in surface.iteritems())
            lines.append('')

        return "\n".join(lines)

    def add_surface(self, state):
        self.surfaces.append(state)
        surfstate = state['SurfaceState']
        if not surfstate in self.states:
            self.states.append(surfstate)

    def find_surface(self, surfacestate):
        return [(i, surface) for (i, surface) in enumerate(self.surfaces)
                 if surface['SurfaceState'] == surfacestate]

    def same_states(self, other):
        return set(self.states) == set(other.states)

    def write(self, fnout, overwrite=False):
        if not overwrite and os.path.exists(fnout):
            print '%s already exists - not overwriting' % fnout
        with open(fnout, 'w') as f:
            f.write(self.as_string())

def hemi_pairs_add_views(spec_left, spec_right, state, indir=None, overwrite=False):
    '''adds views for medial, superior, inferior, anterior, posterior viewing
    of two surfaces together. Also generates these surfaces'''

    ext = '.asc'

    if indir is None:
        indir = os.path.curdir

    if not spec_left.same_states(spec_right):
        raise ValueError('Incompatible states for left and right')

    #views = collections.OrderedDict(m='medial', s='superior', i='inferior', a='anterior', p='posterior')
    # for compatibility use a normal dict
    views = dict(m='medial', s='superior', i='inferior', a='anterior', p='posterior')
    viewkeys = ['m', 's', 'i', 'a', 'p']

    spec_both = [spec_left, spec_right]
    spec_both_new = map(copy.deepcopy, spec_both)

    for view in viewkeys:
        longname = views[view]
        oldfns = []
        newfns = []
        for i, spec in enumerate(spec_both):

            idxdef = spec.find_surface(state)
            if len(idxdef) != 1:
                raise ValueError('Not unique surface with state %s' % state)
            surfidx, surfdef = idxdef[0]

            # take whichever is there (in order of preference)
            # shame that python has no builtin foldr
            surfnamelabels = ['SurfaceName', 'FreeSurferSurface']
            surfname = utils.foldr(surfdef.get, None, surfnamelabels)

            fn = os.path.join(indir, surfname)
            if not os.path.exists(fn):
                raise ValueError("File not found: %s" % fn)

            if not surfname.endswith(ext):
                error('Expected extension %s for %s' % (ext, fn))
            oldfns.append(fn) # store old name

            shortfn = surfname[:-(len(ext))]
            newsurfname = '%s%s%s%s' % (shortfn, _COMPREFIX, longname, ext)
            newfn = os.path.join(indir, newsurfname)

            newsurfdef = copy.deepcopy(surfdef)

            # ensure no naming cnoflicts
            for surfnamelabel in surfnamelabels:
                if surfnamelabel in newsurfdef:
                    newsurfdef.pop(surfnamelabel)
            newsurfdef['SurfaceName'] = newsurfname
            newsurfdef['SurfaceState'] = '%s%s%s' % (_COMPREFIX, view, state)
            spec_both_new[i].add_surface(newsurfdef)
            newfns.append(newfn)

        if all(map(os.path.exists, newfns)) and not overwrite:
            print "Output already exist for %s" % longname
        else:
            surf_left, surf_right = map(surf_fs_asc.read, oldfns)
            surf_both_moved = surf_fs_asc.hemi_pairs_reposition(surf_left,
                                                                surf_right,
                                                                view)

            for fn, surf in zip(newfns, surf_both_moved):
                surf_fs_asc.write(surf, fn, overwrite)
                print "Written %s" % fn

    return tuple(spec_both_new)


def combine_left_right(left, right):
    if set(left.states) != set(right.states):
        raise ValueError('Incompatible states')

    mergeable = lambda x : ((x['Anatomical'] == 'Y') or
                             x['SurfaceState'].startswith(_COMPREFIX))
    to_merge = map(mergeable, left.surfaces)

    s_left, s_right = left.surfaces, right.surfaces

    hemis = ['l', 'r']
    states = [] # list of states
    surfaces = [] # surface specs
    for i, merge in enumerate(to_merge):
        ll, rr = map(copy.deepcopy, [s_left[i], s_right[i]])

        # for now assume they are in the same order for left and right
        if ll['SurfaceState'] != rr['SurfaceState']:
            raise ValueError('Different states for left (%r) and right (%r)' %
                                                                     (ll, rr))

        if merge:
            state = ll['SurfaceState']
            states.append(state)
            surfaces.extend([ll, rr])
        else:
            for hemi, surf in zip(hemis, [ll, rr]):
                state = '%s_%sh' % (surf['SurfaceState'], hemi)
                states.append(state)
                surf['SurfaceState'] = state
                surfaces.append(surf)

    spec = SurfaceSpec(surfaces, states, groups=left.groups)

    return spec

def merge_left_right(both):
    # merges the result form combine_left_right
    # output is a tuple with the surface defintion, and a list
    # of pairs of filenames of surfaces that have to be merged

    lr_infixes = ['_lh', '_rh']
    m_infix = '_mh'

    m_surfaces = []
    m_states = []
    m_groups = both.groups

    # mapping from output filename to tuples with input file names
    # of surfaces to be merged
    merge_filenames = dict()

    _STATE = 'SurfaceState'
    _NAME = 'SurfaceName'

    for i, left in enumerate(both.surfaces):
        for j, right in enumerate(both.surfaces):
            if j <= i:
                continue

            if left[_STATE] == right[_STATE]:
                # apply transformation in naming to both
                # surfaces. result should be the same

                fns = []
                mrg = [] # versions ok to be merged

                for ii, surf in enumerate([left, right]):
                    newsurf = dict()
                    fns.append(surf[_NAME])
                    for k, v in surf.iteritems():
                        newsurf[k] = v.replace(lr_infixes[ii], m_infix)

                        # ensure that right hemi identical to left
                        if ii > 0 and newsurf[k] != mrg[ii - 1][k]:
                            raise ValueError("No match: %r -> %r" % (k, v))
                    mrg.append(newsurf)

                m_states.append(left[_STATE])
                m_surfaces.append(mrg[0])
                merge_filenames[newsurf[_NAME]] = tuple(fns)

    m = SurfaceSpec(m_surfaces, states=m_states, groups=m_groups)

    return m, merge_filenames








def write(fnout, spec, overwrite=False):
    if type(spec) is str and isinstance(fnout, SurfaceSpec):
        fnout, spec = spec, fnout
    spec.write(fnout, overwrite=overwrite)

def read(fn):
    surfaces = []
    states = []
    groups = []
    current_surface = None


    surface_names = []

    with open(fn) as f:
        lines = f.read().split('\n')
        for line in lines:
            m = re.findall(r'\W*([\w\.]*)\W*=\W*([\w\.]*)\W*', line)
            if len(m) == 1:
                k, v = m[0]
                if k == 'StateDef':
                    states.append(v)
                elif k == 'Group':
                    groups.append(v)
                elif not current_surface is None:
                    current_surface[k] = v
            elif 'NewSurface' in line:
                #current_surface = collections.OrderedDict()
                # for comppatibility use a normal dict (which loses the order)
                current_surface = dict()
                surfaces.append(current_surface)

    return SurfaceSpec(surfaces=surfaces or None,
                      states=states or None,
                      groups=groups or None)


def canonical_filename(icold=None, hemi=None, suffix=None):
    if suffix is None:
        suffix = ''
    return '%sh_ico%d%s.spec' % (hemi, icold, suffix)

def find_file(directory, icold=None, hemi=None, suffix=None):
    fn = os.path.join(directory, canonical_filename(icold=icold,
                                                    hemi=hemi,
                                                    suffix=suffix))
    if not os.path.exists(fn):
        raise ValueError("not found: %s" % fn)
    return fn


if __name__ == '__main__':
    fL = '/Users/nick/_tmp/newref/lh_ico32_al.spec'
    fR = '/Users/nick/_tmp/newref/rh_ico32_al.spec'
    fB = '/Users/nick/_tmp/newref/bh_ico32_al.spec'

    import mvpa2.misc.surfing.afni_suma_spec as spec
    sL = spec.read(fL)
    sR = spec.read(fR)
    sB = spec.read(fB)

    print sB
    mm = spec.merge_left_right(sB)
    print mm