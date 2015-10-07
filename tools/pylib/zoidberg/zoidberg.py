from __future__ import division
from builtins import object
from past.utils import old_div

import numpy as np
from boututils import datafile as bdata

# PyEVTK might be called pyevtk or evtk, depending on where it was
# installed from
have_evtk = True
try:
    from pyevtk.hl import gridToVTK
except ImportError:
    try:
        from evtk.hl import gridToVTK
    except ImportError:
        have_evtk = False

import matplotlib.pyplot as plt

import grid
import field
import fieldtracer

def plot_poincare():
    nplot=3
    sym=[".k", ".b", ".r", ".g"]
    phivals = np.arange(100*rot_transf * nplot)*2.*np.pi/(rot_transf*nplot)

    for xpos in xcenter + np.linspace(0, 0.5*np.max(xarray),10):
        pos = (xpos, zcenter)
        result = odeint(field_direction, pos, phivals)
        # import pdb; pdb.set_trace()
        for p in range(nplot):
            plt.plot(result[p::nplot,0], result[p::nplot,1], sym[p])

    plt.xlabel("Radius [m]", fontsize=20)
    plt.ylabel("Height [m]", fontsize=20)
    plt.tick_params(axis='both', labelsize=15)

    for p in range(nplot):
        plt.plot([], [], sym[p], label=r'$Y = \left(%d * L/%d\right)$' % (p, nplot*rot_transf))

    plt.legend()

    plt.savefig("flux_surfaces.eps")

    plt.show()

def make_maps(grid, magnetic_field):
    """Make the forward and backward FCI maps

    Should take B function/values as input
    """

    nx, ny, nz = (grid.nx, grid.ny, grid.nz)

    # Arrays to store X index at end of field-line
    # starting from (x,y,z) and going forward in toroidal angle (y)
    forward_xt_prime = np.zeros( (nx, ny, nz) )
    forward_zt_prime = np.zeros( (nx, ny, nz) )

    # Same but going backwards in toroidal angle
    backward_xt_prime = np.zeros( (nx, ny, nz) )
    backward_zt_prime = np.zeros( (nx, ny, nz) )

    field_tracer = fieldtracer.FieldTracer(grid, magnetic_field)

    for j in range(ny):
        # Go forwards from yarray[j] by an angle delta_y
        coord = field_tracer.follow_field_line(grid.yarray[j], grid.delta_y)
        forward_xt_prime[:,j,:] = coord[:,:,0] / grid.delta_x # X index
        forward_zt_prime[:,j,:] = coord[:,:,1] / grid.delta_z # Z index

        # Go backwards from yarray[j] by an angle -delta_y
        coord = field_tracer.follow_field_line(grid.yarray[j], -grid.delta_y)
        backward_xt_prime[:,j,:] = coord[:,:,0] / grid.delta_x # X index
        backward_zt_prime[:,j,:] = coord[:,:,1] / grid.delta_z # Z index

        print(100.*j/ny)

    maps = {
        'forward_xt_prime' : forward_xt_prime,
        'forward_zt_prime' : forward_zt_prime,
        'backward_xt_prime' : backward_xt_prime,
        'backward_zt_prime' : backward_zt_prime
    }

    return maps

def write_maps(grid, magnetic_field, maps, gridfile='fci.grid.nc', legacy=False):
    """Write FCI maps to BOUT++ grid file

    Inputs
    ------
    grid           - Grid generated by Zoidberg
    magnetic_field - Zoidberg magnetic field object
    maps           - Dictionary of FCI maps
    gridfile       - Output filename
    legacy         - If true, write FCI maps using FFTs
    """

    nx, ny, nz = (grid.nx, grid.ny, grid.nz)
    xarray, yarray, zarray = (grid.xarray, grid.yarray, grid.zarray)

    g_22 = np.zeros((nx,ny)) + 1./grid.Rmaj**2

    totalbx = np.zeros((nx,ny,nz))
    totalbz = np.zeros((nx,ny,nz))
    Bxy = np.zeros((nx,ny,nz))
    for i in np.arange(0,nx):
        for j in np.arange(0,ny):
            for k in np.arange(0,nz):
                Bxy[i,j,k] = np.sqrt((magnetic_field.Bxfunc(xarray[i],zarray[k],yarray[j])**2
                                      + magnetic_field.Bzfunc(xarray[i],zarray[k],yarray[j])**2))
                totalbx[i,j,k] = magnetic_field.Bxfunc(xarray[i],zarray[k],yarray[j])
                totalbz[i,j,k] = magnetic_field.Bzfunc(xarray[i],zarray[k],yarray[j])

    with bdata.DataFile(gridfile, write=True, create=True) as f:
        ixseps = nx+1
        f.write('nx', grid.nx)
        f.write('ny', grid.ny)
        if not legacy:
            # Legacy files don't need nz
            f.write('nz', grid.nz)

        f.write("dx", grid.delta_x)
        f.write("dy", grid.delta_y)

        f.write("ixseps1",ixseps)
        f.write("ixseps2",ixseps)

        f.write("g_22", g_22)

        f.write("Bxy", Bxy[:,:,0])
        f.write("bx", totalbx)
        f.write("bz", totalbz)

        # Legacy grid files need to FFT 3D arrays
        if legacy:
            from boutdata.input import transform3D
            f.write('forward_xt_prime',  transform3D(maps['forward_xt_prime']))
            f.write('forward_zt_prime',  transform3D(maps['forward_zt_prime']))

            f.write('backward_xt_prime', transform3D(maps['backward_xt_prime']))
            f.write('backward_zt_prime', transform3D(maps['backward_zt_prime']))
        else:
            f.write('forward_xt_prime',  maps['forward_xt_prime'])
            f.write('forward_zt_prime',  maps['forward_zt_prime'])

            f.write('backward_xt_prime', maps['backward_xt_prime'])
            f.write('backward_zt_prime', maps['backward_zt_prime'])


def fci_to_vtk(infile, outfile, scale=5):

    if not have_evtk:
        return

    with bdata.DataFile(infile, write=False, create=False) as f:
        bx = f.read('bx')
        bz = f.read('bz')
        if bx is None:
            xt_prime = f.read('forward_xt_prime')
            zt_prime = f.read('forward_zt_prime')
            array_indices = indices(xt_prime.shape)
            bx = xt_prime - array_indices[0,...]
            bz = zt_prime - array_indices[2,...]
        by = np.ones(bx.shape)

        nx, ny, nz = bx.shape

        dx = f.read('dx')
        dy = f.read('dy')
        dz = nx*dx / nz

    x = np.linspace(0, nx*dx, nx)
    y = np.linspace(0, ny*dy, ny)
    z = np.linspace(0, nz*dz, nz)

    gridToVTK(outfile, x*scale, y, z*scale, pointData={'B' : (bx*scale, by*dy, bz*scale)})
