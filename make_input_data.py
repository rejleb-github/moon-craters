#!/usr/bin/env python
"""
Usage: crater_make_dataset.py

Functions for combining LRO LOLA Elevation Model heightmap (https://astrogeology.usgs.gov/search/details/Moon/LRO/LOLA/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014/cub) and Goran Salamuniccar's database (https://astrogeology.usgs.gov/search/map/Moon/Research/Craters/GoranSalamuniccar_MoonCraters).  

The LRO image is a "simple cylindrical" projection, which is synonymous with Equidistant Cylindrical or Plate Carree (http://desktop.arcgis.com/en/arcmap/10.3/guide-books/map-projections/equidistant-cylindrical.htm).
"""
from __future__ import absolute_import, division, print_function

import numpy as np
import pandas as pd
from PIL import Image, ImageChops, ImageOps
import cartopy.crs as ccrs
import cartopy.img_transform as cimg
import matplotlib.pyplot as plt
import matplotlib.axes as mplax
import image_slicer as imsl
import glob
import collections
import pickle
import re


########## Read Cratering CSVs ###########################

def ReadSalamuniccarCraterCSV(filename="./LU78287GT.csv", dropfeatures=False,
                                sortlat=True):
    """Reads Goran Salamuniccar crater file CSV.

    Parameters
    ----------
    filename : str
        csv file of craters
    dropfeatures : bool
        If true, drop sub-features of craters (listed with
        "A", "B", "C"...), leaving only the whole crater 
        (listed as "r").

    Returns
    -------
    craters : pandas.DataFrame
        Craters data frame.
    """
    # Read in crater names
    craters_names = ["ID", "Long", "Lat", "Radius (deg)", 
                        "Diameter (km)", "D_range", "p", "Name"]
    craters_types = [str, float, float, float, float, float, int, str]
    craters = pd.read_csv(open(filename, 'r'), sep=',', 
        usecols=list(range(8)), header=0, engine="c", encoding = "ISO-8859-1",
        names=craters_names, dtype=dict(zip(craters_names, craters_types)))

    # Truncate cyrillic characters
    craters["Name"] = craters["Name"].str.split(":").str.get(0)

    if dropfeatures:
        DropCraterFeatures(craters)

    if sortlat:
        craters.sort_values(by='Lat', inplace=True)

    return craters


def DropCraterFeatures(craters):
    """Drops named crater sub-features (listed with
        "A", "B", "C"...), leaving only the whole crater 
        (listed as "r").

    Parameters
    ----------
    craters : pandas.DataFrame
        Craters data frame.
    """

    # String matching thingy
    def match_end(s):
        if re.match(r" [A-Z]", s[-2:]):
            return True
        return False

    # Find all crater names that ends with A - Z
    basenames = \
            craters.loc[craters["Name"].notnull(), "Name"].apply(match_end)
    drop_index = basenames[basenames].index
    craters.drop(drop_index, inplace=True)


def ReadAlanCraterCSV(filename="./alanalldata.csv", sortlat=True):
    """Reads crater file CSV from Alan (LROC 5 - 20 km craters)

    Parameters
    ----------
    filename : str
        csv file of craters

    Returns
    -------
    craters : pandas.DataFrame
        Craters data frame.
    """
    craters = pd.read_csv(filename, header=0)
    if sortlat:
        craters.sort_values(by='Lat', inplace=True)

    return craters


def ReadCombinedCraterCSV(filealan="./alanalldata.csv", filelu="./LU78287GT.csv", 
                            dropfeatures=False):
    """Combines LROC 5 - 20 km crater dataset with Goran Salamuniccar craters that
    are > 20 km.

    Parameters
    ----------
    filealan : str
        LROC crater file location
    filelu : str
        Salamuniccar crater file location
    dropfeatures : bool
        If true, drop sub-features of craters (listed with
        "A", "B", "C"...), leaving only the whole crater 
        (listed as "r").

    Returns
    -------
    craters : pandas.DataFrame
        Craters data frame.
    """

    # Read in LU crater names
    craters_names = ["Long", "Lat", "Radius (deg)", 
                        "Diameter (km)", "D_range", "p", "Name"]
    craters_types = [float, float, float, float, float, int, str]
    craters = pd.read_csv(open(filelu, 'r'), sep=',', 
        usecols=list(range(1, 8)), header=0, engine="c", encoding = "ISO-8859-1",
        names=craters_names, dtype=dict(zip(craters_names, craters_types)))

    # Truncate cyrillic characters
    craters["Name"] = craters["Name"].str.split(":").str.get(0)

    if dropfeatures:
        DropCraterFeatures(craters)

    craters.drop(["Radius (deg)", "D_range", "p", "Name"], axis=1, inplace=True)
    craters = craters[craters["Diameter (km)"] > 20]

    craters_alan = pd.read_csv(filealan, header=0, usecols=list(range(2, 5)))

    craters = pd.concat([craters, craters_alan], axis=0, ignore_index=True,
                            copy=True)

    craters.sort_values(by='Lat', inplace=True)
    craters.reset_index(inplace=True, drop=True)

    return craters


############# Coordinates to pixels projections ###############


def coord2pix(cx, cy, cdim, imgdim, origin="upper"):
    """Converts coordinate x/y to image pixel locations.

    Parameters
    ----------
    cx : float or ndarray
        Coordinate x
    cy : float or ndarray
        Coordinate y
    cdim : list-like
        Coordinate limits (x_min, x_max, y_min, y_max) of image
    imgdim : list, tuple or ndarray
        Length and height of image, in pixels
    origin : "upper" or "lower"
        Based on imshow convention for displaying image y-axis.
        "upper" means that [0,0] is upper-left corner of image;
        "lower" means it is bottom-left.

    Returns
    -------
    x : float or ndarray
        pixel x positions
    y : float or ndarray
        pixel y positions
    """

    x = imgdim[0] * (cx-cdim[0]) / (cdim[1]-cdim[0])

    if origin == "lower":
        y = imgdim[1] * (cy-cdim[2])/(cdim[3]-cdim[2])
    else:
        y = imgdim[1] * (cdim[3]-cy)/(cdim[3]-cdim[2])

    return x, y


def pix2coord(x, y, cdim, imgdim, origin="upper"):
    """Converts image pixel locations to Plate Carree lat/long.
    Assumes central meridian is at 0 (so long in [-180, 180) ).

    Parameters
    ----------
    x : float or ndarray
        pixel x positions
    y : float or ndarray
        pixel y positions
    cdim : list-like
        Coordinate limits (x_min, x_max, y_min, y_max) of image
    imgdim : list, tuple or ndarray
        Length and height of image, in pixels
    origin : "upper" or "lower"
        Based on imshow convention for displaying image y-axis.
        "upper" means that [0,0] is upper-left corner of image;
        "lower" means it is bottom-left.

    Returns
    -------
    cx : float or ndarray
        Coordinate x
    cy : float or ndarray
        Coordinate y
    """

    cx = (x/imgdim[0]) * (cdim[1]-cdim[0]) + cdim[0]

    if origin == "lower":
        cy = (y/imgdim[1]) * (cdim[3]-cdim[2]) + cdim[2]
    else:
        cy = cdim[3] - (y/imgdim[1]) * (cdim[3]-cdim[2])

    return cx, cy


############# Metres to Pixels ###############


def km2pix(imgheight, latextent, dc=1., a=1737.4):
    """Returns conversion from km to pixels.

    Parameters
    ----------
    imgheight : float
        Height of image in pixels
    latextent : float
        Latitude extent of image in degrees
    dc : float from 0 to 1
        Scaling factor for distortions
    a : float
        Moon radius

    Returns
    -------
    km2pix : float
        Conversion factor pix/km
    """
    return (180./np.pi)*imgheight*dc/latextent/a


##############################################


############# Warp Images and CSVs ###############

def regrid_shape_aspect(regrid_shape, target_extent):
    """
    Helper function copied from cartopy.img_transform for 
    setting regridding shape which is used in several
    plotting methods.
    """
    if not isinstance(regrid_shape, collections.Sequence):
        target_size = int(regrid_shape)
        x_range, y_range = np.diff(target_extent)[::2]
        desired_aspect = x_range / y_range
        if x_range >= y_range:
            regrid_shape = (target_size * desired_aspect, target_size)
        else:
            regrid_shape = (target_size, target_size / desired_aspect)
    return regrid_shape


def WarpImage(img, iproj, iextent, oproj, oextent,
                origin="upper", rgcoeff=1.2):
    """
    Warps images with cartopy.img_transform.warp_array,
    then plots them with imshow.  Based on
    cartopy.mpl.geoaxes.imshow.  Parameter descriptions
    are identical to 
    """

    if iproj == oproj:
        raise Warning("WARNING: input and output transforms are identical!"
                       "Returing input!")
        return img

    else:

        if origin == 'upper':
            # Regridding operation implicitly assumes origin of 
            # image is 'lower', so adjust for that here.
            img = img[::-1]

        # The 1.2 is padding when we rescale the image with imshow
        regrid_shape = rgcoeff*min(img.shape)
        regrid_shape = regrid_shape_aspect(regrid_shape,
                                         oextent)

        # cimg.warp_array uses cimg.mesh_projection, which
        # cannot handle any zeros being used in iextent.  Create
        # iextent_nz to fix
        iextent_nz = np.array(iextent)
        iextent_nz[iextent_nz == 0] = 1e-8
        iextent_nz = list(iextent_nz)

        imgout, extent = cimg.warp_array(img,
                             source_proj=iproj,
                             source_extent=iextent_nz,
                             target_proj=oproj,
                             target_res=regrid_shape,
                             target_extent=oextent,
                             mask_extrapolated=True)

        if origin == 'upper':
            # Transform back
            imgout = imgout[::-1]

        return imgout


# https://stackoverflow.com/questions/2563822/how-do-you-composite-an-image-onto-another-image-with-pil-in-python

def WarpImagePad(img, iproj, iextent, oproj, oextent, 
                origin="upper", rgcoeff=1.2, fillbg="white"):
    """
    Wrapper for WarpImage that adds padding to warped
    image to make it the same size as the original.

    Parameters
    ----------
    img : numpy.ndarray
        Image as a 2D array
    iproj : cartopy.crs.Projection instance
        Input coordinate system
    iextent : list-like
        Coordinate limits (x_min, x_max, y_min, y_max) 
        of input
    oproj : cartopy.crs.Projection instance
        Output coordinate system
    oextent : list-like
        Coordinate limits (x_min, x_max, y_min, y_max) 
        of output
    origin : "lower" or "upper"
        Based on imshow convention for displaying image y-axis.
        "upper" means that [0,0] is upper-left corner of image;
        "lower" means it is bottom-left.
    rgcoeff : float
        Fractional size increase of transformed image height;
        generically set to 1.2 to prevent loss of fidelity
        during transform (though warping can be so extreme
        that this might be meaningless)      

    Returns
    -------
    imgo : PIL.Image.Image
        Warped image with padding
    imgw.size : tuple
        Width, height of picture without padding
    offset : tuple
        Pixel width of (left, top)-side padding
    """

    if type(img) == Image.Image:
        img = np.asanyarray(img)

    # Set background colour
    if fillbg == "white":
        bgval = 255
    else:
        bgval = 0

    # Warp image
    imgw = WarpImage(img, iproj, iextent, oproj, oextent, 
                origin=origin, rgcoeff=rgcoeff)

    # Remove mask, turn image into Image.Image
    imgw = np.ma.filled(imgw, fill_value=bgval)
    imgw = Image.fromarray(imgw, mode="L")

    # Resize to height of original, maintaining
    # aspect ratio.  Note img.shape = height, width, and
    # imgw.size and imgo.size = width, height
    imgw_loh = imgw.size[0] / imgw.size[1]

    # If imgw is stretched horizontally compared to img
    if imgw_loh > img.shape[1]/img.shape[0]:
        imgw = imgw.resize([img.shape[0], 
                    int(np.round(img.shape[0] / imgw_loh))])
    # If imgw is stretched vertically
    else:
        imgw = imgw.resize([int(np.round(imgw_loh*img.shape[0])), 
                    img.shape[0]])

    # Make background image and paste two together
    imgo = Image.new('L', (img.shape[1], img.shape[0]), 
                        (bgval))
    offset = ((imgo.size[0] - imgw.size[0]) // 2, 
                (imgo.size[1] - imgw.size[1]) // 2)
    imgo.paste(imgw, offset)

    return imgo, imgw.size, offset


def WarpCraterLoc(craters, geoproj, oproj, 
                oextent, imgdim, llbd=None,
                origin="upper"):
    """
    Wrapper for WarpImage that adds padding to warped
    image to make it the same size as the original.

    Parameters
    ----------
    craters : pandas.DataFrame
        Crater info
    geoproj : cartopy.crs.Geodetic instance
        Input lat/long coordinate system
    oproj : cartopy.crs.Projection instance
        Output coordinate system
    oextent : list-like
        Coordinate limits (x_min, x_max, y_min, y_max) 
        of output
    imgdim : list, tuple or ndarray
        Length and height of image, in pixels
    llbd : list-like
        Long/lat limits (long_min, long_max, 
        lat_min, lat_max) of image
    origin : "lower" or "upper"
        Based on imshow convention for displaying image y-axis.
        "upper" means that [0,0] is upper-left corner of image;
        "lower" means it is bottom-left.

    Returns
    -------
    ctr_wrp : pandas.DataFrame
        DataFrame that includes pixel x, y positions
    """

    # Get subset of craters within llbd limits
    if llbd is None:
        ctr_wrp = craters
    else:
        ctr_xlim = (craters["Long"] > llbd[0]) & \
                    (craters["Long"] < llbd[1])
        ctr_ylim = (craters["Lat"] > llbd[2]) & \
                    (craters["Lat"] < llbd[3])
        ctr_wrp = craters.loc[ctr_xlim & \
                                ctr_ylim, :].copy()

    # Get output projection coords.
    # [:,:2] becaus we don't need elevation data
    # If statement is in case ctr_wrp has nothing in it
    if ctr_wrp.shape[0]:
        ilong = ctr_wrp["Long"].as_matrix()
        ilat = ctr_wrp["Lat"].as_matrix()
        res = oproj.transform_points(x=ilong, y=ilat,
                                    src_crs=geoproj)[:,:2]

        # Get output
        ctr_wrp["x"], ctr_wrp["y"] = coord2pix(res[:,0], 
                        res[:,1], oextent, imgdim, 
                        origin=origin)
    else:
        ctr_wrp["x"] = []
        ctr_wrp["y"] = []

    return ctr_wrp



############# Warp Plate Carree to Orthographic ###############


def PlateCarree_to_Orthographic(img, oname, llbd, craters, 
                                iglobe=None, ctr_sub=False, 
                                origin="upper", rgcoeff=1.2,
                                dontsave=False, slivercut=0.):
    """Transform Plate Carree image and associated csv file 
    into Orthographic

    Parameters
    ----------
    img : PIL.Image.image or str
        File or filename
    oname : str
        Output filename
    llbd : list-like
        Long/lat limits (long_min, long_max, 
        lat_min, lat_max) of image
    craters : pandas.DataFrame
        Craters dataframe
    iglobe : cartopy.crs.Geodetic instance
        Globe for images.  If False, defaults to spherical Moon.
    ctr_sub : bool
        If True, assumes craters dataframe includes only craters
        within image.  If False, llbd used to cut craters
        from outside image out of (copy of) dataframe.
    origin : "lower" or "upper"
        Based on imshow convention for displaying image y-axis.
        "upper" means that [0,0] is upper-left corner of image;
        "lower" means it is bottom-left.
    rgcoeff : float
        Fractional size increase of transformed image height;
        generically set to 1.2 to prevent loss of fidelity
        during transform (though warping can be so extreme
        that this might be meaningless)
    dontsave : bool
        Save or not save, that is the queseiton.
    slivercut : float from 0 to 1
        If transformed image aspect ratio is to narrow (and would
        lead to a lot of padding, return null images)

    Returns (only if dontsave = True)
    ---------------------------------
    imgo : PIL.Image.image
        Transformed, padded image in PIL.Image format
    ctr_xy : pandas.DataFrame
        Craters with transformed x, y pixel positions and
        pixel radii
    """

    # If user doesn't provide moon globe properties
    if not iglobe:
        iglobe = ccrs.Globe(semimajor_axis=1737400, 
                        semiminor_axis=1737400,
                        ellipse=None)

    # Set up Geodetic (long/lat), Plate Carree (usually long/lat, but
    # not when globe != WGS84) and Orthographic projections
    geoproj = ccrs.Geodetic(globe=iglobe)
    iproj = ccrs.PlateCarree(globe=iglobe)
    oproj = ccrs.Orthographic(central_longitude=np.mean(llbd[:2]), 
                            central_latitude=np.mean(llbd[2:]), 
                            globe=iglobe)

    # Create and transform coordinates of image corners and
    # edge midpoints.  Due to Plate Carree and Orthographic's symmetries,
    # max/min x/y values of these 9 points represent extrema
    # of the transformed image.
    xll = np.array([llbd[0], np.mean(llbd[:2]), llbd[1]])
    yll = np.array([llbd[2], np.mean(llbd[2:]), llbd[3]])
    xll, yll = np.meshgrid(xll, yll)
    xll = xll.ravel(); yll = yll.ravel()

    # [:,:2] becaus we don't need elevation data
    res = iproj.transform_points(x=xll, y=yll,
                                src_crs=geoproj)[:,:2]
    iextent = [min(res[:,0]), max(res[:,0]), 
                min(res[:,1]), max(res[:,1])]

    res = oproj.transform_points(x=xll, y=yll,
                                src_crs=geoproj)[:,:2]
    oextent = [min(res[:,0]), max(res[:,0]), 
                min(res[:,1]), max(res[:,1])]

    # Sanity check for narrow images; done before
    # the most expensive part of function
    oaspect = (oextent[1] - oextent[0]) / (oextent[3] - oextent[2])
    if oaspect < slivercut:
        if dontsave:
            return [None, None]
        return

    if type(img) != Image.Image:
        img = Image.open(img).convert("L")

    imgo, imgwshp, offset = WarpImagePad(img, iproj, iextent, 
                    oproj, oextent, origin=origin, rgcoeff=rgcoeff, 
                    fillbg="black")

    # Convert crater x, y position
    if ctr_sub:
        llbd_in = None
    else:
        llbd_in = llbd
    ctr_xy = WarpCraterLoc(craters, geoproj, oproj, 
                oextent, imgwshp, llbd=llbd_in,
                origin=origin)
    # Shift crater x, y positions by offset
    # (origin doesn't matter for y-shift, since
    # padding is symmetric)
    ctr_xy.loc[:, "x"] += offset[0]
    ctr_xy.loc[:, "y"] += offset[1]

    # Pixel scale for orthographic determined (for images small enough
    # that tan(x) approximately equals x + 1/3x^3 + ... remember you
    # can check size of next expansion term!) by l = R_moon*theta,
    # where theta is the latitude extent of the centre of the image.
    # Because projection transform doesn't guarantee central axis
    # will keep its pixel resolution, we need to calculate the
    # conversion coefficient C = (res[7,1] - res[1,1])/(oextent[3] - oextent[2])
    # C0*pix height/C = theta (theta = latitude extent; C0
    # is the theta per pixel conversion for the Plate Carree image).
    # Thus l_ctr = R_moon*C0*pix_ctr/C.
    Cd = (res[7,1] - res[1,1])/(oextent[3] - oextent[2])
    if Cd < 0.7:
        raise AssertionError("Cd cannot be {0:.2f}!".format(Cd))
    pxperkm = km2pix(imgo.size[1], llbd[3] - llbd[2], \
                        dc=Cd, a=1737.4)
    ctr_xy["Diameter (pix)"] = ctr_xy["Diameter (km)"] * pxperkm

    if dontsave:
        return [imgo, ctr_xy]

    imgo.save(oname)
    ctr_xy.to_csv(oname.split(".png")[0] + ".csv", index=False)


# Much hackier way of making images - don't use (unless you have to)!
#fig = plt.figure(figsize=[img.shape[1]/200., img.shape[0]/200.])

## For a uniform background without axes
#axbg = fig.add_axes([0., 0., 1., 1.])
#axbg.set_xlim([0,1]); axbg.set_ylim([0,1*img.shape[0]/img.shape[1]])
#axbg.imshow(np.tile(np.array([[[200, 200, 255]]], dtype=np.uint8), [2, 2, 1]), origin='upper')
#axbg.set_axis_off()
#a=fig.gca(); a.set_xticks([]); a.set_yticks([])

#ax = fig.add_axes([0., 0., 1., 1.], projection=projection); ax.background_patch.set_fill(False)
#ax.set_extent([min(obounds[:,0]), max(obounds[:,0]), 
#                min(obounds[:,1]), max(obounds[:,1])], crs=projection)
#ax.imshow(img, transform=img_proj, extent=img_extent, cmap="Greys_r", origin="upper", regrid_shape=1.5*img.shape[0])
#ax.set_axis_off()

#plt.savefig("test.png", dpi=200, transparent=False, bbox_inches='tight', pad_inches=0)


############# Create Tiled Orthographic Dataset #############


def AddPlateCarree_XY(craters, imgdim, cdim=[-180, 180, -90, 90], 
                        origin="upper"):
    """Adds x and y pixel locations to craters dataframe.

    Parameters
    ----------
    craters : pandas.DataFrame
        Crater info
    imgdim : list, tuple or ndarray
        Length and height of image, in pixels
    origin : "upper" or "lower"
        Based on imshow convention for displaying image y-axis.
        "upper" means that [0,0] is upper-left corner of image;
        "lower" means it is bottom-left.
    """
    x, y = coord2pix(craters["Long"].as_matrix(), craters["Lat"].as_matrix(), 
                        cdim, imgdim, origin=origin)
    craters["x"] = x
    craters["y"] = y


def CreatePlateCarreeDataSet(img, craters, splitnum, outprefix="out",
                            savecoords=False):
    """Creates set of images and accompanying csvs of crater data.

    Parameters
    ----------
    img : str
        Name of file.
    craters : pandas.DataFrame
        Crater dataframe  
    splitnum : int
        Number of subfiles to split image into.
    outprefix : str
        Output files' prefix.
    savecoords : bool
        If True, saves tile coordinates
    """

    tiles = imsl.slice(img, splitnum, save=False)
    imgshape = list(imsl.get_combined_size(tiles))

    # Origin is upper for image_slicer, and shapes
    # are x-axis ("columns") first, rather than
    # rows as in plt.imread
    AddPlateCarree_XY(craters, imgshape)

    for tile in tiles:
        # Get x, y limits of image
        ctr_xlim = (craters["x"] > tile.coords[0]) & \
                    (craters["x"] < tile.coords[0] + tile.image.size[0])
        ctr_ylim = (craters["y"] > tile.coords[1]) & \
                    (craters["y"] < tile.coords[1] + tile.image.size[1])

        # Get subset of craters within these limits
        curr_craters = craters.loc[ctr_xlim & ctr_ylim, :].copy()
        curr_craters.loc[:,"x"] -= tile.coords[0]
        curr_craters.loc[:,"y"] -= tile.coords[1]

        # Obtain output image name
        outname = tile.generate_filename(prefix=outprefix,
                          format='png', path=True)

        tile.save(outname, format="png")
        curr_craters.to_csv(outname.split(".png")[0] + ".csv", index=False)

    if savecoords:
        tileval = []
        tilename = []

        for t in tiles:
            tileval.append({"pos": t.position, "coord": t.coords,
                            "num": t.number, "size": t.image.size})
            tfilename = t.generate_filename(prefix=outprefix)
            tilename.append(tfilename.split("/")[-1])

        tdict = dict(zip(tilename, tileval))
        pickle.dump(tdict, open(tfilename.split(outprefix)[0] + \
                    outprefix + "_tiles.p", 'wb'))


def CreateOrthographicDataSet(outprefix):
    """Creates set of images and accompanying csvs of crater data from
    a set of Plate Carree data.

    Parameters
    ----------
    outprefix : str
        Plate Carree output files' filepath and image prefix.
    """

    imagelist = sorted(glob.glob(outprefix + "*.png"))
    tdict = pickle.load(open(glob.glob(outprefix + "_tiles.p")[0], 'rb'))

    #lastimg = Image.open(imagelist[-1]).convert("L")
    lastimg = tdict[imagelist[-1].split("/")[-1]]
    imgdim = tuple( np.array(lastimg["coord"]) + \
                    np.array(lastimg["size"]) )

    cdim = [-180, 180, -90, 90]
    prefix_head = outprefix.split("/")[-1]

    for item in imagelist:

        # Obtain long/lat bounds
        pos = np.array(tdict[item.split("/")[-1]]["coord"])
        size = np.array(tdict[item.split("/")[-1]]["size"])
        ix = np.array([pos[0], pos[0] + size[0]])
        iy = np.array([pos[1], pos[1] + size[1]])

        # Using origin="upper" means our latitude coordinates are reversed
        llong, llat = pix2coord(ix, iy, cdim, imgdim, origin="upper")
        llbd = np.r_[llong, llat[::-1]]

        craters = pd.read_csv(open(item.split(".png")[0] + ".csv", 'r'), 
            sep=',', header=0, engine="c", encoding = "ISO-8859-1")

        oname = item.split( "/" + prefix_head )[0] + "/" + \
                "ortho" + item.split( "/" + prefix_head )[1]

        PlateCarree_to_Orthographic(item, oname, llbd, craters, 
                                    iglobe=None, ctr_sub=True, 
                                    origin="upper", rgcoeff=1.2)


################### Create Random Dataset ###########################


def RandRot(img, craters, expand=False, origin="upper"):
    """Rotates and horizontally/vertically flips image at random.
    DOES NOT SEED ITSELF!"""

    # Values to shift craters after rotation
    if origin == "upper":
        rot_shift = [(0, img.size[0]), (img.size[0], img.size[1]), 
                            (img.size[1],0)]
    else:
        rot_shift = [(img.size[1],0), (img.size[0], img.size[1]), 
                            (0, img.size[0])]

    rtoken = np.random.randint(0,4)
    if rtoken > 0:
        img = img.rotate(90*rtoken, expand=expand)

        # Rotate crater coordinates
        if origin == "upper":
            rt = -rtoken
        else:
            rt = rtoken
        costheta = np.cos(90.*rt/180.*np.pi)
        sintheta = np.sin(90.*rt/180.*np.pi)
        xrot = craters["x"]*costheta - craters["y"]*sintheta
        yrot = craters["x"]*sintheta + craters["y"]*costheta
        craters["x"] = xrot + rot_transform[rtoken - 1][0]
        craters["y"] = yrot + rot_transform[rtoken - 1][1]

    # 50% chance of flipping or mirroring
    if np.random.randint(0,2):
        img = ImageOps.mirror(img)
        craters["x"] = img.size[0] - craters["x"]

    if np.random.randint(0,2):
        img = ImageOps.flip(img)
        craters["y"] = img.size[1] - craters["y"]

    return [img, craters]


def ResampleCraters(craters, llbd, imgheight, arad=1737.4, minpix=0):
    """Crops crater file, and removes craters smaller than 
    some user defined minimum value.

    Parameters
    ----------
    craters : pandas.DataFrame
        Crater dataframe
    llbd : list-like
        Long/lat limits (long_min, long_max, 
        lat_min, lat_max) of image
    imgheight : int
        Pixel height of image
    arad : float
        Radius of Moon
    minpix : int
        Minimium crater pixel size to be included
        in output

    Returns
    -------
    ctr_sub : pandas.DataFrame
        Cropped and filtered dataframe
    """

    # Get subset of craters within llbd limits
    ctr_xlim = (craters["Long"] > llbd[0]) & \
                (craters["Long"] < llbd[1])
    ctr_ylim = (craters["Lat"] > llbd[2]) & \
                (craters["Lat"] < llbd[3])
    ctr_sub = craters.loc[ctr_xlim & \
                            ctr_ylim, :].copy()

    if minpix > 0:
        # Obtain pixel per km conversion factor.  Use
        # latitude because Plate carree doesn't distort
        # along this axis
        pxperkm = km2pix(imgheight, llbd[3] - llbd[2], \
                            dc=1., a=arad)
        minkm = minpix / pxperkm
        
        # Remove craters smaller than pixel limit
        ctr_sub = ctr_sub[ctr_sub["Diameter (km)"] >= minkm]
    
    return ctr_sub


#def GenDatasetNP(img, ilen=200, randrot=True, amt=100):
#    """Generates random dataset.

#    Parameters
#    ----------
#    """
#    xm, ym = img.shape[1] - ilen, img.shape[0] - ilen

#    for i in range(amt):
#        xc = np.random.randint(0, xm)
#        yc = np.random.randint(0, ym)

#        im = img[yc:yc + ilen, xc:xc + ilen]

#        if min(im.shape) == 0:
#            print(xc, yc, ilen)

#        yield im.copy()



def GenDataset(img, craters, outhead, ilen_range=np.array([300., 4000.]), 
                olen=300, minpix=0, randrot=False, amt=100, zeropad=4,
                slivercut=0.1, outp=False, istart = 0, seed=None):
    """Generates random dataset from plate image.

    Parameters
    ----------
    img : PIL.Image.Image
        Source image
    craters : pandas.DataFrame
        Crater list csv
    outhead : str
        Filepath and file prefix to save output
        images under.
    ilen_range : list-like
        Lower and upper bounds of image width, in pixels,
        to crop from source.  To always crop the same sized
        image, set lower bound to same value as upper.
    olen : int
        Output image width, in pixels.  Cropped images will be
        downsampled to this size.
    minpix : int
        Minimum crater diameter in pixels to be included in
        crater list.  By default, not useful, since
        our source image is ~100-200 m/px, we downsample by
        at most a factor of 10 and our crater dataset starts at
        d = 5000 m.  However, if you use a different image, or
        setting max(ilen_range) > 10000 px, might be necessary
        to remove craters that are less than ~3 pixels across.
    randrot : bool - UNTESTED!
        If True, randomly rotates and flips image (and corresponding
        craters).  Might as well do it in Keras instead, though.
    amt : int
        Number of images to produce.
    zeropad : int
        Number of zeros to pad output file numbering.
    slivercut : float from 0 to 1
        Occasionally the code samples a small region near the pole,
        in which case the transformation from Plate Carree to
        Orthographic leads to tiny slivers of the Moon surrounded
        by padding.  These images are useless, so the code trashes
        any images whose non-padding region has an width/height ratio
        less than slivercut.  Discarded images are not counted
        as part of amt.  Setting slivercut to 0 disables the cut.
        Setting it too close to 1 will lead to an infinite loop!
    outp : str or None
        If a string, will dump the long/lat boundary and crop
        bounds of all images to a pickle file.  File's name is
        obtained from outhead + outp.
    istart : int
        Output file starting number.  Useful for preventing overwriting
        of files when batch serializing the code (see __main__ script)
    seed : int or None
        np.random.seed input (for testing purposes).    
    """

    # If seed == None, uses an OS-dependent built-in
    # randomizer
    np.random.seed(seed)

    # Get craters
    cdim = [-180, 180, -90, 90]
    AddPlateCarree_XY(craters, list(img.size), cdim=cdim, 
                            origin="upper")

    iglobe = ccrs.Globe(semimajor_axis=1737400, 
                    semiminor_axis=1737400,
                    ellipse=None)

    # Determine log values of ilen range
    ilen_min = np.log10(ilen_range[0])
    ilen_max = np.log10(ilen_range[1])

    i = istart

    if outp:
        outpnames = []
        outpvals = []

    while i < istart + amt:

        # Determine image size to crop
        ilen = int(10**np.random.uniform(ilen_min, ilen_max))
        xm, ym = img.size[0] - ilen, img.size[1] - ilen
        xc = np.random.randint(0, xm)
        yc = np.random.randint(0, ym)
        box = [xc, yc, xc + ilen, yc + ilen]

        # Load necessary because crop may be a lazy operation
        # im.load() should copy it.
        # http://pillow.readthedocs.io/en/3.1.x/reference/Image.html
        im = img.crop(box)
        im.load()

        # Obtain long/lat bounds for coordinate transform
        ix = np.array([box[0], box[2]])
        iy = np.array([box[1], box[3]])
        llong, llat = pix2coord(ix, iy, cdim, list(img.size), origin="upper")
        llbd = np.r_[llong, llat[::-1]]

        # Downsample image
        im = im.resize([olen, olen])

        # Remove all craters that are too small to be seen in image
        ctr_sub = ResampleCraters(craters, llbd, im.size[1], minpix=minpix)

        # Convert Plate Carree to Orthographic
        [imgo, ctr_xy] = PlateCarree_to_Orthographic(im, None, llbd, ctr_sub, 
                                    iglobe=iglobe, ctr_sub=True, 
                                    origin="upper", rgcoeff=1.2, dontsave=True,
                                    slivercut=slivercut)

        # If PlateCarree_to_Orthogonal returns NoneType, skip saving,
        # and don't add 1 to i
        if imgo is None:
            print("Discarding narrow image")
            continue

        # Randomly rotate and/or flip, if user so desires
        if randrot:
            [imgo, ctr_xy] = RandRot(imgo, ctr_xy, origin="upper")

        # Output everything
        oname = outhead + "_{i:0{zp}d}".format(i=i, zp=zeropad)
        imgo.save(oname + ".png")
        ctr_xy.to_csv(oname + ".csv", index=False)

        # Add entry to outp
        if outp:
            outpnames.append(i)
            outpvals.append({"llbd": llbd, "box": box})

        i += 1

        # Create generator
        #yield [np.asanyarray(imgo), ctr_xy]

    pdict = dict( zip(outpnames, outpvals) )
    pickle.dump( pdict, open(outhead + outp, 'wb') )
    

if __name__ == '__main__':

    from mpi4py import MPI
    import make_input_data as mkin
    from PIL import Image
    import numpy as np
    import argparse

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    parser = argparse.ArgumentParser(description='Input data creation script.')
    parser.add_argument('--image_path', metavar='imgpath', type=str, required=False,
                        help='Path to the source image.', default="./LOLA_Global_20k.png")
    parser.add_argument('--lu_csv_path', metavar='lupath', type=str, required=False,
                        help='Path to LU78287 crater csv.', default="./LU78287GT.csv")
    parser.add_argument('--alan_csv_path', metavar='lupath', type=str, required=False,
                        help='Path to LROC crater csv.', default="./alanalldata.csv")
    parser.add_argument('--outhead', metavar='outhead', type=str, required=False,
                        help='Filepath and filename prefix of outputs.', default="out/lola")
    parser.add_argument('--amt', type=int, default=7500, required=False,
                        help='Number of images each thread will make (multiply by number of \
                        threads for total number of images produced).')

    args = parser.parse_args()

    print("rank {0} of {1}".format(rank, size))

    img = Image.open(args.image_path).convert("L")
    craters = mkin.ReadCombinedCraterCSV(filealan=args.alan_csv_path, filelu=args.lu_csv_path,
                                            dropfeatures=True)

    mkin.GenDataset(img, craters, args.outhead, ilen_range=np.array([600., 3000.]),
                    olen=300, amt=args.amt, zeropad=5, slivercut=0.6, outp="_p{0}.p".format(rank),
                    istart = rank*args.amt)



